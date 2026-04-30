"""Voice-first alignment v2 — phase grouping + design ratio preservation.

Workflow:
1. Whisper transcribe → segments + word timestamps.
2. Group segments into VOICE PHASES (consecutive segments, gap >= silence_threshold = phase break).
3. Claude CLI maps phases → scene groups (semantic match against scene story).
4. Per phase: scale_factor = phase_voice_duration / sum(scene.design_durations).
   Apply scale to each scene's design duration → duration_adjusted.
5. Output `VoiceFile` v3 with `duration_original`, `duration_adjusted`,
   `scale_factor`, `phase_id` per scene + top-level `phases` summary.

Render uses `duration_adjusted` (NOT voice_out - voice_in) → preserves design ratios.

Sync orchestrator — call from a worker via `asyncio.to_thread(align_voice_file, ...)`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger as log

from core.voice_mapping import (
    SceneVoiceAssignment,
    SubtitlePhrase,
    VoiceFile,
    VoicePhaseMeta,
)
from voice.whisper_runner import run_whisper

CLAUDE_TIMEOUT_S = 180
DEFAULT_SILENCE_THRESHOLD = 0.5  # seconds; gap >= this = phase break
SCALE_WARN_LOW = 0.5  # warn if scale < this (voice quá ngắn so với design)
SCALE_WARN_HIGH = 1.5  # warn if scale > this (voice quá dài so với design)


# --- Internal types ---------------------------------------------------------


@dataclass
class _Word:
    word: str
    start: float
    end: float


@dataclass
class _Segment:
    text: str
    start: float
    end: float
    words: list[_Word] = field(default_factory=list)


@dataclass
class _Phase:
    phase_id: int
    start: float
    end: float
    duration: float
    text: str
    segments: list[_Segment]


@dataclass
class _PhaseAlloc:
    phase: _Phase
    scene_ids: list[str]
    original_durations: list[float]
    scale_factor: float
    adjusted_durations: list[float]


@dataclass
class AlignResult:
    """Bundle returned by `align_voice_file`: VoiceFile + side-band silent/warn lists."""

    voice_file: VoiceFile
    silent_scenes: list[str]
    warnings: list[str]


# --- Claude wrapper ---------------------------------------------------------


def _resolve_claude_cmd() -> str:
    found = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not found:
        raise RuntimeError(
            "Không tìm thấy `claude` CLI trên PATH. Cài Claude Code và đăng nhập trước."
        )
    return found


def _strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        s = "\n".join(lines[1:-1]) if len(lines) > 2 else s
        if s.lstrip().lower().startswith("json"):
            s = s.split("\n", 1)[1] if "\n" in s else ""
    return s.strip()


def _call_claude(prompt: str) -> str:
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = _resolve_claude_cmd()
    log.info(f"Calling Claude CLI for phase mapping ({cmd})...")
    result = subprocess.run(
        [cmd, "--print"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=CLAUDE_TIMEOUT_S,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI failed (rc={result.returncode}): "
            f"{(result.stderr or '')[:500]}"
        )
    return result.stdout


# --- Phase grouping ---------------------------------------------------------


def _parse_segments(whisper_json: dict[str, Any]) -> list[_Segment]:
    out: list[_Segment] = []
    for seg in whisper_json.get("segments", []):
        words = [
            _Word(w.get("word", ""), float(w.get("start", 0.0)), float(w.get("end", 0.0)))
            for w in seg.get("words", [])
        ]
        out.append(
            _Segment(
                text=seg.get("text", "") or "",
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                words=words,
            )
        )
    return out


def _build_phase(phase_id: int, segments: list[_Segment]) -> _Phase:
    return _Phase(
        phase_id=phase_id,
        start=segments[0].start,
        end=segments[-1].end,
        duration=segments[-1].end - segments[0].start,
        text=" ".join(s.text.strip() for s in segments).strip(),
        segments=segments,
    )


def group_segments_into_phases(
    segments: list[_Segment],
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
) -> list[_Phase]:
    """Split Whisper segments into phases by silence gap >= threshold."""
    if not segments:
        return []
    phases: list[_Phase] = []
    current = [segments[0]]
    for prev, curr in zip(segments, segments[1:]):
        gap = curr.start - prev.end
        if gap >= silence_threshold:
            phases.append(_build_phase(len(phases) + 1, current))
            current = [curr]
        else:
            current.append(curr)
    if current:
        phases.append(_build_phase(len(phases) + 1, current))
    log.info(f"Grouped {len(segments)} segments into {len(phases)} phases")
    for p in phases:
        log.info(f"  Phase{p.phase_id} {p.start:.2f}-{p.end:.2f}s ({p.duration:.2f}s): {p.text[:60]!r}")
    return phases


# --- Claude phase → scenes mapping ------------------------------------------


CLAUDE_PHASE_PROMPT = """You are mapping voice phases to scenes for a video project.

