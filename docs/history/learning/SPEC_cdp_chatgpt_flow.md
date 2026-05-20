# CDP ChatGPT Automation Spec

Last updated: 2026-05-19.

This is the single source of truth for building ChatGPT automation through
Brave CDP with Patchright in this project family. It consolidates the old
`naomi_pipeline` build notes and the newer `script_to_scene_quick` findings.

The main lesson: keep the ChatGPT browser automation path small, observable,
and process-isolated. CLI runs are more stable than long-lived GUI runs.

## Current Quick Project Shape

Root: `D:\Projects\script_to_scene_quick`

Important files:

- `quick_s1_s2.py` - stable CLI smoke chain, fixed `project/source.docx`,
  runs S1 then S2 and exits the process.
- `app_chain.py` - PyQt6 GUI chain runner for S1-S5.
- `core/browser.py` - Brave CDP launch/connect/tab helpers.
- `core/chatgpt_flow.py` - upload, prompt fill, send, stream wait, copy.
- `core/config.py` - parse Custom GPT URLs from `instruction/link_custom_gpt.md`.
- `core/parse.py` - parse copied ChatGPT output into JSON or wrap failures.
- `run_brave_cdp.bat` - starts Brave with `--remote-debugging-port=9223`.
- `run_quick_s1_s2.bat` - CLI quick run.
- `run_app_chain.bat` - GUI run.

Older docs may mention `naomi_pipeline/`, `run.bat`, `smoke_test_s1.py`,
`core/health.py`, or selector recovery modules. Those belonged to an earlier
larger repo shape. Keep the lessons, but do not assume those files exist in
this quick repo.

## Runtime Contract

- Browser: Brave over Chrome DevTools Protocol.
- CDP endpoint: `http://127.0.0.1:9223`.
- Use `127.0.0.1`, not `localhost`.
- Dedicated automation profile: `D:\brave-grok-profile`.
- User's normal Brave profile is separate and should not be killed during
  automation cleanup.
- ChatGPT must already be logged in inside the CDP profile.
- Custom GPT URLs live in `instruction/link_custom_gpt.md`.

## Preferred Architecture

Use CLI as the automation engine.

Recommended shape for future apps:

1. A CLI worker script owns Patchright, CDP, browser tabs, and clipboard.
2. The worker runs one chain or one step, writes logs/output, then exits.
3. GUI, if needed, is only a launcher/monitor that starts the CLI worker as a
   subprocess.
4. On timeout/cancel, the GUI kills the worker process tree and optionally the
   CDP Brave profile tree.

Responsibility split:

| Layer | Owns | Must not own |
|---|---|---|
| GUI | file pickers, mode selection, command construction, stdout/stderr display, progress parsing, Stop/Kill buttons | Patchright browser objects, `async_playwright()`, ChatGPT tab automation, clipboard extraction |
| CLI worker | Patchright, CDP connection, tab routing, file upload, prompt fill, send/wait/copy, JSON/raw output, process exit code | long-lived UI state |

The GUI should answer: "Which command should run, and what is it doing?"
The CLI worker should answer: "How do I drive ChatGPT and produce files?"

Avoid running Patchright directly inside a long-lived PyQt GUI process unless
there is a strong reason. The GUI can look alive while an async browser action
is stuck deep inside CDP.

## Why CLI Is More Stable Than GUI

`quick_s1_s2.py` is stable because:

- It starts one process, runs S1-S2, then calls `app.quit()` and `sys.exit()`.
- Patchright driver state, qasync state, clipboard state, and CDP sessions are
  discarded naturally when the process exits.
- Failures show clearly in stdout/traceback.
- The input/output paths are fixed and predictable.

GUI runs are more fragile because:

- The process and `qasync.QEventLoop` stay alive across attempts.
- Cancel/close can leave a Patchright driver or CDP action half-open.
- Reusing old ChatGPT tabs or `/c/{conversation_id}` pages increases stale UI
  state risk.
- `QApplication.processEvents()` inside async progress logging can create
  re-entry risk.
