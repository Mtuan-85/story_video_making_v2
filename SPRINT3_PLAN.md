# Sprint 3 — Note-Driven Auto Edit với Claude CLI + Kdenlive Backend

> **Status**: LOCKED. Bắt đầu sau khi Sprint 2 (voice-first + render) hoàn thành.
> **Last updated**: April 2026
> **Estimated effort**: ~38h work

---

## 1. Mục tiêu

Tích hợp **note-driven AI editing** vào App 1 (story_video_making):

- Bro xem `final.mp4` (output Sprint 2) trong app
- Mark notes với draggable markers trên timeline
- Claude CLI batch apply tất cả notes → edit MLT XML (`.kdenlive`)
- Render preview proxy (480p) để duyệt
- Render final 1080p khi OK

**Thay thế** Sprint 3 + Sprint 4 cũ (timeline editor app riêng + AI edits) → gộp 1 sprint.

---

## 2. Architecture

### Pipeline tổng

```
Sprint 2 done → final.mp4 (1080p HD)
       ↓
[App 1 mở final.mp4 + UI marker timeline]
       ↓
Bro mark notes (1 hoặc nhiều) — draggable markers
       ↓
Click [🤖 Claude apply all]
       ↓
   Subprocess Claude CLI parse hết notes + project.kdenlive
       ↓
   Generate XML edits (composite tracks, filters, transitions)
       ↓
   Save project.kdenlive (with backup .bak)
       ↓
Click [👁 Render preview proxy 480p]
       ↓
   melt headless render → preview.mp4 (~30-60s tùy độ dài)
       ↓
   App reload python-vlc với preview.mp4
       ↓
Bro xem:
  ├─ OK → Click [🎬 Render final 1080p] → final_edited.mp4
  ├─ Sửa → Edit notes → Re-apply
  └─ Reset → Revert .kdenlive về .bak → mark lại
```

### UI Layout

```
┌─ App 1 (PyQt6 unified) ──────────────────────────┐
│                                                    │
│  ┌─ Video Preview ────────────────────────────┐  │
│  │ python-vlc embed                            │  │
│  │ ▶ Play  ⏸ Pause  ⏹ Stop                    │  │
│  │ ━━━━●━━━━━━━━━━━━━━━━━ 00:15 / 02:30       │  │
│  │     ↑                                       │  │
│  │   marker (draggable, color-coded)          │  │
│  └─────────────────────────────────────────────┘  │
│                                                    │
│  ┌─ Notes Panel ──────────────────────────────┐  │
│  │ 🟦 00:15 → fade_out 1s          [✎] [✗]   │  │
│  │ 🟧 00:30 → text_overlay 3s       [✎] [✗]   │  │
│  │ 🟩 01:20 → slow 0.5x duration 2s [✎] [✗]   │  │
│  │ [+ Add marker @ current time]               │  │
│  └─────────────────────────────────────────────┘  │
│                                                    │
│  [🤖 Claude apply all]  [👁 Render preview]       │
│  [🎬 Render final]      [↺ Reset to backup]       │
└────────────────────────────────────────────────────┘
```

---

## 3. Module structure

```
edit/                                    # NEW — Sprint 3
├── __init__.py
├── note_schema.py            # Action vocabulary + Pydantic schema
├── mlt_editor.py             # xml.etree wrapper cho MLT XML
├── claude_edit_runner.py     # Subprocess Claude CLI
└── melt_runner.py            # Preview proxy + final render qua melt CLI

ui/                                      # EXTEND
├── timeline_widget.py        # NEW: QGraphicsScene + draggable markers
├── preview_pane.py           # EXTEND Sprint 2: sync với timeline
└── notes_panel.py            # NEW: CRUD notes + edit dialog

workers/                                 # EXTEND
└── edit_apply_worker.py      # NEW: Async batch apply + render
```

### Estimate per module

| Module | Hours |
|---|---|
| `ui/timeline_widget.py` (QGraphicsScene + draggable markers) | 7 |
| `ui/preview_pane.py` (extend với sync timeline) | 2 |
| `ui/notes_panel.py` (CRUD + edit dialog) | 3 |
| `core/note_schema.py` (vocabulary + Pydantic) | 1 |
| `edit/mlt_editor.py` (xml.etree + multi-track logic) | 8 |
| `edit/claude_edit_runner.py` (subprocess + prompt template) | 5 |
| `edit/melt_runner.py` (preview proxy + final render) | 3 |
| `workers/edit_apply_worker.py` (async batch) | 2 |
| Integration test với 5-10 sample notes | 3 |
| Bug fix + polish | 4 |
| **Tổng** | **~38h** |

