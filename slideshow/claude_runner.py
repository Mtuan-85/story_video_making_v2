"""
Claude Code subprocess runner v3.

Philosophy: Claude is the animation director, not pixel technician.
- CV already did: detect all objects, crop, give positions
- Claude decides: semantic grouping, pacing, animation choice
- Scenes can contain multiple objects (group with same animation + appear_at)
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def find_claude_executable() -> str:
    for name in ("claude", "claude.exe", "claude.cmd"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(
        "Không tìm thấy Claude Code CLI. Cài từ https://claude.com/download"
    )


def build_prompt(scene_path: Path, processed_dir: Path, metadata_path: Path,
                 plan_path: Path, duration: int, canvas_w: int, canvas_h: int,
                 hint: str = "") -> str:
    """Build prompt cho Claude - role: animation director."""

    hint_section = ""
    if isinstance(hint, str) and hint.strip():
        hint_section = f"\nUSER ADJUSTMENT (follow this carefully):\n{hint.strip()}\n"

    # Forward slashes for Windows paths
    scene_p = str(scene_path).replace("\\", "/")
    proc_p = str(processed_dir).replace("\\", "/")
    meta_p = str(metadata_path).replace("\\", "/")
    plan_p = str(plan_path).replace("\\", "/")

    prompt = f"""You are an animation director designing a cinematic slideshow. Execute immediately, do not ask questions.

YOUR CREATIVE ROLE:
- Watch the original scene as a narrative composition
- Examine each pre-cropped object
- Think: "If I were telling this story, what appears first? Together? Last?"
- Group objects that BELONG together semantically (not by position)
- Design a beautiful reveal sequence with variety in animation

EXECUTION STEPS:
1. Read tool: {scene_p}  (the full original scene)
2. Read tool: {meta_p}   (metadata with all objects)
3. Read tool: each PNG in folder {proc_p}
4. Write tool: create JSON file at {plan_p}
5. Respond with only: "Done"

CONTEXT:
- Canvas: {canvas_w}x{canvas_h}, duration {duration}s
- Objects are pre-cropped, pre-positioned by computer vision
- You do NOT decide position or scale - already fixed
- You DO decide: grouping, ordering, pacing, animation choice
{hint_section}

GROUPING RULES (critical):
- Group objects that share semantic meaning:
  * "These 3 arrows are pointing at the same thing" → group
  * "These 2 eyes belong to same face" → group
  * "These bullet points are siblings in a list" → group
  * "Title + subtitle" → group (or separate for dramatic reveal)
  * "These icons form a row/category" → group
- Objects in SAME group:
  * Appear at SAME appear_at time
  * Use SAME animation type
  * Feel like "one unit" in the reveal
- Solo objects get their own scene
- EVERY object from metadata MUST appear in exactly one scene (no duplicates, no skips)

PACING RULES:
- MINIMUM 3 scenes (3 distinct reveal moments) - reject designs with fewer
- First scene at 0.0-0.5s, last scene around {max(0.5, duration - 1)}s
- Space scenes naturally based on narrative weight - important reveals deserve breathing room
- Avoid clustering scenes too close (< 0.3s apart is usually bad)

ANIMATION CHOICE:
Available: fade_pop, slide_left, slide_right, slide_top, slide_bottom, zoom_in

Pick based on:
- Position of the group in source (objects on left half → slide_left makes sense)
- Narrative role (hero reveals → zoom_in; details → fade_pop; directional elements → slide matching direction)
- Variety: DON'T use same animation for every scene - mix at least 2-3 different types

EXACT JSON TO WRITE at {plan_p}:

{{
  "duration": {duration},
  "scenes": [
    {{
      "objects": ["01_obj.png", "02_obj.png"],
      "appear_at": 0.0,
      "animation": "fade_pop",
      "rationale": "Title group — centerpiece, appears together for impact"
    }},
    {{
      "objects": ["03_obj.png"],
      "appear_at": 1.8,
      "animation": "slide_right",
      "rationale": "Main subject emerges, drawing eye to the right"
    }},
    {{
      "objects": ["04_obj.png", "05_obj.png", "06_obj.png"],
      "appear_at": 3.5,
      "animation": "zoom_in",
      "rationale": "Supporting details bloom in unison — finishes the story"
    }}
  ]
}}

FIELD RULES:
- "objects": array of exact filenames from metadata. Single object = ["xxx.png"]. Group = multiple.
- "appear_at": float in [0.0, {duration}]
- "animation": one of the 6 values listed above
- "rationale": 1 short sentence explaining your choice (helps user understand your reasoning)

