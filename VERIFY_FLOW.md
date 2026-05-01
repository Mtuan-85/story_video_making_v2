# VERIFY FLOW — Voice Alignment Read-Only Audit

> **Goal**: Audit code voice alignment hiện tại (KHÔNG SỬA). Output báo cáo chi tiết để debug.
> **Scope**: Voice mapping + Subtitle generation. SKIP gen ảnh/video, SKIP render visual.
> **Effort**: 1-2h
> **Mode**: READ-ONLY — Claude Code KHÔNG sửa file source nào.

---

## Yêu cầu QUAN TRỌNG

### Tuyệt đối KHÔNG được làm

- ❌ Sửa bất kỳ file source code nào
- ❌ Refactor module
- ❌ "Fix" bug khi thấy
- ❌ Đề xuất "improvement" trong code
- ❌ Tạo file mới ngoài report MD và 1 script audit tạm (nếu cần chạy alignment)

### Chỉ được làm

- ✅ Đọc code (view, grep)
- ✅ Run alignment với data hiện tại
- ✅ Run Whisper, đọc voice_mapping.json output
- ✅ Output 1 file `VERIFY_REPORT.md` ở `D:\Projects\story_video_making\test_live\`

→ Nếu phát hiện bug, **CHỈ ghi vào report**, KHÔNG fix code.

---

## Test data

Project: `D:\Projects\story_video_making\test_live\`

- `scenes.json` — 5 scenes Rainy Cafe Afternoon (đã có)
- `voice/voice1..mp3` — TTS voice (~29s)
- `voice_mapping.json` — output hiện tại (nếu có)

→ KHÔNG xóa, KHÔNG modify data này.

---

## Workflow Claude Code

### Phase 1: Code architecture audit (15 phút)

#### 1.1 List voice modules

```powershell
Get-ChildItem voice\
Get-ChildItem render\
Get-ChildItem workers\ -Filter *voice*
Get-ChildItem ui\dialogs\ -Filter *voice*
```

Output ghi vào report:
- Files có trong voice/
- Files có trong render/ (đặc biệt subtitle_filter, ass_generator)
- Workers liên quan voice
- Dialogs liên quan voice

#### 1.2 Identify entry point

```powershell
# Tìm file orchestrator chính
Select-String -Path voice\*.py -Pattern "def align" -SimpleMatch
Select-String -Path workers\*.py -Pattern "VoiceAlignWorker|class.*[Aa]lign"
```

Trả lời:
- File nào là entry point voice alignment?
- Function chính tên gì?

#### 1.3 Identify subtitle implementation

```powershell
Select-String -Path render\*.py -Pattern "drawtext"
Select-String -Path render\*.py -Pattern "subtitles="
Select-String -Path voice\*.py -Pattern "pysubs2|\.ass"
```

Trả lời:
- Subtitle dùng `drawtext` (cũ) hay `subtitles=` ASS (mới)?
- Có module ass_generator không?
- File ASS có generate không?

### Phase 2: Run alignment with current data (15 phút)

#### 2.1 Run alignment

Nếu có button "Process voice" hoặc tương tự, click. Hoặc gọi function trực tiếp:

```python
# Run alignment, capture output
import asyncio
import json
from pathlib import Path

# Find main alignment function (tìm trong code)
# Gọi nó với test_live data

# Save raw output để inspect
```

Output:
- Whisper transcribe text (full)
- Voice_mapping.json sau khi align
- Log đầy đủ trong console

#### 2.2 Inspect Whisper transcript

Print toàn bộ Whisper output:
- Số segments
- Số words
- Full transcript text
- Per-segment timestamps

→ Verify Whisper hoạt động OK trước khi đánh giá alignment.

### Phase 3: Build voice alignment table (30 phút)

**Đây là phần CHÍNH của verify**. Output bảng chi tiết per scene.

Cho mỗi scene trong scenes.json:

#### 3.1 Extract data

```python
for scene in scenes:
    scene_id = scene["id"]
    script = scene.get("story_en") or ""
    design_dur = scene["duration"]
    
    # Find scene in voice_mapping
    vs = next((s for s in voice_mapping["scenes"] if s["id"] == scene_id), None)
    if vs is None:
        # Scene missing trong voice_mapping
        continue
    
    voice_in = vs.get("voice_in")
    voice_out = vs.get("voice_out")
    is_silent = vs.get("is_silent", False)
    
    # Extract voice text từ Whisper words trong khoảng voice_in/voice_out
    voice_text = extract_voice_text(whisper_words, voice_in, voice_out)
    
    # Calculate fuzzy match score
    from rapidfuzz import fuzz
    score = fuzz.ratio(script.lower(), voice_text.lower())
    
    # Get video duration nếu render đã chạy
    video_path = Path(f"renders/{scene_id}.mp4")
    video_dur = ffprobe_duration(video_path) if video_path.exists() else None
```

#### 3.2 Format report table

```
=== VOICE ALIGNMENT VERIFY TABLE ===