---

## 4. Action Vocabulary v1 (LOCKED — 45 actions)

### Tier hệ thống

| Tier | Đặc điểm | XML complexity |
|---|---|---|
| **Simple** | 1 filter MLT đơn, 1 producer track | Insert filter element |
| **Medium** | 2-3 filters cùng track, hoặc text producer + composite | Multi-element edit |
| **Hard** | Track phụ + composite transition + position/opacity | Multi-track + composite |

### Catalog đầy đủ

#### 4.1 Transitions (Simple)
```python
"fade_in"           # duration
"fade_out"          # duration
"crossfade"         # giữa 2 scene, duration
"dissolve"          # duration
"wipe_left"         # duration
"wipe_right"        # duration
```

#### 4.2 Text overlay (Medium)
```python
"text_overlay"      # text, position, duration, font_size?
"text_typewriter"   # text, position, duration (gõ từng chữ)
"text_emphasize"    # word_to_highlight, duration (highlight word in caption)
```

#### 4.3 Speed (Simple)
```python
"slow"              # factor (0.25-1.0), duration
"speed_up"          # factor (1.0-4.0), duration
"freeze"            # duration (freeze frame)
"ramp_slow"         # duration (slow dần)
"ramp_fast"         # duration (nhanh dần)
"reverse"           # duration (phát ngược)
```

#### 4.4 Trim & cut (Simple)
```python
"trim_before"       # cut everything before this timestamp
"trim_after"        # cut everything after this timestamp
"remove_segment"    # remove from time → time+duration
"split"             # tách scene tại timestamp
"duplicate"         # lặp lại đoạn (loop_count)
```

#### 4.5 Color (Simple/Medium)
```python
"warm"              # duration (warm tint)
"cool"              # duration (cool tint)
"bw"                # duration (black & white)
"vintage"           # duration (vintage film look)
"vibrant"           # duration (tăng saturation)
"desaturate"        # duration (giảm saturation)
"vignette"          # duration (tối 4 góc)
"brightness"        # value (-100 to 100), duration
"contrast"          # value (-100 to 100), duration
```

#### 4.6 Transform & motion (Simple)
```python
"zoom_in"           # target_scale, duration
"zoom_out"          # target_scale, duration
"pan_left"          # distance_pct, duration
"pan_right"         # distance_pct, duration
"pan_up"            # distance_pct, duration
"pan_down"          # distance_pct, duration
"rotate"            # angle_deg, duration
"flip_horizontal"   # duration (mirror)
"shake"             # intensity, duration (camera shake)
"zoom_pulse"        # bpm hoặc duration (pulse zoom)
```

#### 4.7 Blur & focus (Simple)
```python
"blur_gaussian"     # amount (1-20), duration
"blur_motion"       # amount, duration
"sharpen"           # amount, duration
"background_blur"   # amount (1-20), duration  # blur all in segment
```

#### 4.8 Audio (Simple)
```python
"mute"              # duration
"lower_volume"      # level (0-100), duration
"raise_volume"      # level (100-200), duration
"audio_fadein"      # duration
"audio_fadeout"     # duration
"duck_voice"        # duration (BGM giảm khi voice)
```

#### 4.9 Subtitle (Medium) — chỉ áp dụng nếu Sprint 2 xuất subtitle track
```python
"caption_emphasize" # word, time, duration
"caption_color"     # color, time, duration
"caption_position"  # position (top/center/bottom), time, duration
"highlight_word"    # time (sync với word đang phát)
```

#### 4.10 Overlay (Hard)
```python
"image_overlay"     # file_path, position [x_pct, y_pct], scale, 
                    # duration, in_animation, out_animation
"emoji_overlay"     # emoji_unicode, position, scale, duration, animation
```

#### 4.11 Composition (Hard)
```python
"background_video_overlay"   # background_file, background_opacity, 
                              # duration, main_position, main_scale
"picture_in_picture"         # pip_file, position, scale, duration
"split_screen"               # second_file, layout (horizontal/vertical), duration
```

### Đã bỏ (deferred)

```python
"focus_pull"          # cần AI segmentation, defer
"bgm_loop"            # tạm chưa cần
"voiceover_replace"   # phức tạp, defer
"green_screen"        # cần video subject đặc biệt, defer
"glitch"              # có thể thêm sau
"grain_film"          # có thể thêm sau
```