VALIDATE BEFORE WRITING:
- At least 3 scenes? ✓
- Every object from metadata listed exactly once? ✓
- All appear_at values in range? ✓
- Animations varied (not all same)? ✓

EXECUTE NOW. Read. Think like a director. Write. Done.
"""
    return prompt


def extract_json_from_text(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Không parse được JSON:\n{text[:1000]}")


def run_claude_analyze(folder: Path, scene_path: Path, processed_dir: Path,
                       duration: int, canvas_w: int, canvas_h: int,
                       hint: str = "", timeout: int = 300) -> dict:
    cache_dir = folder / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    plan_path = cache_dir / "plan.json"
    metadata_path = processed_dir / "metadata.json"

    if plan_path.exists():
        plan_path.unlink()

    prompt = build_prompt(
        scene_path=scene_path,
        processed_dir=processed_dir,
        metadata_path=metadata_path,
        plan_path=plan_path,
        duration=duration,
        canvas_w=canvas_w,
        canvas_h=canvas_h,
        hint=hint,
    )

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)

    claude_exe = find_claude_executable()
    cmd = [claude_exe, "--print", "--dangerously-skip-permissions"]

    try:
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(folder),
            timeout=timeout,
            encoding='utf-8',
            errors='replace',
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude Code timeout sau {timeout}s")

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude Code lỗi (exit {result.returncode}):\n"
            f"STDERR: {result.stderr[:1500]}\n"
            f"STDOUT: {result.stdout[:800]}"
        )

    if plan_path.exists():
        try:
            with open(plan_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Plan file tồn tại nhưng parse JSON lỗi: {e}\n"
                f"Xem file: {plan_path}"
            )

    try:
        plan = extract_json_from_text(result.stdout)
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        return plan
    except Exception as e:
        raise RuntimeError(
            f"Claude không tạo được plan.\nError: {e}\n\n"
            f"Output:\n{result.stdout[-2000:]}"
        )


def validate_plan(plan: dict, available_objects: list, duration: int,
                  min_scenes: int = 3) -> None:
    """Validate v3 plan: scenes có array 'objects'."""
    from animations import SUPPORTED_ANIMATIONS

    if "scenes" not in plan or not isinstance(plan["scenes"], list):
        raise ValueError("Plan thiếu 'scenes' array")

    if len(plan["scenes"]) < min_scenes:
        raise ValueError(
            f"Plan chỉ có {len(plan['scenes'])} scenes, yêu cầu tối thiểu {min_scenes}. "
            f"Claude cần group ít dừng lại hơn hoặc thêm scenes riêng."
        )

    available_set = set(available_objects)
    used = set()

    for i, scene in enumerate(plan["scenes"]):
        # Support both "objects" (v3) and "object" (v2 legacy)
        if "objects" in scene:
            objs = scene["objects"]
            if not isinstance(objs, list) or len(objs) == 0:
                raise ValueError(f"Scene {i}: 'objects' phải là array non-empty")
        elif "object" in scene:
            # Legacy v2 format → convert
            objs = [scene["object"]]
            scene["objects"] = objs
        else:
            raise ValueError(f"Scene {i}: thiếu 'objects' array")

        for field in ("appear_at", "animation"):
            if field not in scene:
                raise ValueError(f"Scene {i}: thiếu field '{field}'")

        for obj_fn in objs:
            if obj_fn not in available_set:
                raise ValueError(
                    f"Scene {i}: object '{obj_fn}' không tồn tại.\n"
                    f"Available: {sorted(available_set)}"
                )
            if obj_fn in used:
                raise ValueError(
                    f"Scene {i}: object '{obj_fn}' bị duplicate (đã dùng ở scene trước)"
                )
            used.add(obj_fn)

        if scene["animation"] not in SUPPORTED_ANIMATIONS:
            raise ValueError(
                f"Scene {i}: animation '{scene['animation']}' không support.\n"
                f"Available: {SUPPORTED_ANIMATIONS}"
            )

        if not (0 <= scene["appear_at"] <= duration):
            raise ValueError(
                f"Scene {i}: appear_at {scene['appear_at']} ngoài [0, {duration}]"
            )

    unused = available_set - used
    if unused:
        raise ValueError(
            f"Plan BỎ SÓT {len(unused)} objects: {sorted(unused)}. "
            f"Claude phải include TẤT CẢ objects."
        )
