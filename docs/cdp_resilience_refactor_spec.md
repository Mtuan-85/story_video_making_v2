# CDP Resilience — Refactor Spec

**Ngày viết:** 2026-05-20
**Tác giả:** đánh giá dựa trên skill `playwright-cdp-resilient` (D:\CLAUDE\.claude\skills\playwright-cdp-resilient\SKILL_playwright_cdp_resilient.md)
**Mục đích:** Ghi nhận khoảng cách giữa kiến trúc CDP hiện tại và best-practice của skill, kèm đề xuất fix theo thứ tự ưu tiên. Spec này tự đủ — session refactor sau này không cần tra cứu lại skill gốc.

**Phạm vi:** Chỉ phần kết nối CDP / Brave automation. KHÔNG đụng tới gen logic, voice, render.

**Không trong scope:**
- Đổi UI flow (vẫn 1 nút Kết nối, 1 dropdown tab)
- Đổi recovery semantics (vẫn retry 3 → popup user decision)
- Migrate sang chain_runner / process-isolation lớn (đã có spec riêng trong `learning/SPEC_chain_runner*.md`)

---

## 0. TL;DR

Hiện tại có **3 vi phạm nặng** và **4 vi phạm nhẹ** so với best-practice. Vi phạm nặng có thể gây:
- Giết nhầm Brave cá nhân của user (P0 — user-facing damage)
- Hang silent ở lần chạy thứ N (P1 — đã thấy ở các project tương tự)
- Mất session Grok mỗi lần retry (P2 — chậm + tốn login)

Khuyến nghị refactor theo 5 phase, mỗi phase đứng độc lập, có thể ship rời.

---

## 1. Kiến trúc hiện tại — ground truth

### 1.1 File map

| File | Vai trò |
|---|---|
| `ui/connection_panel.py` | QGroupBox: URL input, connect/disconnect, tab dropdown. Sở hữu instance `GrokConnection`. |
| `engines/grok/browser.py` | Class `GrokConnection`: wrap Patchright `connect_over_cdp`, list/select tab, `reconnect_cdp`, `kill_and_relaunch_brave`. |
| `core/config.py` | `load_config()` đọc `config.json` (brave launch params), `wait_brave_ready()` poll `/json/version`. |
| `workers/_retry.py` | `run_with_retry()` — wrap gen factory, fail → `connection.kill_and_relaunch_brave()` → retry, max 3. |
| `ui/main_window.py` | Wire `connection_panel.page_ready` → tạo `GrokImageEngine`/`GrokVideoEngine`; truyền `connection` xuống workers. |
| `launch_brave.bat` | `brave.exe --remote-debugging-port=9222 --user-data-dir="D:\CDP_Browser\brave-grok-profile" --no-first-run https://grok.com/imagine` |
| `config.json` | `{"brave": {"launch_bat": "launch_brave.bat", "process_name": "brave.exe", "debug_port": 9222}}` |

### 1.2 Connection lifecycle

```
User click 🔌
  └─► ConnectionPanel._do_connect()
        └─► GrokConnection.connect(url)
              ├─► async_playwright().start()
              └─► chromium.connect_over_cdp(url)
        └─► _refresh_tabs_async()
              ├─► list_tabs(grok_only=True)
              └─► select_tab(0)  [auto-pick first]
        └─► page_ready.emit(page)
              └─► MainWindow._on_page_ready(page)
                    └─► self.image_engine = GrokImageEngine(page)
                    └─► self.video_engine = GrokVideoEngine(page)
```

### 1.3 Recovery (worker fail)

```
gen_factory() raises
  └─► run_with_retry catches (not CancelledError)
        └─► connection.kill_and_relaunch_brave()
              ├─► taskkill /F /IM brave.exe        ← P0 violation
              ├─► _cleanup() (drop Patchright handles)
              ├─► sleep 2s
              ├─► Popen launch_brave.bat
              ├─► wait_brave_ready(9222, 30s)      ← uses 127.0.0.1 socket OK
              └─► reconnect_cdp()
                    ├─► _cleanup()
                    ├─► connect(_cdp_url)          ← url = "http://localhost:9222"
                    ├─► list_tabs(grok_only=True)
                    └─► select_tab(0)
        └─► refresh_page() (worker callback: engine.page = connection.page)
        └─► retry attempt N+1
  └─► sau 3 fail → return {"needs_user_decision": True}
        └─► MainWindow popup [Retry / Skip / Abort]
```

