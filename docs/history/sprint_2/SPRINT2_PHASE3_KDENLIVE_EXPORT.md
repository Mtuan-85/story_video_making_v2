# Sprint 2 — Phase 3: Kdenlive XML Export

> **Priority**: Sau Phase 1 + 2. Last task của Sprint 2.
> **Mục đích**: Xuất project ra format Kdenlive (.kdenlive XML) để mở trong Kdenlive editor.

---

## Yêu cầu

### Use case

```
1. Trong app: gen scenes + voice align + tweak (Phase 1 + 2)
2. Click "Export Kdenlive XML"
3. App xuất:
   - {project}/export.kdenlive (XML file)
   - References tới existing files trong sources/, voice/, bgm/
4. User mở Kdenlive → File → Open → chọn export.kdenlive
5. Kdenlive load timeline với tất cả tracks ready
6. User edit thêm trong Kdenlive (transitions, effects, color)
7. Render từ Kdenlive
```

→ App là **timeline generator**, Kdenlive là **fine editor**.

### Approach

Dùng **OpenTimelineIO + Kdenlive adapter** chính thức (KHÔNG self-build XML).

```
project (scenes.json + state.json + voice_mapping.json)
    ↓
OTIO Timeline object
    ↓
otio.adapters.write_to_file(timeline, "export.kdenlive", "kdenlive")
    ↓
export.kdenlive (MLT XML)
```

---

## Implementation

### Install dependencies

`requirements.txt`:
```
opentimelineio>=0.18.0
opentimelineio-kdenlive
```

### Module: `render/kdenlive_export.py` (NEW)

