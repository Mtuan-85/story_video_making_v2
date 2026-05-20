# CDP Provider Worker Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Grok image generation out of the GUI process into QProcess workers while adopting the new `meta`-based project schema.

**Architecture:** The GUI remains the owner of project state and UI refresh. Browser automation runs in short-lived worker processes: one process for batch image, one process for single image. The first vertical slice supports Grok only, with task JSON carrying `provider`, `model`, `task_type`, selected scenes, and CDP settings.

**Tech Stack:** Python 3.11, PyQt6 `QProcess`, Pydantic v2, Patchright over CDP, existing `core.Project`, `engines.grok` flows.

---

## File Structure

- Modify `core/schema.py`: accept new `meta` schema, root `character`, root `version` migration into `meta.version`, optional legacy `settings`.
- Modify `core/project.py`: normalize root `version` into `meta.version` before save; keep GUI-owned state writes.
- Modify `workers/batch_image.py` and `workers/single_image.py`: stop being the primary browser automation path after QProcess slice lands; keep legacy-safe until Phase F.
- Create `workers/task_contract.py`: typed task request/events/exit-code helpers.
- Create `workers/process_launcher.py`: PyQt `QProcess` wrapper used by GUI.
- Create `workers/generate_worker.py`: CLI entrypoint for `batch_image` and `single_image`.
- Create `engines/grok/cdp_worker.py`: worker-local CDP connect, stale node cleanup, tab get/open helpers.
- Create `engines/grok/image_worker_flow.py`: Grok batch/single image flow using existing `GrokImageEngine` and `GrokImageRefEngine`.
- Modify `ui/connection_panel.py`: convert from Patchright connection owner to browser health/provider/model panel.
- Modify `ui/main_window.py`: build image tasks, spawn QProcess, parse events, update state/thumbnails.
- Create `tests/test_schema_meta.py`, `tests/test_task_contract.py`, `tests/test_process_event_parser.py`.
- Update `README.md` after implementation.

---

## Task 1: Schema Meta Migration

**Files:**
- Modify: `core/schema.py`
- Test: `tests/test_schema_meta.py`

- [ ] **Step 1: Write failing schema tests**

Create `tests/test_schema_meta.py`:

```python
from core.schema import ScenesJson


def test_loads_meta_schema_without_settings():
    data = {
        "meta": {
            "version": "1.1",
            "project_id": "Naomi_01",
            "title": "Raising Children Who Cooperate Willingly",
            "aspect_ratio": "16:9",
            "language": "en",
            "baseStyle": "Cozy flat cartoon",
            "baseNegative": "photorealistic",
            "image_quality": "quality",
            "video_resolution": "720p",
            "video_duration": "10s",
            "source_citations": "source doc",
        },
        "character": {"Naomi": "A calm Japanese woman."},
        "scenes": [{
            "id": "1",
            "visual_type": "image_grok",
            "effect": "zoom_in",
            "story_en": "Story",
            "imagePrompt": "Prompt",
            "duration": 8,
        }],
    }
    parsed = ScenesJson.model_validate(data)
    assert parsed.meta.version == "1.1"
    assert parsed.meta.baseStyle == "Cozy flat cartoon"
    assert parsed.character["Naomi"].startswith("A calm")
    assert parsed.topic_for_prompt() == parsed.meta.title


def test_root_version_moves_to_meta_version():
    data = {
        "version": "1.1",
        "meta": {
            "project_id": "Naomi_01",
            "title": "Title",
            "aspect_ratio": "16:9",
            "language": "en",
            "baseStyle": "Style",
            "baseNegative": "Negative",
        },
        "scenes": [{
            "id": "1",
            "visual_type": "image_grok",
            "story_en": "Story",
            "duration": 8,
        }],
    }
    parsed = ScenesJson.model_validate(data)
    dumped = parsed.model_dump(exclude_none=True)
    assert parsed.meta.version == "1.1"
    assert "version" not in dumped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_schema_meta.py -v`