### 1.4 Tiến trình & event loop

- 1 tiến trình Python duy nhất (`python main.py`)
- 1 qasync loop chung cho cả Qt UI và Patchright async I/O
- `GrokConnection` là singleton trong GUI, sống cả phiên app
- Workers (subclass `AsyncTaskWorker`) chạy coroutine trên cùng qasync loop, **không** phải subprocess

---

## 2. Đối chiếu với skill `playwright-cdp-resilient`

Bảng đầy đủ — đánh dấu mức độ + evidence + impact.

| # | Quy tắc skill | Code hiện tại | Mức | Impact |
|---|---|---|---|---|
| **V1** | GUI KHÔNG được import `patchright.async_api`. Lý do: qasync + Qt + async-Patchright trong cùng tiến trình tích lũy state hỏng → hang không catch được. | `ui/connection_panel.py:20` → `from engines.grok import GrokConnection` → `engines/grok/browser.py:15` `from patchright.async_api import ...`. Toàn bộ Patchright sống trong tiến trình GUI. | 🔴 Nặng | Đã thấy ở project khác: lần chạy thứ 3 hang silent, không error, GUI không treo nhưng action không tiến. |
| **V2** | One task = one process. Worker chết → driver chết → CDP session sạch cho lần sau. | `workers/*.py` chạy coroutine trên qasync loop chung. Không có QProcess subprocess. | 🔴 Nặng | Cùng nguyên nhân V1. Cancel worker giữa chừng có thể để lại CDP session "half-open". |
| **V3** | Surgical kill theo `--user-data-dir`. KHÔNG `/IM brave.exe` (sẽ giết Brave cá nhân của user). | `engines/grok/browser.py:151-154`: `subprocess.run(["taskkill", "/F", "/IM", process_name])` với `process_name="brave.exe"`. | 🔴 Nặng | **P0 user damage**: mỗi lần retry, mọi tab Brave user đang mở (gmail, work, v.v.) đều bị giết. |
| **V4** | Dùng `127.0.0.1`, không `localhost`. Lý do: Windows DNS path chậm hơn, đôi khi thêm 100-500ms timeout vô lý. | `ui/connection_panel.py:22` `DEFAULT_CDP_URL = "http://localhost:9222"`. `core/config.py:53` Host header `localhost:{port}`. Chỉ `core/config.py:49` `open_connection("127.0.0.1", port)` dùng đúng. | 🟡 Nhẹ | Hiếm khi gây lỗi rõ, nhưng làm chậm reconnect. Fix dễ. |
| **V5** | Dùng port riêng (vd 9223) thay vì 9222 mặc định Chrome. | Dùng 9222. Nếu user mở Chrome/Edge với DevTools mặc định, sẽ collide. | 🟡 Nhẹ | Rủi ro thấp với Brave dedicated profile, nhưng best-practice. |
| **V6** | Kill stale CDP clients (`node.exe` ESTABLISHED tới port) trước khi `connect_over_cdp`. | Không có. `connect()` gọi thẳng `chromium.connect_over_cdp` sau khi `_cleanup()` chỉ dọn Patchright handles trong cùng tiến trình. | 🟡 Vừa | Sau khi user click ⏏ Ngắt + 🔌 Kết nối lại, hoặc sau khi worker cancel, có thể lingering node.exe driver từ Patchright trước. Lần connect mới hang. |
| **V7** | Reconnect-don't-restart ở normal path. Chỉ kill browser khi `connect_over_cdp` thực sự fail. | `kill_and_relaunch_brave()` gọi vô điều kiện sau MỌI exception trong gen. | 🟡 Vừa | Mất session Grok mỗi lần retry → phải login lại / Grok mất conversation state. Chậm 15-30s/retry. |
| **V8** | Exit codes semantic (0/1/2/3/4/5/6) cho IPC giữa launcher và worker. | In-process signals + `{"ok": bool, "needs_user_decision": bool}`. | ⚪ N/A | Chỉ applicable nếu refactor sang process-isolation (V1+V2). |
| **V9** | Project lock theo PID liveness. Tránh 2 worker chạy song song trên cùng project. | Không thấy `.lock` trong `core/` hay `workers/`. (`learning/SPEC_chain_runner_supplemented.md:203` có mention nhưng chưa implement.) | 🟡 Nhẹ | Hiện app chỉ chạy 1 instance, batch nội bộ tuần tự — chưa thấy hậu quả. Cần khi multi-instance. |
| **V10** | Timeouts rõ ràng từng phase, log đầu phase. | `wait_brave_ready` có (30s). `connect_over_cdp` dùng default Patchright (30s implicit). Actions dưới chỉ Patchright default. | 🟡 Nhẹ | Khi hang thì khó biết phase nào. Cần audit `engines/grok/actions.py`. |

