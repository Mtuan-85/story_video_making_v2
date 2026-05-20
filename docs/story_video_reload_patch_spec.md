# Story Video Maker — Reload & Project File Convention Patch

> **Mục đích**: Patch spec để fix 2 vấn đề trong app Story Video Maker hiện tại:
> 1. Reload không refresh thumbnail preview khi user thay đổi file source
> 2. Naming convention `picN.jpg` / `vidN.mp4` cứng nhắc, cần linh hoạt hơn
>
> **Đối tượng đọc**: Claude Code chạy trong project root của Story Video Maker.
> Đọc spec này trước, sau đó investigate code hiện tại để xác định vị trí cần
> sửa, rồi clarify với user trước khi code.
>
> **Trạng thái**: Đây là patch, không phải rebuild. Code base đã có, chỉ
> chỉnh các module liên quan tới project loading + thumbnail generation +
> file path resolution.

---

## 1. Bối cảnh

Story Video Maker là PyQt6 desktop app tự động hóa pipeline tạo video story
từ `scenes.json` → `final.mp4`. Code hiện tại có:

- `core/schema.py` — Pydantic schema cho `scenes.json`
- `core/project.py` — `Project.load()` đọc scenes.json + state.json
- `core/paths.py` — `ProjectPaths` với `image_path(N)`, `video_path(N)`
- `engines/grok/` — automation Grok cho gen ảnh/video
- `slideshow/`, `render/` — render pipelines
- `ui/` — MainWindow + scene rows + dialogs
- `workers/` — async task workers

User workflow điển hình:
1. Tạo scenes.json
2. Gen ảnh/video qua Grok hoặc slideshow → file vào `sources/`
3. Import voice + align
4. Render final.mp4

---

## 2. Vấn đề 1 — Reload không refresh thumbnail

### Triệu chứng

User experience report:
> "Tôi thay đổi lại sources, gen lại, thêm cảnh, bổ sung file. Thay scenes.json
> và scenes_edited.json. Nhưng khi load lại dự án app đã nhận đủ số scenes
> trong sources, NHƯNG preview thì không hiện chuẩn. Vẫn là loading thumb cũ."

Có nghĩa là:
- Scenes count update OK
- Scene rows render đúng số lượng
- Nhưng **thumbnail trong từng scene row vẫn là phiên bản cũ**
- Click "Reload" cũng không sửa được

### Nguyên nhân nghi ngờ

Một hoặc nhiều trong các nguyên nhân sau:
1. Thumbnail được cache vào memory (QPixmap/QImage object) ở scene row widget, reload không invalidate
2. Thumbnail file được cache vào disk (vd `cache/thumb_N.png`) và reload không regen
3. `Project.load()` re-read scenes.json nhưng không re-scan sources/ nên không biết file đã đổi
4. PyQt QPixmap có internal cache theo file path — nếu file path không đổi, QPixmap có thể trả lại bitmap cũ ngay cả khi file disk đã update

### Behavior mong muốn sau khi fix

User click **"Reload project"** trong UI → app phải làm tuần tự:

1. **Re-read `scenes.json` từ disk** — refresh memory state hoàn toàn, không dùng cached `Project` object
2. **Re-read `state.json` từ disk** nếu có
3. **Scan thư mục `sources/`** — list tất cả file thực sự tồn tại trên disk
4. **Reconcile** giữa scenes.json và sources/:
   - Mỗi scene trong JSON: kiểm tra file ảnh + file video có tồn tại không. Đánh dấu status (`has_image`, `has_video`, `missing`) trong runtime state.
   - File trong sources/ không match scene nào: log warning, không tự động xử lý.
5. **Invalidate thumbnail cache** — xóa hoặc bypass mọi cache liên quan tới scene preview:
   - Memory cache: clear QPixmap cache, gán lại từ file path
   - Disk cache: nếu có folder `cache/thumbnails/` hoặc tương tự, regenerate
   - Force PyQt reload pixmap với `QPixmap()` constructor mới + `cache=False` flag nếu cần
6. **Regenerate preview thumbnail** cho mỗi scene từ file source hiện tại trên disk
7. **Update UI** — scene rows render lại với thumbnail mới + status icons mới

### Yêu cầu kỹ thuật cụ thể

- Reload phải **idempotent**: gọi reload 2 lần liên tiếp cho cùng kết quả
- Reload phải **không phá state runtime quan trọng**: ví dụ scene đang được generate, voice đang align, không bị abort
- Reload phải **synchronous từ góc nhìn user**: kết thúc hàm là UI đã hoàn toàn refresh
- Có log rõ ràng: `[HH:MM:SS] Reloading project... 5 scenes, 4 image files, 3 video files in sources/. Regenerated 5 thumbnails.`

### Câu hỏi cần Claude Code investigate trước khi code

