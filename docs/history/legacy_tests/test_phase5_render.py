"""Phase 5 — e2e render driver on test_run.

Walks scenes.json + voice_mapping.json + state.json, runs composite per
scene, concats, applies the ASS file from Phase 4. No worker / qasync — this
is a synchronous test driver.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from render.assemble import apply_ass_subtitle, assemble_concat
from render.composite import composite_scene
from render.visual_fit import aspect_to_size
from voice.ass_generator import generate_final_ass

ROOT = Path("test_run")
WIDTH, HEIGHT = aspect_to_size("16:9")  # 1920x1080
RENDERS_V2 = ROOT / "renders_v2"


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def main() -> None:
    scenes_json = json.loads((ROOT / "scenes.json").read_text(encoding="utf-8"))
    voice_mapping = json.loads((ROOT / "voice_mapping.json").read_text(encoding="utf-8"))
    state = json.loads((ROOT / "state.json").read_text(encoding="utf-8"))

    scenes = scenes_json["scenes"]
    voice_scenes_by_id = {vs["id"]: vs for vs in voice_mapping["scenes"]}
    voice_files = voice_mapping["voice_files"]

    if RENDERS_V2.exists():
        shutil.rmtree(RENDERS_V2)
    RENDERS_V2.mkdir(parents=True)

    print(f"Render canvas: {WIDTH}x{HEIGHT}")
    print(f"Scenes: {len(scenes)}")

    rendered_paths = []
    summary = []
    t0 = time.time()

    for sc in scenes:
        sid = sc["id"]
        vs = voice_scenes_by_id.get(sid)
        if not vs:
            print(f"  {sid}: SKIP (not in voice_mapping)")
            continue

        ss = state["scenes"].get(sid, {})
        img = ss.get("image", {}) or {}
        vid = ss.get("video", {}) or {}
        img_path = ROOT / img["path"] if img.get("path") else None
        vid_path = ROOT / vid["path"] if vid.get("path") else None

        # Decide visual: prefer video if scene.visual_type==video_grok and vid_path ready,
        # otherwise treat as image (covers slideshow + image_grok).
        if sc.get("visual_type") == "video_grok" and vid_path and vid_path.exists():
            scene_for_composite = {
                "id": sid,
                "visual_type": "video_grok",
                "effect": sc.get("effect", "no_effect"),
            }
            visual_path = vid_path
            kind = "video"
        elif img_path and img_path.exists():
            scene_for_composite = {
                "id": sid,
                "visual_type": "image_grok",
                "effect": sc.get("effect", "no_effect"),
            }
            visual_path = img_path
            kind = "image"
        else:
            print(f"  {sid}: SKIP (no usable visual)")
            continue

        out = RENDERS_V2 / f"{sid}.mp4"
        composite_scene(
            scene=scene_for_composite,
            voice_scene=vs,
            visual_path=visual_path,
            voice_files=voice_files,
            project_root=ROOT,
            output_path=out,
            width=WIDTH,
            height=HEIGHT,
        )
        actual = probe_duration(out)
        target = vs["duration_adjusted"]
        summary.append((sid, kind, target, round(actual, 3)))
        rendered_paths.append(out)
        print(f"  {sid} [{kind}]: target={target}s actual={actual:.3f}s -> {out.name}")

    t_composite = time.time() - t0
    print(f"\nCompositing took {t_composite:.1f}s")

    # === Assemble ===
    final_raw = ROOT / "final_v2_raw.mp4"
    if final_raw.exists():
        final_raw.unlink()
    assemble_concat(rendered_paths, final_raw)
    raw_dur = probe_duration(final_raw)
    expected_total = sum(vs["duration_adjusted"] for vs in voice_mapping["scenes"]
                         if vs["id"] in {sid for sid, *_ in summary})
    print(f"final_v2_raw.mp4: {raw_dur:.3f}s (expected ~{expected_total:.3f}s)")
    assert abs(raw_dur - expected_total) < 0.5, f"duration mismatch: {raw_dur} vs {expected_total}"

    # === ASS gen ===
    ass_path = ROOT / "final_v2.ass"
    generate_final_ass(voice_mapping, ass_path, video_width=WIDTH, video_height=HEIGHT)

    # === ASS apply ===
    final_v2 = ROOT / "final_v2.mp4"
    if final_v2.exists():
        final_v2.unlink()
    apply_ass_subtitle(final_raw, ass_path, final_v2)
    final_dur = probe_duration(final_v2)
    print(f"\nfinal_v2.mp4: {final_dur:.3f}s, size={final_v2.stat().st_size // 1024} KB")

    # cleanup intermediate
    final_raw.unlink()

    print("\nSummary:")
    for sid, kind, target, actual in summary:
        delta = abs(actual - target)
        flag = "OK" if delta < 0.15 else f"OFF by {delta:.2f}s"
        print(f"  {sid:8s} [{kind:5s}] target={target:5.2f}s  actual={actual:6.3f}s  {flag}")

    assert all(abs(a - t) < 0.5 for _, _, t, a in summary), "scene duration drift > 0.5s"
    print("\n[PHASE 5 E2E PASS]")


if __name__ == "__main__":
    main()
