"""Voice alignment: Whisper transcribe + Claude CLI scene matching.

Sync orchestrator — call from a worker via `asyncio.to_thread(align_voice_file, ...)`
to avoid blocking the qasync event loop.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from loguru import logger as log

from core.voice_mapping import SceneVoiceAssignment, SubtitlePhrase, VoiceFile
from voice.whisper_runner import run_whisper

CLAUDE_TIMEOUT_S = 180


def _resolve_claude_cmd() -> str:
    """Find `claude` on PATH; raise a helpful error if not installed."""
    found = shutil.which("claude") or shutil.which("claude.cmd") or shutil.which("claude.exe")
    if not found:
        raise RuntimeError(
            "Không tìm thấy `claude` CLI trên PATH. Cài Claude Code và đăng nhập trước."
        )
    return found

CLAUDE_PROMPT_TEMPLATE = """You are an expert at aligning voice transcripts with scene scripts.

# CONTEXT
A voice recording has been transcribed by Whisper (with word-level timestamps).
There are N scene scripts. Each scene's script roughly matches part of the recording.

# SCENES
{scenes_list}

# WHISPER TRANSCRIPT (word-level timestamps included in segments[].words)
{transcript_json}

# TASK
1. Determine which time-range of the transcript belongs to each scene.
2. Output `voice_in` (start sec) and `voice_out` (end sec) per scene using Whisper word timestamps.
3. Polish each phrase's text to match the scene script wording (fix Whisper errors).
4. Group polished text into subtitle phrases (max 8 words each, break at punctuation).
5. Output STRICT JSON only — no markdown, no explanation.

# OUTPUT (strict JSON)
{{
  "alignments": [
    {{
      "scene_id": "SCENE-01",
      "voice_in": 0.0,
      "voice_out": 8.5,
      "confidence": 0.92,
      "subtitle_phrases": [
        {{"text": "Morning.", "start": 0.0, "end": 1.5}},
        {{"text": "The kitchen is still asleep.", "start": 1.5, "end": 3.0}}
      ]
    }}
  ]
}}

# RULES
- Use absolute timestamps (relative to start of voice file) from Whisper segments[].words.
- subtitle_phrases must be inside [voice_in, voice_out] of their scene.
- If a scene has no clear match, omit it (caller will mark silent).
- Confidence 0..1 = how well transcript matches the scene script.
"""


def _strip_code_fence(text: str) -> str:
    """Strip markdown ``` fences if Claude wraps the JSON in them."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        # drop first fence line + trailing fence line
        s = "\n".join(lines[1:-1]) if len(lines) > 2 else s
        # also strip a leading 'json' label if present
        if s.lstrip().lower().startswith("json"):
            s = s.split("\n", 1)[1] if "\n" in s else ""
    return s.strip()


def _call_claude(prompt: str) -> str:
    """Run `claude --print` reading the prompt from stdin (Pro/Max quota).

    stdin avoids Windows' ~8KB command-line length limit; the Whisper
    transcript embedded in the prompt routinely exceeds that.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    cmd = _resolve_claude_cmd()
    log.info(f"Calling Claude CLI for scene alignment ({cmd})...")
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


def _build_voice_file(
    voice_path: Path,
    project_root: Path,
    whisper_result: dict[str, Any],
    claude_data: dict[str, Any],
) -> VoiceFile:
    segments = whisper_result.get("segments") or []
    duration = float(segments[-1].get("end", 0.0)) if segments else 0.0

    assignments: list[SceneVoiceAssignment] = []
    for item in claude_data.get("alignments", []):
        phrases = [
            SubtitlePhrase(
                text=p["text"],
                start=float(p["start"]),
                end=float(p["end"]),
            )
            for p in item.get("subtitle_phrases", [])
        ]
        assignments.append(
            SceneVoiceAssignment(
                id=item["scene_id"],
                voice_in=float(item["voice_in"]),
                voice_out=float(item["voice_out"]),
                confidence=float(item.get("confidence", 0.9)),
                method="whisper_claude",
                subtitle_phrases=phrases,
            )
        )

    try:
        rel = voice_path.resolve().relative_to(project_root.resolve())
        rel_str = str(rel).replace("\\", "/")
    except ValueError:
        rel_str = str(voice_path)

    return VoiceFile(
        file=rel_str,
        duration=duration,
        transcript=whisper_result.get("text", "") or "",
        scenes=assignments,
    )


def align_voice_file(
    voice_path: Path,
    scenes: list[dict[str, Any]],
    work_dir: Path,
    project_root: Path,
    whisper_model: str = "base",
    language: str = "en",
) -> VoiceFile:
    """Run the full alignment pipeline for one voice file.

    Args:
        voice_path: absolute path to the audio file.
        scenes: list of scene dicts with keys `id` + `story_en`/`story_vi`.
        work_dir: writable folder for whisper JSON output.
        project_root: project base for relative-path resolution in VoiceFile.file.
        whisper_model: whisper model size ("tiny" | "base" | "small" | "medium").
        language: BCP-47 short code ("en" | "vi" | ...).

    Returns:
        VoiceFile with all scene assignments.
    """
    voice_path = Path(voice_path)
    work_dir = Path(work_dir)
    project_root = Path(project_root)

    whisper_dir = work_dir / "whisper"
    whisper_result = run_whisper(voice_path, whisper_dir, whisper_model, language)

    scenes_list_str = "\n".join(
        f"- {s['id']}: {s.get('story_en') or s.get('story_vi') or '(no script)'}"
        for s in scenes
    )
    prompt = CLAUDE_PROMPT_TEMPLATE.format(
        scenes_list=scenes_list_str,
        transcript_json=json.dumps(whisper_result, ensure_ascii=False, indent=2),
    )

    raw = _call_claude(prompt)
    clean = _strip_code_fence(raw)
    try:
        claude_data = json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"Claude returned non-JSON. First 500 chars:\n{clean[:500]}")
        raise RuntimeError(f"Parse Claude response fail: {e}") from e

    return _build_voice_file(voice_path, project_root, whisper_result, claude_data)
