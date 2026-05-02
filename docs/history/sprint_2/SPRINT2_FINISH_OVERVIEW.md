# Sprint 2 — Finish Plan (Updated)

> **Goal**: Hoàn thành Sprint 2 với 3 phases. Tổng ~17-23h Claude Code.
>
> **Build sequentially**: Phase 1 → Phase 2 → Phase 3. Test sau mỗi phase.

---

## Tổng quan 3 phases

| Phase | Mục đích | Priority | Effort | File MD |
|---|---|---|---|---|
| 1 | Voice-first alignment logic | **CRITICAL** (bug fix) | 6-8h | SPRINT2_PHASE1_VOICE_FIRST.md |
| 2 | UI improvements + visual_type/effect dropdowns | High | 7-9h | SPRINT2_PHASE2_UI_IMPROVEMENTS.md |
| 3 | Kdenlive XML export | Medium | 5-7h | SPRINT2_PHASE3_KDENLIVE_EXPORT.md |

**Total: 18-24h Claude Code**

---

## Phase 1 — Voice-First (PRIORITY)

### Vấn đề
Hiện tại scenes bị speed up vì voice override duration.

### Giải pháp
Group voice segments thành phases (theo silence). Map phases → scenes. Scale durations per phase giữ tỉ lệ thiết kế.

### Output
- `voice_mapping.json` schema 3.0 với `duration_adjusted`, `scale_factor`, `phase_id` per scene
- `render/composite.py` dùng `duration_adjusted` thay vì `voice_out - voice_in`
- Review dialog hiển thị scale factors + warnings

→ Detail: **`SPRINT2_PHASE1_VOICE_FIRST.md`**

---

## Phase 2 — UI Improvements + Visual/Effect Dropdowns

### Vấn đề
- 2 checkbox thừa
- Không có thumbnail
- Preview dialog không edit được prompt
- Video preview không play (codec issue)
- Không có cách đổi visual_type nhanh
- Không có effect zoom in/out

### Giải pháp gồm 5 nhóm
1. **Bỏ checkbox 2** + bỏ ⚠ + 🔄 ở cuối row
2. **Thumbnail 60px** cache trong `test_run/thumbnails/`
3. **Visual type dropdown** trong row (3 options: image_grok / video_grok / slideshow_v4)
4. **Effect dropdown** trong row (3 options: zoom_in / zoom_out / no_effect)
5. **Preview Dialog** unified (image + video) với edit prompt
6. **VLC integration** cho video preview

### Logic mới
- scenes.json thêm field `effect`
- Default alternate `zoom_in`/`zoom_out` cho image_grok và slideshow_v4
- Default `no_effect` cho video_grok
- User đổi dropdown = auto save scenes.json
- Effect CHỈ apply lúc render final, KHÔNG apply preview/regen
- Batch video dispatch theo visual_type của mỗi scene (skip image_grok)

→ Detail: **`SPRINT2_PHASE2_UI_IMPROVEMENTS.md`** (đã update với effect feature)

---

## Phase 3 — Kdenlive XML Export

### Mục đích
User fine-tune trong Kdenlive (transitions, effects, color) thay vì chỉ render thẳng.

### Giải pháp
OpenTimelineIO + Kdenlive adapter chính thức.

### Output
- `render/kdenlive_export.py`
- `workers/export_worker.py`
- Button "Export Kdenlive XML"
- Bonus: SRT subtitle export

→ Detail: **`SPRINT2_PHASE3_KDENLIVE_EXPORT.md`**

---

## Sprint 4 (Future, bro tự handle)

```
- Timeline editor app riêng (đọc XML từ project hiện tại)
- AI-powered note interpretation
- Custom transitions templates
```

---

## Build Order Tổng

### Sprint 2 finish workflow

```
Day 1-2: Phase 1 (Voice-first)
  - Build voice_aligner v2
  - Update render composite
  - Test với voice mp3 hiện tại
  - COMMIT: "Sprint 2 Phase 1: voice-first alignment"

Day 3-5: Phase 2 (UI + dropdowns)
  - Bỏ checkbox 2 + cleanup row
  - Thumbnail module
  - Visual type + Effect dropdowns trong row
  - Preview Dialog unified
  - VLC integration
  - Effect zoom apply trong render
  - Refactor batch_video dispatch theo visual_type
  - COMMIT: "Sprint 2 Phase 2: UI + visual/effect dropdowns"

Day 6: Phase 3 (Kdenlive export)
  - Install OTIO + adapter
  - Build kdenlive_export module
  - UI button
  - Test với Kdenlive thật
  - COMMIT: "Sprint 2 Phase 3: Kdenlive XML export"

Day 7: E2E test + tag release
  - Full pipeline test
  - Fix bugs
  - Tag release: v0.2.0 Sprint 2 done
```

---

## Files để paste cho Claude Code

| Khi nào | Paste file nào |
|---|---|
| Bắt đầu Phase 1 | `SPRINT2_PHASE1_VOICE_FIRST.md` |
| Phase 1 xong, bắt đầu Phase 2 | `SPRINT2_PHASE2_UI_IMPROVEMENTS.md` |
| Phase 2 xong, bắt đầu Phase 3 | `SPRINT2_PHASE3_KDENLIVE_EXPORT.md` |

→ KHÔNG paste cả 3 cùng lúc. Mỗi phase 1 file để Claude Code focus.

---

## Confirm trước khi bắt đầu

- [x] Sprint 1 + retry logic đã build và test OK
- [x] Code đã push GitHub (backup)
- [x] Voice mp3 hiện tại sẵn sàng để test Phase 1
- [x] 6 ảnh trong sources/ ready
- [ ] VLC cài trên máy (cho Phase 2 video preview)
- [ ] Kdenlive cài trên máy (cho Phase 3 test)

---

Bro paste Phase 1 MD cho Claude Code khi sẵn sàng.