# VOICE PHASES (Whisper transcript, grouped by silence)
{phases_desc}

# SCENES (project design, in order)
{scenes_desc}

# TASK
Group scenes by voice phase. Each phase contains 1+ scenes whose stories match the phase's voice text.

# RULES
1. Scenes MUST stay in the original order (sequential).
2. Each phase's scenes' stories should match the phase's voice text semantically.
3. If a scene has no matching voice (silent design scene), put its id in `silent_scenes`.
4. Every scene id must appear EITHER in exactly one phase OR in silent_scenes.

# OUTPUT — strict JSON only, no markdown, no commentary
{{
  "mapping": [
    {{"phase_id": 1, "scenes": ["SCENE-01", "SCENE-02"]}},
    {{"phase_id": 2, "scenes": ["SCENE-03"]}}
  ],
  "silent_scenes": ["SCENE-08"]
}}
"""


def _call_claude_phase_mapping(
    phases: list[_Phase], scenes: list[dict[str, Any]]
) -> tuple[list[list[str]], list[str]]:
    phases_desc = "\n".join(
        f"  Phase {p.phase_id} ({p.start:.2f}-{p.end:.2f}s, dur={p.duration:.2f}s): {p.text!r}"
        for p in phases
    )
    scenes_desc = "\n".join(
        f"  {s['id']}: design_duration={s.get('duration', 0)}s, "
        f"story={(s.get('story_en') or s.get('story_vi') or '')!r}"
        for s in scenes
    )
    prompt = CLAUDE_PHASE_PROMPT.format(phases_desc=phases_desc, scenes_desc=scenes_desc)
    raw = _call_claude(prompt)
    clean = _strip_code_fence(raw)
    try:
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"Claude returned non-JSON. First 500 chars:\n{clean[:500]}")
        raise RuntimeError(f"Parse Claude response fail: {e}") from e

    mapping_entries = data.get("mapping", [])
    by_phase: dict[int, list[str]] = {entry["phase_id"]: list(entry.get("scenes", []))
                                       for entry in mapping_entries}
    aligned: list[list[str]] = [by_phase.get(p.phase_id, []) for p in phases]
    silent = list(data.get("silent_scenes", []))
    return aligned, silent


# --- Scale factor + adjusted durations --------------------------------------


def _calc_phase_alloc(phase: _Phase, scene_ids: list[str], scene_durs: list[float]) -> _PhaseAlloc:
    total_design = sum(scene_durs)
    if total_design <= 0:
        scale = 1.0
        adjusted = list(scene_durs)
    else:
        scale = phase.duration / total_design
        adjusted = [d * scale for d in scene_durs]
    return _PhaseAlloc(
        phase=phase,
        scene_ids=scene_ids,
        original_durations=scene_durs,
        scale_factor=scale,
        adjusted_durations=adjusted,
    )


def _scale_warning(scale: float, phase_id: int) -> str | None:
    if scale < SCALE_WARN_LOW:
        return f"Phase {phase_id}: scale {scale:.2f} < {SCALE_WARN_LOW} (voice quá ngắn so với design)"
    if scale > SCALE_WARN_HIGH:
        return f"Phase {phase_id}: scale {scale:.2f} > {SCALE_WARN_HIGH} (voice quá dài so với design)"
    return None


# --- Subtitle phrase extraction ---------------------------------------------


def _extract_subtitle_phrases(
    segments: list[_Segment], voice_in: float, voice_out: float
) -> list[SubtitlePhrase]:
    phrases: list[SubtitlePhrase] = []
    for seg in segments:
        if seg.end < voice_in or seg.start > voice_out:
            continue
        start = max(seg.start, voice_in)
        end = min(seg.end, voice_out)
        if end - start < 0.3:
            continue
        text = (seg.text or "").strip()
        if not text:
            continue
        phrases.append(SubtitlePhrase(text=text, start=round(start, 2), end=round(end, 2)))
    return phrases


# --- Public API -------------------------------------------------------------


def align_voice_file(
    voice_path: Path,
    scenes: list[dict[str, Any]],
    work_dir: Path,
    project_root: Path,
    whisper_model: str = "base",
    language: str = "en",
    silence_threshold: float = DEFAULT_SILENCE_THRESHOLD,
) -> AlignResult:
    """Run the voice-first alignment pipeline for one voice file.

    Returns `AlignResult(voice_file, silent_scenes, warnings)`:
      - voice_file (schema v3) carries `phases` + per-scene `duration_*`/`scale_factor`/`phase_id`.
      - silent_scenes: ids Claude marked as silent for THIS voice file.
      - warnings: extreme-scale strings (out of [0.5, 1.5]).
    """
    voice_path = Path(voice_path)
    work_dir = Path(work_dir)
    project_root = Path(project_root)

    # 1. Whisper
    whisper_dir = work_dir / "whisper"
    whisper_result = run_whisper(voice_path, whisper_dir, whisper_model, language)
    segments = _parse_segments(whisper_result)
    voice_duration = max((s.end for s in segments), default=0.0)
    full_transcript = " ".join(s.text.strip() for s in segments).strip()

    # 2. Phase grouping
    phases = group_segments_into_phases(segments, silence_threshold)
    if not phases:
        log.warning("Whisper returned no segments — empty VoiceFile")
        return AlignResult(
            voice_file=VoiceFile(
                file=_rel(voice_path, project_root),
                duration=voice_duration,
                transcript=full_transcript,
                phases=[],
                scenes=[],
            ),
            silent_scenes=[],
            warnings=[],
        )

    # 3. Claude maps phases → scene groups
    phase_to_scene_ids, silent_scene_ids = _call_claude_phase_mapping(phases, scenes)

    # 4. Per phase: scale factor + adjusted durations
    scenes_by_id = {s["id"]: s for s in scenes}
    voice_assignments: list[SceneVoiceAssignment] = []
    phase_metas: list[VoicePhaseMeta] = []
    warnings: list[str] = []

    for phase, scene_ids in zip(phases, phase_to_scene_ids):
        if not scene_ids:
            continue
        # Drop unknown scene ids (Claude hallucination guard).
        valid_ids = [sid for sid in scene_ids if sid in scenes_by_id]
        if not valid_ids:
            log.warning(f"Phase {phase.phase_id}: no valid scene ids in {scene_ids}")
            continue

        durs: list[float] = []
        for sid in valid_ids:
            scene = scenes_by_id[sid]
            if "duration" not in scene:
                raise KeyError(
                    f"Scene {sid} dict missing 'duration' key. "
                    f"Available keys: {list(scene.keys())}. "
                    "Caller must include scene.duration when building scenes list."
                )
            durs.append(float(scene["duration"]))
        alloc = _calc_phase_alloc(phase, valid_ids, durs)

        warn = _scale_warning(alloc.scale_factor, phase.phase_id)
        if warn:
            warnings.append(warn)
            log.warning(warn)

        phase_metas.append(
            VoicePhaseMeta(
                phase_id=phase.phase_id,
                start=round(phase.start, 2),
                end=round(phase.end, 2),
                duration=round(phase.duration, 2),
                scenes=valid_ids,
                scale_factor=round(alloc.scale_factor, 3),
                text=phase.text,
            )
        )

        cursor = phase.start
        for sid, d_orig, d_adj in zip(valid_ids, alloc.original_durations, alloc.adjusted_durations):
            voice_in = round(cursor, 2)
            voice_out = round(cursor + d_adj, 2)
            cursor = voice_out
            phrases = _extract_subtitle_phrases(phase.segments, voice_in, voice_out)
            voice_assignments.append(
                SceneVoiceAssignment(
                    id=sid,
                    voice_in=voice_in,
                    voice_out=voice_out,
                    duration_original=round(d_orig, 2),
                    duration_adjusted=round(d_adj, 2),
                    scale_factor=round(alloc.scale_factor, 3),
                    phase_id=phase.phase_id,
                    confidence=0.92,
                    method="whisper_claude",
                    subtitle_phrases=phrases,
                )
            )

    if warnings:
        log.warning(f"{len(warnings)} extreme-scale warnings (see review dialog)")

    vf = VoiceFile(
        file=_rel(voice_path, project_root),
        duration=round(voice_duration, 2),
        transcript=full_transcript,
        phases=phase_metas,
        scenes=voice_assignments,
    )
    return AlignResult(voice_file=vf, silent_scenes=silent_scene_ids, warnings=warnings)


def _rel(voice_path: Path, project_root: Path) -> str:
    try:
        rel = voice_path.resolve().relative_to(project_root.resolve())
        return str(rel).replace("\\", "/")
    except ValueError:
        return str(voice_path)
