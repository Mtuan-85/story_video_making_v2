from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(extra="forbid")

    url: str = "http://127.0.0.1:9222"
    profile_marker: str = "brave-grok-profile"
    base_url: str = "https://grok.com/imagine"


class TaskOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pick_mode: str = "auto"
    fast_mode: bool = False
    use_refs_for_image: bool = False
    image_refs: list[str] = Field(default_factory=list)
    ref_mapping_path: str | None = None


class GenerateTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    def load(cls, path: str | Path) -> "GenerateTask":
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.model_dump_json(indent=2), encoding="utf-8")


class WorkerEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


def marker_line(marker: str, payload: dict[str, Any]) -> str:
    return f"{marker} {json.dumps(payload, ensure_ascii=False)}"


def event_line(event_type: str, **payload: Any) -> str:
    if "type" in payload:
        raise ValueError("event_line payload must not include type")
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
        try:
            payload = json.loads(text[len(marker) :])
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if event_type is None:
            event_payload = dict(payload)
            parsed_type = event_payload.pop("type", None)
            if not isinstance(parsed_type, str):
                return None
            return WorkerEvent(type=parsed_type, payload=event_payload)
        return WorkerEvent(type=event_type, payload=payload)
    return None
