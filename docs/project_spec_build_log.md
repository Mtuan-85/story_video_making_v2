# Project Spec & Build Log Index

**Ngày cập nhật:** 2026-05-25  
**Mục đích:** File đọc nhanh để biết spec chính, build log chính, và các spec phụ của dự án `story_video_making_v2`.

---

## 1. File nguồn chính

| File | Vai trò | Khi nào đọc |
|---|---|---|
| `README.md` | Tổng quan hiện trạng app, cấu trúc module, cách cài đặt và flow sử dụng | Đọc đầu tiên khi onboard hoặc chạy app |
| `SPEC.md` | Architecture specification gốc: pipeline, schema, folder structure, worker pattern, render/voice/UI | Đọc khi cần hiểu thiết kế nền hoặc build lại từ đầu |
| `BUILD_LOG.md` | Nhật ký build theo session, patch đã làm, kiểm chứng đã chạy, việc còn mở | Đọc trước mỗi session code để tránh lặp việc hoặc mất context |

Quy ước: `README.md` phản ánh trạng thái app hiện tại ngắn gọn; `SPEC.md` là spec kiến trúc dài hạn; `BUILD_LOG.md` là lịch sử triển khai và resume hint.

---

## 2. Spec phụ trong `docs/`

| File | Nội dung |
|---|---|
| `docs/fast_mode_spec.md` | Spec Fast Mode: single re-gen dán prompt nhanh trong PreviewDialog, không áp dụng batch |
| `docs/cdp_provider_worker_refactor_spec.md` | Spec active cho GUI/CDP separation, provider worker contract, schema `meta`, canonical `visual_type` |
| `docs/cdp_resilience_refactor_spec.md` | Spec refactor CDP/Brave resilience, phân tích risk và phase đề xuất |
| `docs/voice_alignment_flow.md` | Active contract cho Process Voice, `voice_matching_timeline.json`, master voice, và final render |
| `docs/history/learning/render_voice_timeline_learning.md` | Learning note về lý do bỏ render cắt voice theo scene |
| `docs/history/` | Nơi lưu patch/spec cũ sau khi sprint đóng |
| `docs/voice_rebuild/` | Tài liệu liên quan rebuild voice pipeline |

Khi một patch/spec phụ đã ship và không còn là tài liệu active, chuyển vào `docs/history/` thay vì để rải ở repo root.

---

## 3. Tóm tắt dự án

Story Video Maker là app desktop PyQt6 tự động hóa pipeline tạo video story từ `scenes.json` tới `final.mp4`.

Pipeline chính:

```text
scenes.json
  -> Grok image/video generation qua Brave CDP + Patchright
  -> slideshow / Ken Burns offline nếu scene dùng visual offline
  -> voice timeline matching + subtitle
  -> visual-only timeline render
  -> final mux: master voice + ASS + BGM
```

Module chính:

| Folder | Vai trò |
|---|---|
| `core/` | Schema, project state, path conventions, config |
| `engines/grok/` | Browser automation, actions, flows, engine adapters |
| `workers/` | Async workers cho batch/single image/video, voice align, render |
| `ui/` | PyQt6 main window, scene list, dialogs, refs panel |
| `render/` | Timeline visual render, subtitle filter, BGM/master-audio mixer, assemble, Kdenlive export |
| `slideshow/` | External slideshow pipeline wrapper |
| `voice/` | Whisper/Claude alignment, subtitle builder, legacy Fish TTS |
| `runtime/` | Estimator/history phục vụ dự đoán thời gian |

---

## 4. Trạng thái build log hiện tại

Theo `BUILD_LOG.md`, các mốc gần nhất:

- 2026-05-07: Patch A/B cho PreviewDialog Gen-lẻ, split Gen Image / Gen Animation, flexible project file naming.
- 2026-05-09: Retry/Cancel popup đơn giản hơn và Fast Mode cho single re-gen.
- 2026-05-20: Implemented schema `meta`, GUI/CDP separation for Grok image worker process, and canonical app-level `visual_type` (`Image`, `Video`, `slideshow`).
- 2026-05-20: Có thêm spec `docs/cdp_resilience_refactor_spec.md` để xử lý risk CDP/Brave.
- 2026-05-25: Final render chuyển sang native `voice_matching_timeline.json` + continuous `master_voice.wav`; BGM active ở `-17dB`; ref image chuyển sang `{stem}_ref_mapping.json`.
- 2026-05-25: Slideshow SFX hiện chỉ nằm trong MP4 slideshow standalone; final render strip audio scene segments (`-an`). Khi mở rộng engine, cần thêm SFX timeline/mix pass nếu muốn SFX vào `final.mp4`.

Việc còn mở đáng chú ý:

- Cần live UI test cho PreviewDialog Gen Image / Gen Animation.
- Cần live test Fast Mode với image, image-with-refs, video, slideshow fallback.
- Cần live test Retry/Cancel khi worker fail đủ 3 lần.
- Subtitle phrase extraction trực tiếp từ `voice_matching_timeline.json` còn deferred; hiện ASS vẫn đọc legacy `voice_mapping.json` nếu có.
- Slideshow SFX trong final render còn deferred; xem `slideshow/README_V2.md` mục Sound Effects Contract.
- Grok video process-worker, ChatGPT, Gemini còn deferred.
- CDP resilience refactor chưa triển khai, chỉ mới có spec.
- Một số doc cũ có thể còn nhắc `preview_image` / `preview_video` dialog sau khi UI chuyển sang PreviewDialog unified.

---

## 5. Quy trình cập nhật tài liệu

Khi làm patch mới:

1. Đọc `BUILD_LOG.md` trước để nắm resume hint và thay đổi chưa commit.
2. Nếu patch có yêu cầu/thiết kế riêng, tạo spec phụ trong `docs/`.
3. Khi code xong, thêm entry mới vào `BUILD_LOG.md` gồm:
   - mục tiêu patch
   - file thay đổi
   - verification đã chạy
   - live test còn thiếu
   - resume hint nếu còn việc mở
4. Nếu thay đổi ảnh hưởng flow user hoặc module map, cập nhật `README.md`.
5. Nếu thay đổi kiến trúc/schema/worker contract dài hạn, cập nhật `SPEC.md`.

---

## 6. Lệnh kiểm tra nhanh

```powershell
git status --short
Get-Content -LiteralPath README.md -TotalCount 120
Get-Content -LiteralPath SPEC.md -TotalCount 120
Get-Content -LiteralPath BUILD_LOG.md -Tail 160
Get-ChildItem docs
```
