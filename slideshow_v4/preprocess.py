"""
Preprocess v4 - Hybrid background removal.

Key improvement: Chroma Key option (giữ text tốt) thay vì chỉ rembg.

Pipeline:
1. Detect bg color + confidence
2. Chọn phương pháp:
   - "chroma" → pixel color distance (giữ text tốt cho bg solid)
   - "rembg" → AI model (tốt cho bg phức tạp)
   - "auto" (default) → confidence cao → chroma; thấp → rembg
3. Find all regions (filter noise, no merge)
4. Crop + save metadata
"""

import json
from pathlib import Path
import numpy as np
import cv2
from PIL import Image


MIN_AREA_PCT = 0.0008   # 0.08% canvas - thấp để catch text nhỏ
# Horizontal rect kernel: gộp text words cùng dòng (word-spacing)
# mà không gộp text với object ở row khác (vertical gap được bảo toàn)
DILATE_KERNEL_W = 35
DILATE_KERNEL_H = 7
BG_CONFIDENCE_THRESHOLD = 0.85  # Trên ngưỡng này → dùng chroma


def detect_bg_color(rgb_array):
    h, w = rgb_array.shape[:2]
    samples = []
    samples.extend([
        rgb_array[0, 0], rgb_array[0, w - 1],
        rgb_array[h - 1, 0], rgb_array[h - 1, w - 1],
    ])
    step_x = max(1, w // 20)
    step_y = max(1, h // 20)
    for x in range(0, w, step_x):
        samples.append(rgb_array[0, x])
        samples.append(rgb_array[h - 1, x])
    for y in range(0, h, step_y):
        samples.append(rgb_array[y, 0])
        samples.append(rgb_array[y, w - 1])

    arr = np.array(samples)
    bg_color = np.median(arr, axis=0).astype(np.uint8)
    distances = np.linalg.norm(arr.astype(int) - bg_color.astype(int), axis=1)
    confidence = float(np.mean(distances < 30))
    return bg_color, confidence


def remove_background_chroma(scene_path: Path, output_path: Path,
                              bg_color: np.ndarray, threshold: int = 25) -> Path:
    """Xóa bg bằng pixel color distance. Giữ text tốt."""
    with Image.open(scene_path) as img:
        rgb = np.array(img.convert("RGB"))

    dist = np.linalg.norm(rgb.astype(int) - bg_color.astype(int), axis=2)
    alpha = (dist > threshold).astype(np.uint8) * 255

    # Smooth edge nhẹ để tránh text bị đứt
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)

    rgba = np.dstack([rgb, alpha])
    Image.fromarray(rgba, "RGBA").save(output_path, "PNG")
    return output_path


def remove_background_rembg(scene_path: Path, output_path: Path,
                             model: str = "u2net") -> Path:
    """Fallback: rembg cho bg phức tạp (không giữ text tốt)."""
    try:
        from rembg import remove, new_session
    except ImportError:
        raise RuntimeError("rembg chưa cài. Chạy: pip install rembg")

    session = new_session(model)
    with Image.open(scene_path) as img:
        img_rgb = img.convert("RGB")
        result = remove(img_rgb, session=session)
    if result.mode != "RGBA":
        result = result.convert("RGBA")
    result.save(output_path, "PNG")
    return output_path


def remove_background(scene_path: Path, output_path: Path,
                      method: str = "auto",
                      bg_color: np.ndarray = None,
                      bg_confidence: float = 0.0,
                      chroma_threshold: int = 25,
                      rembg_model: str = "u2net",
                      log_fn=print) -> tuple:
    """Xóa bg tự động hoặc theo method chỉ định. Returns (path, method_used)."""
    if method == "auto":
        if bg_color is not None and bg_confidence >= BG_CONFIDENCE_THRESHOLD:
            method_used = "chroma"
            log_fn(f"  Auto: confidence {bg_confidence:.2f} → chroma (giữ text tốt)")
        else:
            method_used = "rembg"
            log_fn(f"  Auto: confidence {bg_confidence:.2f} → rembg AI")
    else:
        method_used = method

    if method_used == "chroma":
        if bg_color is None:
            raise ValueError("Chroma key cần bg_color")
        log_fn(f"  Chroma key (threshold={chroma_threshold})")
        remove_background_chroma(scene_path, output_path, bg_color, chroma_threshold)
    elif method_used == "rembg":
        log_fn(f"  rembg ({rembg_model})")
        remove_background_rembg(scene_path, output_path, rembg_model)
    else:
        raise ValueError(f"Method không hợp lệ: {method_used}")

    return output_path, method_used


class Region:
    def __init__(self, bbox, area, label=None):
        self.bbox = bbox
        self.area = area
        self.label = label
        x1, y1, x2, y2 = bbox
        self.center = ((x1 + x2) / 2, (y1 + y2) / 2)
        self.width = x2 - x1
        self.height = y2 - y1

    def __repr__(self):
        return f"Region(bbox={self.bbox}, area={self.area})"


def find_regions(rgba_array, min_area_pct=MIN_AREA_PCT,
                 dilate_w=DILATE_KERNEL_W, dilate_h=DILATE_KERNEL_H):
    """
    Tìm TẤT CẢ regions, không merge.
    
    Horizontal dilate (wide > tall): gộp text words cùng line
    mà không gộp vertical (giữ tách giữa title và content ở các row khác nhau).
    """
    h, w = rgba_array.shape[:2]
    canvas_area = h * w
    min_area = int(canvas_area * min_area_pct)

    alpha = rgba_array[:, :, 3]
    mask = (alpha > 10).astype(np.uint8) * 255

    # Horizontal rect kernel - wide for gộp words, thin for không gộp rows
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_w, dilate_h))
    mask = cv2.dilate(mask, kernel, iterations=1)

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

    regions = []
    for i in range(1, num_labels):
        x, y, w_box, h_box, area = stats[i]
        if area < min_area:
            continue
        if w_box * h_box > canvas_area * 0.9:
            continue
        bbox = (int(x), int(y), int(x + w_box), int(y + h_box))
        regions.append(Region(bbox=bbox, area=int(area), label=i))

    regions.sort(key=lambda r: r.area, reverse=True)
    return regions


