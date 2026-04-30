# Phase 5 — Render: Extend/Speedup + 2-Pass ASS Apply

> **Goal**: Render scenes với fit-to-voice duration + apply ASS subtitle.
> **Effort**: 2-3h

---

## Logic flow

```
1. Per scene composite (NO subtitle yet):
   - Visual: extend hoặc speedup theo duration_adjusted
   - Effect: zoom in/out apply lúc này
   - Voice slice: extract từ voice files theo voice_in/voice_out
   - Output: renders/{scene_id}.mp4

2. Assemble (concat) → final_raw.mp4

3. Generate final.ass (Phase 4)

4. Apply ASS to final_raw.mp4 → final.mp4

5. Cleanup final_raw.mp4
```

---

## Module: `render/visual_fit.py` (NEW)

```python
"""
Visual fit-to-duration: extend hoặc speedup based on visual_type.

For image_grok / slideshow_v4: zoompan duration = duration_adjusted (auto fit).
For video_grok:
  - duration_adjusted < design: setpts speedup
  - duration_adjusted > design: tpad freeze last frame
"""

from loguru import logger as log


# Visual config
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920  # 9:16 portrait
FPS = 30
ZOOM_RANGE = 0.2  # 1.0 → 1.2
TOLERANCE = 0.1   # within 0.1s of design → no fit


def build_zoom_filter(
    effect: str,
    duration_sec: float,
    fps: int = FPS,
    width: int = VIDEO_WIDTH,
    height: int = VIDEO_HEIGHT,
) -> str:
    """Build zoompan filter for image/slideshow."""
    
    if effect == "no_effect":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    
    total_frames = int(duration_sec * fps)
    zoom_target = 1.0 + ZOOM_RANGE
    
    if effect == "zoom_in":
        per_frame = ZOOM_RANGE / total_frames
        z_expr = f"min(zoom+{per_frame:.6f},{zoom_target})"
    elif effect == "zoom_out":
        per_frame = ZOOM_RANGE / total_frames
        z_expr = f"if(eq(on,0),{zoom_target},max(zoom-{per_frame:.6f},1.0))"
    else:
        # Fallback no_effect
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
        )
    
    return (
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={width}x{height}:fps={fps},"
        f"setsar=1"
    )


def build_visual_filter_with_fit(
    visual_type: str,
    duration_design: float,
    duration_adjusted: float,
    effect: str,
) -> tuple[str, list[str]]:
    """
    Build visual filter + extra ffmpeg input args.
    
    Returns:
        (filter_string, input_extra_args)
    """
    
    extra_args = []
    
    # Within tolerance: no fit needed
    if abs(duration_adjusted - duration_design) < TOLERANCE:
        if visual_type in ("image_grok", "slideshow_v4"):
            filter_str = build_zoom_filter(effect, duration_adjusted)
        else:  # video_grok
            filter_str = build_zoom_filter(effect, duration_adjusted)
        return filter_str, extra_args
    
    # Need fit
    if visual_type == "video_grok":
        if duration_adjusted < duration_design:
            # Speedup video
            pts_factor = duration_adjusted / duration_design
            log.info(
                f"Video speedup: design={duration_design}s, voice={duration_adjusted}s, "
                f"setpts={pts_factor:.3f}*PTS"
            )
            filter_parts = [f"setpts={pts_factor:.4f}*PTS"]
        else:
            # Extend = freeze last frame
            extra_duration = duration_adjusted - duration_design
            log.info(
                f"Video extend: design={duration_design}s, voice={duration_adjusted}s, "
                f"freeze last frame +{extra_duration:.2f}s"
            )
            filter_parts = [f"tpad=stop_mode=clone:stop_duration={extra_duration:.3f}"]
        
        # Add zoom effect on top
        zoom_part = build_zoom_filter(effect, duration_adjusted)
        if zoom_part != "":
            # zoompan replaces input timing, so combine differently
            # Strategy: speedup/extend FIRST, then zoom on resulting frames
            filter_parts.append(zoom_part)
        
        filter_str = ",".join(filter_parts)
        return filter_str, extra_args
    
    elif visual_type in ("image_grok", "slideshow_v4"):
        # zoompan handles duration fit automatically (just adjust d=)
        filter_str = build_zoom_filter(effect, duration_adjusted)
        return filter_str, extra_args
    
    else:
        # Unknown visual_type, fallback
        log.warning(f"Unknown visual_type {visual_type}, using fallback")
        return build_zoom_filter("no_effect", duration_adjusted), extra_args
```