Expected: FAIL because `settings` is required and `character`/new meta fields are rejected.

- [ ] **Step 3: Update schema**

In `core/schema.py`:

```python
class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    aspect_ratio: AspectRatio
    language: Language
    baseStyle: str = ""
    baseNegative: str = ""
    image_quality: ImageQuality = "quality"
    video_resolution: VideoResolution = "720p"
    video_duration: VideoDuration = "10s"
    source_citations: str | None = None
    topic: str | None = None
    voice_model_id: str | None = None
    voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    voice_volume: int = Field(default=0, ge=-20, le=20)
```

Keep `Settings` temporarily for legacy input, but make it optional in `ScenesJson`:

```python
class ScenesJson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: Meta
    scenes: list[Scene] = Field(min_length=1)
    character: dict[str, str] = Field(default_factory=dict)
    settings: Settings | None = None

    @model_validator(mode="before")
    @classmethod
    def _migrate_root_version_and_settings(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        meta = dict(data.get("meta") or {})
        root_version = data.pop("version", None)
        if root_version is not None and not meta.get("version"):
            meta["version"] = str(root_version)
        settings = data.get("settings")
        if isinstance(settings, dict):
            for key in (
                "baseStyle",
                "baseNegative",
                "image_quality",
                "video_resolution",
                "video_duration",
                "voice_model_id",
                "voice_speed",
                "voice_volume",
                "topic",
            ):
                if key in settings and key not in meta:
                    meta[key] = settings[key]
        data["meta"] = meta
        data.pop("settings", None)
        return data

    def topic_for_prompt(self) -> str:
        return self.meta.topic or self.meta.title
```

- [ ] **Step 4: Run schema tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_schema_meta.py -v`

Expected: PASS.

- [ ] **Step 5: Commit schema task**

```bash
git add core/schema.py tests/test_schema_meta.py
git commit -m "schema: move project settings into meta"
```

---

## Task 2: Task Contract and Event Parser

**Files:**
- Create: `workers/task_contract.py`
- Test: `tests/test_task_contract.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_task_contract.py`:

```python
import json

from workers.task_contract import (
    EXIT_SUCCESS,
    GenerateTask,
    WorkerEvent,
    parse_worker_line,
)


def test_generate_task_defaults_to_grok_9222():
    task = GenerateTask(
        task_id="t1",
        project_file="D:/p/story.json",
        project_root="D:/p",
        task_type="batch_image",
        scene_ids=["1"],
    )
    assert task.provider == "grok"
    assert task.model == "grok-auto"
    assert task.cdp.url == "http://127.0.0.1:9222"


def test_parse_event_line():
    line = 'EVENT {"type":"scene_done","scene_id":"1","asset":"image","path":"sources/pic1.jpg"}'
    event = parse_worker_line(line)
    assert isinstance(event, WorkerEvent)
    assert event.type == "scene_done"
    assert event.payload["path"] == "sources/pic1.jpg"


def test_task_done_line_has_payload():
    event = parse_worker_line('TASK DONE {"success":1,"total":1}')
    assert event.type == "task_done"
    assert event.payload["success"] == 1
    assert EXIT_SUCCESS == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_task_contract.py -v`

Expected: FAIL because `workers.task_contract` does not exist.

- [ ] **Step 3: Implement contract**

Create `workers/task_contract.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

TaskType = Literal["batch_image", "single_image", "batch_video", "single_video"]
Provider = Literal["grok", "chatgpt", "gemini"]

EXIT_SUCCESS = 0
EXIT_FLOW_FAILED = 1
EXIT_PREREQ_MISSING = 2
EXIT_USER_KILLED = 3
EXIT_PARSE_FAILED = 4
EXIT_CDP_UNREACHABLE = 5
EXIT_PROJECT_LOCKED = 6


class CdpConfig(BaseModel):
    url: str = "http://127.0.0.1:9222"
    profile_marker: str = "brave-grok-profile"
    base_url: str = "https://grok.com/imagine"


