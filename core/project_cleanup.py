"""Cleanup helpers for project-local generated outputs."""

from __future__ import annotations

import shutil
from pathlib import Path


def clean_temp_outputs(project_root: Path, keep_visual_cache: bool = True) -> list[Path]:
    """Remove disposable temp outputs.

    By default keeps `temp/final_video_only.mp4` and its metadata because those
    are the visual render cache used to speed up final mux/subtitle tests.
    """
    root = Path(project_root)
    temp = root / "temp"
    if not temp.exists():
        return []

    keep_names = {"final_video_only.mp4", "final_video_only.json"} if keep_visual_cache else set()
    removed: list[Path] = []
    for child in list(temp.iterdir()):
        if child.name in keep_names:
            continue
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            removed.append(child)
        except OSError:
            continue
    return removed


def clean_kdenlive_cache(project_root: Path) -> list[Path]:
    cache_dir = Path(project_root) / "cache" / "kdenlive"
    if not cache_dir.exists():
        return []
    shutil.rmtree(cache_dir)
    return [cache_dir]
