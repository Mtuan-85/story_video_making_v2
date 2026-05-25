# Sprint Spec 2 v3 — Production Kdenlive / MLT XML Export

## 0. Status

This spec supersedes the earlier MVP-style version. It is intended for production implementation.

Main corrections from earlier draft:

```text
1. Always export beat_pause as a separate visible clip.
   - Do not silently extend the previous scene clip.
   - Separate pause clip is better for manual editing.

2. Master audio stays intact on A1 by default.
   - No per-scene audio slicing in v1 production export.

3. Scene visuals are separate clips on V1.
   - Each clip name must include scene_id.
   - Beat pauses must include beat_id.

4. Final timeline duration must match master audio duration.

5. Slideshow is treated as pre-rendered video.
```

---

# 1. Objective

Convert `voice_matching_timeline.json` from Sprint 1 into an editable Kdenlive project.

Output:

```text
project_name.kdenlive
```

or:

```text
project_name.mlt
```

The project must be editable manually in Kdenlive.

---

# 2. Core Principle

```text
Do not flatten the video too early.
Export an editable timeline:
    A1 = master audio
    V1 = scene visual clips + beat pause clips
    markers = beat/scene/pause boundaries
```

---

# 3. Input Contract

The exporter consumes:

```text
outputs/voice_matching_timeline.json
```

Expected root structure:

```json
{
  "project_id": "Naomi_01",
  "fps": 30,
  "width": 1280,
  "height": 720,
  "audio_master": "outputs/master_voice.wav",
  "total_duration": 123.45,
  "beats": [],
  "timeline": [],
  "markers": [],
  "diagnostics": {}
}
```

Timeline item types:

```text
scene
beat_pause
```

Future item types:

```text
subtitle
overlay
music
sfx
transition
```

---

# 4. Output Project Structure

Recommended output folder:

```text
exports/kdenlive/
  Naomi_01.kdenlive
  project_assets/
  generated/
    freeze_frames/
    placeholders/
```

The Kdenlive project should reference project-relative paths whenever possible.

---

# 5. Track Layout

Required tracks:

```text
V2 — optional subtitles / overlays / labels
V1 — main visual clips
A1 — master voice audio
A2 — optional music / SFX
```

Minimum production v1:

```text
V1 + A1
```

---

# 6. Audio Export Strategy

## 6.1 Default: Master Audio Mode

Place `master_voice.wav` as one continuous audio clip on A1.

```text
A1: master_voice.wav from 0.00s → total_duration
```

Do not slice audio by scene in v1.

Reason:

```text
- Stable sync
- Simpler XML
- Easier manual editing
- Avoids many small audio clips
```

## 6.2 Validation

Before export:

```text
ffprobe(master_voice.wav) duration ≈ timeline.total_duration
```

Tolerance:

```text
±0.05s or ±1 frame
```

If mismatch:

```text
Fail export in strict mode.
Warn in development mode.
```

---

# 7. Visual Clip Strategy

Each timeline item with `type="scene"` becomes one V1 clip.

Required fields:

```json
{
  "type": "scene",
  "scene_id": "SCENE-01",
  "render_in": 0.00,
  "render_out": 2.81,
  "visual_type": "image",
  "visual_source": "sources/SCENE-01.jpg"
}
```

## 7.1 Image scene

```text
Use pixbuf/image producer.
Place image from render_in to render_out.
Clip name = SCENE-01.
```

## 7.2 Video scene

```text
Use avformat/video producer.
Place clip from render_in to render_out.
If source longer than target:
    trim source.
If source shorter than target:
    use configured fit policy.
```

## 7.3 Slideshow scene

Slideshow is pre-rendered as MP4.

```text
visual_type = video
visual_source = sources/{scene_id}.mp4
```

No special exporter path.

## 7.4 Silent scene

Silent scene is still a visual clip.

```text
Place its visual_source on V1.
Duration = allocated timeline duration.
No separate audio clip is needed because A1 master audio already contains silence or available gap.
```

---

# 8. Visual Fit Policy

The exporter must support explicit visual fit policy.

Recommended config:

```json
{
  "video_fit_policy": "trim_or_freeze_tail",
  "image_fit_policy": "hold",
  "missing_asset_policy": "placeholder"
}
```

Allowed video policies:

```text
trim
freeze_tail
speed_adjust
trim_or_freeze_tail
```

Recommended default:

```text
trim_or_freeze_tail
```

## 8.1 Video shorter than target

If source duration < target duration:

```text
1. Place video source for its full duration.
2. Generate freeze frame from last frame.
3. Place freeze frame for remaining duration.
```

Alternative:

```text
speed_adjust
```

but this is not recommended as default for manual edit because it changes video motion.

## 8.2 Video longer than target

Trim to target duration.

## 8.3 Image

Hold image for target duration.

---

# 9. Beat Pause Export

Beat pause must always be visible and editable.

Hard rule:

```text
Always export beat_pause as a separate V1 clip.
Do not silently extend the previous scene clip.
```

Input:

```json
{
  "type": "beat_pause",
  "beat_id": "beat-01",
  "after_scene_id": "SCENE-03",
  "render_in": 8.42,
  "render_out": 8.92,
  "duration": 0.50,
  "visual_policy": "freeze_tail"
}
```

## 9.1 If previous scene is image

```text
Reuse the same image source as a new separate clip.
Clip name = beat-01_pause
```

## 9.2 If previous scene is video or slideshow

Generate freeze frame:

```text
generated/freeze_frames/SCENE-03_freeze.jpg
```

Example command:

```bash
ffmpeg -y -sseof -0.1 -i sources/SCENE-03.mp4 -frames:v 1 generated/freeze_frames/SCENE-03_freeze.jpg
```

Then place freeze image as V1 clip:

```text
render_in = beat_pause.render_in
render_out = beat_pause.render_out
clip name = beat-01_pause
```

## 9.3 If freeze frame generation fails

Fallback:

```text
Use black placeholder image named beat-01_pause_missing_freeze.jpg
Warn in diagnostics.
```

---

# 10. Asset Registry

Build a registry before writing XML.

Required asset types:

```text
- master audio
- scene images
- scene videos
- freeze frames
- placeholders
```

Example:

```json
{
  "asset_id": "asset_SCENE_01_visual",
  "path": "sources/SCENE-01.jpg",
  "type": "image",
  "exists": true
}
```

Validation:

```text
- Every scene visual_source must exist or placeholder must be generated.
- Every freeze frame path must exist before XML write.
- master_voice.wav must exist.
```

---

# 11. Placeholder Policy

Config:

```json
{
  "missing_asset_policy": "placeholder"
}
```

Allowed values:

```text
strict
placeholder
```

## strict

Fail export if any asset is missing.

## placeholder

Generate placeholder image:

```text
generated/placeholders/SCENE-12_placeholder.jpg
```

The placeholder should show:

```text
SCENE-12
Missing visual source
Expected: sources/SCENE-12.mp4
```

---

# 12. Time Conversion

Intermediate timeline uses seconds.

Kdenlive/MLT export should use frames consistently.

```python
def sec_to_frame(sec: float, fps: int) -> int:
    return int(round(sec * fps))
```

Clip frames:

```python
start_frame = sec_to_frame(render_in, fps)
end_frame = sec_to_frame(render_out, fps)
duration_frames = end_frame - start_frame
```

Validation:

```python
if duration_frames < 1:
    warn_or_skip("clip_too_short")
```

For MLT `out` fields, confirm whether the implementation uses inclusive or exclusive frame indexing. Store this in one utility function and never duplicate time math in multiple places.

---

# 13. MLT/Kdenlive Builder Requirements

The XML builder must:

```text
1. Create project profile:
   - width
   - height
   - fps
   - progressive/interlaced config

2. Register producers:
   - master audio
   - each unique scene visual source
   - generated freeze frames
   - placeholders

3. Create playlists/tracks:
   - V1 playlist
   - optional V2 playlist
   - A1 playlist
   - optional A2 playlist

4. Insert clips:
   - scene clips on V1
   - beat_pause clips on V1
   - master audio on A1

5. Insert markers/guides:
   - beat start
   - beat end
   - scene start
   - pause start

6. Save XML.
```