```python
"""
Export project to Kdenlive XML via OpenTimelineIO adapter.
"""

from pathlib import Path
import opentimelineio as otio
from opentimelineio import opentime, schema
from loguru import logger as log


DEFAULT_FPS = 30
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920  # 9:16 portrait


def build_otio_timeline(project, voice_mapping: dict | None) -> schema.Timeline:
    """
    Build OTIO Timeline from project data.
    
    Tracks:
    - V1: Visual track (image/video/slideshow per scene)
    - A1: Voice
    - A2: BGM (optional)
    """
    timeline = schema.Timeline(
        name=project.scenes_json.meta.title or "Story Video"
    )
    
    rate = DEFAULT_FPS
    
    # V1 — Video track
    video_track = schema.Track(name="Video", kind=schema.TrackKind.Video)
    
    cursor_seconds = 0.0
    for scene in project.scenes_json.scenes:
        scene_id = scene.id
        scene_state = project.state["scenes"].get(scene_id, {})
        
        visual_path = _get_visual_path(project, scene_id, scene_state)
        if not visual_path:
            log.warning(f"{scene_id}: no visual ready, skip")
            continue
        
        duration_sec = _get_scene_duration(scene, voice_mapping)
        
        clip = schema.Clip(
            name=scene_id,
            media_reference=schema.ExternalReference(
                target_url=str(visual_path).replace("\\", "/"),
            ),
            source_range=opentime.TimeRange(
                start_time=opentime.RationalTime(0, rate),
                duration=opentime.RationalTime(duration_sec * rate, rate),
            ),
        )
        
        # Add Kdenlive metadata for effect (so user thấy trong Kdenlive)
        if scene.effect and scene.effect != "no_effect":
            clip.metadata["kdenlive"] = {
                "effect_note": f"Apply {scene.effect} (zoom range 1.0-1.2)",
            }
        
        video_track.append(clip)
        cursor_seconds += duration_sec
    
    timeline.tracks.append(video_track)
    
    # A1 — Voice track
    voice_path = _get_voice_path(project, voice_mapping)
    if voice_path:
        audio_track = schema.Track(name="Voice", kind=schema.TrackKind.Audio)
        voice_clip = schema.Clip(
            name="Voice",
            media_reference=schema.ExternalReference(
                target_url=str(voice_path).replace("\\", "/"),
            ),
            source_range=opentime.TimeRange(
                start_time=opentime.RationalTime(0, rate),
                duration=opentime.RationalTime(cursor_seconds * rate, rate),
            ),
        )
        audio_track.append(voice_clip)
        timeline.tracks.append(audio_track)
    
    # A2 — BGM track (optional)
    bgm_path = _get_bgm_path(project)
    if bgm_path:
        bgm_track = schema.Track(name="BGM", kind=schema.TrackKind.Audio)
        bgm_clip = schema.Clip(
            name="BGM",
            media_reference=schema.ExternalReference(
                target_url=str(bgm_path).replace("\\", "/"),
            ),
            source_range=opentime.TimeRange(
                start_time=opentime.RationalTime(0, rate),
                duration=opentime.RationalTime(cursor_seconds * rate, rate),
            ),
        )
        bgm_clip.metadata["kdenlive"] = {"volume": 0.15}  # ~15dB lower
        bgm_track.append(bgm_clip)
        timeline.tracks.append(bgm_track)
    
    return timeline


def _get_visual_path(project, scene_id: str, scene_state: dict) -> Path | None:
    selected = scene_state.get("selected_visual", "image")
    
    if selected == "image":
        path_str = scene_state.get("image", {}).get("path")
    elif selected == "video":
        path_str = scene_state.get("video", {}).get("path")
    else:
        return None
    
    if not path_str:
        return None
    
    full_path = project.paths.root / path_str
    return full_path if full_path.exists() else None


def _get_scene_duration(scene, voice_mapping: dict | None) -> float:
    """Use duration_adjusted from voice-first logic if available."""
    if voice_mapping:
        for vf in voice_mapping.get("voice_files", []):
            for vs in vf.get("scenes", []):
                if vs["id"] == scene.id:
                    return vs.get("duration_adjusted", scene.duration)
    return float(scene.duration)


def _get_voice_path(project, voice_mapping: dict | None) -> Path | None:
    if not voice_mapping:
        return None
    
    files = voice_mapping.get("voice_files", [])
    if not files:
        return None
    
    rel_path = files[0]["file"]
    full_path = project.paths.root / rel_path
    return full_path if full_path.exists() else None


def _get_bgm_path(project) -> Path | None:
    bgm_dir = project.paths.root / "bgm"
    if not bgm_dir.exists():
        return None
    
    for ext in [".mp3", ".m4a", ".wav"]:
        for f in sorted(bgm_dir.glob(f"*{ext}")):
            return f
    return None


def export_kdenlive(
    project,
    voice_mapping: dict | None,
    output_path: Path,
):
    """Export project to Kdenlive XML."""
    timeline = build_otio_timeline(project, voice_mapping)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        otio.adapters.write_to_file(
            timeline,
            str(output_path),
            adapter_name="kdenlive",
        )
        log.info(f"Exported Kdenlive: {output_path}")
    except Exception as e:
        log.error(f"Kdenlive export failed: {e}")
        raise
    
    return output_path


def export_srt(voice_mapping: dict, output_path: Path) -> Path:
    """Bonus: Export subtitles to SRT format."""
    lines = []
    counter = 1
    
    for vf in voice_mapping.get("voice_files", []):
        for scene in vf.get("scenes", []):
            for phrase in scene.get("subtitle_phrases", []):
                start = _seconds_to_srt_time(phrase["start"])
                end = _seconds_to_srt_time(phrase["end"])
                lines.append(f"{counter}")
                lines.append(f"{start} --> {end}")
                lines.append(phrase["text"])
                lines.append("")
                counter += 1
    
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _seconds_to_srt_time(sec: float) -> str:
    """1.5 → 00:00:01,500"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```

### Worker: `workers/export_worker.py` (NEW)

```python
import asyncio
from pathlib import Path
from PyQt6.QtCore import pyqtSignal
from loguru import logger as log

from workers._async_thread import AsyncTaskWorker
from render.kdenlive_export import export_kdenlive, export_srt


class ExportKdenliveWorker(AsyncTaskWorker):
    export_done = pyqtSignal(str)  # kdenlive path
    export_failed = pyqtSignal(str)
    
    def __init__(self, project, voice_mapping, output_path: Path, also_srt: bool = True):
        super().__init__()
        self.project = project
        self.voice_mapping = voice_mapping
        self.output_path = output_path
        self.also_srt = also_srt
    
    async def run(self):
        try:
            log.info(f"Exporting Kdenlive XML to {self.output_path}")
            
            # Run sync export in thread
            await asyncio.to_thread(
                export_kdenlive,
                self.project,
                self.voice_mapping,
                self.output_path,
            )
            
            # Bonus: SRT export
            if self.also_srt and self.voice_mapping:
                srt_path = self.output_path.with_suffix(".srt")
                await asyncio.to_thread(
                    export_srt,
                    self.voice_mapping,
                    srt_path,
                )
                log.info(f"Exported SRT: {srt_path}")
            
            self.export_done.emit(str(self.output_path))
        
        except Exception as e:
            log.error(f"Export failed: {e}")
            self.export_failed.emit(str(e))
```

