from workers.process_launcher import collect_events_from_text


def test_collect_events_from_text_ignores_human_logs():
    text = "\n".join(
        [
            "hello",
            'TASK START {"task_id":"t","task_type":"batch_image"}',
            'EVENT {"type":"scene_started","scene_id":"1"}',
            'TASK DONE {"success":1,"total":1}',
        ]
    )

    events = collect_events_from_text(text)

    assert [event.type for event in events] == ["task_start", "scene_started", "task_done"]


def test_collect_events_from_text_ignores_invalid_json_marker():
    text = "\n".join(
        [
            'TASK START {"task_id":"t","task_type":"batch_image"}',
            "EVENT {invalid json",
            'TASK DONE {"success":1,"total":1}',
        ]
    )

    events = collect_events_from_text(text)

    assert [event.type for event in events] == ["task_start", "task_done"]


def test_collect_events_from_text_parses_task_failed():
    events = collect_events_from_text('TASK FAILED {"reason":"cdp unavailable","code":5}')

    assert [event.type for event in events] == ["task_failed"]
    assert events[0].payload == {"reason": "cdp unavailable", "code": 5}
