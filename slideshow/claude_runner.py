"""Claude Code runner for auto-pick zones (vision-based)."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def find_claude_executable() -> str:
    """Locate Claude CLI in PATH."""
    for name in ("claude", "claude.exe", "claude.cmd"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        "Không tìm thấy Claude Code CLI. Cài từ https://claude.com/download "
        "và đảm bảo `claude` có trong PATH."
    )


def call_claude(
    prompt: str,
    timeout: int = 300,
    log_dir: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> str:
    """Call Claude CLI via subprocess. Returns raw stdout text.

    Args:
        prompt: full prompt sent via stdin.
        timeout: subprocess timeout in seconds (default 300).
        log_dir: if provided, write claude_prompt.txt and claude_response.txt here.
        cwd: working directory for the subprocess.
    """
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    env["PYTHONIOENCODING"] = "utf-8"

    claude_exe = find_claude_executable()
    cmd = [claude_exe, "--print", "--dangerously-skip-permissions"]

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "claude_prompt.txt").write_text(prompt, encoding="utf-8")

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            env=env,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Claude CLI timeout sau {timeout}s") from exc

    if log_dir is not None:
        (log_dir / "claude_response.txt").write_text(
            f"=== EXIT {result.returncode} ===\n"
            f"=== STDOUT ===\n{result.stdout}\n"
            f"=== STDERR ===\n{result.stderr}\n",
            encoding="utf-8",
        )

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-1500:]
        raise RuntimeError(
            f"Claude CLI lỗi (exit {result.returncode}). "
            f"Stderr:\n{stderr_tail}"
        )

    return result.stdout


def build_auto_prompt(
    image_path: Path,
    image_size: tuple,
    bg_color: tuple,
    duration: float,
    free_hint: str,
    plan_path: Path,
) -> str:
    """Build vision prompt for Claude auto-pick zones.

    Returns the prompt text to send to Claude CLI.
    """
    w, h = image_size
    r, g, b = bg_color
    bg_hex = f"#{r:02x}{g:02x}{b:02x}".upper()

    image_path_forward = str(image_path).replace("\\", "/")
    plan_path_forward = str(plan_path).replace("\\", "/")

    prompt = f"""You are an animation director designing a sticker-reveal animation for an infographic. Execute immediately, do not ask questions.

YOUR ROLE:
- Identify the meaningful "zones" in the image: groups of visual elements that should animate together as one sticker
- Each zone covers one conceptual unit (e.g. a character + its label + its arrow → one zone)
- You decide: which zones, where (bbox), what animation, what timing, what sound

EXECUTION STEPS:
1. Read tool: {image_path_forward}  (open the image)
2. Examine the image carefully — identify the semantic groups
3. Write tool: create JSON file at {plan_path_forward}
4. Respond with only: "Done"

IMAGE METADATA:
- Path: {image_path_forward}
- Dimensions: {w}x{h} (pixel coordinates origin at top-left)
- Background color (solid): RGB({r}, {g}, {b}) — hex {bg_hex}
- Total video duration: {duration}s

USER FREE HINT (follow this carefully):
{free_hint if free_hint else "(none)"}

DEFINE THE BBOX IN TWO PASSES.

PASS 1 — Initial bbox:
- Each bbox is [x1, y1, x2, y2] in image pixel coordinates
- Identify each conceptual unit (a character + label + arrow → one zone)
- Draw a rough rectangle around it including borders/shadows/decorations

PASS 2 — Margin verification (MANDATORY):
After Pass 1, you MUST verify each bbox edge has at least 20 pixels of
clean background between the edge and ANY non-background pixel of the
element. This means:
- Top edge: scan from (x1, y1) downward — first 20 rows must be pure
  background (no shadow, no halo, no element pixel)
- Same check for bottom, left, right
- If any edge fails, EXPAND that edge outward until it passes

Common mistakes to avoid:
- Drop shadows, edges, surplus parts extending outside the visible content
- Halos or glow effects around stickers
- Soft outlines that blur into the background
All of these MUST be inside the bbox. They are part of the element.

ANIMATION CATALOG
=================

ENTRY animations (pick one per zone):
- fade_in        : alpha 0->1, generic safe
- scale_pop      : scales from 0.5 with overshoot, playful
- slide_in_left  : slides from left edge
- slide_in_right : slides from right edge
- slide_in_top   : slides from top
- slide_in_bottom: slides from bottom
- drop_in        : drops from above with bounce, dramatic

