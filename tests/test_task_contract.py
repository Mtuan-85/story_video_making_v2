import json

import pytest
from pydantic import ValidationError

from workers.task_contract import (
    EXIT_CDP_UNREACHABLE,
    EXIT_FLOW_FAILED,
    EXIT_PARSE_FAILED,
    EXIT_PREREQ_MISSING,
    EXIT_PROJECT_LOCKED,
    EXIT_SUCCESS,
    EXIT_USER_KILLED,
    GenerateTask,
    WorkerEvent,
    event_line,
    marker_line,
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


def test_task_start_line_has_payload():
    event = parse_worker_line('TASK START {"task_id":"t1","task_type":"batch_image","provider":"grok"}')
    assert event.type == "task_start"
    assert event.payload["task_id"] == "t1"
    assert event.payload["provider"] == "grok"


def test_task_failed_line_has_payload():
    event = parse_worker_line('TASK FAILED {"reason":"cdp unavailable","code":5}')
    assert event.type == "task_failed"
    assert event.payload["reason"] == "cdp unavailable"
    assert event.payload["code"] == EXIT_CDP_UNREACHABLE


def test_marker_line_formats_json_payload():
    line = marker_line("TASK DONE", {"success": 1, "total": 1})
    marker, payload = line.split(" ", 2)[0:2], line.split(" ", 2)[2]
    assert " ".join(marker) == "TASK DONE"
    assert json.loads(payload) == {"success": 1, "total": 1}


def test_event_line_includes_event_type():
    line = event_line("scene_started", scene_id="1")
    marker, payload = line.split(" ", 1)
    assert marker == "EVENT"
    assert json.loads(payload) == {"type": "scene_started", "scene_id": "1"}


def test_event_line_rejects_payload_type_override():
    with pytest.raises(ValueError, match="type"):
        event_line("scene_started", type="scene_done")


def test_exit_constants_are_stable():
    assert EXIT_SUCCESS == 0
    assert EXIT_FLOW_FAILED == 1
    assert EXIT_PREREQ_MISSING == 2
    assert EXIT_USER_KILLED == 3
    assert EXIT_PARSE_FAILED == 4
    assert EXIT_CDP_UNREACHABLE == 5
    assert EXIT_PROJECT_LOCKED == 6


def test_generate_task_rejects_unknown_top_level_field():
    with pytest.raises(ValidationError):
        GenerateTask(
            task_id="t1",
            project_file="D:/p/story.json",
            project_root="D:/p",
            task_type="batch_image",
            scene_ids=["1"],
            providre="chatgpt",
        )


def test_generate_task_rejects_unknown_cdp_field():
    with pytest.raises(ValidationError):
        GenerateTask(
            task_id="t1",
            project_file="D:/p/story.json",
            project_root="D:/p",
            task_type="batch_image",
            scene_ids=["1"],
            cdp={"url": "http://127.0.0.1:9222", "unexpected": True},
        )


def test_generate_task_rejects_unknown_options_field():
    with pytest.raises(ValidationError):
        GenerateTask(
            task_id="t1",
            project_file="D:/p/story.json",
            project_root="D:/p",
            task_type="batch_image",
            scene_ids=["1"],
            options={"pick_mode": "auto", "unexpected": True},
        )


def test_generate_task_save_load_round_trip_and_unrelated_line_returns_none(tmp_path):
    task_path = tmp_path / "task.json"
    task = GenerateTask(
        task_id="t1",
        project_file="D:/p/story.json",
        project_root="D:/p",
        task_type="batch_image",
        scene_ids=["1"],
    )

    task.save(task_path)

    loaded = GenerateTask.load(task_path)
    assert loaded == task
    assert json.loads(task_path.read_text(encoding="utf-8"))["cdp"]["url"] == "http://127.0.0.1:9222"
    assert parse_worker_line("regular worker output") is None
