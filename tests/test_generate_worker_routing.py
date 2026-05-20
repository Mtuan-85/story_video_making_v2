from workers import generate_worker
from workers.task_contract import (
    EXIT_FLOW_FAILED,
    EXIT_SUCCESS,
    GenerateTask,
    parse_worker_line,
)


def _task(*, task_id="route", task_type="batch_image", provider="grok"):
    return GenerateTask(
        task_id=task_id,
        project_file="project.json",
        project_root=".",
        task_type=task_type,
        scene_ids=["1"],
        provider=provider,
    )


def _parsed_events(stdout):
    return [
        event
        for line in stdout.splitlines()
        if (event := parse_worker_line(line)) is not None
    ]


def test_non_dry_run_routes_grok_image_task(monkeypatch, capsys):
    import types

    async def fake_run_grok_image_task(task):
        assert task.task_id == "route"
        return 1, 1

    monkeypatch.setitem(
        __import__("sys").modules,
        "engines.grok.image_worker_flow",
        types.SimpleNamespace(run_grok_image_task=fake_run_grok_image_task),
    )

    result = generate_worker.run(_task(), dry_run=False)

    assert result == EXIT_SUCCESS
    events = _parsed_events(capsys.readouterr().out)
    assert [event.type for event in events] == ["task_start", "task_done"]
    assert events[1].payload["success"] == 1
    assert events[1].payload["total"] == 1
    assert isinstance(events[1].payload["duration_sec"], (int, float))


def test_non_dry_run_returns_flow_failed_for_partial_success(monkeypatch, capsys):
    import types

    async def fake_run_grok_image_task(task):
        return 1, 2

    monkeypatch.setitem(
        __import__("sys").modules,
        "engines.grok.image_worker_flow",
        types.SimpleNamespace(run_grok_image_task=fake_run_grok_image_task),
    )

    result = generate_worker.run(_task(), dry_run=False)

    assert result == EXIT_FLOW_FAILED
    events = _parsed_events(capsys.readouterr().out)
    assert [event.type for event in events] == ["task_start", "task_done"]
    assert events[1].payload["success"] == 1
    assert events[1].payload["total"] == 2


def test_non_dry_run_emits_task_failed_when_flow_raises(monkeypatch, capsys):
    import types

    async def fake_run_grok_image_task(task):
        raise RuntimeError("boom")

    monkeypatch.setitem(
        __import__("sys").modules,
        "engines.grok.image_worker_flow",
        types.SimpleNamespace(run_grok_image_task=fake_run_grok_image_task),
    )

    result = generate_worker.run(_task(), dry_run=False)

    assert result == EXIT_FLOW_FAILED
    events = _parsed_events(capsys.readouterr().out)
    assert [event.type for event in events] == ["task_start", "task_failed"]
    assert events[1].payload == {
        "task_id": "route",
        "reason": "boom",
        "code": EXIT_FLOW_FAILED,
    }