1. Thumbnail hiện tại được tạo như thế nào? Cache ở đâu (memory only, disk, hay cả 2)?
2. `Project.load()` có cơ chế force-reload không hay chỉ load lần đầu?
3. Scene row widget có reference QPixmap trực tiếp không? Có cần emit signal để row tự refresh không?
4. Nút "Reload project" trong UI hiện tại đang làm gì? Trigger function nào? Thiếu gì so với behavior mong muốn ở trên?

---

## 3. Vấn đề 2 — Naming convention cứng nhắc

### Hiện tại

Code dựa vào convention `picN.jpg` / `vidN.mp4`:
- Scene id 1 → `sources/pic1.jpg`, `sources/vid1.mp4`
- Scene id 2 → `sources/pic2.jpg`, `sources/vid2.mp4`
- ...

`core/paths.py` có `image_path(N)`, `video_path(N)` build path bằng template.

### Vấn đề khi user re-organize

User thực tế:
> "Tôi thay đổi lại sources vì không phù hợp, gen lại, thêm cảnh, bổ sung file.
> Tôi đổi tên thành `scene_05.jpg` và `scene_05.mp4` vào sources."

User muốn:
- Đổi tên file source theo ý mình (vd `scene_05.jpg` thay vì `pic5.jpg`)
- Thêm scene mới mà không phải shift toàn bộ index của scene cũ
- Multiple naming patterns coexist trong cùng project

### Behavior mong muốn

scenes.json là **source of truth** cho file path. Mỗi scene entry có thể chứa
explicit path:

```json
{
  "id": 5,
  "image_file": "scene_05.jpg",
  "video_file": "scene_05.mp4",
  "visual_type": "Image",
  "story_en": "...",
  "duration": 3.0,
  ...
}
```

