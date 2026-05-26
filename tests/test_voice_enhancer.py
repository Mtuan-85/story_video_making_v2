from pathlib import Path

from voice.voice_enhancer import (
    apply_voice_pacing_operations,
    build_voice_pacing_operations,
)


def test_voice_enhancer_inserts_pause_after_sentence_punctuation_when_gap_is_too_short():
    words = [
        {"word": "Hello.", "start": 0.0, "end": 0.30},
        {"word": "Next", "start": 0.36, "end": 0.70},
    ]

    plan = build_voice_pacing_operations(
        source=Path("voice/raw/master_voice.wav"),
        output=Path("voice/enhance/master_voice.wav"),
        words=words,
    )

    assert plan["version"] == "voice_pacing_operations.v1"
    assert plan["source"] == "voice/raw/master_voice.wav"
    assert plan["output"] == "voice/enhance/master_voice.wav"
    assert plan["operations"] == [
        {
            "type": "insert_pause",
            "after_word_i": 0,
            "at_sec": 0.30,
            "insert_ms": 440,
            "reason": "missing_sentence_pause",
        }
    ]


def test_voice_enhancer_does_not_touch_existing_natural_sentence_pause():
    words = [
        {"word": "Hello.", "start": 0.0, "end": 0.30},
        {"word": "Next", "start": 0.76, "end": 1.10},
    ]

    plan = build_voice_pacing_operations(
        source=Path("voice/raw/master_voice.wav"),
        output=Path("voice/enhance/master_voice.wav"),
        words=words,
    )

    assert plan["operations"] == []


def test_apply_voice_pacing_operations_builds_ffmpeg_concat_with_inserted_silence(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "voice" / "raw" / "master_voice.wav"
    output = tmp_path / "voice" / "enhance" / "master_voice.wav"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"audio")
    calls = []

    class Result:
        returncode = 0
        stderr = ""

    def fake_run(cmd, capture_output, text, encoding, errors, timeout):
        calls.append(cmd)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"enhanced")
        return Result()

    monkeypatch.setattr("voice.voice_enhancer.subprocess.run", fake_run)
    plan = {
        "version": "voice_pacing_operations.v1",
        "source": str(source),
        "output": str(output),
        "operations": [
            {
                "type": "insert_pause",
                "after_word_i": 0,
                "at_sec": 0.30,
                "insert_ms": 440,
                "reason": "missing_sentence_pause",
            }
        ],
    }

    report = apply_voice_pacing_operations(source, output, plan)

    cmd = calls[0]
    assert cmd[:4] == ["ffmpeg", "-y", "-i", str(source)]
    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert "anullsrc=channel_layout=stereo:sample_rate=44100:d=0.440" in filter_complex
    assert "concat=n=3:v=0:a=1[out]" in filter_complex
    assert report["inserted_pause_ms"] == 440
    assert report["operation_count"] == 1
    assert output.exists()
