# SPEC — Naomi Chain Runner with State & Process Isolation

Last updated: 2026-05-20 — supplemented

Spec này định nghĩa kiến trúc mới cho `script_to_scene_quick`, kế thừa
`SPEC_cdp_chatgpt_flow.md` (CDP/ChatGPT flow) và áp dụng pattern GUI
launcher + CLI worker đã verified từ `quick_s1_s2.py`.

Mục tiêu: chạy chain S1→S5 với **state persist** và **tách mỗi step
thành process riêng**, cho phép resume, rerun từng step, và tận dụng
Brave đang mở mà không cần restart.

## 1. Nguyên tắc cốt lõi

1. **1 step = 1 process**. Worker process sống đúng thời gian chạy 1 step
   rồi exit. Patchright/CDP session dọn sạch khi process kết thúc.
2. **GUI không sở hữu Patchright**. GUI chỉ là QProcess launcher + log
   viewer + state display. Vi phạm rule này = quay lại pattern fragile
   của `app_chain.py` cũ.
3. **State persist sau mỗi step**. File `state.json` ghi atomic. Crash
   giữa step không corrupt state.
4. **Brave đang chạy → reconnect, không kill**. Chỉ kill Brave khi
   `connect_over_cdp` thật sự fail (recovery path duy nhất).
5. **Step độc lập về process, phụ thuộc về data**. S2 process không cần
   biết S1 process; chỉ cần file `project_S1.json` đã tồn tại trên disk.
6. **Rerun step phải invalidate downstream**. Nếu chạy lại S2 thành công,
   kết quả S3-S5 cũ không còn đáng tin theo logic chain, dù file output cũ
   vẫn còn trên disk.
7. **Một project chỉ có một worker active**. Dùng project-level lock để tránh
   hai GUI/worker cùng ghi vào `state.json` hoặc cùng overwrite output.

## 2. Kiến trúc

```
┌────────────────────────────────────────────────────────────┐
│  app_chain.py (GUI, long-lived)                            │
│                                                              │
│  - Project picker (folder chứa source.docx)                │
│  - Step status table (đọc state.json, auto-refresh)        │
│  - Buttons: Run All / Run Sn / Run from Sn / Reset / Kill  │
│  - QProcess subprocess manager                              │
│  - Stdout/stderr stream → log panel                         │
│  - Parse log markers → update progress bar                  │
│                                                              │
│  KHÔNG import patchright, KHÔNG own page/browser objects   │
└─────────────────────────┬──────────────────────────────────┘
                          │ QProcess.start("python", ["worker_step.py", ...])
                          ▼
┌────────────────────────────────────────────────────────────┐
│  worker_step.py (CLI, short-lived)                         │
│                                                              │
│  Args: --step S1..S5 --project-dir PATH                    │
│                                                              │
│  1. Acquire project lock                                  │
│  2. Load state.json                                         │
│  3. Validate prerequisite (input file của step có chưa)    │
│  4. Set step running with run_id + pid                      │
│  5. async_playwright() + launch_brave_over_cdp             │
│  6. Run step (SPEC_cdp_chatgpt_flow.md flow)               │
│  7. Save project_Sn.json + project_Sn.raw.txt              │
│  8. Update state.json atomic + invalidate downstream        │
│  9. Print log markers stable cho GUI parse                  │
│ 10. Release lock + sys.exit(code)                           │
└────────────────────────────────────────────────────────────┘
```

## 3. File structure

```
script_to_scene_quick/
├── core/                       (giữ nguyên — đã verified)
│   ├── browser.py              (đã có _kill_stale_cdp_clients + reconnect logic)
│   ├── chatgpt_flow.py         (đã có upload/fill/submit/copy)
│   ├── config.py               (load_gpt_urls)
│   ├── parse.py                (parse_or_wrap)
│   └── state.py                ★ MỚI — state I/O + prerequisite check + lock + invalidation
├── instruction/
│   └── link_custom_gpt.md
├── project/                    (1 project, mở rộng sau thành multi-project)
│   ├── source.docx             ← user cung cấp
│   ├── state.json              ← worker ghi atomic
│   ├── project_S1.json         ← worker output
│   ├── project_S1.raw.txt      ← backup raw clipboard
│   ├── project_S2.json
│   ├── ...
│   └── state.json.tmp          (tạm thời, sẽ rename)
├── worker_step.py              ★ MỚI — CLI worker
├── app_chain.py                ★ REFACTOR — GUI launcher, QProcess
├── run_brave_cdp.bat
└── run_app_chain.bat
```