EMPHASIS animations (optional, runs after entry completes):
- none           : no emphasis
- pulse          : scale wave 1.0 -> peak -> 1.0
- glow           : warm halo around sticker, alpha pulse
- shake          : wiggle position, decays

SOUNDS (must pick one):
- pop, flip, whoosh, swoosh, ding

NATURAL DURATION DEFAULTS (you can adjust):
- fade_in entry: 0.5s
- scale_pop entry: 0.6s
- slide_in_* entry: 0.6s
- drop_in entry: 0.8s
- pulse emphasis: 0.4s
- glow emphasis: 0.6s
- shake emphasis: 0.4s

YOUR TASK
=========
Generate zone plan JSON conforming to this schema:

{{
  "duration": {duration},
  "zones": [
    {{
      "label": "zone name (short, 1-3 words)",
      "bbox": [x1, y1, x2, y2],
      "animation": "fade_in",
      "emphasis": "none",
      "sound": "pop",
      "appear_at": 0.0,
      "end_at": 0.5,
      "rationale": "why you picked this animation and timing"
    }}
  ]
}}

REQUIREMENTS
============
1. Generate one zone per distinct conceptual unit.
2. Honor the user's free_hint above. Examples of intent:
   - "Zone 1-2 cùng lúc, zone 3 sau" => zone 1 and 2 share appear_at, zone 3 later
   - "Pacing nhanh" => shorter gaps, smaller durations
   - "Pacing chậm rãi" => longer gaps, more breathing room
   - "Zone 2 dramatic" => use drop_in or scale_pop with emphasis
3. appear_at distribution: fit within total duration. Don't cram everything
   in first 2 seconds. Don't leave 3+ seconds of dead time at the end.
   Last zone's end_at should be ~0.5s before total duration.
4. end_at = appear_at + entry_duration + (emphasis_delay + emphasis_duration if emphasis)
5. Pick animation + sound that match the visual intent of each zone
6. Default sound by entry animation when no specific intent:
   fade_in->ding, scale_pop->pop, slide_in_*->swoosh, drop_in->pop
7. Minimum 2 zones, maximum 12 zones per image.

OUTPUT
======
Write the JSON to: {plan_path_forward}

Use the Write tool to create that file. Do not print the JSON to stdout.
After writing, print one line: "Done"
"""

    return prompt


def run_auto_pick(
    image_path: Path,
    image_size: tuple,
    bg_color: tuple,
    duration: float,
    free_hint: str,
    work_dir: Path,
    log_cb=None,
) -> dict:
    """Run Claude auto-pick zones.

    Args:
        image_path: Path to source image
        image_size: (width, height) tuple
        bg_color: (r, g, b) tuple
        duration: video duration in seconds
        free_hint: user hint text
        work_dir: working directory (where Claude can read/write files)
        log_cb: optional callback for progress logs

    Returns:
        dict with 'duration' and 'zones[]' entries
    """
    if log_cb is None:
        log_cb = print

    plan_path = work_dir / "auto_plan.json"
    if plan_path.exists():
        plan_path.unlink()

    log_cb("Building Claude prompt...")
    prompt = build_auto_prompt(
        image_path=image_path,
        image_size=image_size,
        bg_color=bg_color,
        duration=duration,
        free_hint=free_hint,
        plan_path=plan_path,
    )

    log_cb("Calling Claude CLI (30-60s)...")
    # CRITICAL: cwd must be image's parent directory so Claude's Read tool
    # can resolve the image path (we pass absolute path in prompt but cwd
    # is also needed in case prompt resolves relative paths).
    stdout = call_claude(
        prompt=prompt,
        timeout=300,
        log_dir=work_dir,
        cwd=image_path.parent,
    )

    # Try to load the plan file that Claude wrote
    if plan_path.exists():
        log_cb(f"Loading plan from {plan_path.name}...")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        # Fallback: try to extract JSON from stdout
        log_cb("Extracting JSON from stdout...")
        import re
        match = re.search(r"\{.*\}", stdout, re.DOTALL)
        if not match:
            raise RuntimeError("Claude didn't return JSON in stdout or write file")
        plan = json.loads(match.group())

    zones = plan.get("zones") or []
    if not zones:
        raise RuntimeError(
            "Claude không tìm thấy zone nào. Thử viết hint cụ thể hơn."
        )

    log_cb(f"Claude proposed {len(zones)} zone(s)")
    return plan