- The UI can appear frozen while the task is actually waiting inside
  `page.evaluate`, `locator.click`, `expect_response`, or clipboard polling.

Observed GUI hang:

```text
[23:27:54]   Upload: D:\Projects\script_to_scene_quick\project\project\source.docx
[23:27:58]   Upload network done: 200
[23:27:59]   Fill prompt (95 chars)
```

This means upload succeeded and the flow was stuck in `fill_prompt()`, inside
`composer.evaluate(...)`. Normally it should either log `Prompt filled (...)`
or fail after the timeout. If it hangs there, treat it as a stale
Patchright/CDP/browser-action state, not a Custom GPT prompt problem.

## Step Flow

For one ChatGPT step:

1. Open or reuse the Custom GPT tab for the step.
2. If the tab is on `/c/{conversation_id}`, navigate back to the GPT base URL.
3. Wait for composer readiness.
4. Upload the input file directly into `#upload-files`.
5. Wait for `/backend-api/files` 2xx.
6. Fill the prompt by JS `evaluate` on `#prompt-textarea`.
7. Wait for the send button to exist and be enabled.
8. Click send.
9. Wait for stream completion: Stop button gone AND Copy response exists.
10. Scroll to bottom, click Copy response, read OS clipboard.
11. Save raw text and parsed JSON.

## Key Selectors

```python
SEL_COMPOSER = "#prompt-textarea"
SEL_FILE_INPUT = "#upload-files, input[type='file']"
SEL_SEND_BTN = "#composer-submit-button"
SEL_STOP_BTN = "button[aria-label*='Stop' i]"
SEL_COPY_RESPONSE_BTN = (
    'button[aria-label="Copy response"], '
    'button[data-testid="copy-turn-action-button"]'
)
SEL_SCROLL_TO_BOTTOM = "#thread-bottom-container button.cursor-pointer.h-8.w-8"
```

Use the exact `Copy response` selector. Generic `aria-label^='Copy'` can match
unrelated UI buttons.

## Known Issues and Required Handling

### 1. Plus Button Upload Hangs

The ChatGPT plus button can hang on Playwright/Patchright actionability even
when the page is responsive. The hidden file input is already mounted.

Required handling:

- Never click the plus button in production flow.
- Set files directly on `#upload-files, input[type='file']`.
- Wait for `/backend-api/files` 2xx as the canonical upload-complete signal.

### 2. Composer Locator Actionability Can Hang

Earlier flow clicked or waited on the composer via locator actionability. This
can hang even when the DOM exists and is visible.

Required handling:

- Use JS polling/evaluate for composer readiness where possible.
- In `fill_prompt`, re-locate composer after upload because the attachment chip
  can remount the composer.
- Fill via `composer.evaluate(...)`: focus, replace `innerHTML`, append a `p`,
  dispatch `InputEvent`, then verify inserted text.
- If `Fill prompt (...)` is the last log line, inspect for stale CDP/Patchright
  state before changing prompt logic.

### 3. Send Button Disabled After Upload

After upload, ChatGPT may validate the file for a few seconds. The send button
exists but is disabled or has `aria-disabled="true"`.

Required handling:

- Poll until `#composer-submit-button` exists and is not disabled.
- Do not click immediately after upload.

### 4. Stop Button Alone Is Not a Done Signal

ChatGPT may hide/show Stop during transient states. Stop disappearing alone can
race with final message rendering.

Required handling:

- Treat stream as done only when `stop_count == 0` AND `copy_count > 0`.
- Keep a generous stream timeout for long S1/S3/S4 outputs.

### 5. Copy Button Is Affected by Sticky Bottom Overlay

`#thread-bottom-container` can intercept pointer events. A visible Copy button
can still be hard to click.

Required handling:

- Scroll to bottom before locating Copy.
- Disable pointer events on `#thread-bottom-container`.
- Click the last `Copy response` button.
- Clear OS clipboard before click.
- Poll OS clipboard for fresh text after click.

### 6. Virtualized Thread Can Unmount Copy Buttons