class TaskOptions(BaseModel):
    pick_mode: str = "auto"
    fast_mode: bool = False
    use_refs_for_image: bool = False
    image_refs: list[str] = Field(default_factory=list)


class GenerateTask(BaseModel):
    task_id: str
    project_file: str
    project_root: str
    task_type: TaskType
    scene_ids: list[str]
    provider: Provider = "grok"
    model: str = "grok-auto"
    cdp: CdpConfig = Field(default_factory=CdpConfig)
    options: TaskOptions = Field(default_factory=TaskOptions)

    @classmethod
    def load(cls, path: Path) -> "GenerateTask":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")


class WorkerEvent(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


def marker_line(marker: str, payload: dict[str, Any]) -> str:
    return f"{marker} {json.dumps(payload, ensure_ascii=False)}"


def event_line(event_type: str, **payload: Any) -> str:
    return marker_line("EVENT", {"type": event_type, **payload})


def parse_worker_line(line: str) -> WorkerEvent | None:
    text = line.strip()
    for marker, event_type in (
        ("EVENT ", None),
        ("TASK START ", "task_start"),
        ("TASK DONE ", "task_done"),
        ("TASK FAILED ", "task_failed"),
    ):
        if not text.startswith(marker):
            continue
        payload = json.loads(text[len(marker):])
        if event_type is None:
            typ = str(payload.pop("type"))
            return WorkerEvent(type=typ, payload=payload)
        return WorkerEvent(type=event_type, payload=payload)
    return None
```

- [ ] **Step 4: Run contract tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_task_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Commit contract task**

```bash
git add workers/task_contract.py tests/test_task_contract.py
git commit -m "workers: add generation task contract"
```

---

## Task 3: Worker CLI No-Op Slice

**Files:**
- Create: `workers/generate_worker.py`
- Modify: `pyproject.toml` only if packaging needs to include new file automatically; likely no change because `workers` package is included.
- Test: `tests/test_worker_cli_noop.py`

- [ ] **Step 1: Write no-op CLI test**

Create `tests/test_worker_cli_noop.py`:

```python
import subprocess
import sys

from workers.task_contract import GenerateTask


def test_worker_cli_noop(tmp_path):
    project = tmp_path / "project.json"
    project.write_text('{"meta":{"project_id":"p","title":"T","aspect_ratio":"16:9","language":"en"},"scenes":[{"id":"1","visual_type":"image_grok","story_en":"s","duration":1}]}', encoding="utf-8")
    task = GenerateTask(
        task_id="noop",
        project_file=str(project),
        project_root=str(tmp_path),
        task_type="batch_image",
        scene_ids=[],
    )
    task_path = tmp_path / "task.json"
    task.save(task_path)
    result = subprocess.run(
        [sys.executable, "-m", "workers.generate_worker", "--task", str(task_path), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "TASK START" in result.stdout
    assert "TASK DONE" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_worker_cli_noop.py -v`

Expected: FAIL because CLI module does not exist.

- [ ] **Step 3: Implement CLI shell**

Create `workers/generate_worker.py`:

```python
from __future__ import annotations

import argparse
import sys
import time

from workers.task_contract import (
    EXIT_FLOW_FAILED,
    EXIT_SUCCESS,
    GenerateTask,
    event_line,
    marker_line,
)


def _print(line: str) -> None:
    print(line, flush=True)


def run_task(task: GenerateTask, *, dry_run: bool = False) -> int:
    t0 = time.monotonic()
    _print(marker_line("TASK START", {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "provider": task.provider,
        "model": task.model,
    }))
    if dry_run:
        for scene_id in task.scene_ids:
            _print(event_line("scene_started", scene_id=scene_id))
            _print(event_line("scene_done", scene_id=scene_id, asset="image", path=""))
        _print(marker_line("TASK DONE", {
            "success": len(task.scene_ids),
            "total": len(task.scene_ids),
            "duration_sec": round(time.monotonic() - t0, 2),
        }))
        return EXIT_SUCCESS

    _print(marker_line("TASK FAILED", {
        "reason": "real worker flow not implemented yet",
        "code": EXIT_FLOW_FAILED,
    }))
    return EXIT_FLOW_FAILED


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    task = GenerateTask.load(args.task)
    return run_task(task, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run no-op CLI tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_worker_cli_noop.py -v`

Expected: PASS.

- [ ] **Step 5: Commit CLI shell**

```bash
git add workers/generate_worker.py tests/test_worker_cli_noop.py
git commit -m "workers: add generation worker cli shell"
```

---

## Task 4: QProcess Launcher

**Files:**
- Create: `workers/process_launcher.py`
- Test: `tests/test_process_event_parser.py`

- [ ] **Step 1: Write parser-focused tests**

Create `tests/test_process_event_parser.py`:

```python
from workers.process_launcher import collect_events_from_text


def test_collect_events_from_text_ignores_human_logs():
    text = "\n".join([
        "hello",
        'TASK START {"task_id":"t","task_type":"batch_image"}',
        'EVENT {"type":"scene_started","scene_id":"1"}',
        'TASK DONE {"success":1,"total":1}',
    ])
    events = collect_events_from_text(text)
    assert [e.type for e in events] == ["task_start", "scene_started", "task_done"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/test_process_event_parser.py -v`

Expected: FAIL because `workers.process_launcher` does not exist.

- [ ] **Step 3: Implement launcher/parser**

Create `workers/process_launcher.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QProcess, pyqtSignal

from workers.task_contract import GenerateTask, WorkerEvent, parse_worker_line


def collect_events_from_text(text: str) -> list[WorkerEvent]:
    events: list[WorkerEvent] = []
    for line in text.splitlines():
        event = parse_worker_line(line)
        if event is not None:
            events.append(event)
    return events


class GenerateProcess(QObject):
    event = pyqtSignal(object)
    log_line = pyqtSignal(str)
    finished = pyqtSignal(int)

    def __init__(self, task: GenerateTask, task_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.task = task
        self.task_path = Path(task_path)
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc.readyReadStandardOutput.connect(self._read_stdout)
        self.proc.finished.connect(self._on_finished)

    def start(self, *, dry_run: bool = False) -> None:
        self.task.save(self.task_path)
        args = ["-m", "workers.generate_worker", "--task", str(self.task_path)]
        if dry_run:
            args.append("--dry-run")
        self.proc.start(sys.executable, args)

    def kill(self) -> None:
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()

    def is_running(self) -> bool:
        return self.proc.state() != QProcess.ProcessState.NotRunning

    def _read_stdout(self) -> None:
        data = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self.log_line.emit(line)
            event = parse_worker_line(line)
            if event is not None:
                self.event.emit(event)

    def _on_finished(self, code: int, _status) -> None:
        self.finished.emit(int(code))
```

- [ ] **Step 4: Run parser tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_process_event_parser.py -v`

Expected: PASS.

- [ ] **Step 5: Commit launcher**

```bash
git add workers/process_launcher.py tests/test_process_event_parser.py
git commit -m "workers: add qprocess generation launcher"
```

---

## Task 5: Update Prompt Settings Call Sites to Meta

**Files:**
- Modify: `workers/batch_image.py`
- Modify: `workers/batch_video.py`
- Modify: `workers/single_image.py` only if direct settings access appears
- Modify: `workers/single_video.py` only if direct settings access appears

- [ ] **Step 1: Search settings call sites**

Run: `rg -n "scenes_json\.settings|settings\." workers core ui engines`

Expected current hits include `workers/batch_image.py` and `workers/batch_video.py`.

- [ ] **Step 2: Update image settings helper**

In `workers/batch_image.py`, change `_build_image_settings`:

```python
def _build_image_settings(project: Project, scene: Scene, output_path: Path) -> dict[str, Any]:
    meta = project.scenes_json.meta
    full_prompt = (
        f"{scene.imagePrompt or ''}\n\n"
        f"Style: {meta.baseStyle}\n\n"
        f"Negative: {meta.baseNegative}"
    )
    return {
        "prompt": full_prompt,
        "aspect": meta.aspect_ratio,
        "quality": meta.image_quality,
        "output_path": output_path,
        "topic": project.scenes_json.topic_for_prompt(),
        "style": meta.baseStyle,
        "debug_dir": project.paths.temp_dir / "candidates",
    }
```

- [ ] **Step 3: Update video settings helper**

In `workers/batch_video.py`, change `_build_video_settings`:

```python
def _build_video_settings(project: Project, output_path: Path) -> dict[str, Any]:
    meta = project.scenes_json.meta
    return {
        "aspect": meta.aspect_ratio,
        "resolution": meta.video_resolution,
        "duration": meta.video_duration,
        "output_path": output_path,
    }
```

- [ ] **Step 4: Run search again**

Run: `rg -n "scenes_json\.settings" workers core ui engines`

Expected: no hits.

- [ ] **Step 5: Run compile check**

Run: `.venv\Scripts\python.exe -m py_compile core\schema.py workers\batch_image.py workers\batch_video.py workers\single_image.py workers\single_video.py`

Expected: exit 0.

- [ ] **Step 6: Commit meta call-site update**

```bash
git add workers/batch_image.py workers/batch_video.py
git commit -m "workers: read generation defaults from meta"
```

---

## Task 6: Grok Worker CDP Helpers

**Files:**
- Create: `engines/grok/cdp_worker.py`

- [ ] **Step 1: Create helper module**

Create `engines/grok/cdp_worker.py` with:

```python
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from patchright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright


def kill_stale_cdp_clients(port: int) -> int:
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=5)
    candidate_pids: set[int] = set()
    for line in result.stdout.splitlines():
        if f"127.0.0.1:{port}" in line and "ESTABLISHED" in line:
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                candidate_pids.add(int(m.group(1)))
    killed = 0
    for pid in candidate_pids:
        ps = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if "node.exe" in ps.stdout.lower():
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False, capture_output=True)
            killed += 1
    return killed


def _port_from_url(url: str) -> int:
    m = re.search(r":(\d+)", url)
    if not m:
        raise ValueError(f"CDP URL missing port: {url}")
    return int(m.group(1))


@dataclass
class WorkerCdpSession:
    pw: Playwright
    browser: Browser
    context: BrowserContext
    page: Page

    async def close(self) -> None:
        try:
            await self.browser.close()
        finally:
            await self.pw.stop()


async def connect_worker_cdp(cdp_url: str, base_url: str) -> WorkerCdpSession:
    port = _port_from_url(cdp_url)
    kill_stale_cdp_clients(port)
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(cdp_url, timeout=15_000)
        if not browser.contexts:
            raise RuntimeError("Browser không có context nào")
        context = browser.contexts[0]
        page = await get_or_open_tab(context, base_url)
        return WorkerCdpSession(pw=pw, browser=browser, context=context, page=page)
    except Exception:
        await pw.stop()
        raise


async def get_or_open_tab(context: BrowserContext, base_url: str) -> Page:
    for page in context.pages:
        url = page.url or ""
        if url.startswith(base_url):
            await page.bring_to_front()
            return page
    for page in context.pages:
        if page.url in ("about:blank", "chrome://newtab/"):
            await page.goto(base_url, wait_until="domcontentloaded")
            await page.bring_to_front()
            return page
    page = await context.new_page()
    await page.goto(base_url, wait_until="domcontentloaded")
    await page.bring_to_front()
    return page
```

- [ ] **Step 2: Compile helper**

Run: `.venv\Scripts\python.exe -m py_compile engines\grok\cdp_worker.py`

Expected: exit 0.

- [ ] **Step 3: Commit helper**

```bash
git add engines/grok/cdp_worker.py
git commit -m "grok: add worker-local cdp helpers"
```

---

## Task 7: Grok Image Worker Flow

**Files:**
- Create: `engines/grok/image_worker_flow.py`
- Modify: `workers/generate_worker.py`

- [ ] **Step 1: Implement Grok image flow**

Create `engines/grok/image_worker_flow.py`:

```python
from __future__ import annotations

import time
from pathlib import Path

from core.project import Project
from engines.grok.cdp_worker import connect_worker_cdp
from engines.grok.engine import GrokImageEngine
from engines.grok.image_ref_engine import GrokImageRefEngine
from workers.batch_image import _build_image_settings
from workers.task_contract import GenerateTask, event_line


def _print(line: str) -> None:
    print(line, flush=True)


async def run_grok_image_task(task: GenerateTask) -> tuple[int, int]:
    project = Project.load(Path(task.project_file))
    session = await connect_worker_cdp(task.cdp.url, task.cdp.base_url)
    success = 0
    total = len(task.scene_ids)
    try:
        engine = GrokImageEngine(session.page)
        for scene_id in task.scene_ids:
            scene = project.scene(scene_id)
            idx = project.scene_index(scene_id)
            output_path = project.paths.image_path(idx)
            _print(event_line("scene_started", scene_id=scene_id, asset="image"))
            started = time.monotonic()
            settings = _build_image_settings(project, scene, output_path)
            settings["pick_mode"] = task.options.pick_mode
            settings["fast_mode"] = task.options.fast_mode
            prompt = settings.pop("prompt")
            try:
                refs = [Path(p) for p in task.options.image_refs] if task.options.use_refs_for_image else []
                if refs:
                    ref_engine = GrokImageRefEngine(session.page)
                    result = await ref_engine.gen_image_with_refs(
                        scene_id=scene_id,
                        prompt=prompt,
                        ref_paths=refs,
                        output_path=output_path,
                        aspect=project.scenes_json.meta.aspect_ratio,
                        fast_mode=task.options.fast_mode,
                    )
                    if not result.get("ok"):
                        raise RuntimeError(result.get("reason") or "image_ref_engine failed")
                    result_path = Path(result["path"])
                else:
                    result_path = await engine.gen_image(prompt=prompt, settings=settings, ref_image=None)
            except Exception as e:
                _print(event_line("scene_failed", scene_id=scene_id, asset="image", reason=str(e)))
                continue
            success += 1
            rel = str(Path(result_path).resolve().relative_to(project.paths.root)).replace("\\", "/")
            _print(event_line(
                "scene_done",
                scene_id=scene_id,
                asset="image",
                path=rel,
                duration_sec=round(time.monotonic() - started, 2),
            ))
    finally:
        await session.close()
    return success, total
```

- [ ] **Step 2: Route real image tasks from CLI**

In `workers/generate_worker.py`, update `run_task` real path:

```python
import asyncio
from engines.grok.image_worker_flow import run_grok_image_task
```

Inside `run_task`:

```python
    if task.provider != "grok":
        _print(marker_line("TASK FAILED", {
            "reason": f"provider not implemented: {task.provider}",
            "code": EXIT_FLOW_FAILED,
        }))
        return EXIT_FLOW_FAILED
    if task.task_type not in ("batch_image", "single_image"):
        _print(marker_line("TASK FAILED", {
            "reason": f"task_type not implemented: {task.task_type}",
            "code": EXIT_FLOW_FAILED,
        }))
        return EXIT_FLOW_FAILED
    try:
        success, total = asyncio.run(run_grok_image_task(task))
    except Exception as e:
        _print(marker_line("TASK FAILED", {"reason": str(e), "code": EXIT_FLOW_FAILED}))
        return EXIT_FLOW_FAILED
    _print(marker_line("TASK DONE", {
        "success": success,
        "total": total,
        "duration_sec": round(time.monotonic() - t0, 2),
    }))
    return EXIT_SUCCESS if success == total else EXIT_FLOW_FAILED
```

- [ ] **Step 3: Compile worker flow**

Run: `.venv\Scripts\python.exe -m py_compile workers\generate_worker.py engines\grok\image_worker_flow.py`

Expected: exit 0.

- [ ] **Step 4: Commit Grok image flow**

```bash
git add workers/generate_worker.py engines/grok/image_worker_flow.py
git commit -m "grok: run image generation in worker process"
```

---

## Task 8: Wire GUI Batch Image and Single Image to QProcess

**Files:**
- Modify: `ui/main_window.py`
- Modify: `ui/connection_panel.py`

- [ ] **Step 1: Add health/provider panel fields**

In `ui/connection_panel.py`, replace Patchright connection responsibilities with plain UI state:

```python
DEFAULT_CDP_URL = "http://127.0.0.1:9222"

def selected_provider(self) -> str:
    return "grok"

def selected_model(self) -> str:
    return "grok-auto"

def cdp_url(self) -> str:
    return self.url_edit.text().strip() or DEFAULT_CDP_URL
```

Keep any old signals temporarily if needed by `MainWindow`, but stop emitting `page_ready(page)` after this task.

- [ ] **Step 2: Add process fields in MainWindow**

In `ui/main_window.py`, import:

```python
from datetime import datetime
from workers.process_launcher import GenerateProcess
from workers.task_contract import GenerateTask
```

Add:

```python
self._generate_proc: GenerateProcess | None = None
```

- [ ] **Step 3: Build task helper**

Add method:

```python
def _build_generate_task(self, task_type: str, scene_ids: list[str], fast_mode: bool = False) -> GenerateTask:
    if self.project is None:
        raise RuntimeError("Project chưa load")
    task_id = f"{datetime.now():%Y%m%d_%H%M%S}_{task_type}"
    return GenerateTask(
        task_id=task_id,
        project_file=str(self.project.paths.scenes_original),
        project_root=str(self.project.paths.root),
        task_type=task_type,
        scene_ids=scene_ids,
        provider=self.connection_panel.selected_provider(),
        model=self.connection_panel.selected_model(),
        cdp={"url": self.connection_panel.cdp_url(), "base_url": "https://grok.com/imagine"},
        options={
            "fast_mode": fast_mode,
            "use_refs_for_image": self.project.get_use_refs_for_image(),
            "image_refs": [str(p) for p in self.project.get_image_refs()],
        },
    )
```

- [ ] **Step 4: Add process start helper**

Add:

```python
def _start_generate_process(self, task: GenerateTask) -> None:
    if self._generate_proc is not None and self._generate_proc.is_running():
        QMessageBox.information(self, "Đang chạy", "Một generation worker đang chạy.")
        return
    task_path = self.project.paths.temp_dir / "tasks" / f"{task.task_id}.json"
    proc = GenerateProcess(task, task_path, parent=self)
    proc.log_line.connect(self._append_log)
    proc.event.connect(self._on_generate_event)
    proc.finished.connect(self._on_generate_finished)
    self._generate_proc = proc
    self.btn_stop.setEnabled(True)
    proc.start()
```

- [ ] **Step 5: Handle worker events**

Add:

```python
def _on_generate_event(self, event) -> None:
    if self.project is None:
        return
    if event.type == "scene_started":
        sid = event.payload["scene_id"]
        self.project.update_scene_state(sid, event.payload.get("asset", "image"), {"status": "generating", "fail_reason": None})
        self.scene_list.refresh_row(sid)
    elif event.type == "scene_done":
        sid = event.payload["scene_id"]
        asset = event.payload.get("asset", "image")
        path = event.payload["path"]
        self.project.update_scene_state(sid, asset, {"status": "ready", "path": path, "fail_reason": None})
        from core.thumbnail import regenerate_thumbnail
        visual_path = self.project.paths.root / path
        regenerate_thumbnail(project_root=self.project.paths.root, scene_id=sid, visual_path=visual_path, visual_kind=asset)
        self.scene_list.refresh_row(sid)
    elif event.type == "scene_failed":
        sid = event.payload["scene_id"]
        asset = event.payload.get("asset", "image")
        reason = event.payload.get("reason", "unknown")
        self.project.update_scene_state(sid, asset, {"status": "failed", "fail_reason": reason})
        self.scene_list.refresh_row(sid)
```

- [ ] **Step 6: Route batch/single image**

In `_start_batch_image`, replace legacy `BatchImageWorker` construction with:

```python
task = self._build_generate_task("batch_image", list(selected_ids))
self._start_generate_process(task)
```

In `_regen_one`, replace `SingleImageWorker` construction with:

```python
task = self._build_generate_task("single_image", [scene_id], fast_mode=fast_mode)
self._start_generate_process(task)
```

- [ ] **Step 7: Stop handler kills process**

Update stop logic so active `GenerateProcess.kill()` is called.

- [ ] **Step 8: Compile GUI**

Run: `.venv\Scripts\python.exe -m py_compile ui\main_window.py ui\connection_panel.py`

Expected: exit 0.

- [ ] **Step 9: Commit GUI wiring**

```bash
git add ui/main_window.py ui/connection_panel.py
git commit -m "ui: launch image generation via qprocess worker"
```

---

## Task 9: Verification and Docs

**Files:**
- Modify: `README.md`
- Modify: `BUILD_LOG.md`

- [ ] **Step 1: Run unit tests**

Run: `.venv\Scripts\python.exe -m pytest tests -v`

Expected: all tests pass.

- [ ] **Step 2: Run compile sweep**

Run:

```powershell
.venv\Scripts\python.exe -m py_compile core\schema.py workers\task_contract.py workers\process_launcher.py workers\generate_worker.py engines\grok\cdp_worker.py engines\grok\image_worker_flow.py ui\main_window.py ui\connection_panel.py
```

Expected: exit 0.

- [ ] **Step 3: Manual no-browser dry run**

Create a temporary task JSON with `--dry-run`:

```powershell
.venv\Scripts\python.exe -m workers.generate_worker --task path\to\task.json --dry-run
```

Expected: stdout includes `TASK START`, per-scene `EVENT`, `TASK DONE`, exit 0.

- [ ] **Step 4: Manual Grok smoke test**

Precondition: user opens Brave automation profile with CDP port 9222 and is logged into Grok.

Run app:

```powershell
.venv\Scripts\python.exe main.py
```

Test:
- Load project with new meta schema.
- Select 2 scenes.
- Click Batch ảnh.
- Confirm GUI logs worker markers.
- Confirm `sources/picN.jpg` files appear.
- Confirm scene rows update ready state and thumbnail.
- Open PreviewDialog for one scene and Gen Image.
- Confirm single image process runs and updates that scene.

- [ ] **Step 5: Update README**

Document:
- GUI no longer owns Patchright for image generation.
- Browser must be opened at `127.0.0.1:9222`.
- Provider/model is project-level, Grok only for now.
- Slideshow remains offline render/tool flow, not provider/model.

- [ ] **Step 6: Update BUILD_LOG**

Add a session entry with:
- schema meta migration
- QProcess task contract
- Grok batch/single image worker process
- verification commands and live-test status

- [ ] **Step 7: Commit docs**

```bash
git add README.md BUILD_LOG.md
git commit -m "docs: document cdp worker image generation flow"
```

---

## Self-Review

Spec coverage:
- Meta schema update covered by Task 1 and Task 5.
- GUI/CDP separation covered by Tasks 2, 3, 4, 6, 7, 8.
- Batch image and single image both covered by Tasks 7 and 8.
- Port decision uses `127.0.0.1:9222` in task contract and UI plan.
- Slideshow is excluded from this implementation plan.
- Provider/model is project-level in Task 8.

Known scope gaps:
- Batch video and single video are intentionally deferred.
- ChatGPT/Gemini providers are intentionally unsupported.
- Worker-owned state with run_id is intentionally deferred.
- Explicit `image_file`/`video_file` naming is intentionally deferred.

