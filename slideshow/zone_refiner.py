"""Refine Claude's rough bbox into a tight content-aware polygon.

Includes granular per-step logging so when the pipeline hangs, the log
shows exactly which step + how long it took for each zone.
"""

import time
from typing import Callable, List, Optional, Tuple

import cv2
import numpy as np


# Tuned constants
CHROMA_THRESHOLD = 15
MIN_COMPONENT_AREA = 100
DOUGLAS_PEUCKER_EPSILON = 2.0
EDGE_TOUCH_RATIO = 0.05
EXPANSION_PX = 30
MAX_EXPAND_ITERATIONS = 2

# Safety caps to prevent runaway processing on pathological inputs
MAX_BBOX_PIXELS = 30_000_000   # ~5500x5500 — reject larger crops
MAX_DILATION_PX = 25
MAX_COMPONENTS = 5000          # if more than this, skip the filter (too slow + noisy)


def _log(log_cb: Optional[Callable], msg: str) -> None:
    """Safe log helper."""
    if log_cb is not None:
        try:
            log_cb(msg)
        except Exception:
            pass


def compute_dilation_margin(bbox_w: int, bbox_h: int) -> int:
    """Dilation margin scales with bbox size, capped at MAX_DILATION_PX."""
    return max(8, min(MAX_DILATION_PX, int(0.03 * min(bbox_w, bbox_h))))