---

# 14. Markers / Guides

Markers are required for manual editing.

Generate markers for:

```text
- every beat.voice_in
- every beat.voice_out
- every beat.pause_in where pause_after_sec > 0
- every scene.render_in
```

Marker naming:

```text
BEAT beat-01 — hook — insightful_teaching
BEAT-END beat-01
SCENE SCENE-01
PAUSE beat-01 — 0.5s
```

If Kdenlive guide color is supported, use:

```text
beat     = blue
scene    = green
pause    = orange
warning  = red
```

---

# 15. Clip Naming

Every exported clip must be human-readable.

Required naming:

```text
SCENE-01
SCENE-02
SCENE-03
beat-01_pause
SCENE-12_placeholder
```

Do not use only internal producer IDs as visible clip names.

---

# 16. Validation Before XML Export

The exporter must validate:

```text
- timeline JSON schema is valid
- audio_master exists
- audio duration ≈ total_duration
- each item has render_in/render_out
- render_out > render_in
- each visual_source exists or placeholder generated
- no major overlap on V1
- no timeline gap unless explicitly allowed
- final visual timeline duration ≈ audio duration
```

Pseudo-code:

```python
def validate_timeline_for_export(timeline, total_duration, fps):
    items = [
        x for x in timeline
        if x["type"] in ("scene", "beat_pause")
    ]
    items = sorted(items, key=lambda x: x["render_in"])

    for item in items:
        if item["render_out"] <= item["render_in"]:
            raise ValueError(f"Invalid duration: {item}")

    for prev, cur in zip(items, items[1:]):
        if cur["render_in"] < prev["render_out"] - 0.05:
            raise RuntimeError(f"Timeline overlap: {prev} -> {cur}")

    end = max(x["render_out"] for x in items) if items else 0
    if abs(end - total_duration) > max(0.05, 1 / fps):
        raise RuntimeError(
            f"Timeline end {end} does not match total_duration {total_duration}"
        )
```

---

# 17. Exporter Module Structure

Recommended files:

```text
exporters/
  kdenlive_exporter.py
  mlt_builder.py
  asset_registry.py
  freeze_frame.py
  placeholder.py
  timecode.py
  validators.py
```

Suggested API:

```python
def export_kdenlive_project(
    timeline_json_path: str,
    output_path: str,
    project_root: str,
    fps: int = 30,
    width: int = 1280,
    height: int = 720,
    missing_asset_policy: str = "placeholder"
) -> str:
    ...
```

---

# 18. Diagnostics

Output:

```text
exports/kdenlive/export_diagnostics.json
```

Required fields:

```json
{
  "project": "Naomi_01",
  "output": "exports/kdenlive/Naomi_01.kdenlive",
  "assets": {
    "missing": [],
    "generated_freeze_frames": [],
    "placeholders": []
  },
  "timeline": {
    "duration": 123.45,
    "clip_count": 86,
    "beat_pause_count": 25,
    "overlaps": [],
    "gaps": []
  },
  "warnings": [],
  "errors": []
}
```

---

# 19. Acceptance Criteria

The sprint is complete when:

```text
1. The exporter reads voice_matching_timeline.json.
2. It creates a Kdenlive/MLT XML project.
3. Master audio is placed on A1 as one continuous clip.
4. Scene visual clips are placed separately on V1.
5. Beat pauses are exported as separate visible V1 clips.
6. Image pause reuses the image as a separate clip.
7. Video/slideshow pause uses generated freeze frame.
8. Missing visual sources use placeholder or fail by config.
9. Beat, scene, and pause markers are exported.
10. Clip names are human-readable.
11. Project opens in Kdenlive.
12. User can manually move, trim, replace, or extend scene clips.
13. Timeline duration matches master audio duration within tolerance.
```

---

# 20. Final Statement

```text
The Kdenlive exporter must create an editable project, not a flattened render. Master audio stays intact on A1. Scene visuals are placed as separate clips on V1. Beat pauses are always separate visible clips. Silent scenes are normal scene clips with allocated duration. Markers expose beat and scene structure. The project should open in Kdenlive and allow manual editing while preserving sync with the master audio.
```
