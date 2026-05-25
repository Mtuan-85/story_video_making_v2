# Slideshow v2 — Zone-Animate Engine Integration

**Effective: May 2026**

This is the new slideshow engine, replacing the old object-cropping + group-animation approach with zone-based polygon animation using zone_animate M1 pipeline.

## Architecture

### Key Differences from v1

| Aspect | v1 (old) | v2 (new) |
|---|---|---|
| **Detection** | rembg + horizontal dilate → individual objects | Chroma-key BG → Claude vision picks zones |
| **Grouping** | Claude decides grouping/animation | Claude picks zones directly (simpler) |
| **Animation** | filter_complex overlay on objects | M1 renderer + frame composition (robust) |
| **Threading** | Async worker thread | Sync function (single-thread, no cancel) |
| **Integration** | Async wrapper / shared thread pool | Fresh `SlideshowWorker` QThread calls package directly |

### Module Structure

```
slideshow/
├── __init__.py              # Package entry, exports render_slideshow_v2
├── orchestrator.py          # Main pipeline orchestrator
├── bg_detect.py             # Detect background color from borders
├── claude_runner.py         # Claude CLI wrapper + vision prompt
├── zone_refiner.py          # Refine bboxes to tight polygons (chroma-key + CV)
├── renderer.py              # Render video using zone_animate M1 pipeline
└── README_V2.md             # This file
```

### Pipeline Stages

```
Image
  ↓
[1] Detect BG color (median of border pixels)
  ↓
[2] Claude vision auto-pick zones (bboxes + animation/sound/timing)
  ↓
[3] Refine bboxes → tight polygons
  ├─ Chroma-key mask (pixels far from bg_color)
  ├─ Edge-touch expansion (if content touches bbox edge)
  ├─ Connected component filtering
  ├─ Dilation for edge recovery
  └─ Douglas-Peucker simplification
  ↓
[4] Resolve overlaps (centroid-based rasterization)
  ↓
[5] Render video (zone_animate M1 pipeline)
  ├─ Extract stickers (polygon masks + anti-aliasing)
  ├─ Build base canvas (source image with zones masked)
  ├─ Render frames (PIL, apply zone animations)
  └─ Encode to MP4 (ffmpeg)
  ↓
MP4 output
```

**Total time: ~1-2 minutes** (Claude dominates: 30-60s)

## API

### Main Entry Point

```python
from slideshow import render_slideshow_v2

mp4_path = render_slideshow_v2(
    image_path=Path("scene.png"),
    output_path=Path("output.mp4"),
    duration_sec=8.0,
    aspect_ratio="16:9",  # or "9:16" for tiktok
    hint="slow pacing, zones left to right",  # optional
    log_cb=print,  # optional progress callback
)
```

### Legacy Render Layer

```python
from render.slideshow import render_slideshow

# Deprecated async wrapper kept only for old callers.
mp4_path = await render_slideshow(
    image_path=Path("scene.png"),
    output_path=Path("output.mp4"),
    duration_sec=8.0,
    aspect_ratio="16:9",
    hint="...",
    log_cb=print,
)
```

## Claude Prompt Structure

The Claude prompt sent to v2 uses **vision mode** + Read/Write tools:

1. **Read** the source image to understand composition
2. **Examine** and identify semantic zones
3. **Pick zones** with bboxes, animation, timing, sound
4. **Write** JSON plan to file
5. **Respond** with "Done"

