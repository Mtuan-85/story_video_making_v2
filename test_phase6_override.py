"""E2E test for render duration override (Phase 6 Step 7 case 4).

Forces SCENE-03 render_mode=custom render_duration=8s. Voice covers 5.98s, so
the audio should be 5.98s of voice + 2.02s of silence pad. Visual should
play for the full 8s.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # noqa: S101

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from render.composite import composite_scene


def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


async def main() -> None:
    project_root = ROOT / "test_live"
    mapping = json.loads((project_root / "voice_mapping.json").read_text(encoding="utf-8"))
    scenes_json = json.loads((project_root / "scenes.json").read_text(encoding="utf-8"))["scenes"]

    sc03 = next(s for s in scenes_json if s["id"] == "SCENE-03")
    vs03 = next(s for s in mapping["scenes"] if s["id"] == "SCENE-03")
    # Set custom override
    vs03["render_mode"] = "custom"
    vs03["custom_duration"] = 8.0
    vs03["render_duration"] = 8.0

    voice_files = mapping["voice_files"]
    state = json.loads((project_root / "state.json").read_text(encoding="utf-8"))
    visual_path = (project_root / state["scenes"]["SCENE-03"]["video"]["path"]).resolve()

    output = project_root / "renders_override" / "SCENE-03.mp4"
    output.parent.mkdir(exist_ok=True)
    await asyncio.to_thread(
        composite_scene,
        scene=sc03,
        voice_scene=vs03,
        visual_path=visual_path,
        voice_files=voice_files,
        project_root=project_root,
        output_path=output,
        width=1920,
        height=1080,
    )
    dur = ffprobe_duration(output)
    voice_dur = vs03["voice_out"] - vs03["voice_in"]
    print(f"  voice_dur={voice_dur:.2f}s, render_duration={vs03['render_duration']:.2f}s")
    print(f"  output: {output.name} ({dur:.2f}s)")
    expected = 8.0
    delta = abs(dur - expected)
    assert delta < 0.15, f"Expected ~{expected}s, got {dur:.2f}s"
    assert dur > voice_dur, "Render must exceed voice duration"
    print(f"\n=== Override case (custom 8s on 5.98s voice): PASS — pad {dur - voice_dur:.2f}s silence ===")


if __name__ == "__main__":
    asyncio.run(main())