### Điểm CODE HIỆN TẠI ĐANG LÀM ĐÚNG (giữ nguyên khi refactor)

- ✅ Brave launch manual qua `.bat`, persistent `--user-data-dir`. Session Grok bền giữa các lần chạy.
- ✅ `launch_brave.bat` dùng profile riêng `D:\CDP_Browser\brave-grok-profile` (khác profile cá nhân). Đây là nền tảng để V3 fix khả thi.
- ✅ Tab filter `grok.com` trong `list_tabs(grok_only=True)`.
- ✅ `reconnect_cdp()` có `_cleanup()` trước `connect()` lại — đúng pattern.
- ✅ `asyncio.CancelledError` propagate, KHÔNG trigger relaunch (`_retry.py:47-48, 58-59`). Đúng theo skill.
- ✅ `wait_brave_ready` dùng raw asyncio socket (không pull httpx). Đúng tinh thần "minimal deps".
- ✅ Retry có giới hạn (3), exhaust → user decision. KHÔNG retry vô hạn.
- ✅ Atomic state write trong `core/project.py` (theo README). Tránh corrupt khi crash giữa chừng.

---

## 3. Đề xuất refactor theo phase

Mỗi phase đứng riêng — có thể ship rời, có thể skip phase sau nếu phase trước đã giải quyết đủ.

### Phase 1 — Quick wins (1-2 giờ, ZERO architecture change)

**Mục tiêu:** Fix P0 user damage + giảm rủi ro với effort tối thiểu.

#### 1.1 Surgical kill thay cho `/IM brave.exe` — **BẮT BUỘC**

**File:** `engines/grok/browser.py:149-154`

**Hiện tại:**
```python
log.warning(f"[BRAVE] Killing {process_name}...")
try:
    subprocess.run(
        ["taskkill", "/F", "/IM", process_name],
        capture_output=True, timeout=10,
    )
```

**Đổi thành:**
```python
log.warning(f"[BRAVE] Killing automation Brave (profile match)...")
try:
    # Match by --user-data-dir trong command line, KHÔNG /IM brave.exe.
    # Tránh giết Brave cá nhân của user.
    # Profile path đọc từ config — mặc định từ launch_brave.bat
    profile_marker = cfg.get("profile_marker", "brave-grok-profile")
    ps_cmd = (
        f"Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.Name -eq 'brave.exe' -and "
        f"$_.CommandLine -like '*{profile_marker}*' }} | "
        f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, timeout=15,
    )
```

**Config thêm vào `config.json`:**
```json
{
  "brave": {
    "launch_bat": "launch_brave.bat",
    "process_name": "brave.exe",
    "debug_port": 9222,
    "profile_marker": "brave-grok-profile"
  }
}
```

**Verify:** Mở Brave cá nhân + chạy app + trigger retry → Brave cá nhân vẫn sống, chỉ profile automation chết.

**Edge case:** Nếu user đổi `launch_brave.bat` để dùng profile khác, cần update `profile_marker` tương ứng. Document trong README.

---

#### 1.2 `localhost` → `127.0.0.1`

**Files & lines:**
- `ui/connection_panel.py:22` — `DEFAULT_CDP_URL = "http://127.0.0.1:9222"`
- `core/config.py:53` — Host header → `f"Host: 127.0.0.1:{port}\r\n"`
- `engines/grok/browser.py:33` (docstring) — update để consistent
- `README.md:165` — update mention
- `SPEC.md:912` — update mock UI text

**Verify:** Reconnect time đo trước/sau (kỳ vọng nhanh hơn 100-500ms trên Windows).

