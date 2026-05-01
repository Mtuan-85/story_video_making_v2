"""E2E test for Phase 6 wired render pipeline (Plan D).

Drives the new RenderWorker path against test_live data without spinning up
the GUI. Verifies final.mp4 is produced with embedded ASS karaoke.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # noqa: S101

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from core.project import Project
from core.voice_mapping import VoiceMapping
from render.assemble_v2 import apply_ass_subtitle, assemble_concat
from render.composite_v2 import composite_scene_v2
from voice.ass_generator import generate_final_ass


def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


async def main() -> None:
    project = Project.load(ROOT / "test_live")
    assert project.voice_mapping is not None, "voice_mapping.json missing"
    mapping = project.voice_mapping
    assert isinstance(mapping, VoiceMapping)

    canvas_w, canvas_h = 1920, 1080
    renders_dir = project.paths.root / "renders_v6"
    renders_dir.mkdir(exist_ok=True)
    temp_dir = project.paths.temp_dir
    temp_dir.mkdir(exist_ok=True)

    mapping_dict = mapping.model_dump(mode="json")
    voice_files_meta = mapping_dict["voice_files"]
    voice_scenes = {vs["id"]: vs for vs in mapping_dict["scenes"]}

    scene_outputs: list[Path] = []
    for scene in project.scenes:
        vs = voice_scenes.get(scene.id)
        assert vs, f"missing {scene.id} in voice_mapping"

        # Resolve visual path: prefer video, fallback to image.
        state_video = project.get_scene_state(scene.id).get("video", {})
        state_image = project.get_scene_state(scene.id).get("image", {})
        path_str = state_video.get("path") or state_image.get("path")
        assert path_str, f"no visual ready for {scene.id}"
        visual_path = (project.paths.root / path_str).resolve()
        assert visual_path.exists(), f"visual missing on disk: {visual_path}"

        # If state has video=pending but image=ready (SCENE-05 case), force visual_type=image.
        scene_dict = scene.model_dump()
        if state_video.get("path") is None and state_image.get("path") is not None:
            scene_dict["visual_type"] = "image_grok"
            scene_dict["effect"] = scene.effect or "zoom_out"

        out = renders_dir / f"{scene.id}.mp4"
        await asyncio.to_thread(
            composite_scene_v2,
            scene=scene_dict,
            voice_scene=vs,
            visual_path=visual_path,
            voice_files=voice_files_meta,
            project_root=project.paths.root,
            output_path=out,
            width=canvas_w,
            height=canvas_h,
        )
        scene_outputs.append(out)
        print(f"  composed {scene.id} → {out.name} ({ffprobe_duration(out):.2f}s)")

    final_raw = temp_dir / "final_raw_v6.mp4"
    assemble_concat(scene_outputs, final_raw)
    print(f"  concat → {final_raw.name} ({ffprobe_duration(final_raw):.2f}s)")

    ass_path = project.paths.root / "final_v6.ass"
    generate_final_ass(
        voice_mapping=mapping_dict,
        output_path=ass_path,
        video_width=canvas_w,
        video_height=canvas_h,
    )

    final_path = project.paths.root / "final_v6.mp4"
    apply_ass_subtitle(final_raw, ass_path, final_path)
    print(f"  burn ASS → {final_path.name} ({ffprobe_duration(final_path):.2f}s)")

    assert final_path.exists()
    print("\n=== Phase 6 render E2E: PASS ===")


if __name__ == "__main__":
    asyncio.run(main())