Key design rules built into prompt:
- Zone = semantic unit (character + label + arrow = 1 zone)
- Bboxes must have ≥20px clean margin on all edges
- Minimum 2 zones, maximum 12
- Animation variety (don't use same animation for all zones)
- Pacing: fit within duration, avoid dead time

## Zone Refinement Algorithm

**Challenge:** Claude's bboxes are rough; they may miss drop shadows, halos, or soft edges.

**Solution:** Multi-pass refinement

1. **Chroma-key mask** — pixels with `|rgb - bg_color| > CHROMA_THRESHOLD` (15)
2. **Edge-touch detection** — if >5% of bbox edge is content, expand that edge outward
3. **Component filtering** — drop components <100px² (noise)
4. **Dilation** — expand outward by 3-15px (size-dependent) to recover soft edges
5. **Contour extraction** — find largest boundary, simplify via Douglas-Peucker (ε=2px)
6. **Result** — tight polygon that preserves edges + shadows

## Base Canvas (M3 Approach)

Frame 0 = **source image with zone regions painted bg_color**

Benefit:
- Non-zone content (title, decorative arrows, background) stays visible throughout
- Only zone areas start "hidden" and get revealed by animation
- More natural for infographics where context matters

## Failure Modes

| Scenario | Behavior |
|---|---|
| Claude times out (>300s) | Raise RuntimeError |
| Claude returns no zones | Raise RuntimeError ("no zones found") |
| Zone bbox refinement fails | Skip that zone, continue with others |
| All zones fail refinement | Raise RuntimeError |
| Ffmpeg encode fails | Raise RuntimeError with tail of stderr |

No graceful fallback; the caller (SlideshowWorker) handles failure via state update.

## No Cancellation

Unlike v1, v2 does **not support mid-process cancellation** once Claude call starts:

- Before Claude call: caller can decide not to invoke
- After Claude call: runs to completion (no `stop_requested` flag)
- Design: full automation flow, user only reviews after

If user wants to cancel, they must kill the process or wait for render to finish.

## Preview/Edit After Render

After successful render, the caller can:

1. **Preview** the output MP4
2. **Open Zone Editor** (small zone editor modal)
   - View the zones as polygons overlaid on source
   - Edit polygons if desired
   - **Re-render** (does NOT call Claude again, just re-renders with new polygons)
3. **Accept** or **Redo** (call render_slideshow_v2 again with new hint)

The zone editor reuses the `zone_animate_app.zone_editor.ZoneEditorDialog` component.

## Sound Effects Contract

Each zone stores a `sound` value. Supported bundled sounds are:

```text
pop, flip, whoosh, swoosh, ding
```

During slideshow rendering:

1. `renderer._collect_audio_inputs()` resolves `slideshow/assets/sounds/{sound}.wav`.
2. Each sound is offset to the zone `appear_at`.
3. `_encode_video()` mixes all zone sounds into the standalone slideshow MP4.
4. `SlideshowEditDialog` lets the user edit sound per zone and provides
   `Sound all -> Apply` for bulk changes before re-render.

Important: story final render currently treats slideshow MP4s as visual-only.
`render/timeline_visual.py` uses `-an` for scene segments, then final mux adds
continuous `master_voice.wav` and optional BGM. Therefore slideshow SFX are
audible in the standalone slideshow MP4 preview, but not in `final.mp4`.

Future expansion: preserve slideshow SFX in final render by building an SFX
audio timeline from slideshow scene segments and mixing it into the final
master-voice/BGM pass.

## Constants & Tuning

All tunable parameters live in `zone_refiner.py` top-level:

- `CHROMA_THRESHOLD = 15` — color distance threshold for chroma mask
- `MIN_COMPONENT_AREA = 20` — minimum blob size in px²
- `DOUGLAS_PEUCKER_EPSILON = 2.0` — polygon simplification tolerance
- `EDGE_TOUCH_RATIO = 0.05` — threshold for edge-touch expansion (5% of edge)
- `EXPANSION_PX = 30` — bbox growth per edge-touch iteration
- `MAX_EXPAND_ITERATIONS = 2` — cap iterations to avoid runaway growth

Adjust these if zones are too loose or too tight for specific image types.

## Integration with story_video_making_v2

1. **SlideshowWorker** imports and calls `slideshow.render_slideshow_v2` directly inside a fresh QThread.
2. **render/slideshow.py** is deprecated and retained only for legacy imports.
3. **No mid-process cancellation** — full pipeline runs to completion once started.
4. **User can edit after render** — `SlideshowEditDialog` loads saved zones JSON and re-renders without Claude.

### Workflow in MainWindow

1. User selects scenes with `visual_type="slideshow"` and ready source images
2. User clicks **Batch Edit** → creates one `SlideshowWorker` per scene, run sequentially by MainWindow
3. Worker calls `render_slideshow_v2` → full pipeline → MP4
4. On success: updates `project.state[scene_id]["video"]` with MP4 path + `source_type="slideshow"` and `project.state[scene_id]["edit"]` with zones/thumb paths
5. On failure: updates state with `fail_reason`, emits signal
6. User can open Zone Editor to refine/re-render without Claude

## Performance

**Measured timings** (example):

- BG detection: ~2-3s
- Claude vision + plan: 30-60s (dominates; network-dependent)
- Polygon refinement: 5-10s
- Video render (8s @ 1920x1080, 30fps): 20-40s
- **Total: 1-2 minutes per scene**

## Debugging

Key debug artifacts in work directory:

- `auto_plan.json` — Claude's raw zone output
- `claude_prompt.txt` — full prompt sent to Claude
- `claude_response.txt` — Claude's exit code + stdout/stderr

When things fail:
1. Check `claude_response.txt` for CLI errors
2. Check `auto_plan.json` for Claude's output format
3. Run test images with simple colors (solid BG) first
4. Adjust `CHROMA_THRESHOLD` if zones are too loose/tight

## Future Enhancements

- [ ] Batch zone editing (edit one, apply to similar images)
- [ ] Zone template library (save/reuse good zone sets)
- [ ] Custom sound upload (currently fixed 5 assets/sounds/)
- [ ] Emphasis animations per zone (currently all zones same entry + optional emphasis)
- [ ] Keyframe-based animation (currently linear interpolation)
