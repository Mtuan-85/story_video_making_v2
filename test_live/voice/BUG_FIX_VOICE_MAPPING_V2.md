# Bug Fix v2 — Duration vẫn = 0 sau fix lần 1

> **Status**: Fix lần 1 (Pydantic → dict) không giải quyết được bug.
> **Hypothesis**: Schema có thể không define field `duration` hoặc tên field mismatch.

---

## Trạng thái sau fix lần 1

### Đã cải thiện

- `voice_in` đọc đúng từ phase.start:
  - Phase 2: voice_in = 17.24
  - Phase 3: voice_in = 25.08

### Vẫn bug

```
Phase 1 (3 scenes): scale = 1.00 (phải là 0.71)
Phase 2 (1 scene):  scale = 1.00 (phải là 1.76)
Phase 3 (1 scene):  scale = 1.00 (phải là 0.96)

Mọi scene: 
  duration_original = 0.0  ❌
  duration_adjusted = 0.0  ❌
  voice_out == voice_in    ❌ (do dur_adj = 0)
```

### Verify từ scenes.json

```json
{"id": "SCENE-01", "duration": 8, ...}
{"id": "SCENE-02", "duration": 5, ...}
{"id": "SCENE-03", "duration": 10, ...}
{"id": "SCENE-04", "duration": 4, ...}
{"id": "SCENE-05", "duration": 5, ...}
```

→ scenes.json **CÓ** field `duration` đúng.

→ Vấn đề ở khâu **load** vào Pydantic, không phải ở scenes.json.

---

## Hypothesis mới

### Hypothesis A: Schema thiếu field `duration`

`core/schema.py` class `Scene` có thể không define `duration`:

```python
class Scene(BaseModel):
    id: str
    visual_type: str
    effect: str
    story_en: str
    imagePrompt: str
    videoPrompt: Optional[str] = None
    # MISSING: duration field
```

→ Pydantic ignore field từ JSON → `scene.model_dump()` không có key `"duration"`.

### Hypothesis B: Field name khác

```python
class Scene(BaseModel):
    duration_seconds: int = Field(alias="duration")  # alias mismatch
```

→ Khi dump: key thành `"duration_seconds"` không phải `"duration"`.

### Hypothesis C: Field type sai

```python
class Scene(BaseModel):
    duration: float = 0.0  # default 0
```

Nếu không có validator strict, Pydantic có thể không enforce → fallback 0.

---

## Verify Plan (làm trước khi fix)

### Step 1: Inspect schema

```bash
type core\schema.py
```

Tìm class `Scene`. Locate field liên quan duration. Verify:
- Có field `duration` không?
- Type là gì? (`int` / `float` / `Optional[int]`)
- Có alias không?
- Có default value không?

### Step 2: Test load scenes.json

Tạo file test ngắn `test_load_scenes.py`:

```python
from core.project import Project
from pathlib import Path
import json

p = Project.load(Path("test_run"))

print("=" * 60)
print("First scene info:")
print("=" * 60)
scene = p.scenes_json.scenes[0]
print(f"Type: {type(scene).__name__}")
print(f"Has 'duration' attr: {hasattr(scene, 'duration')}")

if hasattr(scene, "duration"):
    print(f"scene.duration = {scene.duration}")

print("\nAll attributes:")
for attr in dir(scene):
    if not attr.startswith("_"):
        try:
            val = getattr(scene, attr)
            if not callable(val):
                print(f"  {attr} = {val!r}")
        except Exception:
            pass

print("\nmodel_dump():")
dump = scene.model_dump()
print(json.dumps(dump, indent=2))
print(f"\nKeys: {list(dump.keys())}")
```

Run:
```bash
python test_load_scenes.py
```

→ Output sẽ chỉ rõ:
- Field `duration` có tồn tại không
- Value bao nhiêu
- Dump có key `duration` không

### Step 3: Inspect voice_aligner pipeline

`voice/voice_aligner.py` — Locate đoạn:

```python
scenes_dict = {s["id"]: s for s in scenes}
...
scene_durs = [scenes_dict[sid]["duration"] for sid in scene_ids]
```

→ Verify cách access. Nếu `scenes` đã là dicts (sau model_dump):
- `scene["duration"]` work nếu dict có key `"duration"`
- `scene["duration"]` fail nếu key khác (vd `"duration_seconds"`)

### Step 4: Inspect voice_align_worker

`workers/voice_align_worker.py` — Locate chỗ pass scenes:

```python
# Hiện tại có thể:
scenes_data = [s.model_dump() for s in self.project.scenes_json.scenes]

# Verify scenes_data[0] có key "duration" không
log.debug(f"scenes_data[0]: {scenes_data[0]}")
```

Add debug log để confirm.

---

## Fix Plan

### Trường hợp Hypothesis A đúng (schema thiếu duration)

**File**: `core/schema.py`

Add field vào class `Scene`:

