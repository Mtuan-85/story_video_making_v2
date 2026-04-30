Bug report:
1. UI cho phép user ??i visual_type qua dropdown ? m?i scene row
2. Log confirm các thay ??i ?ã save scenes.json (xem log)
3. Khi click "Batch animation", popup ??m sai s? scene (2 thay vì 4)
4. Slideshow scenes b? skip trong batch animation

Tr?ng thái hi?n t?i:
- SCENE-01: video_grok
- SCENE-02: video_grok
- SCENE-03: slideshow
- SCENE-04: video_grok
- SCENE-05: image_grok

Popup báo: "S?p gen 2 video"
?úng ph?i là: 4 scenes (3 video_grok + 1 slideshow)

Inspect 3 ch?:

# 1. Filter logic trong batch_video worker
File: workers/batch_video.py

Tìm ch? filter scenes by visual_type. Verify:
- Có include "slideshow" / "slideshow_v4" không?
- Visual_type literal ?ang dùng là gì? ("slideshow" hay "slideshow_v4"?)
  ? Quan tr?ng vì UI dropdown hi?n "slideshow" (xem screenshot)
  ? Schema có th? dùng "slideshow_v4"
  ? Mismatch ? filter skip

# 2. Estimator counting trong popup confirmation
File: workers/batch_video.py ho?c ui/main_window.py

Tìm ch? build popup message "S?p gen X video".
Verify count ?úng theo cùng filter ? m?c 1.

# 3. Schema visual_type values
File: core/schema.py

Tìm Literal/Enum c?a VisualType. Verify giá tr? ?ang dùng:
- "image_grok"
- "video_grok"
- "slideshow" ho?c "slideshow_v4"?

# 4. UI dropdown values
File: ui/scene_row.py

Tìm VISUAL_TYPE_OPTIONS list. Verify giá tr? gi?ng schema.

# Fix expected:
- Unify visual_type literal: dùng "slideshow_v4" ho?c "slideshow", cùng 1 giá tr? xuyên su?t
- Filter trong batch_video: include c? slideshow
- Dispatch: 
  - video_grok ? gen i2v qua Grok
  - slideshow / slideshow_v4 ? render slideshow module
  - image_grok ? skip (không c?n video)
- Estimator count ?úng s? scene c?n gen

# Test sau fix:
1. Tr?ng thái: 3 video_grok + 1 slideshow + 1 image_grok
2. Click Batch animation
3. Popup ph?i báo: "S?p gen 4 animation" (ho?c tách: "3 video + 1 slideshow")
4. Click Yes ? gen 3 video_grok i2v + 1 slideshow render
5. Verify state.json: video.status = ready cho c? 4 scenes

Inspect và paste output 4 ch? trên cho user xem tr??c khi fix.