## 4. State schema

File: `<project_dir>/state.json`. Atomic write qua `state.json.tmp` →
`os.replace`.

```json
{
  "version": 1,
  "created_at": "2026-05-20T01:00:00",
  "updated_at": "2026-05-20T01:03:00",
  "project_dir": "D:/Projects/script_to_scene_quick/project",
  "active_run_id": null,
  "steps": {
    "S1": {
      "status": "done",
      "run_id": "20260520_010000_S1_a1b2",
      "pid": 12345,
      "started_at": "2026-05-20T01:00:00",
      "completed_at": "2026-05-20T01:01:34",
      "duration_s": 94.1,
      "input_file": "source.docx",
      "output_file": "project_S1.json",
      "raw_file": "project_S1.raw.txt",
      "chars": 15066,
      "parse_ok": true,
      "error": null,
      "stale_reason": null
    },
    "S2": {
      "status": "failed",
      "run_id": "20260520_010200_S2_c3d4",
      "pid": 12390,
      "started_at": "2026-05-20T01:02:00",
      "failed_at": "2026-05-20T01:02:45",
      "input_file": "project_S1.json",
      "output_file": "project_S2.json",
      "raw_file": "project_S2.raw.txt",
      "parse_ok": null,
      "error": "ChatGPTResponseError: Stream not done in 600s",
      "stale_reason": null
    },
    "S3": {"status": "pending"},
    "S4": {"status": "pending"},
    "S5": {"status": "pending"}
  }
}
```

Status values: `pending` / `running` / `done` / `failed` / `stale`.

`running` được set khi worker bắt đầu, kèm `run_id` và `pid`. Khi worker
exit, nó chỉ được update state nếu `run_id` trong state vẫn khớp với
`run_id` của worker hiện tại. Rule này tránh worker cũ chết muộn rồi ghi
đè state của worker mới.

Nếu GUI thấy `running` nhưng QProcess tương ứng không còn sống, GUI treat
là indeterminate/stale-running và cho phép user mark failed hoặc retry.

Nếu `state.json` corrupt khi load → backup thành `state.json.corrupt.bak`
và tạo mới. Output files (`project_S*.json`) không bị đụng. GUI có thể
hiển thị nút **Recover state from existing outputs**, nhưng không auto-mark
`done` nếu chưa kiểm tra file output hợp lệ.

### Downstream invalidation rule

Nếu một step đã `done` được chạy lại thành công, toàn bộ downstream steps
không còn được tin cậy theo logic chain. Không xóa output cũ tự động, nhưng
state phải phản ánh rằng các output đó đã stale.

Examples:

- Rerun S1 success → mark S2, S3, S4, S5 as `stale` hoặc `pending`.
- Rerun S2 success → mark S3, S4, S5 as `stale` hoặc `pending`.
- Rerun S3 success → mark S4, S5 as `stale` hoặc `pending`.
- Rerun S4 success → mark S5 as `stale` hoặc `pending`.

Khuyến nghị phase 1: dùng `stale` để GUI cảnh báo rõ ràng, giữ lại
`output_file`/`raw_file` cũ để user có thể mở/recover. Khi user chạy lại
downstream step, status chuyển từ `stale` → `running` → `done`/`failed`.

`Run All` chỉ nên chạy các step có status `pending`, `failed`, hoặc `stale`;
bỏ qua step `done`.

## 5. Worker contract

### CLI arguments

```
python worker_step.py --step Sn --project-dir PATH

  --step          S1 | S2 | S3 | S4 | S5
  --project-dir   Absolute path tới folder chứa source.docx
```

### Prerequisite map

| Step | Input file | Output file |
|---|---|---|
| S1 | `source.docx` | `project_S1.json` |
| S2 | `project_S1.json` | `project_S2.json` |
| S3 | `project_S2.json` | `project_S3.json` |
| S4 | `project_S3.json` | `project_S4.json` |
| S5 | `project_S4.json` | `project_S5.json` (JSON array, voice beats) |