### UI button trong MainWindow

```python
# ui/main_window.py — thêm button + handler

# Trong _build_ui():
self.btn_export_kdenlive = QPushButton("📤 Export Kdenlive XML")
self.btn_export_kdenlive.clicked.connect(self._on_export_kdenlive)
# Add vào toolbar bên cạnh btn_render

# Handler:
def _on_export_kdenlive(self):
    if not self.project:
        QMessageBox.warning(self, "Error", "No project loaded")
        return
    
    output_path = self.project.paths.root / "export.kdenlive"
    
    if output_path.exists():
        reply = QMessageBox.question(
            self, "File exists",
            f"export.kdenlive đã tồn tại. Overwrite?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
    
    voice_mapping_dict = (
        self.project.voice_mapping.model_dump()
        if self.project.voice_mapping else None
    )
    
    self._export_worker = ExportKdenliveWorker(
        project=self.project,
        voice_mapping=voice_mapping_dict,
        output_path=output_path,
        also_srt=True,
    )
    self._export_worker.export_done.connect(self._on_export_done)
    self._export_worker.export_failed.connect(self._on_export_failed)
    self._export_worker.start()


def _on_export_done(self, path: str):
    QMessageBox.information(
        self, "Export OK",
        f"Đã xuất Kdenlive XML:\n{path}\n\n"
        f"Mở Kdenlive → File → Open → chọn file này.\n\n"
        f"Lưu ý: effects/transitions/color chưa export, user add manual sau.",
    )


def _on_export_failed(self, reason: str):
    QMessageBox.critical(self, "Export failed", reason)
```

---

## Test Plan

### Test 1: Export project chưa có voice align
- Load test_run, có 6 ảnh nhưng chưa import voice
- Click Export Kdenlive
- Verify: export.kdenlive tạo OK
- Open Kdenlive → load file → verify timeline đúng

### Test 2: Export project có voice align (Phase 1)
- Load test_run, đã import voice + run alignment v2
- Click Export
- Verify: V1 clips dùng `duration_adjusted`
- Verify: A1 track có voice mp3
- Verify: A2 track có BGM
- Open Kdenlive → verify duration match voice

### Test 3: Export với mix visual_type
- Scenes: 3 image_grok + 1 video_grok + 1 slideshow_v4
- Verify: clips trong timeline đúng path từ state.json (theo selected_visual)

### Test 4: Path encoding Windows
- Verify paths trong XML dùng forward slash
- Open trong Kdenlive trên Windows → load OK

### Test 5: SRT export bonus
- Verify .srt file tạo cùng lúc với .kdenlive
- Import SRT vào Kdenlive subtitle track → đúng timestamps

### Test 6: Edge case - missing files
- Delete 1 ảnh trong sources/
- Export
- Verify: warning trong log, scene đó skip
- File export vẫn tạo OK

---

## Limitations cần document

OTIO Kdenlive adapter giới hạn:

| Feature | Status |
|---|---|
| Basic clips trên track | ✅ Support |
| Multiple tracks | ✅ Support |
| Clip in/out trim | ✅ Support |
| Effects (zoom in/out) | ❌ Lost — user re-add trong Kdenlive |
| Transitions (xfade) | ❌ Lost |
| Subtitle track | ⚠️ Use SRT bonus |
| Color grading | ❌ Lost |
| Audio volume | ⚠️ Partial qua metadata |

→ Document trong README + show warning khi export.

User sau khi mở Kdenlive cần manual:
- Add transitions giữa clips (drag-drop)
- Re-apply zoom effects (Kdenlive's "Pan and Zoom" effect)
- Color grading nếu cần
- Import SRT subtitle file

---

## Build Order

1. **Install dependencies** (5 phút)
2. **render/kdenlive_export.py** (2-3h)
3. **workers/export_worker.py** (30 phút)
4. **UI integration** (30 phút)
5. **SRT export bonus** (1h)
6. **Test với Kdenlive thật** (1-2h)

**Total: ~5-7h**

---

## Confirm trước khi code

- [ ] OTIO + Kdenlive adapter installable
- [ ] Output file: `{project_root}/export.kdenlive` + `export.srt`
- [ ] Timeline: V1 (visual) + A1 (voice) + A2 (BGM)
- [ ] Use `duration_adjusted` từ Phase 1 voice_mapping nếu có
- [ ] Path forward-slash (Windows compat)
- [ ] Document limitations

Build từng phần, test với Kdenlive thật sau mỗi phần.