```python
class Scene(BaseModel):
    id: str
    visual_type: VisualType
    effect: EffectType = "no_effect"
    duration: int = 5  # default 5 seconds
    story_en: str = ""
    story_vi: Optional[str] = None
    imagePrompt: str = ""
    videoPrompt: Optional[str] = None
    emotion: Optional[str] = None
```

→ Sau khi add, reload project, scene.duration sẽ có value đúng.

### Trường hợp Hypothesis B đúng (alias mismatch)

**File**: `core/schema.py`

Sửa alias hoặc dùng `populate_by_name`:

```python
from pydantic import BaseModel, Field

class Scene(BaseModel):
    model_config = {"populate_by_name": True}
    
    duration: int = Field(default=5, alias="duration")
    # ... other fields
```

### Trường hợp Hypothesis C (type tolerant)

**File**: `core/schema.py`

Strict type:

```python
class Scene(BaseModel):
    duration: int  # required, no default
```

→ Pydantic sẽ raise error nếu scenes.json miss → biết ngay.

---

## Defensive fix trong align function

**File**: `voice/voice_aligner.py`

Sau khi fix schema, add defensive check:

```python
async def align_voice_to_scenes_v2(scenes, ...):
    # Validate input
    if not scenes:
        raise ValueError("scenes list empty")
    
    sample = scenes[0]
    if isinstance(sample, dict):
        if "duration" not in sample:
            raise KeyError(
                f"Scene dict missing 'duration' key. "
                f"Available keys: {list(sample.keys())}"
            )
        if sample["duration"] <= 0:
            log.warning(
                f"Scene {sample.get('id')} has duration={sample['duration']}, "
                f"alignment will be off"
            )
    
    scenes_dict = {s["id"]: s for s in scenes}
    
    # ... rest of logic
```

→ Fail fast khi schema/data wrong, không silent bug.

---

## Test Plan sau fix

### Test 1: Verify schema có duration

```bash
python test_load_scenes.py
```

Expected:
```
scene.duration = 8
Keys: [..., 'duration', ...]
```

### Test 2: Re-run voice alignment

UI: Import voice → assign 5 scenes → Start.

Expected `voice_mapping.json`:

```json
{
  "phases": [
    {
      "phase_id": 1,
      "duration": 16.42,
      "scenes": ["SCENE-01", "SCENE-02", "SCENE-03"],
      "scale_factor": 0.714  ← (16.42 / 23 = 0.714)
    },
    {
      "phase_id": 2,
      "duration": 7.02,
      "scenes": ["SCENE-04"],
      "scale_factor": 1.755  ← (7.02 / 4 = 1.755)
    },
    {
      "phase_id": 3,
      "duration": 4.80,
      "scenes": ["SCENE-05"],
      "scale_factor": 0.96   ← (4.80 / 5 = 0.96)
    }
  ],
  "scenes": [
    {
      "id": "SCENE-01",
      "voice_in": 0.0,
      "voice_out": 5.71,           ← 8 × 0.714
      "duration_original": 8,      ← > 0 ✓
      "duration_adjusted": 5.71,   ← > 0 ✓
      "scale_factor": 0.714,
      "subtitle_phrases": [...]    ← có data ✓
    },
    {
      "id": "SCENE-02",
      "voice_in": 5.71,
      "voice_out": 9.28,           ← 5.71 + 5×0.714
      "duration_original": 5,
      "duration_adjusted": 3.57,
      ...
    },
    ...
  ]
}
```

### Test 3: Verify warnings

Phase 2 scale = 1.755 > 1.5 → phải có warning:

```json
"warnings": [
  "Phase 2: scale 1.76 > 1.5 (voice quá dài so với design)"
]
```

### Test 4: Render thử

Click "Render final":
- Total duration ≈ 29.88s (= voice duration)
- Scenes timing đúng theo `duration_adjusted`
- Subtitles hiện đúng

---

## Build Order

1. **Verify schema** (5 phút) — run test_load_scenes.py
2. **Inspect voice_aligner.py + voice_align_worker.py** (5 phút)
3. **Identify hypothesis đúng** (A/B/C) (1 phút)
4. **Apply fix tương ứng** (15 phút)
5. **Add defensive check trong align function** (5 phút)
6. **Re-run alignment** (5 phút)
7. **Verify voice_mapping.json mới có data thật** (2 phút)
8. **Test render** (5 phút)

**Total: ~45 phút**

---

## Confirm trước khi code

- [ ] Run test_load_scenes.py để biết hypothesis nào đúng
- [ ] Paste output cho user xem
- [ ] Confirm fix approach trước khi apply
- [ ] Re-test sau fix với voice mp3 hiện tại
- [ ] Verify scale factors đúng theo công thức:
  - Phase 1: 16.42 / 23 = 0.714
  - Phase 2: 7.02 / 4 = 1.755
  - Phase 3: 4.80 / 5 = 0.96

Inspect và test trước, fix sau, không guess.