---

## Module: `render/voice_slicer.py` (NEW)

```python
"""
Slice voice audio cho 1 scene từ multiple voice files.

Strategy: ffmpeg concat demuxer ghép voice files trên-fly,
sau đó atrim slice theo voice_in/voice_out global timestamps.
"""

import tempfile
from pathlib import Path
from loguru import logger as log


def build_voice_concat_list(voice_files: list[dict], project_root: Path) -> Path:
    """
    Build concat demuxer list file.
    
    Format:
    ```
    file 'C:/path/voice1.mp3'
    file 'C:/path/voice2.mp3'
    ```
    """
    list_file = Path(tempfile.mkdtemp()) / "voice_concat.txt"
    
    lines = []
    for vf in voice_files:
        # Use absolute path with forward slashes
        full_path = (project_root / "voice" / vf["file"]).resolve()
        path_str = str(full_path).replace("\\", "/")
        # Escape single quotes in path (rare)
        path_str = path_str.replace("'", "\\'")
        lines.append(f"file '{path_str}'")
    
    list_file.write_text("\n".join(lines), encoding="utf-8")
    return list_file


def get_voice_slice_args(
    voice_files: list[dict],
    voice_in: float,
    voice_out: float,
    project_root: Path,
) -> tuple[list[str], Path]:
    """
    Build ffmpeg args to use sliced voice as audio input.
    
    Returns:
        (input_args, concat_list_file_to_cleanup)
    """
    concat_list = build_voice_concat_list(voice_files, project_root)
    
    input_args = [
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
    ]
    
    # Audio filter to slice
    duration = voice_out - voice_in
    audio_filter = f"atrim=start={voice_in}:duration={duration},asetpts=PTS-STARTPTS"
    
    return input_args, audio_filter, concat_list


def get_silent_audio_args(duration: float) -> tuple[list[str], str]:
    """Generate silent audio for silent scene."""
    input_args = [
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(duration),
    ]
    audio_filter = "anull"
    return input_args, audio_filter
```

---

## Module: `render/composite.py` (REWRITE)

```python
"""
Composite scene: visual + voice slice (NO subtitle, applied later in 2-pass).
"""

import subprocess
from pathlib import Path
from loguru import logger as log

from render.visual_fit import build_visual_filter_with_fit, VIDEO_WIDTH, VIDEO_HEIGHT, FPS
from render.voice_slicer import (
    get_voice_slice_args,
    get_silent_audio_args,
)


def composite_scene(
    scene: dict,                # scenes.json scene dict
    voice_scene: dict,          # voice_mapping scene dict
    visual_path: Path,          # path to image/video file
    voice_files: list[dict],    # voice_mapping voice_files
    project_root: Path,
    output_path: Path,
) -> Path:
    """
    Composite 1 scene: visual + voice slice (NO subtitle).
    
    Output: scene_{id}.mp4 with correct duration_adjusted timing.
    """
    
    duration_adjusted = voice_scene["duration_adjusted"]
    duration_design = voice_scene["duration_original"]
    visual_type = scene["visual_type"]
    effect = scene.get("effect", "no_effect")
    
    log.info(
        f"Composite {scene['id']}: "
        f"visual={visual_type}, effect={effect}, "
        f"design={duration_design}s, adjusted={duration_adjusted}s"
    )
    
    # Visual filter
    visual_filter, _ = build_visual_filter_with_fit(
        visual_type, duration_design, duration_adjusted, effect
    )
    
    # Visual input
    if visual_type in ("image_grok", "slideshow_v4"):
        # Static image + loop
        visual_input = ["-loop", "1", "-i", str(visual_path)]
    else:
        # Video file
        visual_input = ["-i", str(visual_path)]
    
    # Audio input
    cleanup_files = []
    if voice_scene.get("is_silent"):
        audio_input, audio_filter = get_silent_audio_args(duration_adjusted)
    else:
        audio_input, audio_filter, concat_list = get_voice_slice_args(
            voice_files=voice_files,
            voice_in=voice_scene["voice_in"],
            voice_out=voice_scene["voice_out"],
            project_root=project_root,
        )
        cleanup_files.append(concat_list)
    
    # Build filter_complex
    filter_complex = (
        f"[0:v]{visual_filter}[v];"
        f"[1:a]{audio_filter}[a]"
    )
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        *visual_input,
        *audio_input,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-t", str(duration_adjusted),
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", str(FPS),
        str(output_path),
    ]
    
    log.debug(f"FFmpeg cmd: {' '.join(cmd[:10])}...")
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    # Cleanup temp files
    for f in cleanup_files:
        try:
            f.unlink()
            f.parent.rmdir()
        except Exception:
            pass
    
    if result.returncode != 0:
        log.error(f"Composite {scene['id']} failed: {result.stderr[-1000:]}")
        raise RuntimeError(f"FFmpeg composite failed for {scene['id']}")
    
    log.info(f"  → {output_path.name}")
    return output_path
```