---

## 5. Note JSON Schema

### Schema cơ bản

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class Note(BaseModel):
    id: str                              # UUID
    time: str                            # "MM:SS.mmm" hoặc "HH:MM:SS.mmm"
    action: str                          # 1 trong 45 actions
    duration: Optional[float] = None     # giây
    
    # Optional params (tùy action)
    text: Optional[str] = None
    position: Optional[str] = None       # "top"/"center"/"bottom" hoặc [x, y]
    scale: Optional[float] = None
    factor: Optional[float] = None
    file: Optional[str] = None
    color: Optional[str] = None
    amount: Optional[float] = None
    level: Optional[int] = None
    angle: Optional[float] = None
    
    # Composition specific
    background_file: Optional[str] = None
    background_opacity: Optional[float] = None
    
    # Animation
    in_animation: Optional[str] = None
    out_animation: Optional[str] = None
    
    # State
    status: Literal["pending", "applied", "approved", "rejected"] = "pending"
    rationale: Optional[str] = None       # Claude giải thích sau apply
```

### Ví dụ notes.json

```json
{
  "notes": [
    {
      "id": "n1",
      "time": "00:15.000",
      "action": "fade_out",
      "duration": 1.0,
      "status": "pending"
    },
    {
      "id": "n2",
      "time": "00:30.500",
      "action": "text_overlay",
      "text": "Welcome",
      "position": "top",
      "duration": 3.0,
      "status": "pending"
    },
    {
      "id": "n3",
      "time": "01:20.000",
      "action": "slow",
      "factor": 0.5,
      "duration": 2.0,
      "status": "pending"
    },
    {
      "id": "n4",
      "time": "00:00.000",
      "action": "background_video_overlay",
      "background_file": "broll/timelapse.mp4",
      "background_opacity": 0.4,
      "duration": 30.0,
      "status": "pending"
    },
    {
      "id": "n5",
      "time": "01:45.000",
      "action": "image_overlay",
      "file": "stickers/logo.png",
      "position": [0.7, 0.2],
      "scale": 0.3,
      "duration": 5.0,
      "in_animation": "fade",
      "out_animation": "fade",
      "status": "pending"
    }
  ]
}
```

---

## 6. Pre-conditions trước Sprint 3

### Sprint 2 phải xong:
- [ ] Voice align (Whisper + Claude) hoạt động
- [ ] Render final.mp4 1080p với subtitle drawtext + BGM
- [ ] Output file: `{project}/final.mp4`

### Tools setup:
- [ ] **Kdenlive** OR **MLT framework** standalone installed
  - Windows: bundled với Kdenlive Windows installer
  - Linux: `apt install melt` hoặc bundled
- [ ] `melt` binary trong PATH (test: `melt --version`)
- [ ] **Claude CLI** đã login subscription (test: `claude --version`)
- [ ] **OpenTimelineIO** Python lib (`uv pip install opentimelineio opentimelineio-kdenlive-adapter`) — optional, để xuất .kdenlive native

### App 1 phải có:
- [ ] python-vlc embed working (Sprint 2 part)
- [ ] qasync event loop (Sprint 1)
- [ ] Project state.json schema (Sprint 1)

---

## 7. Pipeline flow chi tiết

### 7.1 Mark notes
1. User mở `final.mp4` → loaded vào python-vlc
2. User click [+ Add marker] khi xem video
3. Marker tạo tại timestamp current playhead
4. Marker draggable: click + drag để chỉnh time (snap 0.5s)
5. Double-click marker → dialog edit:
   ```
   ┌─ Edit Note ─────────────────┐
   │ Time: 00:15.5               │
   │ Action: [▾ fade_out]        │
   │ Duration: [1.0] s           │
   │ Extra params: tùy action    │
   │ [Save] [Delete] [Cancel]    │
   └──────────────────────────────┘
   ```
6. Notes lưu vào `{project}/notes.json`

### 7.2 Apply all notes
1. Click [🤖 Claude apply all]
2. Worker spawn subprocess Claude CLI:
   ```bash
   echo "$prompt" | claude --print --dangerously-skip-permissions
   ```
3. Prompt context:
   - Notes JSON
   - Vocabulary 45 actions với XML pattern map
   - File project.kdenlive (MLT XML hiện tại)
4. Claude generate **XML diff/patch** cho từng note
5. App apply diff lên project.kdenlive
6. Backup `project.kdenlive.bak` trước khi save
7. Update notes.json: status = "applied" + rationale từ Claude

### 7.3 Render preview proxy
1. Click [👁 Render preview]
2. melt CLI với profile proxy 480p:
   ```bash
   melt project.kdenlive -profile atsc_480p_30 -consumer avformat:preview.mp4 \
        vcodec=libx264 b=1500k acodec=aac
   ```
3. Render time: ~30-60s tùy duration
4. Reload python-vlc với `preview.mp4`

### 7.4 Approve / Reject / Refine
1. Bro xem preview
2. Per-note actions:
   - **Approve**: status → "approved"
   - **Reject**: revert XML diff cho note đó → re-render preview
   - **Refine**: edit note + comment → re-apply Claude
3. Khi tất cả notes "approved" → enable [🎬 Render final]

### 7.5 Render final
1. Click [🎬 Render final]
2. melt CLI với profile production 1080p:
   ```bash
   melt project.kdenlive -profile atsc_1080p_30 -consumer avformat:final_edited.mp4 \
        vcodec=libx264 b=8000k acodec=aac
   ```
3. Output: `{project}/final_edited.mp4`

---

## 8. Claude CLI prompt template (skeleton)

```python
PROMPT_TEMPLATE = """
You are a video editor AI. Apply the following notes to a Kdenlive MLT XML 
project file.

## Action Vocabulary
{vocabulary_with_xml_patterns}

## Current MLT XML
```xml
{current_kdenlive_xml}
```

## Notes to Apply (apply ALL)
```json
{notes_json}
```

## Instructions
1. For each note, generate the MLT XML edits needed.
2. Output a JSON response with:
   - "edits": array of {{"note_id", "xml_patches": [...]}}
   - "rationale": brief explanation per note
3. XML patches format: {{op: "insert"|"modify"|"delete", xpath: "...", content: "..."}}
4. Return ONLY valid JSON, no preamble or markdown fences.

## Composite track patterns (Hard tier)
{composite_patterns}

Output JSON now:
"""
```

App 1 parse JSON response, apply patches via `xml.etree`, save .kdenlive.

---

## 9. Test strategy

### Tier 1: Simple actions (smoke test)
```
Input: 1 note "fade_out at 00:15 duration 1s"
Expect: 
- project.kdenlive có thêm <filter mlt_service="brightness"> 
  với keyframes