[1] SCENE-01
    Script   : "Rain taps softly on the cafe window. The street outside blurs into amber lights."
    Voice    : "Rain taps softly on the cafe window, the street outside blurs into amber lights."
               (voice_in: 0.00s, voice_out: 6.44s, dur: 6.44s)
    Match    : 96.0%  ✓ PASS
    Design   : 8.0s
    Adjusted : 6.44s  (Δ -1.56s)
    Video    : 6.44s  (composite output)
    Diagnosis: OK

[2] SCENE-02
    Script   : "A barista wipes the counter slowly. Steam curls from a fresh espresso."
    Voice    : "A barista wipes the counter slowly. Steam curls from a fresh espresso, three small things on the"
               (voice_in: 7.36s, voice_out: 11.85s, dur: 4.49s)
    Match    : 64.2%  ⚠ WARNING
    Design   : 5.0s
    Adjusted : 4.49s  (Δ -0.51s)
    Video    : 4.49s
    Diagnosis: EXTRA — voice contains additional content "three small things on the"
               that belongs to SCENE-03 script

[3] SCENE-03
    Script   : "Three small things on the table. A cup, a notebook, a fountain pen."
    Voice    : "table. A cup, a notebook, a fountain pen. He opens the notebook. The page is empty, waiting."
               (voice_in: 15.42s, voice_out: 20.82s, dur: 5.40s)
    Match    : 38.5%  ✗ FAIL
    Design   : 10.0s
    Adjusted : 8.97s  (Δ -1.03s)
    Video    : 8.97s
    Diagnosis: SHIFTED — voice content belongs to mix of SCENE-03 ("Three small...")
               + SCENE-04 ("He opens the notebook"). Boundaries misaligned.

...
```

#### 3.3 Diagnosis heuristic

Simple rules để Claude Code phán đoán:

```python
def diagnose(script, voice_text, score):
    script_norm = normalize(script)
    voice_norm = normalize(voice_text)
    
    if score >= 90:
        return "OK"
    
    # Voice contains all of script + extra
    if script_norm in voice_norm and len(voice_norm) > len(script_norm) * 1.3:
        return f"EXTRA — voice has {len(voice_norm) - len(script_norm)} extra chars after script"
    
    # Script contains voice (voice cut too early)
    if voice_norm in script_norm and len(voice_norm) < len(script_norm) * 0.7:
        return f"MISSING — voice cut at {len(voice_norm)}/{len(script_norm)} chars"
    
    # Voice text starts in middle of script
    if any_word_overlap(script_norm, voice_norm) < 0.3:
        return "SHIFTED — voice content doesn't start with script"
    
    # Mixed content (likely overlap with neighbor scene)
    return "OVERLAP — mixed content from multiple scenes"


def normalize(text):
    import re
    return re.sub(r"[^\w\s]", "", text.lower()).strip()
```

→ Claude Code dùng heuristic đơn giản này. KHÔNG cần AI sophisticated.

### Phase 4: Subtitle audit (15 phút)

#### 4.1 Inspect subtitle output

Render 1 scene (vd SCENE-05) và inspect:

```python
# Render SCENE-05
# Hoặc tìm renders/SCENE-05.mp4 nếu đã có

# Extract frames
ffmpeg -i test_live/renders/SCENE-05.mp4 -vf "fps=2" test_live/temp/scene05_%02d.png
```

Inspect frames:
- Subtitle có hiện không?
- Position (top/middle/bottom)?
- Color (white / yellow)?
- Karaoke effect (word-by-word) hay toàn phrase?
- Có tràn màn hình không?
- Có wrap nhiều dòng không?

#### 4.2 Inspect subtitle filter trong composite

Tìm composite code:

```powershell
Select-String -Path render\composite.py -Pattern "drawtext|subtitles="
```

Output trong report:
- File subtitle filter
- Filter chain expression hiện tại
- Có dùng .ass file không?
- Margin config có không?

#### 4.3 Inspect subtitle phrases trong voice_mapping

```python
# Đọc voice_mapping.json
for scene in voice_mapping["scenes"]:
    print(f"[{scene['id']}] {len(scene.get('subtitle_phrases', []))} phrases")
    for p in scene.get("subtitle_phrases", []):
        print(f"  - \"{p['text']}\" ({p['start']:.2f}-{p['end']:.2f}s)")
        if "words" in p:
            print(f"    words: {len(p['words'])} word timestamps")
        else:
            print(f"    NO word timestamps")
```

Verify:
- Mỗi phrase có words array không?
- Phrase length max bao nhiêu chars?
- Phrase có trùng nội dung giữa các scenes không?

### Phase 5: Output report (15 phút)

Save to `D:\Projects\story_video_making\test_live\VERIFY_REPORT.md`:

```markdown
# Verify Report — Voice Alignment Audit

**Date**: 2026-XX-XX
**Project**: test_live
**Mode**: Read-only audit (no code changes)

---

## 1. Code Architecture Audit

