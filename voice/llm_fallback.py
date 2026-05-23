"""LLM fallback: Claude CLI alignment for one scene.

Only invoked when deterministic score < SCORE_THRESHOLD. Search window scoped
by prev/next scene's word indices so the prompt stays small.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess

from loguru import logger as log

from voice.deterministic_aligner import scene_script


CLAUDE_TIMEOUT = 120  # seconds


def _find_claude_executable() -> str | None:
    """Resolve the `claude` CLI on Windows where shims are .cmd/.bat."""
    for name in ("claude", "claude.exe", "claude.cmd"):
        path = shutil.which(name)
        if path:
            return path
    return None


async def claude_align_scene(
    scene: dict,
    whisper_words: list[dict],
    search_start_idx: int,
    search_end_idx: int,
    language: str = "en",
) -> dict:
    """Use Claude CLI to align ONE scene within a search window.

    Args:
        scene: dict with id + script
        whisper_words: full whisper word list (global indices)
        search_start_idx: lower bound (inclusive, in whisper_words)
        search_end_idx: upper bound (inclusive)

    Returns:
        Result dict similar to deterministic_aligner output, with method="llm".
    """
    if search_start_idx > search_end_idx or search_start_idx >= len(whisper_words):
        log.warning(f"{scene['id']}: invalid search window, skip LLM")
        return {
            "id": scene["id"],
            "voice_in": None,
            "voice_out": None,
            "score": 0,
            "is_silent": True,
            "method": "llm_invalid_window",
            "matched_text": None,
            "word_indices": None,
            "warning": "search_window_invalid",
        }

    window_end = min(search_end_idx + 1, len(whisper_words))
    window_words = whisper_words[search_start_idx:window_end]
    story = scene_script(scene)

    words_desc = "\n".join(
        f"  [{i + search_start_idx}] {w['start']:.2f}-{w['end']:.2f}s: {w['word']}"
        for i, w in enumerate(window_words)
    )

    prompt = f"""You are aligning a scene's narration to Whisper word timestamps.

SCENE:
ID: {scene["id"]}
Story: "{story}"

WHISPER WORDS (with global timestamps, search window only):
{words_desc}

TASK:
Find the EXACT word timestamps where this scene's narration begins and ends in the voice.

RULES:
1. The scene story is the GROUND TRUTH. Whisper may have minor errors (e.g., "He" vs "She", "you" vs "your").
2. voice_in = start time of FIRST word matching scene story
3. voice_out = end time of LAST word matching scene story
4. Use word indices [N] from above to identify positions
5. The match may span natural pauses (silence between sentences) — that's OK
6. If part of the story is missing in this voice window, match what's present
7. If the scene story has NO match in this window at all, return is_silent=true

OUTPUT JSON ONLY (no markdown, no commentary):
{{
  "is_silent": false,
  "voice_in_word_idx": N,
  "voice_out_word_idx": M,
  "voice_in": <timestamp>,
  "voice_out": <timestamp>,
  "confidence": "high",
  "reasoning": "Brief explanation"
}}

Or if no match:
{{
  "is_silent": true,
  "reasoning": "Why no match"
}}

Confidence levels:
- "high": clear match, voice_in/out exactly correct
- "medium": match but boundaries slightly uncertain
- "low": partial or fuzzy match
"""

    log.info(f"{scene['id']}: LLM fallback (window {search_start_idx}-{search_end_idx})")

    claude_exe = _find_claude_executable()
    if not claude_exe:
        log.error(f"{scene['id']}: 'claude' CLI not found in PATH")
        return _build_failure_result(scene["id"], "llm_cli_missing")

    def _run() -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env.pop("ANTHROPIC_API_KEY", None)  # force Pro/Max subscription mode
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        return subprocess.run(
            [claude_exe, "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLAUDE_TIMEOUT,
            env=env,
        )

    try:
        result = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        log.error(f"{scene['id']}: Claude CLI timeout")
        return _build_failure_result(scene["id"], "llm_timeout")

    if result.returncode != 0:
        log.error(
            f"{scene['id']}: Claude CLI failed (rc={result.returncode}): "
            f"{(result.stderr or '')[:300]}"
        )
        return _build_failure_result(scene["id"], "llm_subprocess_failed")

    text = (result.stdout or "").strip()

    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        log.error(f"{scene['id']}: Claude returned invalid JSON: {text[:200]}")
        return _build_failure_result(scene["id"], "llm_invalid_json")

    if data.get("is_silent"):
        log.info(f"{scene['id']}: LLM says silent — {data.get('reasoning', '')}")
        return {
            "id": scene["id"],
            "voice_in": None,
            "voice_out": None,
            "score": 0,
            "is_silent": True,
            "method": "llm_silent",
            "matched_text": None,
            "word_indices": None,
            "reasoning": data.get("reasoning", ""),
        }

    in_idx = data.get("voice_in_word_idx")
    out_idx = data.get("voice_out_word_idx")

    if in_idx is None or out_idx is None:
        log.warning(f"{scene['id']}: LLM JSON missing word indices: {data}")
        return _build_failure_result(scene["id"], "llm_bad_indices")

    if not (0 <= in_idx <= out_idx < len(whisper_words)):
        log.warning(f"{scene['id']}: LLM returned invalid indices ({in_idx}, {out_idx})")
        return _build_failure_result(scene["id"], "llm_bad_indices")

    matched_text = " ".join(
        whisper_words[i]["word"]
        for i in range(in_idx, out_idx + 1)
    )

    score = _confidence_to_score(data.get("confidence", "medium"))

    log.info(
        f"{scene['id']}: LLM matched score={score} "
        f"({data['voice_in']:.2f}-{data['voice_out']:.2f}s) "
        f"conf={data.get('confidence')}"
    )

    return {
        "id": scene["id"],
        "voice_in": data["voice_in"],
        "voice_out": data["voice_out"],
        "score": score,
        "is_silent": False,
        "method": "llm",
        "matched_text": matched_text,
        "word_indices": [in_idx, out_idx],
        "confidence": data.get("confidence", "medium"),
        "reasoning": data.get("reasoning", ""),
    }


def _confidence_to_score(conf: str) -> float:
    return {"high": 90.0, "medium": 75.0, "low": 60.0}.get(conf.lower(), 70.0)


def _build_failure_result(scene_id: str, method: str) -> dict:
    return {
        "id": scene_id,
        "voice_in": None,
        "voice_out": None,
        "score": 0,
        "is_silent": True,
        "method": method,
        "matched_text": None,
        "word_indices": None,
        "warning": method,
    }