- preview.mp4 fade out đúng vị trí
```

### Tier 2: Medium actions
```
Input: 2 notes: text_overlay + slow
Expect:
- Track 2 (text producer) tạo mới
- Speed filter applied đúng segment
- Preview render OK
```

### Tier 3: Hard actions (composition)
```
Input: 1 note "background_video_overlay" 
       với background_file=broll.mp4, opacity=0.4
Expect:
- Track 0 (background, full screen, opacity 40%)
- Track 1 (main, opacity 100%, on top)
- Composite transition between tracks
- Preview render OK với layered video
```

### Tier 4: Combined (real use case)
```
Input: 5-10 notes hỗn hợp
Expect:
- Tất cả applied không conflict
- Preview render OK
- Final render OK
- File size hợp lý
```

---

## 10. Out of Scope (Sprint 4+ future)

- Drag-and-drop reorder scenes (NLE-like)
- AI-suggest notes từ video content (Claude xem video → tự đề xuất edits)
- Custom MLT filter chain bro tự define
- Multi-track audio mixing UI
- Color grading panel với LUT support
- Effect templates library (save/reuse note combinations)
- Export to FCP7 XML / DaVinci XML / Premiere XML cho NLE pro
- Batch render nhiều project parallel

---

## 11. Khi nào bắt đầu Sprint 3?

**Pre-condition checklist** (tất cả phải PASS):
- [ ] Sprint 2 hoàn thành: voice + render + final.mp4 OK
- [ ] App 1 đã commit Sprint 2 lên GitHub
- [ ] Bro test final.mp4 thực tế với 1-2 project, satisfy với output
- [ ] `melt --version` chạy OK trong terminal
- [ ] `claude --version` chạy OK
- [ ] Bro đọc lại file SPRINT3_PLAN.md này, confirm scope

→ Khi pass hết → mình viết `MIGRATION_PLAN_SPRINT3.md` chi tiết với:
- Code skeleton từng module
- Claude prompt template hoàn chỉnh
- MLT XML pattern reference (cho 45 actions)
- Test cases cụ thể

→ Bro paste cho Claude Code build.

---

## End of Sprint 3 Plan