Worker check input file tồn tại trước khi connect CDP. Missing input →
exit 2.

### Project lock

Worker phải acquire project-level lock trước khi set `running` hoặc connect
CDP. Lock file: `<project_dir>/.chain.lock`.

Lock content đề xuất:

```json
{
  "run_id": "20260520_010000_S1_a1b2",
  "pid": 12345,
  "step": "S1",
  "started_at": "2026-05-20T01:00:00"
}
```

Behavior:

- Nếu `.chain.lock` tồn tại và PID còn sống → exit 6.
- Nếu `.chain.lock` tồn tại nhưng PID đã chết → remove stale lock rồi chạy tiếp.
- Worker release lock trong `finally`.
- GUI Stop/Kill có thể để lại stale lock; lần chạy sau phải tự detect PID chết
  và cleanup.

Worker check input file tồn tại trước khi connect CDP. Missing input →
exit 2.

### Exit codes

| Code | Ý nghĩa | GUI action |
|---|---|---|
| 0 | Success, output ghi xong, `parse_ok=True` | Mark step done, có thể chạy step tiếp |
| 1 | Browser/CDP/ChatGPT flow fail | Show error trong log, suggest retry / kill brave |
| 2 | Prerequisite missing (input file chưa có) | Nhắc user chạy step trước đó |
| 3 | Stop signal received gracefully / killed by GUI | Show "Stopped", mark failed/stopped |
| 4 | Parse failed but raw output saved | Mark failed or done-with-warning tùy UI; cho user mở `.raw.txt` |
| 5 | CDP not reachable / Brave not available | Suggest relaunch `run_brave_cdp.bat` hoặc Kill Brave + Retry |
| 6 | Project lock exists and active | Báo project đang có worker khác chạy |

### Log protocol (GUI parse được)

Worker print stdout line-by-line, mỗi line bắt đầu bằng `[HH:MM:SS]`.
GUI parse các marker sau:

```
STEP S1 START              → bắt đầu step
  Input: <path>            → input file đã resolve
  ...                      → log chi tiết (CDP connect, upload, etc.)
STEP S1 DONE 94.1s, 15066 chars, parse_ok=True
STEP S1 FAILED after 45.2s: <error>
STEP S1 PARSE_FAILED after 94.1s, raw_saved=project_S1.raw.txt: <error>
STEP S1 PREREQ_MISSING: <message>
EVENT {"type":"step_done","step":"S1","duration_s":94.1,"chars":15066,"parse_ok":true}
```

GUI **không** parse log chi tiết bên trong. Chỉ parse marker chính hoặc
`EVENT {...}` JSON line nếu có. Log chi tiết hiển thị raw cho user đọc.

### Process behaviors

- Worker **không retry tự động**. Fail 1 lần → exit. User quyết định
  rerun.
- Worker **ghi `running` với `run_id` + `pid`** ngay sau khi acquire lock
  và validate prerequisite.
- Worker **không poll state file** trong khi chạy. Chỉ load 1 lần đầu
  + 1 lần reload trước khi save final state. Khi save final state, worker
  phải verify `run_id` còn khớp trước khi ghi.
- Worker **không kill brave** trừ khi `launch_brave_over_cdp` recovery
  path raise (`core/browser.py` line 32-46 đã có).
- Worker **không poll `.stop` flag**. Stop = GUI kill QProcess hard
  (`Stop` button) → process tree dispose → state.json có thể vẫn ở
  `running`, GUI tự reconcile khi process exit.

Nếu sau này cần graceful stop, thêm `.stop` flag check **giữa các
sub-action** trong step (upload xong / submit xong) — nhưng không
priority ở phase này.

## 6. GUI contract

### Responsibilities

GUI **owns**:

- Project folder picker (browse dialog)
- State file display (auto-refresh từ disk, vd watch via QFileSystemWatcher
  hoặc poll 1s)
- Buttons: Run All / Run Sn / Run from Sn / Reset state / Kill Brave
- QProcess lifecycle (spawn / read stdout / wait finished / kill)
- Stdout/stderr streaming vào log panel
- Progress bar update (parse marker từ stdout)
- Disable buttons khi worker đang chạy