ChatGPT virtualizes long conversations. If the final assistant message is not
in viewport, its Copy button may not be in the DOM.

Required handling:

- Use the scroll-to-bottom button when available.
- Also JS-scroll likely scroll containers.
- Locate Copy after scrolling, not before.

### 7. Stale Patchright CDP Clients

After cancelled GUI runs, Patchright's driver process can stay connected to
port `9223`. `/json/version` may still respond while new CDP actions hang.

Required handling:

- Before connecting, scan `netstat -ano` for `ESTABLISHED` clients whose remote
  endpoint is `127.0.0.1:9223`.
- Kill only those client PIDs, not unrelated `node.exe`.
- If the whole CDP Brave session is bad, kill only the Brave tree using
  `D:\brave-grok-profile`, not the user's normal Brave profile.

Useful commands:

```powershell
netstat -ano | Select-String ':9223'
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python|pythonw|node|brave' } |
  Select-Object ProcessId,ParentProcessId,Name,CreationDate,CommandLine |
  Format-List
taskkill /F /PID <cdp-brave-root-pid> /T
```

Evidence from 2026-05-19 cleanup:

- CDP Brave root PID `10508` was listening on `127.0.0.1:9223`.
- Killing PID `10508 /T` removed the CDP session.
- Normal user Brave root PID `21336` was left untouched.

### 8. DOM Diagnostics Can Freeze Live Flow

Frequent DOM snapshots, selector counts, or broad `evaluate` diagnostics
between live actions can freeze the ChatGPT renderer or Patchright action
layer.

Required handling:

- Production flow should log step boundaries and essential state only.
- Deep DOM diagnostics belong in smoke tests or one-off debug sessions, between
  actions, not interleaved with production actions.

### 9. GUI Output Path Can Nest `project\project`

Current GUI logic creates output as:

```python
project_dir = docx_path.parent / "project"
```

If the user selects `project/source.docx`, output becomes
`project/project/source.docx`.

This does not directly cause a prompt-fill hang if upload returns 200, but it
causes confusion and makes GUI runs differ from CLI quick tests.

Required handling for future builds:

- Choose a project root explicitly.
- Do not derive output by blindly appending `project` to the input file parent.
- Prefer fixed CLI convention for smoke tests: root `project/source.docx`,
  outputs next to it.

### 10. Reusing `/c/` Conversation Tabs Carries State

Reusing a tab on `/c/{conversation_id}` can carry old upload chips, model
state, conversation context, or stale React/ProseMirror state.

Required handling:

- Navigate back to the Custom GPT base URL before each step if URL contains
  `/c/`.
- For maximum stability, a CLI worker should start from a clean process and
  clean tab selection.
- Avoid repeatedly closing/opening tabs inside a live GUI unless necessary;
  tab close/new-page cycles can also destabilize CDP.

### 11. JSON Parse Failure Is Usually Model Output, Not Browser Flow

S1 may return almost-JSON with unescaped quotes inside strings. Example:

```json
"introduction": "I said, "Jinro, just cooperate.""
```

This is invalid JSON, but the browser flow is still successful if upload,
submit, stream wait, Copy response, and clipboard read completed.

Required handling:

- Save `.raw.txt` always.
- Parse into `.json` when possible.
- If parse fails, wrap raw output with `_parse_failed` for debugging.
- Fix output instructions or model behavior separately from CDP flow.

### 12. ChatGPT Refusals, Rate Limits, and UI Changes

The flow does not guarantee model success. ChatGPT can rate-limit, refuse,
change UI labels, or fail custom GPT loading.

Required handling:

- Treat short/empty clipboard as `ChatGPTResponseError`.
- Keep raw response.
- Keep selector failures loud; do not silently retry forever.
- Update this spec when selectors or visible UI behavior change.

## Recommended Timeouts

Keep timeouts explicit and logged:

- CDP connect: 15s.
- Composer readiness: 30s.
- Upload input set: 15s.
- Upload network `/backend-api/files`: 30s.
- Prompt fill evaluate: 10s.
- Send enabled: 30s.
- Stream response: 600s or higher for long steps.
- Copy button visible: 15s.
- Clipboard poll: 8s.