---

#### 1.3 Đổi port mặc định 9222 → 9223

**Files:**
- `config.json` — `"debug_port": 9223`
- `launch_brave.bat:4` — `--remote-debugging-port=9223`
- `ui/connection_panel.py:22` — `http://127.0.0.1:9223`
- `.claude/settings.local.json:15` — `localhost:9222` → `127.0.0.1:9223` trong allowlist
- `README.md:120` — update doc

**Note:** Đây là breaking change cho user đã setup cũ. Document migration trong commit message + README. KHÔNG silent change.

---

### Phase 2 — Stale CDP client cleanup (2-4 giờ, không đổi kiến trúc)

**Mục tiêu:** Fix V6 — tránh hang lần thứ N do node.exe driver lingering.

#### 2.1 Thêm helper `kill_stale_cdp_clients`

**File mới:** `engines/grok/_cdp_cleanup.py`

```python
"""Kill lingering Patchright node.exe drivers tied to CDP port.

Sau khi worker cancel hoặc Patchright crash trong tiến trình, node.exe
driver vẫn giữ ESTABLISHED connection tới :PORT. CDP `/json/version`
vẫn 200, nhưng connect_over_cdp mới có thể hang. Helper này dọn
node.exe có connection còn sống tới port — KHÔNG đụng brave.exe.
"""
from __future__ import annotations
import re
import subprocess
from loguru import logger as log


def kill_stale_cdp_clients(port: int) -> int:
    """Returns số PID node.exe bị kill."""
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception as e:
        log.debug(f"[CDP-CLEANUP] netstat failed: {e}")
        return 0

    candidate_pids: set[int] = set()
    for line in result.stdout.splitlines():
        if f"127.0.0.1:{port}" in line and "ESTABLISHED" in line:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                candidate_pids.add(int(m.group(1)))

    killed = 0
    for pid in candidate_pids:
        try:
            ps = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5,
            )
            if "node.exe" in ps.stdout.lower():
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    check=False, capture_output=True, timeout=5,
                )
                killed += 1
                log.info(f"[CDP-CLEANUP] killed stale node.exe PID {pid}")
        except Exception as e:
            log.debug(f"[CDP-CLEANUP] PID {pid} check failed: {e}")
    return killed
```

#### 2.2 Wire vào `GrokConnection`

**File:** `engines/grok/browser.py`

Trong `connect()` — TRƯỚC `async_playwright().start()`:
```python
from engines.grok._cdp_cleanup import kill_stale_cdp_clients

async def connect(self, cdp_url: str) -> None:
    if await self.is_connected():
        return
    # Dọn node.exe driver từ tiến trình Patchright trước (nếu có).
    # An toàn — chỉ kill node.exe có ESTABLISHED tới port CDP của ta.
    port = self._port_from_url(cdp_url)
    if port:
        kill_stale_cdp_clients(port)
    self._pw = await async_playwright().start()
    ...
```

Trong `reconnect_cdp()` — TRƯỚC `connect()`:
```python
async def reconnect_cdp(self) -> None:
    url = self._cdp_url
    if not url:
        raise RuntimeError("reconnect_cdp: chưa từng connect")
    log.warning(f"Reconnect CDP {url}...")
    await self._cleanup()
    port = self._port_from_url(url)
    if port:
        kill_stale_cdp_clients(port)
    await self.connect(url)
    ...
```

Helper:
```python
@staticmethod
def _port_from_url(url: str) -> int | None:
    m = re.search(r":(\d+)", url)
    return int(m.group(1)) if m else None
```

**Verify checklist:**
- [ ] Connect → cancel worker giữa chừng → connect lại → không hang
- [ ] Connect → ⏏ Ngắt → connect lại → không hang
- [ ] 10 batch tuần tự không restart Brave → vẫn ổn

---

### Phase 3 — Soft reconnect path (4-8 giờ, vẫn không đổi kiến trúc)

**Mục tiêu:** Fix V7 — giữ session Grok khi có thể, chỉ kill+relaunch khi thực sự cần.

#### 3.1 Tách 2 recovery primitive

**File:** `engines/grok/browser.py`