def refine_polygon_from_bbox(
    source_array: np.ndarray,
    bbox: List[int],
    bg_color: Tuple[int, int, int],
    log_cb: Optional[Callable] = None,
    zone_label: str = "?",
) -> List[Tuple[int, int]]:
    """Refine Claude's rough bbox into a tight polygon.

    Logs each step with timing so a stuck step can be identified.

    Args:
        source_array: RGB image as numpy array (H, W, 3)
        bbox: [x1, y1, x2, y2] in image pixel coordinates
        bg_color: (r, g, b) background color
        log_cb: optional progress callback (e.g. print or loguru)
        zone_label: label for log messages (e.g. "zone_1", "sandals")

    Returns:
        List of (x, y) polygon vertices in image coordinates
    """
    t_total = time.monotonic()

    try:
        x1, y1, x2, y2 = [int(v) for v in bbox]
    except (TypeError, ValueError) as e:
        raise ValueError(f"Bbox không phải 4 số nguyên: {bbox} ({e})")

    # Validate order
    if x2 <= x1 or y2 <= y1:
        raise ValueError(
            f"Invalid bbox order: x1={x1} x2={x2} y1={y1} y2={y2} (need x2>x1 and y2>y1)"
        )

    h_src, w_src = source_array.shape[:2]

    # Clip to image bounds
    x1 = max(0, min(x1, w_src - 1))
    y1 = max(0, min(y1, h_src - 1))
    x2 = max(x1 + 5, min(x2, w_src))
    y2 = max(y1 + 5, min(y2, h_src))

    bbox_w_initial = x2 - x1
    bbox_h_initial = y2 - y1
    _log(log_cb, f"     [{zone_label}] start refine bbox=({x1},{y1},{x2},{y2}) size={bbox_w_initial}x{bbox_h_initial}")

    # Safety: reject huge bboxes
    if bbox_w_initial * bbox_h_initial > MAX_BBOX_PIXELS:
        raise ValueError(
            f"Bbox quá lớn ({bbox_w_initial}x{bbox_h_initial}={bbox_w_initial*bbox_h_initial} px), "
            f"max={MAX_BBOX_PIXELS}"
        )

    # ===== Edge-touch expansion (iterative) =====
    t_step = time.monotonic()
    iterations_done = 0
    for it in range(MAX_EXPAND_ITERATIONS):
        crop = source_array[y1:y2, x1:x2]
        h, w = crop.shape[:2]

        if w < 5 or h < 5:
            break

        mask = _build_chroma_mask(crop, bg_color)

        edges_touch = []
        if np.mean(mask[0, :]) > EDGE_TOUCH_RATIO * 255:
            edges_touch.append("top")
        if np.mean(mask[-1, :]) > EDGE_TOUCH_RATIO * 255:
            edges_touch.append("bottom")
        if np.mean(mask[:, 0]) > EDGE_TOUCH_RATIO * 255:
            edges_touch.append("left")
        if np.mean(mask[:, -1]) > EDGE_TOUCH_RATIO * 255:
            edges_touch.append("right")

        if not edges_touch:
            break

        # Apply expansion; if bbox didn't actually change (already at image
        # boundary), bail out — further iterations would do the same.
        prev_bbox = (x1, y1, x2, y2)
        if "top" in edges_touch:
            y1 = max(0, y1 - EXPANSION_PX)
        if "bottom" in edges_touch:
            y2 = min(h_src, y2 + EXPANSION_PX)
        if "left" in edges_touch:
            x1 = max(0, x1 - EXPANSION_PX)
        if "right" in edges_touch:
            x2 = min(w_src, x2 + EXPANSION_PX)

        if (x1, y1, x2, y2) == prev_bbox:
            break
        iterations_done += 1

    elapsed = time.monotonic() - t_step
    _log(log_cb, f"     [{zone_label}] edge-expansion: {iterations_done} iter, {elapsed*1000:.0f}ms")

    # ===== Final crop + chroma mask =====
    t_step = time.monotonic()
    crop = source_array[y1:y2, x1:x2]
    h, w = crop.shape[:2]

    if w < 5 or h < 5:
        raise ValueError("Bbox too small after clipping")

    mask = _build_chroma_mask(crop, bg_color)
    _log(log_cb, f"     [{zone_label}] chroma-mask: {w}x{h}, {(mask>0).sum()} fg-px, {(time.monotonic()-t_step)*1000:.0f}ms")

    # ===== Morphological open =====
    t_step = time.monotonic()
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    # Defensive: ensure contiguous uint8 before cv2 (prevents heap corruption)
    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    _log(log_cb, f"     [{zone_label}] morph-open: {(time.monotonic()-t_step)*1000:.0f}ms")

    # ===== Connected components filter (uses stats, not O(N*pixels) loop) =====
    t_step = time.monotonic()
    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    n_labels, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )
    # n_labels includes background (label 0)
    n_components = n_labels - 1
    _log(log_cb, f"     [{zone_label}] components: {n_components} found")

    if n_components > MAX_COMPONENTS:
        # Pathological case: too many tiny components, filter would be slow
        _log(log_cb, f"     [{zone_label}] WARN: {n_components} > {MAX_COMPONENTS}, skipping area filter")
    elif n_components > 0:
        # Build keep mask in ONE pass using vectorized lookup
        # stats[label_idx, cv2.CC_STAT_AREA] = pixel count
        areas = stats[:, cv2.CC_STAT_AREA]  # shape (n_labels,)
        # label 0 = background, keep it 0
        keep_lookup = np.zeros(n_labels, dtype=np.uint8)
        for i in range(1, n_labels):
            if areas[i] >= MIN_COMPONENT_AREA:
                keep_lookup[i] = 255
        # Vectorized: mask = keep_lookup[labels]
        mask = keep_lookup[labels]
    _log(log_cb, f"     [{zone_label}] components-filter: {(time.monotonic()-t_step)*1000:.0f}ms, kept-px={(mask>0).sum()}")

    if (mask > 0).sum() == 0:
        raise ValueError("All components filtered out (no content above MIN_COMPONENT_AREA)")

    # ===== Dilate to recover edges =====
    # Kernel must be (margin*2+1, margin*2+1) to actually expand by `margin` px
    # on each side (radius = margin). Prior bug used (margin, margin) which only
    # gave half the expected radius — cut character edges / dropped shadows.
    t_step = time.monotonic()
    dilation = compute_dilation_margin(w, h)
    kernel_size = dilation * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    _log(log_cb, f"     [{zone_label}] dilate radius={dilation}px (kernel={kernel_size}x{kernel_size}): {(time.monotonic()-t_step)*1000:.0f}ms")

    # ===== Find contour + simplify =====
    t_step = time.monotonic()
    mask = np.ascontiguousarray(mask, dtype=np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("No contour found after dilation")

    largest = max(contours, key=cv2.contourArea)
    if largest.shape[0] < 3:
        raise ValueError("Contour has fewer than 3 vertices")

    simplified = cv2.approxPolyDP(
        largest, DOUGLAS_PEUCKER_EPSILON, closed=True
    )
    if simplified.shape[0] < 3:
        simplified = largest
    _log(log_cb, f"     [{zone_label}] contour+simplify: {simplified.shape[0]} verts, {(time.monotonic()-t_step)*1000:.0f}ms")

    # ===== Translate to source coords =====
    polygon = []
    for pt in simplified:
        px, py = int(pt[0][0]) + x1, int(pt[0][1]) + y1
        polygon.append((px, py))

    if len(polygon) < 3:
        raise ValueError("Final polygon has fewer than 3 vertices")

    _log(log_cb, f"     [{zone_label}] TOTAL: {(time.monotonic()-t_total)*1000:.0f}ms, {len(polygon)} vertices")
    return polygon


def _build_chroma_mask(
    crop: np.ndarray, bg_color: Tuple[int, int, int]
) -> np.ndarray:
    """Build chroma-key mask: pixels far from bg_color.

    NOTE: Uses int32 squared-distance (NOT np.linalg.norm) to avoid BLAS
    threading issues that cause heap corruption (0xc0000374) when called
    repeatedly with non-contiguous numpy slices on Windows.

    Always returns a C-contiguous uint8 array so OpenCV can safely operate
    on it without memory-layout assumptions.
    """
    # Ensure contiguous int32 copy (also detaches from any parent array slice)
    crop_contig = np.ascontiguousarray(crop, dtype=np.int32)
    bg = np.array(bg_color, dtype=np.int32)
    diff = crop_contig - bg
    dist_sq = (diff * diff).sum(axis=2)
    mask = (dist_sq > (CHROMA_THRESHOLD * CHROMA_THRESHOLD)).astype(np.uint8) * 255
    return np.ascontiguousarray(mask)


def resolve_overlaps(
    polygons: List[List[Tuple[int, int]]],
    image_size: Tuple[int, int],
    log_cb: Optional[Callable] = None,
) -> List[List[Tuple[int, int]]]:
    """Resolve overlapping polygons via centroid-distance assignment.

    Algorithm:
      1. Rasterize each polygon into its own per-zone mask
      2. Sum masks → overlap_count_map (pixels claimed by 2+ zones)
      3. For each overlap pixel, assign to nearest-centroid zone
      4. Re-extract per-zone contours from final label_mask

    Returns list of polygons same length/order as input.
    """
    t_total = time.monotonic()

    if not polygons:
        return polygons

    n = len(polygons)
    if n == 1:
        return polygons

    w, h = image_size
    pad = 4
    cw, ch = w + 2 * pad, h + 2 * pad

    _log(log_cb, f"     resolve_overlaps: {n} zones on {w}x{h} canvas")

    # Safety: prevent runaway memory on huge images
    if n * cw * ch > 500_000_000:
        _log(log_cb, f"     WARN: canvas too large ({n}*{cw}*{ch} bytes), skipping overlap resolution")
        return polygons

    # Step 1: rasterize each polygon
    t_step = time.monotonic()
    from PIL import Image, ImageDraw

    per_zone_masks = np.zeros((n, ch, cw), dtype=np.uint8)
    for idx, poly in enumerate(polygons):
        if len(poly) < 3:
            continue
        mask_img = Image.new("L", (cw, ch), 0)
        shifted = [(x + pad, y + pad) for x, y in poly]
        ImageDraw.Draw(mask_img).polygon(shifted, fill=1)
        per_zone_masks[idx] = np.array(mask_img, dtype=np.uint8)
    _log(log_cb, f"     resolve_overlaps: rasterize {(time.monotonic()-t_step)*1000:.0f}ms")

    # Step 2: detect overlap (cast to int32 to avoid uint8 overflow if n > 255)
    t_step = time.monotonic()
    overlap_count = per_zone_masks.sum(axis=0, dtype=np.int32)
    has_overlap = (overlap_count > 1).any()
    _log(log_cb, f"     resolve_overlaps: overlap-check {(time.monotonic()-t_step)*1000:.0f}ms, has_overlap={has_overlap}")

    # Step 3: compute centroids
    t_step = time.monotonic()
    centroids = []
    for idx in range(n):
        mask = per_zone_masks[idx] > 0
        if not mask.any():
            centroids.append(None)
            continue
        ys, xs = np.where(mask)
        centroids.append((float(np.mean(xs)), float(np.mean(ys))))
    _log(log_cb, f"     resolve_overlaps: centroids {(time.monotonic()-t_step)*1000:.0f}ms")

    # Step 4: build final label mask
    t_step = time.monotonic()
    label_mask = np.zeros((ch, cw), dtype=np.int32)

    if not has_overlap:
        any_claim = overlap_count > 0
        if any_claim.any():
            label_mask[any_claim] = (
                np.argmax(per_zone_masks, axis=0)[any_claim] + 1
            )
    else:
        non_overlap = (overlap_count == 1)
        if non_overlap.any():
            label_mask[non_overlap] = (
                np.argmax(per_zone_masks, axis=0)[non_overlap] + 1
            )

        overlap_pixels = np.where(overlap_count > 1)
        n_overlap = len(overlap_pixels[0])
        _log(log_cb, f"     resolve_overlaps: {n_overlap} overlap pixels to reassign")

        if n_overlap > 0:
            ys_overlap = overlap_pixels[0].astype(np.float32)
            xs_overlap = overlap_pixels[1].astype(np.float32)

            best_zone = np.zeros(len(ys_overlap), dtype=np.int32)
            best_dist = np.full(len(ys_overlap), np.inf, dtype=np.float32)

            for idx in range(n):
                c = centroids[idx]
                if c is None:
                    continue
                cx, cy = c
                claims = per_zone_masks[idx, ys_overlap.astype(int), xs_overlap.astype(int)] > 0
                if not claims.any():
                    continue
                dx = xs_overlap - cx
                dy = ys_overlap - cy
                dist = dx * dx + dy * dy
                mask_update = claims & (dist < best_dist)
                best_zone[mask_update] = idx + 1
                best_dist[mask_update] = dist[mask_update]

            label_mask[ys_overlap.astype(int), xs_overlap.astype(int)] = best_zone

    _log(log_cb, f"     resolve_overlaps: label-mask build {(time.monotonic()-t_step)*1000:.0f}ms")

    # Step 5: re-extract polygons
    t_step = time.monotonic()
    result = _rasterized_to_polygons(label_mask.astype(np.uint8), pad, n, polygons)
    _log(log_cb, f"     resolve_overlaps: re-extract {(time.monotonic()-t_step)*1000:.0f}ms")

    _log(log_cb, f"     resolve_overlaps TOTAL: {(time.monotonic()-t_total)*1000:.0f}ms")
    return result


def _rasterized_to_polygons(
    label_array: np.ndarray,
    pad: int,
    n_zones: int,
    original_polygons: Optional[List[List[Tuple[int, int]]]] = None,
) -> List[List[Tuple[int, int]]]:
    """Convert rasterized label image back to polygons.

    If a zone lost all pixels, fall back to original polygon.
    """
    result = []

    for idx in range(n_zones):
        label_idx = idx + 1
        mask = (label_array == label_idx).astype(np.uint8) * 255

        if not mask.any():
            if original_polygons and idx < len(original_polygons):
                result.append(original_polygons[idx])
            else:
                result.append([])
            continue

        mask = np.ascontiguousarray(mask, dtype=np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            if original_polygons and idx < len(original_polygons):
                result.append(original_polygons[idx])
            else:
                result.append([])
            continue

        largest = max(contours, key=cv2.contourArea)
        simplified = cv2.approxPolyDP(
            largest, DOUGLAS_PEUCKER_EPSILON, closed=True
        )

        polygon = []
        for pt in simplified:
            px, py = int(pt[0][0]) - pad, int(pt[0][1]) - pad
            polygon.append((max(0, px), max(0, py)))

        if len(polygon) >= 3:
            result.append(polygon)
        else:
            if original_polygons and idx < len(original_polygons):
                result.append(original_polygons[idx])
            else:
                result.append([])

    return result