- `image_file` và `video_file` là path **relative to sources/** (hoặc absolute nếu muốn)
- Nếu field không có → fallback theo convention cũ (`picN.jpg`, `vidN.mp4`) để backward compat
- Khi gen Grok / slideshow xong → ghi explicit path vào scenes.json với tên file vừa download

### Migration cho project hiện có

User mở project cũ với scenes.json không có `image_file`/`video_file` field:
- Lần load đầu tiên: app detect missing field, auto-fill bằng convention cũ:
  ```json
  "image_file": "pic5.jpg",
  "video_file": "vid5.mp4"
  ```
- Save scenes.json lại với fields mới
- User có thể edit sau

### Câu hỏi cần investigate trước khi code

1. `core/schema.py` define `Scene` Pydantic model như thế nào? Field nào hiện đang có?
2. `core/paths.py` `image_path(N)` / `video_path(N)` được gọi ở đâu trong code base? Cần refactor để nhận path từ scene entry thay vì hardcode template.
3. Engine adapters (`engines/grok/engine.py` `GrokImageEngine.gen_image()`) hiện ghi file ra path nào? Sau khi đổi convention, các engine này cần update path arg.
4. Migration cho project cũ có nên auto-convert hay yêu cầu user trigger thủ công?

---

## 4. Vấn đề 3 — Project file convention

### User request

User muốn cơ chế:
> "Chọn file json dự án `projectA.json` → tìm `projectA_edited.json`, nếu không
> có thì là dự án mới, tạo `projectA_edition.json`, `projectA_state.json`, và
> tạo các thư mục cơ bản trong thư mục root đó để chạy."

### Đề xuất đơn giản hóa (cần user confirm)

User mô tả 3 file (`_edited`, `_edition`, `_state`) — tôi đề xuất giảm xuống
**2 file** cho đơn giản, trừ khi user có lý do specific cần 3 file:

```
project_root/
├── projectA.json              # User chọn — canonical scenes definition (read-write)
├── projectA_state.json        # Auto-created — runtime state cache (UI state, last reload time, ...)
├── sources/
│   ├── scene_01.jpg
│   ├── scene_01.mp4
│   └── ...
├── voice/                     # Voice files (optional)
├── thumbnails/                # Auto-generated, regen on reload
└── renders/                   # Per-scene composite outputs (optional intermediate)
└── final.mp4                  # Final output
```

**Open project flow:**

User chọn `projectA.json` qua file dialog:

1. Detect project root = parent folder của `projectA.json`
2. Tìm `projectA_state.json`:
   - Có → load runtime state
   - Không có → tạo blank, treat as new project session
3. Auto-create folders thiếu (`sources/`, `voice/`, `thumbnails/`, `renders/`) nếu chưa tồn tại
4. Load scenes from `projectA.json`
5. Run reload pipeline (mục 2 trên) để sync với sources/

**Câu hỏi cho user (Claude Code phải hỏi user trước khi code):**

- 3 file `_edited`, `_edition`, `_state` mỗi cái phục vụ purpose gì? Hay simplify xuống 2 file là đủ?
- `_state.json` cần track gì? (last selected scene, render progress, voice align method, last reload time, thumbnail invalidation key, ...)
- Có cần version field trong project json để future-proof migration không?

---

## 5. Acceptance criteria

App pass nếu:

### Reload behavior

1. **Reload basic**: User edit scenes.json bên ngoài app (thêm scene 6) → click Reload trong app → scene 6 xuất hiện với thumbnail đúng.

2. **Reload sau đổi tên file**: User rename `pic5.jpg` thành `scene_05.jpg` + update scenes.json field `image_file`: `"scene_05.jpg"` → click Reload → thumbnail hiển thị `scene_05.jpg`, không phải cached version cũ.

3. **Reload sau replace file**: User overwrite `pic5.jpg` (cùng tên file nhưng nội dung khác) → click Reload → thumbnail update với content mới (test này phát hiện QPixmap cache issue).

4. **Reload với file bị xóa**: User xóa `pic5.jpg` khỏi sources/ nhưng vẫn còn entry trong scenes.json → click Reload → scene row 5 hiển thị icon "missing image" + log warning, không crash.

5. **Reload với orphan file**: User để file `random.jpg` trong sources/ không match scene nào → click Reload → log warning về orphan, scene rows không thay đổi.

### Naming convention

6. **Backward compat**: Mở project cũ (scenes.json không có `image_file`/`video_file`) → app load OK với convention `picN.jpg`/`vidN.mp4` → save → scenes.json update với explicit fields.

7. **Custom naming**: User edit scenes.json với `"image_file": "scene_05.jpg"` → reload → app dùng đúng path đó, không tự động fall back về `pic5.jpg`.

8. **Gen mới với explicit path**: User trigger Grok gen ảnh cho scene mới → engine ghi file với tên user-chosen (hoặc auto-generated từ scene id) → scenes.json update với path đó.

### Project file

9. **Mở project mới**: Pick `newproject.json` (chưa tồn tại) → app tạo file + folders → state blank.

10. **Mở project có sẵn**: Pick `projectA.json` đã có → tự load `projectA_state.json` nếu có, runtime state restored.

11. **Auto-create folders**: Mở project mà sources/ không có → app tự tạo, log info.

---

## 6. Implementation guidance cho Claude Code

### Step 1 — Investigation

Đọc và summarize cho user:
- `core/schema.py` — current Scene fields
- `core/paths.py` — path resolution logic
- `core/project.py` — load/save flow
- UI module render thumbnail (search `QPixmap`, `thumbnail`, `preview`)
- Reload logic hiện tại (search `reload`, `refresh`)

### Step 2 — Clarify với user

Trước khi code, hỏi user:
1. 3 file `_edited`/`_edition`/`_state` cần phân biệt rõ vai trò không, hay simplify được?
2. Migration auto hay manual? (auto convert old scenes.json sang new format khi load lần đầu)
3. Naming convention mới: chỉ accept basename relative tới sources/ hay accept absolute path? Recommend basename only để portable.
4. Thumbnail invalidation: dùng file mtime? hash? hay luôn regen mỗi reload?

### Step 3 — Plan + propose

Sau khi user trả lời, propose plan với danh sách file cần sửa + summary thay đổi mỗi file. Không code trước khi user approve plan.

### Step 4 — Implement theo phase

Suggest order:
- A. Schema update (Scene field `image_file`, `video_file` optional)
- B. Path resolution refactor (đọc từ scene entry với fallback)
- C. Reload pipeline (full re-read + invalidate cache + regen thumb)
- D. Project file convention (state.json, auto-create folders)
- E. Migration cho project cũ
- F. UI integration + test

Sau mỗi phase báo lại user test trước khi tiếp.

### Step 5 — Manual smoke test

Sau khi code xong, test các acceptance criteria ở mục 5 với project thật của user.

---

## 7. Notes

- **Không** rewrite Story Video Maker từ đầu. Chỉ patch các module liên quan.
- **Giữ** backward compat với scenes.json cũ khi có thể (auto-migrate, không break).
- **Vietnamese log messages** để consistent với UI hiện tại.
- **Atomic save** cho scenes.json + state.json (write tmp + rename) để tránh corrupt khi crash giữa save.
- **Document** mỗi quyết định kiến trúc lớn vào `ARCHITECTURE.md` hoặc README để future maintainers hiểu.

---

## End of Patch Spec

**Single source of truth**: File này là patch spec, đọc cùng với codebase
hiện tại (`core/`, `engines/`, `ui/`, `workers/`, `render/`).

**Do not**: Build new project từ đầu. Modify Milestone 1 / Zone Animate /
slideshow_v4 (đó là project khác).

**For Claude Code**: Investigate codebase trước, clarify với user, propose
plan, code theo phase. Sau mỗi phase test thực tế với project của user.