GUI **không** owns:

- Patchright (`from patchright...` không xuất hiện trong app_chain.py)
- CDP session, browser, page, context objects
- ChatGPT flow logic
- Clipboard reading

### Buttons & behaviors

| Button | Logic |
|---|---|
| **Run All** | Tuần tự spawn worker cho mỗi step `status != "done"`. Nếu 1 step exit 1/2 → dừng, không chạy tiếp. |
| **Run S1** ... **Run S5** | Spawn worker cho đúng step đó. Overwrite output cũ. Disable nếu prerequisite chưa có (S2 cần S1.json). |
| **Run from S3** | Spawn worker S3 → S4 → S5 tuần tự. Dùng output S2 đang có (không chạy lại S1, S2). |
| **Reset state** | Confirm dialog → xóa `state.json`. Output files (`project_S*.json`) giữ nguyên (để user có thể recover). |
| **Kill Brave + Retry** | Subprocess gọi `taskkill /F /IM brave.exe /T` cho profile `D:\brave-grok-profile` (cần match cmd line). Sau đó user phải tự `run_brave_cdp.bat`. Hoặc bundle action: kill + relaunch + retry last failed step. |
| **Stop** | `QProcess.kill()`. Sau khi process exit, GUI đánh dấu step đang `running` thành `failed` với error="User stopped". |

Safe Kill Brave command pattern:

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -eq "brave.exe" -and
    $_.CommandLine -like "*D:\brave-grok-profile*"
  } |
  ForEach-Object {
    taskkill /F /PID $_.ProcessId /T
  }
```

Không dùng `taskkill /F /IM brave.exe /T`, vì có thể kill nhầm Brave
thường của user.

### QProcess wiring (skeleton)

```python
self.proc = QProcess(self)
self.proc.setProgram(sys.executable)
self.proc.setArguments([
    str(ROOT / "worker_step.py"),
    "--step", step_name,
    "--project-dir", str(project_dir),
])
self.proc.setProcessChannelMode(QProcess.MergedChannels)  # stderr → stdout
self.proc.readyReadStandardOutput.connect(self._on_stdout)
self.proc.finished.connect(self._on_finished)
self.proc.start()
```

GUI **không** dùng `qasync`, không dùng `asyncio`. Plain Qt event loop +
QProcess.

### State refresh

Options (chọn 1):

- **Poll**: `QTimer` 1 giây tick → đọc state.json → update table.
- **Watch**: `QFileSystemWatcher.addPath(state_json)` → reload trigger.

Poll đơn giản hơn, không có race với atomic write (rename). Khuyên dùng
poll cho phase đầu.

## 7. CDP reconnect strategy

Áp dụng `core/browser.py` đã có. Mỗi worker process:

```
1. _kill_stale_cdp_clients()           ~50ms
   └─ Kill Patchright node.exe ESTABLISHED về port 9223
   └─ KHÔNG đụng brave.exe, KHÔNG đụng node.exe khác

2. ensure_brave_running()              ~10ms (nếu Brave đang sống)
   └─ Check http://127.0.0.1:9223/json/version
   └─ Live → return ngay
   └─ Dead → launch Brave (chỉ trong case này)

3. connect_over_cdp(timeout=15s)       ~1-2s
   └─ Tạo CDP session mới cho process này

4. Recovery (chỉ nếu step 3 fail):
   └─ kill stale clients lần 2
   └─ kill_brave() ← chỉ ở đây
   └─ ensure_brave_running() (relaunch)
   └─ connect_over_cdp() lại