Thêm method mới:
```python
async def soft_reconnect(self) -> bool:
    """Thử reconnect KHÔNG kill browser.

    Returns True nếu reconnect OK, False nếu cần escalate sang kill+relaunch.
    Dùng cho: stale Patchright driver, websocket disconnect, page closed
    nhưng Brave còn sống.
    """
    port = self._port_from_url(self._cdp_url) if self._cdp_url else None
    if not port:
        return False
    # Brave còn sống?
    if not await wait_brave_ready(port=port, timeout=3):
        return False  # Brave chết → escalate
    try:
        kill_stale_cdp_clients(port)
        await self._cleanup()
        await self.connect(self._cdp_url)
        tabs = await self.list_tabs(grok_only=True)
        if not tabs:
            return False  # Không có grok tab → có thể cần relaunch để mở trang
        await self.select_tab(int(tabs[0]["index"]))
        return True
    except Exception as e:
        log.warning(f"[SOFT-RECONNECT] failed: {e}")
        return False
```

#### 3.2 Update `_retry.py` — escalate strategy

**File:** `workers/_retry.py`

```python
for attempt in range(1, max_attempts + 1):
    log_cb(f"[ATTEMPT {attempt}/{max_attempts}] {scene_id}")
    try:
        result = await gen_factory()
        return {"ok": True, "result": result, "attempts": attempt}
    except asyncio.CancelledError:
        raise
    except Exception as e:
        last_err = e
        log_cb(f"[FAIL {attempt}] {scene_id}: {e}")

    if attempt < max_attempts:
        # Escalation: attempt 1→2 thử soft reconnect; attempt 2→3 kill+relaunch.
        try:
            if attempt == 1:
                log_cb("[RECOVERY] soft reconnect...")
                ok = await connection.soft_reconnect()
                if not ok:
                    log_cb("[RECOVERY] soft failed → kill+relaunch")
                    await connection.kill_and_relaunch_brave(project_root=project_root)
            else:
                log_cb("[RECOVERY] kill+relaunch...")
                await connection.kill_and_relaunch_brave(project_root=project_root)
            refresh_page()
        except asyncio.CancelledError:
            raise
        except Exception as relaunch_err:
            log_cb(f"[RECOVERY FAIL] {relaunch_err}")
```

**Rationale:** Attempt 2 thử nhẹ trước (giữ session); chỉ attempt 3 mới kill. Tiết kiệm ~20s + giữ login Grok cho lỗi tạm thời (network blip, stale driver).

**Verify:** Force 1 exception trong gen → attempt 2 dùng soft, KHÔNG kill brave. Force 2 exception liên tiếp → attempt 3 kill+relaunch.

---

### Phase 4 — Per-phase timeouts + logs (audit work, không refactor lớn)

**Mục tiêu:** Fix V10 — khi hang, biết phase nào hang.

**Cần audit:** `engines/grok/actions.py` — list tất cả `await page.*`, `await locator.*`. Mỗi action wrap với explicit timeout + log đầu phase:

```python
log.info(f"[PHASE] fill_prompt ({len(text)} chars)")
async with asyncio.timeout(10):
    await composer.evaluate(...)
```

**Khuyến nghị bảng timeout (theo skill):**
| Phase | Timeout |
|---|---|
| CDP connect | 15s |
| Composer ready | 30s |
| File upload (`set_input_files`) | 15s |
| Upload network (`wait_for_response`) | 30s |
| Prompt fill | 10s |
| Send button enabled | 30s |
| Stream complete (image/video gen) | 600s |

**Note:** Spec này CHỈ liệt kê standard. Số cụ thể trong code Grok có thể khác (vd Grok video gen có thể cần 900s). Audit + chốt số trong commit refactor.

---

### Phase 5 — Process isolation (REFACTOR LỚN — chỉ làm nếu phase 1-4 không đủ)

**Trigger:** Sau khi đã fix phase 1-4, vẫn gặp hang silent ở lần chạy thứ N.

**Mục tiêu:** Fix V1 + V2 + V8 + V9 — đưa kiến trúc về one-task-one-process như skill yêu cầu.

**Estimate:** 1-2 tuần. Cần redesign worker layer.

**Tham khảo:** `learning/SPEC_chain_runner_supplemented.md` đã có spec cho chain runner pattern — đọc lại trước khi bắt đầu.

