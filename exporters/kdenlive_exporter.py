"""Top-level Kdenlive/MLT exporter.

Public API: `export_kdenlive_project(...)`.

Pipeline:
    1. Load voice_matching_timeline.json
    2. Validate (validators.validate_timeline_for_export)
    3. Resolve audio_master path
    4. Build asset registry (generate freezes + placeholders)
    5. Build MLT XML
    6. Write .kdenlive + export_diagnostics.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger as log

from exporters.asset_registry import (
    POLICY_PLACEHOLDER,
    POLICY_STRICT,
    AssetRegistry,
    build_registry,
)
from exporters.mlt_builder import build_mlt_xml, write_mlt_xml
from exporters.validators import validate_timeline_for_export


@dataclass
class ExportResult:
    ok: bool
    kdenlive_path: Optional[Path]
    diagnostics_path: Optional[Path]
    diagnostics: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def export_kdenlive_project(
    timeline_json_path: Path,
    output_path: Path,
    project_root: Path,
    title: Optional[str] = None,
    aspect_ratio: str = "16:9",
    missing_asset_policy: str = POLICY_PLACEHOLDER,
    strict_no_match: bool = False,
) -> ExportResult:
    """Export a voice_matching_timeline.json to a Kdenlive .kdenlive file.

    Args:
        timeline_json_path: from Sprint 1 (voice_matching_timeline.json)
        output_path: target .kdenlive file (e.g. exports/kdenlive/Naomi2.kdenlive)
        project_root: project root for asset path resolution
        title: project title in MLT header (default: derived from output_path.stem)
        aspect_ratio: "16:9" or "9:16"
        missing_asset_policy: "strict" (fail) or "placeholder"
        strict_no_match: fail on any unmatched voiced scene

    Returns:
        ExportResult with .ok, paths, diagnostics, errors, warnings.
    """
    timeline_json_path = Path(timeline_json_path).resolve()
    output_path = Path(output_path).resolve()
    project_root = Path(project_root).resolve()

    log.info(f"Kdenlive export: {timeline_json_path.name} → {output_path.name}")

    # ---- Load timeline ----
    if not timeline_json_path.exists():
        return ExportResult(
            ok=False, kdenlive_path=None, diagnostics_path=None,
            errors=[f"Timeline JSON not found: {timeline_json_path}"],
        )

    try:
        timeline = json.loads(timeline_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return ExportResult(
            ok=False, kdenlive_path=None, diagnostics_path=None,
            errors=[f"Timeline JSON invalid: {e}"],
        )

    # ---- Resolve audio_master to absolute path ----
    # The timeline JSON may store the path absolute OR relative to project_root.
    # Try several candidates so we don't end up doubling segments.
    audio_master_raw = timeline.get("audio_master") or ""
    audio_master = _resolve_audio_master(audio_master_raw, project_root, timeline_json_path)
    # Update timeline so downstream sees absolute path
    timeline["audio_master"] = str(audio_master.resolve()).replace("\\", "/")

    fps = int(timeline.get("fps") or 30)
    width = int(timeline.get("width") or 1920)
    height = int(timeline.get("height") or 1080)

    # ---- Validate ----
    report = validate_timeline_for_export(
        timeline, fps=fps, strict_no_match=strict_no_match,
    )
    if not report.ok:
        diag = {
            "project": title or output_path.stem,
            "output": str(output_path),
            "errors": report.errors,
            "warnings": report.warnings,
        }
        diag_path = _write_diagnostics(diag, output_path)
        return ExportResult(
            ok=False, kdenlive_path=None, diagnostics_path=diag_path,
            diagnostics=diag,
            errors=report.errors, warnings=report.warnings,
        )

    # ---- Build asset registry ----
    registry = build_registry(
        timeline_items=timeline.get("timeline") or [],
        master_audio_path=audio_master,
        project_root=project_root,
        output_dir=output_path.parent,
        fps=fps, width=width, height=height,
        missing_asset_policy=missing_asset_policy,
    )
    if registry.errors:
        diag = {
            "project": title or output_path.stem,
            "output": str(output_path),
            "errors": registry.errors,
            "warnings": [*report.warnings, *registry.warnings],
        }
        diag_path = _write_diagnostics(diag, output_path)
        return ExportResult(
            ok=False, kdenlive_path=None, diagnostics_path=diag_path,
            diagnostics=diag,
            errors=registry.errors, warnings=report.warnings + registry.warnings,
        )

    # ---- Build XML ----
    root_xml = build_mlt_xml(
        timeline=timeline,
        registry=registry,
        aspect_ratio=aspect_ratio,
        title=title or output_path.stem,
    )

    # ---- Write .kdenlive ----
    kdenlive_path = write_mlt_xml(root_xml, output_path)

    # ---- Diagnostics ----
    timeline_items = timeline.get("timeline") or []
    diag = {
        "project": title or output_path.stem,
        "output": str(kdenlive_path).replace("\\", "/"),
        "assets": {
            "missing": [],
            "generated_freeze_frames": registry.generated_freeze_frames,
            "placeholders": registry.placeholders,
        },
        "timeline": {
            "duration": float(timeline.get("total_duration") or 0),
            "clip_count": sum(
                1 for it in timeline_items
                if it.get("type") in ("scene", "beat_pause")
                and it.get("render_in") is not None
            ),
            "beat_pause_count": sum(
                1 for it in timeline_items if it.get("type") == "beat_pause"
            ),
            "overlaps": [
                w for w in report.warnings if "overlap" in w.lower()
            ],
            "gaps": [
                w for w in report.warnings if "gap" in w.lower()
            ],
        },
        "warnings": [*report.warnings, *registry.warnings],
        "errors": [],
    }
    diag_path = _write_diagnostics(diag, output_path)

    log.info(
        f"Export complete: {kdenlive_path.name} "
        f"(clips={diag['timeline']['clip_count']}, "
        f"pauses={diag['timeline']['beat_pause_count']}, "
        f"warnings={len(diag['warnings'])})"
    )
    return ExportResult(
        ok=True,
        kdenlive_path=kdenlive_path,
        diagnostics_path=diag_path,
        diagnostics=diag,
        errors=[],
        warnings=report.warnings + registry.warnings,
    )


def _resolve_audio_master(raw: str, project_root: Path, timeline_json_path: Path) -> Path:
    """Find the audio_master file across plausible roots.

    Candidates (in order):
      1. raw as absolute path
      2. raw relative to project_root
      3. raw relative to the parent of timeline_json (usually voice/)
      4. raw relative to project_root.parent (covers "project 1/voice/...")
    Returns the first existing candidate, or the project_root-relative path
    (so the caller's error message points at the most likely intended location).
    """
    p = Path(raw)
    if p.is_absolute() and p.exists():
        return p

    candidates = [
        p if p.is_absolute() else (project_root / p),
        timeline_json_path.parent / p.name,
        project_root.parent / p,
    ]
    for c in candidates:
        try:
            if c.exists():
                return c.resolve()
        except OSError:
            continue
    # No hit — return the most-intuitive guess so error message is sensible
    return (project_root / p) if not p.is_absolute() else p


def _write_diagnostics(diag: dict, output_path: Path) -> Path:
    """Write export_diagnostics.json next to the .kdenlive file."""
    diag_path = output_path.parent / "export_diagnostics.json"
    diag_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = diag_path.with_suffix(diag_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(diag, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(diag_path)
    log.info(f"Wrote {diag_path.name}")
    return diag_path