---

## Module: `render/assemble.py` (UPDATE)

```python
"""
Assemble all scene composites into final video.
2-pass: assemble → apply ASS.
"""

import subprocess
import tempfile
from pathlib import Path
from loguru import logger as log


def assemble_concat(scene_paths: list[Path], output_path: Path) -> Path:
    """Concat scene videos (no transitions, hard cuts)."""
    
    if not scene_paths:
        raise ValueError("No scenes to assemble")
    
    # Build concat list file
    list_file = Path(tempfile.mkdtemp()) / "concat_list.txt"
    lines = [f"file '{p.resolve().as_posix()}'" for p in scene_paths]
    list_file.write_text("\n".join(lines), encoding="utf-8")
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",  # stream copy, no re-encode (fast)
        str(output_path),
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    try:
        list_file.unlink()
        list_file.parent.rmdir()
    except Exception:
        pass
    
    if result.returncode != 0:
        log.error(f"Assemble failed: {result.stderr[-1000:]}")
        raise RuntimeError("FFmpeg assemble failed")
    
    log.info(f"Assembled: {output_path.name}")
    return output_path


def apply_ass_subtitle(
    input_video: Path,
    ass_path: Path,
    output_video: Path,
) -> Path:
    """
    Apply ASS subtitle to video (re-encode video, copy audio).
    """
    
    if not ass_path.exists():
        log.warning(f"ASS file not found: {ass_path}, skip subtitle")
        # Just copy input → output
        import shutil
        shutil.copy(input_video, output_video)
        return output_video
    
    # Escape ASS path for ffmpeg subtitles filter
    # On Windows: backslash → forward slash, escape colon
    ass_safe = str(ass_path.resolve()).replace("\\", "/")
    ass_safe = ass_safe.replace(":", "\\:")
    
    output_video.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_video),
        "-vf", f"subtitles='{ass_safe}'",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "copy",  # don't re-encode audio
        str(output_video),
    ]
    
    log.info(f"Applying ASS subtitle...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    
    if result.returncode != 0:
        log.error(f"Apply ASS failed: {result.stderr[-1000:]}")
        raise RuntimeError("FFmpeg apply ASS failed")
    
    log.info(f"  → {output_video.name}")
    return output_video
```

---

## Module: `workers/render_worker.py` (UPDATE)

