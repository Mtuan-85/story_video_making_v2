from pathlib import Path

import pysubs2

from render.bgm_mixer import (
    build_bgm_mix_command,
    build_master_audio_mix_command,
    burn_subtitle_and_mix_bgm,
)
from voice.ass_generator import generate_final_ass


def test_bgm_mix_command_burns_subtitles_and_mixes_sorted_looped_bgm(tmp_path: Path) -> None:
    input_video = tmp_path / "final_raw.mp4"
    ass_path = tmp_path / "final.ass"
    output_video = tmp_path / "final.mp4"
    bgm_files = [
        tmp_path / "b_song.mp3",
        tmp_path / "a_song.mp3",
    ]

    cmd = build_bgm_mix_command(
        input_video=input_video,
        ass_path=ass_path,
        output_video=output_video,
        bgm_files=bgm_files,
        target_duration=12.0,
        bgm_db=-17.0,
        fade_sec=2.0,
    )
    cmd_text = " ".join(cmd)

    assert cmd[:5] == ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    assert cmd.index(str(tmp_path / "a_song.mp3")) < cmd.index(str(tmp_path / "b_song.mp3"))
    assert "subtitles=" in cmd_text
    assert "concat=n=2:v=0:a=1[bgm_cycle]" in cmd_text
    assert "aloop=loop=-1:size=2147483647" in cmd_text
    assert "atrim=duration=12.000" in cmd_text
    assert "volume=-17.0dB" in cmd_text
    assert "afade=t=in:st=0:d=2.00" in cmd_text
    assert "afade=t=out:st=10.00:d=2.00" in cmd_text
    assert "amix=inputs=2:duration=first:normalize=0[a]" in cmd_text
    assert "-map [v]" in cmd_text
    assert "-map [a]" in cmd_text


def test_master_audio_mix_command_normalizes_voice_and_mixes_bgm(tmp_path: Path) -> None:
    input_video = tmp_path / "video_only.mp4"
    master_audio = tmp_path / "master_voice.wav"
    ass_path = tmp_path / "final.ass"
    output_video = tmp_path / "final.mp4"
    bgm_files = [tmp_path / "song.mp3"]

    cmd = build_master_audio_mix_command(
        input_video=input_video,
        master_audio=master_audio,
        ass_path=ass_path,
        output_video=output_video,
        bgm_files=bgm_files,
        target_duration=30.0,
        bgm_db=-17.0,
    )
    cmd_text = " ".join(cmd)

    assert cmd.index(str(master_audio)) > cmd.index(str(input_video))
    assert "subtitles=" in cmd_text
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in cmd_text
    assert "volume=-17.0dB" in cmd_text
    assert "amix=inputs=2:duration=first:normalize=0[a]" in cmd_text
    assert "-map [v]" in cmd_text
    assert "-map [a]" in cmd_text


def test_bgm_mix_command_can_mix_without_subtitles(tmp_path: Path) -> None:
    input_video = tmp_path / "final_raw.mp4"
    output_video = tmp_path / "final.mp4"
    bgm_files = [tmp_path / "song.mp3"]

    cmd = build_bgm_mix_command(
        input_video=input_video,
        ass_path=None,
        output_video=output_video,
        bgm_files=bgm_files,
        target_duration=8.0,
    )
    cmd_text = " ".join(cmd)

    assert "subtitles=" not in cmd_text
    assert "[0:v]copy[v]" in cmd_text
    assert "amix=inputs=2:duration=first:normalize=0[a]" in cmd_text


def test_burn_subtitle_and_mix_bgm_keeps_bgm_when_ass_missing(monkeypatch, tmp_path: Path) -> None:
    input_video = tmp_path / "final_raw.mp4"
    input_video.write_bytes(b"video")
    missing_ass = tmp_path / "missing.ass"
    output_video = tmp_path / "final.mp4"
    bgm_dir = tmp_path / "bgm"
    bgm_dir.mkdir()
    (bgm_dir / "song.mp3").write_bytes(b"bgm")
    calls = {}

    monkeypatch.setattr("render.bgm_mixer._ffprobe_duration", lambda _path: 8.0)

    def fake_run(cmd, **_kwargs):
        calls["cmd"] = cmd
        output_video.write_bytes(b"mixed")

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr("render.bgm_mixer.subprocess.run", fake_run)

    result = burn_subtitle_and_mix_bgm(input_video, missing_ass, output_video, bgm_dir)

    assert result == output_video
    assert output_video.read_bytes() == b"mixed"
    assert "subtitles=" not in " ".join(calls["cmd"])


def test_generate_final_ass_uses_centered_wrapped_subtitle_style(tmp_path: Path) -> None:
    output_path = tmp_path / "final.ass"
    voice_mapping = {
        "scenes": [
            {
                "id": "SCENE-01",
                "is_silent": False,
                "voice_in": 0.0,
                "voice_out": 1.0,
                "render_duration": 1.0,
                "freeze_pause_after": 0.0,
                "subtitle_phrases": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "words": [
                            {"word": "hello", "start": 0.0, "end": 0.5},
                            {"word": "world", "start": 0.5, "end": 1.0},
                        ],
                    }
                ],
            }
        ]
    }

    generate_final_ass(voice_mapping, output_path, video_width=1920, video_height=1080)

    subs = pysubs2.load(str(output_path))
    style = subs.styles["Default"]

    assert subs.info["WrapStyle"] == "0"
    assert style.fontname == "Cambria"
    assert style.fontsize == 50
    assert style.bold is True
    assert style.alignment == pysubs2.Alignment.MIDDLE_CENTER
    assert style.marginv == 100
    assert style.marginl == 100
    assert style.marginr == 100
