# Grok Automation

Desktop app (PyQt6) tự động hoá batch generate ảnh/video trên `grok.com/imagine` qua Patchright + CDP.

---

## Tính năng

- 🎨 **4 mode**: text-to-image, image-to-image, text-to-video, image-to-video
- 🤖 **3 pick mode** cho ảnh: auto (free), Claude pick (free, smart), manual dashboard (deferred)
- 📋 Batch xử lý từ JSON prompt list
- 📁 Auto rename file theo `{project}_pic1`, `{project}_vid1`...
- 🌐 Connect vào Chrome đã login sẵn (không spawn browser mới)
- 🧠 Vision pick best variant via Claude Code CLI subprocess (Pro/Max sub, không tốn API)

---

## Setup

### 1. Cài tools

| Tool | Cách cài |
|---|---|
| Python 3.11/3.12 | https://www.python.org/downloads/ |
| Node.js LTS 18+ | https://nodejs.org/ |
| uv | `pip install uv` |
| Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |
| Google Chrome | (đã có) |

Login Claude Code:
```powershell
claude login
```
→ Chọn **"Claude Pro/Max subscription"** (KHÔNG dùng API key)

Đảm bảo `ANTHROPIC_API_KEY` env var trống:
```powershell
echo $env:ANTHROPIC_API_KEY
# Phải hiện trống. Nếu có → xoá qua sysdm.cpl > Environment Variables
```

### 2. Setup project

```powershell
cd path\to\grok_automation

# Tạo venv + cài deps
uv venv
uv sync
```

### 3. Launch Chrome với debug port

Edit `launch_chrome.bat` nếu cần đổi path. Sau đó **double-click** để mở Chrome:

```bat
launch_chrome.bat
```

Lần đầu: login Grok manually trong Chrome này. Profile lưu tại `D:\chrome-grok-profile`, lần sau không cần login lại.

### 4. Verify CDP đã chạy

Mở browser khác (Brave, Firefox), truy cập:
```
http://localhost:9222/json/version
```
Phải ra JSON kiểu `{"Browser": "Chrome/...", ...}` → OK.

---

## Sử dụng

### 1. Chuẩn bị JSON prompt

Copy `examples/prompts_t2i.json` → sửa lại theo nhu cầu:

```json
{
  "project_name": "my_project",
  "mode": "text_to_image",
  "settings": {
    "quality": "quality",
    "aspect": "16:9",
    "pick_mode": "claude"
  },
  "prompts": [
    { "id": 1, "text": "..." },
    { "id": 2, "text": "..." }
  ]
}
```

Với image-to-image hoặc image-to-video, thêm `ref_folder` và `ref_image` cho mỗi prompt:
```json
{
  "ref_folder": "D:/refs",
  "prompts": [
    { "id": 1, "text": "...", "ref_image": "lion.jpg" }
  ]
}
```

### 2. Run app

```powershell
uv run python main.py
```

Trong app:
1. **Connection**: click Connect → chọn tab `grok.com/imagine` từ dropdown
2. **Project**: nhập tên project (sẽ thành prefix file name)
3. **Generation**: chọn mode + options (hoặc load từ JSON)
4. **Prompts**: load JSON file
5. Click **▶ Start**

App sẽ:
- Generate từng prompt theo JSON
- Pick best variant (theo `pick_mode`)
- Download với tên `{project}_pic1.jpg`, `{project}_pic2.jpg`...
- Save vào `output/{project}/`

---

## Output structure

```
output/
└── my_project/
    ├── candidates/                    # Debug only
    │   ├── 0001/
    │   │   ├── strip.png              # Capture 4 ảnh trước khi pick
    │   │   ├── prompt.txt             # Prompt gốc
    │   │   └── pick.json              # Choice + reason từ Claude
    │   └── 0002/
    ├── my_project_pic1.jpg            # Ảnh đã chọn, đã rename
    ├── my_project_pic2.jpg
    └── my_project_pic3.jpg
```

---

## Pick modes giải thích

| Mode | Cost | Speed | Smart? | Dùng khi nào |
|---|---|---|---|---|
| `auto` | Free | <1s | ❌ | Test nhanh, batch lớn không cần chất lượng |
| `claude` | Free* | ~30-60s | ✅ | Production, chất lượng đồng đều |
| `manual` | Free | Tuỳ user | ✅✅ | Quan trọng, review từng ảnh (chưa build) |

*Free nếu có Pro/Max subscription. Pro plan có rate limit.

---

## Troubleshooting

### "Cannot connect to localhost:9222"
- Chrome chưa chạy với debug port. Chạy lại `launch_chrome.bat`.
- Port 9222 bị app khác chiếm. Đổi `DEBUG_PORT` trong batch file.

### "Tab grok.com not found"
- Mở thủ công tab `grok.com/imagine` trong Chrome đã launch.
- Refresh dropdown trong app.

### "Claude CLI subprocess timeout"
- Pro plan rate limit. Đợi 5-10 phút.
- Hoặc đổi `pick_mode: "auto"` để skip Claude.

### "ANTHROPIC_API_KEY detected"
- App từ chối chạy nếu env var này tồn tại (để tránh tính phí API).
- Xoá qua System Properties → Environment Variables.

### Selector fail (UI Grok thay đổi)
- Re-run DOM Inspector extension trên grok.com/imagine.
- Update `grok/selectors.py` với selector mới.

---

## Architecture

Xem `CLAUDE.md` cho project context và `flow_spec.md` cho chi tiết flows.

```
grok_automation/
├── grok/                  # Automation logic
├── ui/                    # PyQt6 widgets
├── workers/               # QThread + asyncio bridge
├── examples/              # JSON templates
└── output/                # Auto-created results
```

---

## License

Internal tool. Không phải sản phẩm chính thức.

Built with: Python, PyQt6, Patchright, qasync, Claude Code CLI.
