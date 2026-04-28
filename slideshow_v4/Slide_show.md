# 🎬 AI Slideshow Generator v4

Tạo video slideshow tự động từ **1 ảnh scene duy nhất** (bg đơn + nhiều objects + text) bằng cách kết hợp Computer Vision và Claude Code.

**Workflow**: 1 ảnh → tự xóa bg → tự tách objects → Claude group thông minh & design animation → render MP4.

---

## Mục lục

1. [Tính năng](#tính-năng)
2. [Luồng hoạt động](#luồng-hoạt-động)
3. [Cài đặt](#cài-đặt)
4. [Cách dùng](#cách-dùng)
5. [Cấu trúc folder](#cấu-trúc-folder)
6. [Kiến trúc kỹ thuật](#kiến-trúc-kỹ-thuật)
7. [Tuning parameters](#tuning-parameters)
8. [Troubleshooting](#troubleshooting)
9. [FAQ](#faq)

---

## Tính năng

- ✅ **Input tối giản**: chỉ cần 1 ảnh scene với background đơn màu
- ✅ **Giữ text labels**: Chroma key thay vì chỉ AI model — preserve pixel-perfect text (infographic, education content)
- ✅ **Auto-group thông minh**: Claude Code xem scene và group objects có liên quan (text + ảnh tương ứng cùng scene)
- ✅ **6 animations**: `fade_pop`, `slide_left/right/top/bottom`, `zoom_in` — Claude tự pick phù hợp từng vị trí
- ✅ **2 output presets**: YouTube (1920×1080) & TikTok (1080×1920)
- ✅ **Re-generate với hint**: không ưng kết quả → nhập hint ngắn → Claude điều chỉnh
- ✅ **Không tốn API**: dùng Claude Pro/Max subscription qua Claude Code CLI
- ✅ **Cache reuse**: lần chạy 2 trên cùng scene không preprocess lại

---

## Luồng hoạt động

```
┌────────────────────┐
│ 1 ảnh scene.png    │  (bg trắng + 4 objects + 4 text labels)
│ (AI gen, 1024×1024)│
└──────────┬─────────┘
           │
           ▼
┌────────────────────────────────────────┐
│ 1. DETECT BG COLOR                     │
│    Corner+border sampling → median     │
│    → RGB(255,255,255) confidence 1.00  │
└──────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────┐
│ 2. REMOVE BG                           │
│    Auto mode:                          │
│    - confidence > 0.85 → Chroma key    │
│    - confidence ≤ 0.85 → rembg AI      │
│    → scene_nobg.png (RGBA)             │
└──────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────┐
│ 3. FIND REGIONS                        │
│    - Alpha mask                        │
│    - Horizontal dilate 35×7            │
│      (gộp text words cùng dòng)        │
│    - Connected components              │
│    - Filter area < 0.08% canvas        │
│    → 8 regions (4 ảnh + 4 text)        │
└──────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────┐
│ 4. CROP & SAVE                         │
│    Mỗi region → tight crop → PNG       │
│    Lưu position_in_source + size       │
│    → processed/01_obj.png..08_obj.png  │
└──────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────┐
│ 5. CLAUDE CODE ANALYZE                 │
│    Prompt:                             │
│    - Xem scene gốc + 8 PNG đã tách     │
│    - Group semantically (text + image  │
│      tương ứng → cùng scene)           │
│    - Chọn order + animation + pacing   │
│    → plan.json với scenes[]            │
└──────────┬─────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────┐
│ 6. FFMPEG RENDER                       │
│    - Canvas solid color = bg detected  │
│    - Source→canvas coord mapping       │
│    - Multi-object overlay per scene    │
│    - Animation via filter_complex      │
│    → movie/final.mp4                   │
└────────────────────────────────────────┘
```

---

## Cài đặt

### Yêu cầu hệ thống

- Windows 10/11 (Linux/macOS có thể work nhưng chưa test)
- Python 3.11 hoặc 3.12
- Node.js 18+ (cho Claude Code)
- ffmpeg 6.0+
- ~500 MB disk (cache + packages)
- Internet lần đầu để tải rembg model (~170 MB) và packages

### Bước 1: Python, Node, ffmpeg, Claude Code

| Tool | Download | Verify |
|---|---|---|
| Python 3.12 | https://www.python.org/downloads/ (tick **Add to PATH**) | `python --version` |
| Node.js LTS | https://nodejs.org/ | `node --version` |
| ffmpeg | https://www.gyan.dev/ffmpeg/builds/ (release-essentials.zip) → thêm `bin/` vào PATH | `ffmpeg -version` |
| Claude Code | `npm install -g @anthropic-ai/claude-code` | `claude --version` |

**Sau khi cài Claude Code**:
```powershell
claude login
```
Chọn **"Claude Pro/Max subscription"** (KHÔNG dùng API key).

**Quan trọng**: đảm bảo biến env `ANTHROPIC_API_KEY` KHÔNG tồn tại, nếu không sẽ bị tính phí API thay vì dùng subscription:
```powershell
echo $env:ANTHROPIC_API_KEY
# Output phải trống. Nếu có giá trị → xóa qua sysdm.cpl → Environment Variables
```

### Bước 2: UV (package manager nhanh)

UV tạo venv và cài deps nhanh hơn pip ~10x, dùng hard-link để tiết kiệm disk giữa nhiều project.

```powershell
pip install uv
```

**Setup cache folder chung** (1 lần cho mọi project):
```powershell
[Environment]::SetEnvironmentVariable("UV_CACHE_DIR", "D:\caches\uv", "User")
[Environment]::SetEnvironmentVariable("PIP_CACHE_DIR", "D:\Python\cache\pip", "User")
```

**Đóng PowerShell → mở mới** để biến env refresh, rồi verify:
```powershell
uv cache dir
# Phải hiện: D:\caches\uv
```

### Bước 3: Setup project

```powershell
cd D:\Projects\Slide_show_automation\slideshow_v4

# Tạo venv (khuyến nghị đặt tên "venv" để run.bat hoạt động)
uv venv venv

# Activate
venv\Scripts\activate

# Cài dependencies (lần đầu ~30s, lần sau ~5s vì dùng cache)
uv pip install -r requirements.txt

# Pre-download rembg model (~170 MB, chỉ 1 lần)
python -c "from rembg import new_session; new_session('u2net'); print('OK')"
```

### Bước 4: Tạo `run.bat` để chạy 1-click

Trong folder project:
```powershell
@"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo [Loi] Chua tao venv. Xem README muc Cai dat.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python main.py
if errorlevel 1 pause
"@ | Out-File -Encoding ASCII run.bat
```

Lần sau chỉ cần **double-click `run.bat`**.

---

## Cách dùng

### Chuẩn bị folder input

```
D:\Projects\my_scene\
└── scene.png    ← 1 ảnh duy nhất, tên bất kỳ (ưu tiên .png)
```

**Yêu cầu ảnh scene**:
- **Background là màu đơn** (trắng, kem, xám, pastel...) — càng đơn càng tốt
- **Objects không chạm/chồng nhau** (nếu chạm sẽ bị coi là 1 object)
- **Text có thể có**, stroke rõ, màu tương phản với bg
- Format: PNG/JPG/WebP
- Resolution: từ 1024×1024 trở lên để tách object đủ độ phân giải

**Ví dụ tốt**: infographic về life cycle, diagram có label, step-by-step instruction card

**Ví dụ kém**: ảnh chụp phức tạp, bg có texture, objects overlap

### Chạy app

```powershell
python main.py
```

Hoặc double-click `run.bat`.

### Trong app

1. **Browse...** → chọn folder chứa scene
2. **Duration**: tổng thời gian video (vd: 5-10s)
3. **Preset**: YouTube hoặc TikTok
4. **Xóa BG**:
   - **Auto** (khuyên dùng): bg confidence cao → chroma, thấp → rembg
   - **Chroma (giữ text)**: force chroma key — tốt cho infographic, bg trắng
   - **AI rembg**: force AI — cho bg phức tạp, không có text
5. Click **⚡ Generate**

**Pipeline chạy**:
- Preprocess (~5-10s): tách objects
- Claude Code analyze (~30-60s): design animation
- Render ffmpeg (~10-30s): export MP4

Xong có link clickable mở folder kết quả.

### Re-generate với hint

Không ưng kết quả → click **🔄 Re-generate** → nhập hint:

```
- "Text labels và ảnh tương ứng phải cùng scene"
- "Object 1 và 2 nên xuất hiện riêng từng cái"
- "Animation chậm lại, pacing từ tốn"
- "Tất cả text dùng fade_pop, images dùng slide"
- "Scene đầu nên dramatic hơn, zoom_in cho hero"
```

Claude đọc hint và điều chỉnh plan. Preprocess không chạy lại (dùng cache).

---

## Cấu trúc folder

### Trước khi chạy

```
my_scene/
└── scene.png
```

### Sau khi chạy

```
my_scene/
├── scene.png                      (giữ nguyên)
├── .cache/                        ← app tự tạo
│   ├── scene_nobg.png             (output sau bước xóa bg)
│   ├── plan.json                  (layout + animation từ Claude)
│   └── processed/
│       ├── 01_obj.png             (các objects đã tách, transparent)
│       ├── 02_obj.png
│       ├── ...
│       └── metadata.json          (position, size, bg_color, method)
└── movie/
    └── final.mp4                  ← VIDEO OUTPUT (overwrite mỗi lần)
```

### metadata.json schema

```json
{
  "scene_source": "scene.png",
  "source_size": [1024, 768],
  "bg_color_rgb": [255, 255, 255],
  "bg_confidence": 1.0,
  "bg_removal_method": "chroma",
  "chroma_threshold": 25,
  "regions_detected": 8,
  "objects": [
    {
      "filename": "01_obj.png",
      "position_in_source": [200, 50],
      "size": [301, 51],
      "area": 17483,
      "bbox_in_source": [200, 50, 501, 101]
    }
  ]
}
```

### plan.json schema

```json
{
  "duration": 7,
  "scenes": [
    {
      "objects": ["01_obj.png", "02_obj.png"],
      "appear_at": 0.0,
      "animation": "slide_top",
      "rationale": "Title group — text + image stage 1"
    },
    {
      "objects": ["03_obj.png"],
      "appear_at": 2.0,
      "animation": "slide_left",
      "rationale": "Hero subject emerges"
    }
  ]
}
```

- `objects[]`: 1 hoặc nhiều object cùng xuất hiện (group)
- `appear_at`: giây bắt đầu animation
- `animation`: 1 trong 6 loại
- `rationale`: Claude giải thích lý do chọn (debug + hiểu logic)

---

## Kiến trúc kỹ thuật

### Modules

```
slideshow_v4/
├── main.py              # Entry point (PyQt6 QApplication)
├── ui.py                # MainWindow — form inputs, status, result
├── worker.py            # QThread pipeline orchestrator
├── preprocess.py        # Bước 1-4: bg removal + segmentation + crop
├── claude_runner.py     # Bước 5: subprocess call Claude Code
├── renderer.py          # Bước 6: ffmpeg filter_complex builder
├── animations.py        # 6 animation expressions cho ffmpeg overlay
├── debug_preprocess.py  # Script debug standalone (không qua GUI)
├── requirements.txt
└── run.bat              # Windows 1-click launcher
```

### Phương pháp xóa background

#### Chroma Key (recommended cho bg solid)

```python
dist = ||pixel_rgb - bg_color_rgb||
alpha = 255 if dist > threshold else 0
```

**Ưu**:
- Giữ text pixel-perfect (stroke, viền, anti-alias)
- Nhanh (~0.5s)
- Deterministic, predictable
- Không cần GPU/model

**Nhược**:
- Chỉ work với bg solid color
- Nếu object có màu trùng bg → bị xóa nhầm

#### rembg AI (fallback cho bg phức tạp)

U²-Net salient object detection.

**Ưu**: tách được object trên bg ảnh thật, texture, gradient
**Nhược**: **xóa mất text** (text không phải "salient subject" theo VLM)

#### Auto mode

```python
if bg_confidence >= 0.85:  # 85% pixel viền cùng màu
    use chroma_key
else:
    use rembg
```

### Horizontal dilate để gộp text

Text có word-spacing — connected components sẽ tách mỗi word thành region riêng.

**Fix**: Morphological dilate **wide>tall kernel**:
```
Kernel 35×7:
  - Width 35: gộp words cùng dòng
  - Height 7: KHÔNG gộp dòng này với dòng khác
```

Kết quả:
- "4. BỌ TRƯỞNG THÀNH" = 1 region (không phải 4)
- Vẫn tách giữa text row và image row phía dưới

### Coordinate mapping source → canvas

Source có thể là 1024×1024 nhưng canvas là 1920×1080.

```python
scale = min(canvas_w / source_w, canvas_h / source_h)
offset_x = (canvas_w - source_w * scale) / 2
offset_y = (canvas_h - source_h * scale) / 2

# Object position:
target_x = offset_x + pos_src_x * scale
target_y = offset_y + pos_src_y * scale
target_w = size_src_w * scale
target_h = size_src_h * scale
```

Background canvas = solid color (= bg detected) phủ phần còn lại.

### ffmpeg filter_complex structure

```
[0:v] → scale bg to canvas → [bg]
[1:v] → scale obj1 → format=rgba → fade → [obj1]
[bg][obj1] → overlay(x_expr, y_expr) → [v1]
[2:v] → scale obj2 → format=rgba → fade → [obj2]
[v1][obj2] → overlay → [v2]
...
[vN] → format=yuv420p → [out]
```

Animation expression (vd slide_left):
```
x='if(lt(t, start), -w,
    if(lt(t, start+dur), -w + (t-start)/dur * (target_x+w),
       target_x))'
```

### Claude Code integration

Subprocess call qua **stdin pipe** (không phải command line arg — tránh escape issue):

```python
subprocess.run(
    ["claude", "--print", "--dangerously-skip-permissions"],
    input=prompt,           # prompt qua stdin
    env={...no API_KEY},    # force subscription
    ...
)
```

Claude dùng **Read + Write tools** để xem images và ghi `plan.json`.

### Validation plan

Sau khi Claude trả plan.json:
- Minimum 3 scenes (tránh video nhàm)
- Tất cả objects từ metadata phải có trong plan (no skip)
- No duplicate object giữa scenes
- appear_at trong khoảng [0, duration]
- Animation ∈ SUPPORTED_ANIMATIONS
- Auto-convert legacy `"object"` (v2) → `"objects"` array (v3+)

---

## Tuning parameters

Edit trong `preprocess.py` nếu default không phù hợp:

```python
MIN_AREA_PCT = 0.0008        # Region nhỏ hơn X% canvas = noise, bỏ
                              # 0.0005 nếu text quá nhỏ bị filter mất
                              # 0.002 nếu có quá nhiều noise

DILATE_KERNEL_W = 35          # Width dilate — gộp text words
                              # Tăng (50, 70) nếu words cách xa
                              # Giảm (20, 25) nếu bị gộp nhầm object

DILATE_KERNEL_H = 7           # Height dilate — giữ tách giữa rows
                              # KHÔNG tăng >15 vì sẽ gộp nhầm text với image row dưới

BG_CONFIDENCE_THRESHOLD = 0.85   # Auto mode chia dòng
                                  # Giảm xuống 0.7 nếu muốn dùng chroma nhiều hơn
```

Trong `preprocess_scene()`:
```python
chroma_threshold=25     # Khoảng cách RGB để coi là foreground
                         # 15: giữ text stroke mỏng, anti-alias
                         # 35-50: clean edges nhưng mất detail mỏng
```

Trong `claude_runner.py`:
```python
timeout=300             # Claude Code timeout (giây)
                         # Tăng nếu nhiều objects cần phân tích
```

---

## Troubleshooting

### "Không tìm thấy ffmpeg" khi chạy app

ffmpeg chưa trong PATH. Fix:
```powershell
# Check xem ffmpeg.exe ở đâu
Get-ChildItem -Path D:\ -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object FullName

# Thêm folder chứa nó vào PATH
[Environment]::SetEnvironmentVariable("Path", $env:Path + ";D:\ffmpeg\bin", "User")

# Đóng terminal, mở mới, verify:
ffmpeg -version
```

### "Claude Code không tạo được plan"

1. Check Claude Code login:
   ```powershell
   claude --version
   claude /status
   ```
2. Check không có `ANTHROPIC_API_KEY`:
   ```powershell
   echo $env:ANTHROPIC_API_KEY
   # Phải trống
   ```
3. Tăng timeout trong `claude_runner.py` từ 300 → 600

### Text bị mất sau preprocess

- **Nguyên nhân phổ biến**: anh chọn "AI rembg" thay vì "Chroma" hoặc "Auto"
- **Fix**: chọn radio **Chroma (giữ text)**
- Verify: xem `.cache\scene_nobg.png` — nếu text có trong file này thì preprocess OK

### Text không gộp thành 1 label (bị tách từng chữ)

Tăng `DILATE_KERNEL_W`:
```python
DILATE_KERNEL_W = 50  # thay vì 35
```

### Text gộp nhầm với image (1 text row + 1 image row thành 1 region)

Giảm `DILATE_KERNEL_H`:
```python
DILATE_KERNEL_H = 5  # thay vì 7
```

### Objects nhỏ bị filter mất

Giảm `MIN_AREA_PCT`:
```python
MIN_AREA_PCT = 0.0003  # bắt objects siêu nhỏ
```

### App không load code mới sau khi update file

Python đã cache bytecode. Fix:
```powershell
cd D:\Projects\Slide_show_automation\slideshow_v4
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
```

Đóng app, mở lại.

### Debug trực tiếp (không qua GUI)

```powershell
venv\Scripts\activate
python debug_preprocess.py D:\Projects\my_scene
```

Script log chi tiết từng bước, không phụ thuộc Qt.

---

## FAQ

**Q: Tạo 1 video mất bao lâu?**
A: Tổng ~1-2 phút: preprocess 5-10s, Claude 30-60s, render 10-30s (tùy duration).

**Q: Có tốn tiền API không?**
A: Không, nếu đã login Claude Code bằng Pro/Max subscription. App tự clear biến `ANTHROPIC_API_KEY` trước khi spawn subprocess để đảm bảo.

**Q: Subscription có giới hạn gì?**
A: Pro plan có rate limit — render nhiều video liên tục có thể bị delay. Max plan cho giới hạn cao hơn. Check `~/.claude/` để xem usage logs.

**Q: Có thể chạy offline không?**
A: Chroma key + ffmpeg hoạt động offline. Chỉ Claude Code cần internet để gọi API từ anthropic.com.

**Q: Ảnh source phải đúng tỉ lệ với output không?**
A: Không. Scene 1024×1024 có thể render ra YouTube 1920×1080 — app tự scale fit, giữ aspect ratio, pad bg color 2 bên.

**Q: Có support animation custom không?**
A: Hiện có 6 animation hardcoded. Để thêm, edit `animations.py` và list `SUPPORTED_ANIMATIONS`. Cần cả expression ffmpeg và update prompt cho Claude biết.

**Q: Có thể batch render nhiều folder không?**
A: UI hiện 1 folder/lần. Nhưng có thể viết script batch gọi `worker.py` directly trong loop.

**Q: Làm sao check usage của Claude Code subscription?**
A:
```powershell
claude /status
```
Hoặc check folder `~/.claude/` có session logs.

**Q: App có tracking hay telemetry không?**
A: Không. App chỉ gọi Claude Code CLI và ffmpeg local. Claude Code có telemetry riêng của Anthropic (có thể opt-out qua settings của Claude Code).

**Q: Sao text đôi khi bị mất dấu?**
A: Nếu text Unicode có dấu (tiếng Việt), cần font system support đủ character. Chroma key giữ pixel nên không mất dấu trừ khi font source đã bị mất sẵn.

**Q: Có thể edit plan.json thủ công không?**
A: Có. Sau khi preprocess xong, file `.cache/plan.json` có thể edit tay. Nhưng re-generate sẽ overwrite. Nếu muốn giữ: backup ra tên khác.

---

## Versioning

- **v1**: Reference image + N objects riêng lẻ → Claude layout + render
- **v2**: 1 scene → rembg split → `max_objects` + hierarchical merge → Claude layout
- **v3**: Bỏ `max_objects`, Claude tự group, multi-object per scene
- **v4** (current): Thêm Chroma Key để giữ text, horizontal dilate để gộp word labels

---

## License

Tool cá nhân, không phải sản phẩm chính thức của Anthropic. Tuân thủ ToS của Claude subscription khi dùng.

Built with: Python, PyQt6, Pillow, OpenCV, rembg, ffmpeg, Claude Code CLI.