### 1.1 Voice modules (`voice/`)
- voice_aligner.py — entry point, function `align_voice_to_scenes()`
- whisper_runner.py — Whisper wrapper
- subtitle_builder.py — fallback subtitle (no Claude)
- (other files...)

### 1.2 Render subtitle implementation
- Subtitle filter: `drawtext` ❌  (using legacy approach, not ASS)
- File: `render/subtitle_filter.py` line 45
- ASS module: NOT FOUND
- pysubs2: NOT INSTALLED

### 1.3 Workers
- `workers/voice_align_worker.py`
- (other...)

### 1.4 Comparison vs Plan D spec
| Plan D component | Status in current code |
|---|---|
| voice/voice_scanner.py (multi-file) | ❌ MISSING |
| voice/deterministic_aligner.py | ❌ MISSING (using Claude phase mapping instead) |
| voice/llm_fallback.py | ❌ MISSING |
| voice/ass_generator.py | ❌ MISSING |
| Phase grouping logic | ✅ STILL PRESENT (Plan D removed) |
| Drawtext subtitle | ✅ STILL PRESENT (Plan D removed) |

→ Conclusion: Code hiện tại vẫn là Sprint 2 architecture, chưa migrate sang Plan D.

---

## 2. Whisper Output

Whisper transcribed `voice/voice1..mp3`:
- Duration: <TO BE FILLED>
- Segments: <TO BE FILLED>
- Words: <TO BE FILLED>
- Full transcript:

> "<TO BE FILLED — paste actual Whisper output here>"

(Print word-level timestamps if helpful)

---

## 3. Voice Alignment Verify Table

[Bảng chi tiết per scene như Phase 3]

---

## 4. Subtitle Audit

### 4.1 Subtitle output type
- Type: drawtext (legacy)
- File: `render/subtitle_filter.py`
- Filter snippet: `drawtext=fontsize=64:fontcolor=yellow:...`

### 4.2 Subtitle phrases analysis
- Total phrases: 7
- Average phrase length: 84 chars (TOO LONG, should be ~50)
- Phrases with word timestamps: 0/7 ❌ (no karaoke possible)
- Duplicate text between scenes:
  - SCENE-02 phrase[0] == SCENE-03 phrase[0] (same text "A barista wipes...")

### 4.3 Visual inspection (rendered SCENE-05)
- Subtitle position: bottom 80%  ✓
- Color: yellow with black border  ✓
- Size: 64px (too large, overflows)  ❌
- Karaoke: NO (whole phrase yellow at once)  ❌
- Margin: 0 (overflows screen edges)  ❌

---

## 5. Bugs Detected (sorted by severity)

### CRITICAL
1. **Subtitle phrases lặp text giữa scenes** — bug ở chunking algorithm
2. **Voice mapping group multi-scenes vào 1 phase** — bug Sprint 2 phase logic
3. **Subtitle drawtext (no ASS karaoke)** — Plan D chưa apply

### HIGH
4. **Subtitle quá to + tràn màn hình** — fontsize 64 thay vì 50
5. **No margin 2 bên** — tràn ngang
6. **Subtitle phrases không có word timestamps** — không karaoke được

### MEDIUM
7. SCENE-04 voice text overlap với SCENE-03 và SCENE-05
8. Phase grouping silence threshold 0.5s gây cắt sai

---

## 6. Recommendations (NOT IMPLEMENTED)

→ Build Sprint 3 voice rebuild Plan D theo MD docs/voice_rebuild/.

KHÔNG implement gì trong session này. User sẽ quyết định fix sau.
```

---

## Build order Claude Code

1. **Phase 1** (15 phút): list files + identify entry points
2. **Phase 2** (15 phút): run alignment, capture output
3. **Phase 3** (30 phút): build voice align table
4. **Phase 4** (15 phút): subtitle audit
5. **Phase 5** (15 phút): write VERIFY_REPORT.md

Total: **~1.5h**

---

## Critical reminders

1. **NO CODE CHANGES** — touch nothing in voice/, render/, workers/, ui/
2. **Output single file** — `D:\Projects\story_video_making\test_live\VERIFY_REPORT.md`
3. **Voice align table phải chi tiết** — 3 dòng (Script / Voice / Match) + Diagnosis + Video duration per scene
4. **Diagnosis dùng simple heuristic** — không cần Claude AI sophisticated
5. **Compare with Plan D spec** — point out gap rõ ràng

---

## Confirm trước khi run

- [ ] Voice mp3 hiện tại đã sẵn sàng (test_live/voice/voice1..mp3)
- [ ] scenes.json đã có 5 scenes
- [ ] voice_mapping.json hiện tại (nếu có) sẽ được đọc, KHÔNG ghi đè
- [ ] rapidfuzz available (verify: `python -c "from rapidfuzz import fuzz"`)
  - Nếu không có: `pip install rapidfuzz` (chỉ install, không sửa code)
- [ ] Backup test_live trước khi run (just in case)

→ Run xong, paste VERIFY_REPORT.md cho user. KHÔNG fix gì.