**Hướng phác:**
1. GUI bỏ hoàn toàn import `engines.grok` / `patchright`.
2. Tách workers ra script độc lập: `python -m workers.cli gen_image --scene-id N --project /path/to/project`.
3. GUI dùng `QProcess` để spawn + đọc stdout (markers `^TASK DONE`, `^TASK FAILED`, `^EVENT {...}`).
4. Workers exit code: 0/1/2/3/4/5/6 theo skill section "Exit Codes as Semantic API".
5. State synchronization: `state.json` atomic + `run_id` ghost-writer protection (đã có nền móng trong `core/project.py`).
6. Project lock `.chain.lock` theo PID liveness (V9).

**Trade-off:** Mất khả năng share `connection` singleton giữa workers — mỗi worker tự `connect_over_cdp`. Bù lại: hang một worker không ảnh hưởng worker khác, GUI luôn responsive.

**KHÔNG bắt đầu phase 5 nếu phase 1-4 đã giải quyết hang issue.** Skill chỉ ra rằng phase 1-4 fix được 80% case; phase 5 cho 20% hard case còn lại.

---

## 4. Migration order & risk

| Phase | Effort | Risk | Ship rời được? |
|---|---|---|---|
| 1.1 Surgical kill | 30 phút | Thấp (test bằng cách mở Brave cá nhân song song) | ✅ |
| 1.2 localhost→127.0.0.1 | 10 phút | Rất thấp | ✅ |
| 1.3 Port 9222→9223 | 20 phút | Trung (breaking cho user cũ — cần migration note) | ✅ |
| 2 Stale CDP cleanup | 2-4 giờ | Thấp (helper là pure side effect, không đụng connect path) | ✅ |
| 3 Soft reconnect | 4-8 giờ | Trung (đổi retry logic — cần test 2 escalation level) | ✅ |
| 4 Per-phase timeouts | 4-8 giờ audit | Thấp (mỗi action wrap độc lập) | ✅ |
| 5 Process isolation | 1-2 tuần | Cao (đổi worker architecture) | ❌ Không (cần đổi đồng bộ workers + GUI + state) |

**Khuyến nghị order:** 1.1 → 1.2 + 1.3 (cùng commit, vì cả 2 đều là URL/port change) → 2 → 3 → 4. Dừng ở 4 trừ khi vẫn có hang.

---

## 5. Acceptance criteria

Sau phase 1-4, kỳ vọng:

- [ ] **P0 fix**: Mở Brave cá nhân + chạy batch → trigger retry → Brave cá nhân không bị giết.
- [ ] **V4 fix**: Reconnect time đo trước = X, sau = X - 100ms (tối thiểu).
- [ ] **V6 fix**: Cancel worker 10 lần liên tiếp + reconnect → không hang lần nào.
- [ ] **V7 fix**: Force lỗi gen 1 lần → soft reconnect thành công → KHÔNG có log `taskkill`.
- [ ] **V10 fix**: Mỗi action log `[PHASE] ...` ở đầu + có `asyncio.timeout`.
- [ ] 20 batch image tuần tự (4-scene mỗi batch) → 0 hang silent, 0 false retry.
- [ ] Session Grok còn (không bị logout) sau 5 lần kill+relaunch.

Nếu (5) hoặc (6) fail → trigger phase 5.

---

## 6. Phụ lục — quick reference checklist khi refactor

Mỗi PR refactor cần ít nhất:

- [ ] Update spec này (mark phase done + add learning từ implementation)
- [ ] Update `README.md` nếu user-facing change (port, profile path, error popup wording)
- [ ] Update `.claude/settings.local.json` allowlist nếu đổi command pattern
- [ ] Manual test trên Windows với Brave cá nhân đang chạy song song
- [ ] Đo lại time-to-recovery trước/sau

---

## 7. Tham chiếu

- Skill gốc: `D:\CLAUDE\.claude\skills\playwright-cdp-resilient\SKILL_playwright_cdp_resilient.md`
- Spec process-isolation tương lai: `learning/SPEC_chain_runner_supplemented.md`
- Spec CDP flow tương tự (ChatGPT, dùng 127.0.0.1:9223): `learning/SPEC_cdp_chatgpt_flow.md`
- Current code: `engines/grok/browser.py`, `core/config.py`, `workers/_retry.py`, `ui/connection_panel.py`
