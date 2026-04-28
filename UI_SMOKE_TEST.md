# UI SMOKE TEST — Story Video Maker

> Goal: Test app PyQt6 + Grok engine end-to-end qua UI.
> Mục tiêu: click 1 button gen được 1 ảnh = SUCCESS.

---

## Bước 0 — Pre-flight check (5 phút)

### 0.1. Verify dependencies

```powershell
cd D:\Projects\story_video_making
.venv\Scripts\activate

# Check core packages
python -c "import PyQt6; print('PyQt6 OK')"
python -c "import patchright; print('patchright OK')"
python -c "import qasync; print('qasync OK')"
python -c "from loguru import logger; print('loguru OK')"

# Verify imports from project
python -c "from core.schema import ScenesJson; print('schema OK')"
python -c "from core.project import Project; print('project OK')"
python -c "from engines.grok.engine import GrokImageEngine; print('engine OK')"
python -c "from ui.main_window import MainWindow; print('main_window OK')"
```

→ Tất cả phải in `OK`. Nếu có ImportError → báo cho mình debug.

### 0.2. ffmpeg available

```powershell
ffmpeg -version | Select-Object -First 1
```

→ Phải in version. Nếu không có:
```powershell
winget install Gyan.FFmpeg
# Đóng terminal, mở lại để PATH refresh
```

### 0.3. Patchright browser installed

```powershell
patchright --version
ls .venv\Lib\site-packages\patchright\driver\package\.local-browsers
```

→ Phải có folder `chromium-XXXX` bên trong. Nếu chưa:
```powershell
patchright install chromium
```

---

## Bước 1 — Launch Brave debug (1 phút)

Tạo file `launch_brave_debug.bat` ngay tại project root:

```bat
@echo off
set BRAVE="C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe"
set PROFILE=D:\brave-grok-profile
%BRAVE% --remote-debugging-port=9222 --user-data-dir=%PROFILE% --no-first-run https://grok.com/imagine
```

→ Double-click `launch_brave_debug.bat`. Brave mở vào grok.com/imagine.

**Login Grok 1 lần** (nếu lần đầu profile mới). Sau đó để Brave chạy nền, KHÔNG đóng.

### Verify CDP

```powershell
curl http://localhost:9222/json/version | ConvertFrom-Json | Select Browser, webSocketDebuggerUrl
```

→ Phải in JSON có `Browser`, `webSocketDebuggerUrl`. Nếu fail → Brave chưa launch debug port đúng.

---

## Bước 2 — Setup test project (2 phút)

```powershell
# Tạo project test
mkdir test_run -ErrorAction SilentlyContinue

# Copy scenes.json mẫu vào
copy examples\scenes_voice_test.json test_run\scenes.json

# Verify
type test_run\scenes.json | Select-Object -First 5
```

→ Phải thấy JSON header `{"version": "1.0", ...}`.

---

## Bước 3 — Launch app PyQt6 (3 phút)

```powershell
python main.py
```

### Expected:

| ✓ | Item |
|---|---|
| ☐ | Cửa sổ PyQt6 mở ra, không crash |
| ☐ | Có panel "Connection" (CDP URL field, Connect button) |
| ☐ | Có panel "Project" (Load button) |
| ☐ | Có scene list area (rỗng) |
| ☐ | Có log/status area |
| ☐ | Title bar "Story Video Maker" hoặc tương tự |

### Nếu crash khi launch:

```
ImportError: ... → paste error cho mình
ModuleNotFoundError: ... → file thiếu, paste cho mình
Qt error → set env QT_DEBUG_PLUGINS=1 và relaunch
```

→ Screenshot UI gửi mình verify trước khi đi tiếp.

---

## Bước 4 — Test Connection (2 phút)

Trong UI:

1. **Field CDP URL** → để default `http://localhost:9222`
2. **Click [Connect]**

### Expected:

| ✓ | Item |
|---|---|
| ☐ | Status hiển thị "Connected" hoặc icon xanh |
| ☐ | Log area hiện message "Connected to Brave" |
| ☐ | KHÔNG có exception popup |

### Nếu fail:

- "Connection refused" → Brave chưa launch debug port. Re-run `launch_brave_debug.bat`
- "No tabs found" → Brave có nhưng chưa mở tab. Mở thủ công https://grok.com/imagine

---

## Bước 5 — Test Load Project (2 phút)

1. **Click [Load Project]** hoặc tương tự
2. **Browse to** `D:\Projects\story_video_making\test_run\scenes.json`
3. **Open**

### Expected:

| ✓ | Item |
|---|---|
| ☐ | Scene list hiển thị 6 rows (SCENE-01 → SCENE-06) |
| ☐ | Mỗi row có ID + visual_type + status icons |
| ☐ | Status icons đều "pending" (grey/empty) |
| ☐ | File `test_run/state.json` được tự tạo |

Verify state.json:
```powershell
type test_run\state.json
```

→ Phải có 6 scenes với status pending.

---

## Bước 6 — TEST CHÍNH: Gen 1 ảnh (5-10 phút)

Đây là test quan trọng nhất.

1. **Click vào SCENE-01** → highlight row
2. **Click [Gen Image]** trên scene-01 (hoặc button trên toolbar áp dụng cho scene đang select)

### Expected timeline:

```
T=0s:  Status icon SCENE-01 chuyển sang "generating" (vàng/spinner)
T=0-5s: Brave window TỰ ĐỘNG:
       - Switch to Image mode
       - Set Quality + Aspect 16:9
       - Type prompt vào input
       - Click Submit
T=5-60s: Grok đang generate (4 ảnh masonry)
T=60-90s: Download 1 ảnh về sources/SCENE-01.jpg
T=DONE: Status icon SCENE-01 → "ready" (xanh)
        File sources/SCENE-01.jpg tồn tại
```

### Verify cuối:

```powershell
ls test_run\sources\
type test_run\state.json | Select-String "SCENE-01"
```

→ Phải có file ảnh + state SCENE-01.image = "ready".

### Nếu fail giữa chừng:

| Triệu chứng | Nguyên nhân | Fix |
|---|---|---|
| Click button không phản hồi | Worker không emit signal | Check worker code |
| Brave không tự động làm gì | Engine không connect được | Check log app |
| Mode switch fail | Selector sai | Update `engines/grok/selectors.py` |
| Submit không work | Selector sai | Inspect DOM thật |
| "Rate limit" | Grok bị throttle | Đợi 5 phút retry |
| Download không có file | `MIN_DATA_URI_LEN` filter loop | Tăng wait timeout |

→ Bất kỳ lỗi nào, **paste log app + screenshot Brave** cho mình.

---

## Bước 7 — Stress test (optional)

Nếu Bước 6 PASS, thử:

### 7.1. Gen ảnh batch

Click [Batch Image] → app gen tuần tự 6 ảnh cho 6 scenes.

→ Mất ~6-10 phút. Verify cuối cùng có 6 file ảnh.

### 7.2. Restart app verify state restore

1. Đóng app (X)
2. Mở lại: `python main.py`
3. Load lại `test_run/scenes.json`

→ Status icons phải hiển thị ĐÚNG (xanh cho scenes đã gen, pending cho chưa).

### 7.3. Gen video (1 scene)

1. Đổi 1 scene sang `visual_type: video_grok` trong UI (hoặc edit JSON)
2. Click [Gen Video]

→ Mất ~3-5 phút. Verify file `.mp4` xuống.

---

## Acceptance Criteria

Sprint 1 PASS khi tất cả mục sau đạt:

| ✓ | Tiêu chí |
|---|---|
| ☐ | App PyQt6 launch không crash |
| ☐ | Connect CDP thành công |
| ☐ | Load JSON, scene list hiển thị đúng |
| ☐ | Gen 1 ảnh thành công, file lưu đúng path |
| ☐ | Status icons cập nhật real-time |
| ☐ | state.json persist đúng |
| ☐ | App restart restore được state |
| ☐ | Gen 1 video Grok hoạt động (optional) |

→ PASS hết → Sprint 1 DONE → Sang Sprint 2 (voice splitter).

---

## Báo cáo cho mình

Sau khi test, bro paste:

1. **Bước 0.1 output** — verify imports OK
2. **Screenshot UI** sau khi launch (Bước 3)
3. **Screenshot** sau khi load project (Bước 5)
4. **Screenshot** Brave + UI lúc gen ảnh (Bước 6)
5. **Final state**:
   - `ls test_run\sources\`
   - `type test_run\state.json`
6. **Bất kỳ error message** nào gặp phải

Mình sẽ debug nếu fail, hoặc xác nhận PASS để sang Sprint 2.

---

## Files cần chuẩn bị trước

| File | Vị trí | Status |
|---|---|---|
| `examples/scenes_voice_test.json` | đã có | ✅ |
| `launch_brave_debug.bat` | tạo Bước 1 | ☐ |
| `voice/__init__.py` | Claude Code làm | ☐ |
| `main.py` | Claude Code làm | ☐ |
| `core/schema.py` cleanup | Claude Code làm | ☐ |

→ Sau khi Claude Code xong 3 tasks → Bước 0.1 verify → Bước 1 → ... → Bước 6.