```

Bro user mở Brave bằng `run_brave_cdp.bat` 1 lần lúc đầu phiên. Chạy
10+ worker liên tiếp đều **tận dụng Brave đó**, không restart.

ChatGPT login session persist trong profile `D:\brave-grok-profile` →
worker mới connect là dùng login session cũ luôn, không cần re-login.

## 8. Tab strategy

Theo `core/browser.py:get_or_open_tab`:

- Skip tabs có `/c/{conversation_id}` (stale execution context).
- Match tab theo URL prefix base.
- Hoặc dùng tab trống reusable (about:blank / chrome://newtab).
- Hoặc tạo tab mới.

Worker không close tab cũ. Để Brave tự manage. Sau nhiều run, Brave có
thể tích lũy tabs `/c/` cũ — bro có thể đóng manual hoặc dùng nút "Cleanup
tabs" trong GUI (tương lai).

## 9. Recovery procedures

### Case 1: Worker exit 1 (browser/CDP/ChatGPT flow fail)

GUI hành xử:
- Hiển thị error message trong log + status table
- Suggest user: xem log chi tiết, có thể chỉ là rate limit / model refuse
- User click **Run Sn** lại nếu muốn retry chính step đó

Không auto-retry. Vì nguyên nhân fail rất khác nhau (rate limit, content
policy, CDP, network, ChatGPT UI change) — auto-retry che giấu vấn đề.

### Case 2: Worker exit nhưng output file vẫn ghi được

Có thể xảy ra nếu fail ở bước save state (rất hiếm). Output `project_Sn.json`
có nhưng state vẫn `running` hoặc `failed`. GUI cho user nút "Mark Sn as
done manually" để reconcile — KHÔNG auto-detect.

### Case 3: Worker exit 4 (parse failed but raw saved)

Interpretation:
- Browser flow đã upload, submit, stream wait, copy clipboard thành công.
- Lỗi nằm ở model output không phải JSON hợp lệ hoặc parse rule chưa đủ tốt.

GUI hành xử:
- Hiển thị warning khác với browser fail.
- Cho user mở `project_Sn.raw.txt`.
- Nếu `parse_or_wrap` đã tạo wrapped JSON, có thể cho phép continue thủ công,
  nhưng mặc định không chạy downstream nếu output JSON không đạt contract.

### Case 4: Hang permanent (worker stuck)

Symptom: log dừng ở `Fill prompt` hoặc `Stream wait`, không có marker
`DONE` hoặc `FAILED`. QProcess.state() = Running mãi.

GUI hành xử:
- User click **Stop** → `QProcess.kill()`
- Process exit code = -1 / 137 (terminated)
- GUI mark step `failed` với error="Killed by user (timeout)"
- Suggest user: **Kill Brave + Retry**

### Case 5: CDP stale (connect_over_cdp hang)

`core/browser.py` đã handle: timeout 15s → recovery path → kill brave +
relaunch. Worker output sẽ có log `Cannot connect to Brave over CDP`.

GUI: hiển thị error, user click **Kill Brave + Retry** hoặc tự chạy
`run_brave_cdp.bat`.

### Case 6: Tất cả fail liên tiếp

Nếu Run All fail ở mọi step:
1. Open `run_brave_cdp.bat` console — Brave còn sống không?
2. Check tab ChatGPT trong Brave — còn login không?
3. `netstat -ano | findstr :9223` — port có ESTABLISHED stale không?
4. Kill toàn bộ Brave tree của profile `D:\brave-grok-profile` (không
   đụng Brave normal):
   ```powershell
   Get-CimInstance Win32_Process |
     Where-Object { $_.CommandLine -like '*brave-grok-profile*' } |
     Select-Object ProcessId
   taskkill /F /PID <pid> /T
   ```
5. Relaunch `run_brave_cdp.bat`
6. Manual verify ChatGPT login
7. Thử lại

## 10. Log markers — quy ước

Worker stdout dùng các marker sau (case-sensitive, GUI regex parse được):

```
^STEP (S\d) START$
^STEP (S\d) DONE ([\d.]+)s, (\d+) chars, parse_ok=(True|False)$
^STEP (S\d) FAILED after ([\d.]+)s?: (.+)$
^STEP (S\d) PARSE_FAILED after ([\d.]+)s, raw_saved=(.+): (.+)$
^STEP (S\d) PREREQ_MISSING: (.+)$
^EVENT (\{.*\})$
```

Các log khác là free-form (in bằng `print(f"[HH:MM:SS] ...")`). GUI
hiển thị raw, không parse. Nếu có `EVENT {...}` hợp lệ, GUI ưu tiên parse
JSON event hơn regex text marker.

## 11. Tách project nhiều hơn (future)

Phase này: chỉ 1 project, folder cố định `script_to_scene_quick/project/`.

Phase sau (nếu cần):
- GUI hỗ trợ chọn project folder bất kỳ
- Mỗi project có state.json riêng + output files riêng
- Recent projects dropdown
- Mỗi worker invoke với `--project-dir` tương ứng

Worker code không đổi (đã accept `--project-dir` arg từ phase 1).

## 12. Known issues (chừa chỗ update)

Khi gặp issue mới, ghi vào đây:

- Symptom (log line / behavior)
- Root cause (nếu biết)
- Handling required
- Evidence (date + project run reference)

### Issue 1 — placeholder

(Chưa có issue nào trong design này — sẽ update sau khi chạy thực tế.)

## 13. Verification baseline

Sẽ update sau implementation. Format:

```
Baseline run YYYY-MM-DD:
  - Project: ...
  - Source: ...
  - Steps: S1 (94.1s) → S2 (...) → S3 (...) → S4 (...) → S5 (...)
  - Total: ...
  - Issues: none / list
