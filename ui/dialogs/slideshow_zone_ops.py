"""Pure zone-list operations for the slideshow editor."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def resequence_zones(zones: list[dict[str, Any]]) -> None:
    """Assign stable 1-based order according to current list order."""
    for idx, zone in enumerate(zones, start=1):
        zone["order"] = idx


def next_zone_id(zones: list[dict[str, Any]]) -> int:
    used = {int(z.get("zone_id") or z.get("id") or 0) for z in zones}
    zone_id = 1
    while zone_id in used:
        zone_id += 1
    return zone_id


def move_zone(zones: list[dict[str, Any]], zone_id: int, delta: int) -> bool:
    """Move zone up/down by swapping list position. Returns True if changed."""
    idx = _index_of(zones, zone_id)
    if idx is None:
        return False
    new_idx = idx + delta
    if new_idx < 0 or new_idx >= len(zones):
        return False
    zones[idx], zones[new_idx] = zones[new_idx], zones[idx]
    resequence_zones(zones)
    return True


def delete_zone(zones: list[dict[str, Any]], zone_id: int) -> dict[str, Any] | None:
    idx = _index_of(zones, zone_id)
    if idx is None:
        return None
    removed = zones.pop(idx)
    resequence_zones(zones)
    return removed


def add_default_zone(
    zones: list[dict[str, Any]],
    image_size: tuple[int, int],
    template: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a new editable rectangular zone centered on the source image."""
    zone_id = next_zone_id(zones)
    width, height = image_size
    box_w = max(30, int(width * 0.30))
    box_h = max(30, int(height * 0.30))
    x1 = max(0, (width - box_w) // 2)
    y1 = max(0, (height - box_h) // 2)
    x2 = min(width, x1 + box_w)
    y2 = min(height, y1 + box_h)

    zone = deepcopy(template) if template else {}
    zone.update(
        {
            "zone_id": zone_id,
            "label": f"zone_{zone_id}",
            "polygon": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
            "animation": zone.get("animation", "fade_in"),
            "emphasis": zone.get("emphasis", "none"),
            "sound": zone.get("sound", "ding"),
            "appear_at": float(zone.get("appear_at", 0.0)),
            "end_at": float(zone.get("end_at", 0.5)),
        }
    )
    zones.append(zone)
    resequence_zones(zones)
    return zone


def apply_sound_to_all(zones: list[dict[str, Any]], sound: str) -> int:
    """Set the same sound value on all zones. Returns changed row count."""
    changed = 0
    for zone in zones:
        if zone.get("sound") != sound:
            changed += 1
        zone["sound"] = sound
    return changed


def _index_of(zones: list[dict[str, Any]], zone_id: int) -> int | None:
    for idx, zone in enumerate(zones):
        if int(zone.get("zone_id") or zone.get("id") or -1) == int(zone_id):
            return idx
    return None