def crop_region(rgba_array, region: Region, padding: int = 5):
    h, w = rgba_array.shape[:2]
    x1, y1, x2, y2 = region.bbox
    x1 = max(0, x1 - padding)
    y1 = max(0, y1 - padding)
    x2 = min(w, x2 + padding)
    y2 = min(h, y2 + padding)
    cropped = rgba_array[y1:y2, x1:x2]
    img = Image.fromarray(cropped, "RGBA")
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
        actual_x = x1 + bbox[0]
        actual_y = y1 + bbox[1]
    else:
        actual_x, actual_y = x1, y1
    return img, (actual_x, actual_y)


def find_scene_image(folder: Path) -> Path:
    for f in sorted(folder.iterdir()):
        if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
            if f.name.startswith('.'):
                continue
            return f
    raise FileNotFoundError(f"Không tìm thấy ảnh nào trong {folder}")


def preprocess_scene(scene_path: Path, cache_dir: Path,
                     bg_method: str = "auto",
                     chroma_threshold: int = 25,
                     rembg_model: str = "u2net",
                     log_fn=print) -> dict:
    """
    Full pipeline: scene.png → N objects.
    
    Args:
        bg_method: "auto" (default) | "chroma" (giữ text) | "rembg" (AI)
        chroma_threshold: 15-50, default 25. Thấp hơn → giữ text mỏng hơn.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    processed_dir = cache_dir / "processed"
    processed_dir.mkdir(exist_ok=True)

    for old_file in processed_dir.glob("*.png"):
        old_file.unlink()

    log_fn("Đọc scene image...")
    with Image.open(scene_path) as img:
        scene_rgb = np.array(img.convert("RGB"))
    source_h, source_w = scene_rgb.shape[:2]

    bg_color, bg_confidence = detect_bg_color(scene_rgb)
    log_fn(f"  BG: RGB{tuple(bg_color.tolist())} confidence {bg_confidence:.2f}")

    log_fn(f"Xóa background (method={bg_method})...")
    nobg_path = cache_dir / "scene_nobg.png"
    _, method_used = remove_background(
        scene_path=scene_path,
        output_path=nobg_path,
        method=bg_method,
        bg_color=bg_color,
        bg_confidence=bg_confidence,
        chroma_threshold=chroma_threshold,
        rembg_model=rembg_model,
        log_fn=log_fn,
    )

    with Image.open(nobg_path) as img:
        rgba = np.array(img.convert("RGBA"))

    alpha_pct = (rgba[:, :, 3] > 10).sum() / (source_h * source_w) * 100
    log_fn(f"  Foreground coverage: {alpha_pct:.1f}%")

    log_fn(f"Tìm regions (min_area={MIN_AREA_PCT*100:.2f}% canvas, "
           f"dilate {DILATE_KERNEL_W}x{DILATE_KERNEL_H} for text gộp)...")
    regions = find_regions(rgba)
    log_fn(f"  Detected {len(regions)} regions")

    if len(regions) == 0:
        raise RuntimeError(
            "Không tách được object nào. Kiểm tra bg color hoặc thử method khác."
        )

    regions.sort(key=lambda r: (r.bbox[1] // 50, r.bbox[0]))

    log_fn(f"Crop {len(regions)} objects...")
    object_metadata = []

    for i, region in enumerate(regions, start=1):
        cropped_img, actual_pos = crop_region(rgba, region, padding=5)
        filename = f"{i:02d}_obj.png"
        out_path = processed_dir / filename
        cropped_img.save(out_path, "PNG")

        meta = {
            "filename": filename,
            "position_in_source": [int(actual_pos[0]), int(actual_pos[1])],
            "size": list(cropped_img.size),
            "area": int(region.area),
            "bbox_in_source": [int(v) for v in region.bbox],
        }
        object_metadata.append(meta)
        log_fn(f"  [{i:02d}] pos={meta['position_in_source']}, "
               f"size={meta['size']}, area={meta['area']}")

    metadata = {
        "scene_source": scene_path.name,
        "source_size": [source_w, source_h],
        "bg_color_rgb": bg_color.tolist(),
        "bg_confidence": round(bg_confidence, 2),
        "bg_removal_method": method_used,
        "chroma_threshold": chroma_threshold if method_used == "chroma" else None,
        "rembg_model": rembg_model if method_used == "rembg" else None,
        "regions_detected": len(regions),
        "objects": object_metadata,
    }

    meta_path = processed_dir / "metadata.json"
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    log_fn(f"✓ Saved metadata ({len(object_metadata)} objects, method: {method_used})")
    return metadata