```python
"""
Full render orchestration: 2-pass with ASS apply.
"""

from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from workers._async_thread import AsyncTaskWorker
from render.composite import composite_scene
from render.assemble import assemble_concat, apply_ass_subtitle
from voice.ass_generator import generate_final_ass


class RenderWorker(AsyncTaskWorker):
    progress_update = pyqtSignal(int, int, str)  # current, total, message
    render_done = pyqtSignal(str)  # output path
    render_failed = pyqtSignal(str)
    
    def __init__(self, project, voice_mapping):
        super().__init__()
        self.project = project
        self.voice_mapping = voice_mapping
    
    async def run(self):
        try:
            scenes = self.project.scenes_json.scenes
            voice_scenes = self.voice_mapping["scenes"]
            voice_files = self.voice_mapping["voice_files"]
            project_root = self.project.paths.root
            renders_dir = project_root / "renders"
            renders_dir.mkdir(exist_ok=True)
            
            total = len(scenes)
            
            # === PASS 1: Composite each scene (NO subtitle) ===
            scene_paths = []
            for i, scene_obj in enumerate(scenes):
                scene_id = scene_obj.id
                
                # Find matching voice scene
                vs = next((s for s in voice_scenes if s["id"] == scene_id), None)
                if not vs:
                    log.error(f"{scene_id}: not in voice_mapping, skip")
                    continue
                
                # Get visual path
                visual_path = self._get_visual_path(scene_obj)
                if not visual_path or not visual_path.exists():
                    log.error(f"{scene_id}: visual not found, skip")
                    continue
                
                self.progress_update.emit(
                    i + 1, total,
                    f"Composite {scene_id}..."
                )
                
                output = renders_dir / f"{scene_id}.mp4"
                composite_scene(
                    scene=scene_obj.model_dump(),
                    voice_scene=vs,
                    visual_path=visual_path,
                    voice_files=voice_files,
                    project_root=project_root,
                    output_path=output,
                )
                scene_paths.append(output)
            
            # === PASS 2: Assemble (concat) ===
            self.progress_update.emit(total, total, "Assembling...")
            final_raw = project_root / "final_raw.mp4"
            assemble_concat(scene_paths, final_raw)
            
            # === PASS 3: Generate ASS ===
            self.progress_update.emit(total, total, "Generating subtitles...")
            ass_path = project_root / "final.ass"
            generate_final_ass(
                voice_mapping=self.voice_mapping,
                output_path=ass_path,
                video_width=1080,
                video_height=1920,
            )
            
            # === PASS 4: Apply ASS ===
            self.progress_update.emit(total, total, "Applying subtitles...")
            final_path = project_root / "final.mp4"
            apply_ass_subtitle(final_raw, ass_path, final_path)
            
            # Cleanup intermediate
            try:
                final_raw.unlink()
            except Exception:
                pass
            
            self.render_done.emit(str(final_path))
        
        except Exception as e:
            log.error(f"Render failed: {e}")
            self.render_failed.emit(str(e))
    
    def _get_visual_path(self, scene_obj) -> Path | None:
        """Get visual path from project state."""
        scene_state = self.project.state["scenes"].get(scene_obj.id, {})
        selected = scene_state.get("selected_visual", "image")
        
        if selected == "image":
            path_str = scene_state.get("image", {}).get("path")
        elif selected == "video":
            path_str = scene_state.get("video", {}).get("path")
        else:
            return None
        
        if not path_str:
            return None
        
        full = self.project.paths.root / path_str
        return full if full.exists() else None
```

---

## Test plan

### Test 1: Composite single scene (image)

```python
from render.composite import composite_scene
from pathlib import Path

scene = {"id": "TEST", "visual_type": "image_grok", "effect": "zoom_in"}
voice_scene = {
    "duration_original": 5.0,
    "duration_adjusted": 5.0,
    "is_silent": False,
    "voice_in": 0.0,
    "voice_out": 5.0,
}

composite_scene(
    scene=scene,
    voice_scene=voice_scene,
    visual_path=Path("test_run/sources/pic1.jpg"),
    voice_files=[{"file": "voice1..mp3", "duration": 29.88, "offset": 0.0}],
    project_root=Path("test_run"),
    output_path=Path("/tmp/test_scene.mp4"),
)

# Verify output
assert Path("/tmp/test_scene.mp4").exists()
# Use ffprobe to verify duration
```

### Test 2: Composite với extend (voice dài hơn design)

```python
scene = {"id": "TEST", "visual_type": "video_grok", "effect": "no_effect"}
voice_scene = {
    "duration_original": 5.0,
    "duration_adjusted": 8.0,  # extend 3s
    ...
}
# Expect: video freeze last frame for 3s
```

### Test 3: Composite với speedup (voice ngắn hơn design)

```python
voice_scene = {
    "duration_original": 8.0,
    "duration_adjusted": 5.0,  # speedup
    ...
}
# Expect: video speedup ~1.6x
```

### Test 4: Full pipeline với voice hiện tại

```python
import asyncio
from workers.render_worker import RenderWorker

# Setup project with current test_run
# Run render
# Verify final.mp4 exists, total duration = sum of duration_adjusted
```

### Test 5: Verify ASS apply

After render, play `final.mp4`:
- Verify subtitles hiện đúng (karaoke yellow fill)
- Verify timing match voice
- Verify audio sync với visual

---

## Build order

1. Create `render/visual_fit.py` (45 phút)
2. Create `render/voice_slicer.py` (45 phút)
3. Rewrite `render/composite.py` (45 phút)
4. Update `render/assemble.py` (30 phút)
5. Update `workers/render_worker.py` (30 phút)
6. Test 1 + 2 + 3 (30 phút)
7. Test 4 full pipeline (30 phút)
8. Tweak nếu cần
9. Commit

**Total: ~3-4h**

---

## Confirm trước khi code

- [ ] Phase 4 đã build xong (ASS generator work)
- [ ] voice_mapping.json hiện tại có data đúng sau Phase 3
- [ ] Test scenes có đủ image_grok + video_grok + slideshow_v4 để cover all paths
- [ ] FFmpeg có libx264, libass enabled

→ Build xong → Phase 6 (UI cleanup).