```

## 14. Non-goals (phase 1)

Để rõ ràng những thứ KHÔNG làm trong design này:

- ❌ Resume từng sub-action trong 1 step (checkpoint trong upload/fill/etc.)
- ❌ Multi-worker concurrent (chạy nhiều step song song trong cùng project)
- ❌ Auto-retry worker khi fail
- ❌ Claude CLI check sau mỗi step (đã loại khỏi quick path)
- ❌ Voice approve dialog cho S5
- ❌ Multi-project workspace
- ❌ Step rollback (undo step done)
- ❌ Diff giữa các lần chạy
- ❌ Cloud sync state

Những thứ trên có thể add sau khi baseline 1-project, 1-worker, 1-chain
hoạt động ổn định.

## 15. Mối quan hệ với spec khác

- `SPEC_cdp_chatgpt_flow.md` — vẫn là contract cho `core/chatgpt_flow.py`.
  Spec này KHÔNG override các selector, timeout, error handling đã định
  nghĩa ở đó.
- Spec này chỉ thêm tầng **orchestration** (state + process isolation +
  GUI launcher) **bên trên** flow đã verified.
- Nếu phát hiện vấn đề ở tầng CDP/ChatGPT flow, update
  `SPEC_cdp_chatgpt_flow.md`, không phải file này.

## 16. Implementation checklist bổ sung

Phase 1 nên implement tối thiểu:

- [ ] `core/state.py`: atomic read/write, default state, corrupt backup.
- [ ] `core/state.py`: prerequisite map S1-S5.
- [ ] `core/state.py`: `run_id` generation + `pid` tracking.
- [ ] `core/state.py`: downstream invalidation after successful rerun.
- [ ] `core/state.py`: `.chain.lock` acquire/release/stale cleanup.
- [ ] `worker_step.py`: exit codes 0/1/2/3/4/5/6.
- [ ] `worker_step.py`: save `.raw.txt` before parse.
- [ ] `worker_step.py`: distinguish parse failure from browser/CDP failure.
- [ ] `app_chain.py`: QProcess only, no Patchright/qasync/asyncio import.
- [ ] `app_chain.py`: safe Kill Brave by command line profile match, not `/IM brave.exe`.
- [ ] `app_chain.py`: show stale downstream steps clearly.

## 17. Tóm tắt nhanh

| Concept | Cũ (app_chain.py monolithic) | Mới (spec này) |
|---|---|---|
| Process lifetime | 1 GUI process chạy cả chain | 1 process = 1 step |
| Patchright owner | GUI (qasync) | Worker (asyncio.run) |
| State | Trong memory, mất khi GUI close | File state.json persist |
| Rerun S3 sau S1+S2 done | Chạy lại từ S1 | Click Run S3, dùng output S2 đã có; S4-S5 bị mark stale |
| Fail S2 | Cả chain abort | S1 còn nguyên, click Run S2 lại |
| Brave restart | Mỗi rerun (worst case) | Không, reuse |
| GUI hang | Nhiều khả năng | Process độc lập, GUI luôn responsive |
| Code complexity | Cao (async + qasync + Qt) | Thấp (worker: asyncio thuần; GUI: Qt thuần) |
