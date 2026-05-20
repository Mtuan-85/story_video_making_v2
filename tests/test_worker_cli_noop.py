import subprocess
import sys

from workers.task_contract import EXIT_FLOW_FAILED, GenerateTask, parse_worker_line


def _write_project(tmp_path):
    project = tmp_path / "project.json"
    project.write_text(
        '{"meta":{"project_id":"p","title":"T","aspect_ratio":"16:9","language":"en"},'
        '"scenes":[{"id":"1","visual_type":"Image","story_en":"s","duration":1}]}',
        encoding="utf-8",
    )
    return project


def _write_task(tmp_path, *, scene_ids=None, task_type="batch_image"):
    task = GenerateTask(
        task_id="noop",
        project_file=str(_write_project(tmp_path)),
        project_root=str(tmp_path),
        task_type=task_type,
        scene_ids=[] if scene_ids is None else scene_ids,
    )
    task_path = tmp_path / "task.json"
    task.save(task_path)
    return task_path


def _run_worker(task_path, *extra_args):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "workers.generate_worker",
            "--task",
            str(task_path),
            *extra_args,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )


def _parsed_events(stdout):
    return [
        event
        for line in stdout.splitlines()
        if (event := parse_worker_line(line)) is not None
    ]


def test_worker_cli_noop(tmp_path):
    task_path = _write_task(tmp_path)

    result = _run_worker(task_path, "--dry-run")

    assert result.returncode == 0
    events = _parsed_events(result.stdout)
    assert [event.type for event in events] == [
        "task_start",
        "task_done",
    ]
    assert events[0].payload == {
        "task_id": "noop",
        "task_type": "batch_image",
        "provider": "grok",
        "model": "grok-auto",
    }
    assert events[1].payload["success"] == 0
    assert events[1].payload["total"] == 0
    assert isinstance(events[1].payload["duration_sec"], (int, float))


def test_worker_cli_dry_run_emits_scene_events_for_requested_scene(tmp_path):
    task_path = _write_task(tmp_path, scene_ids=["1"])

    result = _run_worker(task_path, "--dry-run")

    assert result.returncode == 0
    events = _parsed_events(result.stdout)
    assert [event.type for event in events] == [
        "task_start",
        "scene_started",
        "scene_done",
        "task_done",
    ]
    assert events[1].payload == {"scene_id": "1", "asset": "image"}
    assert events[2].payload == {
        "scene_id": "1",
        "asset": "image",
        "path": "",
        "duration_sec": 0,
    }
    assert events[3].payload["success"] == 1
    assert events[3].payload["total"] == 1
    assert isinstance(events[3].payload["duration_sec"], (int, float))


def test_worker_cli_dry_run_uses_video_asset_for_video_tasks(tmp_path):
    task_path = _write_task(tmp_path, scene_ids=["1"], task_type="single_video")

    result = _run_worker(task_path, "--dry-run")

    assert result.returncode == 0
    events = _parsed_events(result.stdout)
    assert events[1].payload == {"scene_id": "1", "asset": "video"}
    assert events[2].payload == {
        "scene_id": "1",
        "asset": "video",
        "path": "",
        "duration_sec": 0,
    }
    assert events[3].payload["success"] == 1


def test_worker_cli_non_dry_run_fails_for_unsupported_task_type(tmp_path):
    task_path = _write_task(tmp_path, task_type="batch_video")

    result = _run_worker(task_path)

    assert result.returncode == EXIT_FLOW_FAILED
    assert "TASK FAILED" in result.stdout
    events = _parsed_events(result.stdout)
    assert events[0].payload == {
        "task_id": "noop",
        "task_type": "batch_video",
        "provider": "grok",
        "model": "grok-auto",
    }
    assert events[1].payload == {
        "task_id": "noop",
        "reason": "task_type not implemented: batch_video",
        "code": EXIT_FLOW_FAILED,
    }