If an action does not respect its timeout, suspect Patchright/CDP action-layer
hang or event-loop re-entry, especially inside GUI.

## GUI Design Rules for Future Builds

Preferred:

- GUI launches `quick_*` or `worker_*` CLI script as subprocess.
- GUI streams stdout/stderr into the UI.
- GUI parses progress from stable log lines, for example `STEP S1 (1/5)` or
  `[S1] DONE ...`, instead of inspecting browser state.
- GUI has Stop button that kills the subprocess tree.
- GUI has optional Kill CDP button that kills only the automation Brave tree
  listening on port `9223`.
- CLI worker owns CDP and exits after one run.
- GUI never calls Patchright directly.
- CLI worker returns a process exit code: `0` success, non-zero failure.
- CLI worker writes all durable output (`*.raw.txt`, `*.json`, logs) before
  exit so the GUI can be restarted without losing evidence.

Avoid:

- Long-lived GUI process owning Patchright and Brave CDP directly.
- GUI importing `patchright.async_api` or calling `async_playwright()`.
- GUI passing around live `page`, `browser`, or `context` objects.
- Calling `QApplication.processEvents()` inside async task callbacks.
- Reusing internal task objects after cancellation.
- Hiding exceptions behind only a message box.
- Continuing after a browser action appears hung.

If a GUI must own Patchright:

- Add a hard watchdog around each step at the process level, not just
  `asyncio.wait_for` around individual calls.
- On cancel, close browser contexts where possible, stop the qasync loop, and
  verify no `python/pythonw` worker remains.
- Provide a "Kill CDP Session" action that kills only the automation Brave
  profile tree.

## Operational Runbook

### Before a Run

1. Kill stale CDP session if needed:

   ```powershell
   netstat -ano | Select-String ':9223'
   ```

2. Start Brave CDP:

   ```bat
   run_brave_cdp.bat
   ```

3. Confirm ChatGPT is logged in inside the CDP Brave profile.

4. Prefer quick CLI smoke:

   ```bat
   run_quick_s1_s2.bat
   ```

### If It Hangs at `Fill prompt`

Interpretation:

- Upload has already completed.
- The problem is not the file path or Custom GPT instruction.
- The hang is likely in `composer.evaluate(...)` or CDP action routing.

Action:

1. Do not keep clicking GUI controls.
2. Kill the GUI worker or CDP session.
3. Check `netstat :9223`.
4. Restart `run_brave_cdp.bat`.
5. Reproduce with CLI quick flow.

### If It Hangs at Stream Wait

Interpretation:

- Prompt was sent.
- ChatGPT may still be generating, blocked, rate-limited, or UI changed.

Action:

1. Look for Stop button and final Copy button in the Brave tab.
2. If response exists but Copy button is not detected, suspect virtual scroll
   or selector drift.
3. If no response, inspect ChatGPT UI manually for refusal/rate-limit.

### If Clipboard Is Empty

Interpretation:

- Copy click did not fire, clipboard permission failed, or wrong Copy button
  was selected.

Action:

1. Clear clipboard before retry.
2. Scroll to bottom.
3. Use exact `Copy response` selector.
4. Avoid generic Copy selectors.

## Verification Baseline

Known good quick flow:

- `quick_s1_s2.py`
- Input: `project/source.docx`
- Output: `project/project_S1.json`, `project/project_S2.json`, raw text files.
- S1 and S2 complete through upload, prompt fill, send, stream wait, copy.

Known bad/fragile GUI symptom:

- `app_chain.py` direct Patchright ownership.
- Selected input under `project/source.docx` caused `project/project/source.docx`.
- Hang observed after upload 200 at `Fill prompt (95 chars)`.
- Killing CDP Brave PID listening on `9223` cleaned the session.

## Documentation Policy

Keep this file as the single spec note for this automation pattern.

Do not maintain separate build logs for the same facts. If a new issue is
found, add:

- symptom/log line;
- root cause if known;
- required handling;
- verification evidence;
- date.
