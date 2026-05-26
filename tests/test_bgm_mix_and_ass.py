from pathlib import Path

import pysubs2

from render.bgm_mixer import (
    build_bgm_mix_command,
    build_master_audio_mix_command,
    burn_subtitle_mix_master_audio_bgm,
    burn_subtitle_and_mix_bgm,
    estimate_final_mux_timeout,
    parse_ffmpeg_progress_percent,
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
    assert "fontsdir=" in cmd_text
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
    assert "fontsdir=" in cmd_text
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in cmd_text
    assert "volume=-17.0dB" in cmd_text
    assert "amix=inputs=2:duration=first:normalize=0[a]" in cmd_text
    assert "-map [v]" in cmd_text
    assert "-map [a]" in cmd_text


def test_master_audio_mix_command_can_use_qsv_encoder(tmp_path: Path) -> None:
    cmd = build_master_audio_mix_command(
        input_video=tmp_path / "video_only.mp4",
        master_audio=tmp_path / "master_voice.wav",
        ass_path=None,
        output_video=tmp_path / "final.mp4",
        bgm_files=[],
        target_duration=30.0,
        video_encoder="h264_qsv",
    )
    cmd_text = " ".join(cmd)

    assert "-c:v h264_qsv" in cmd_text
    assert "-global_quality 23" in cmd_text
    assert "-crf" not in cmd
    assert "libx264" not in cmd


def test_final_mux_timeout_scales_for_long_projects_and_many_bgm_files() -> None:
    timeout = estimate_final_mux_timeout(target_duration=732.431, bgm_count=10)

    assert timeout > 900
    assert timeout >= int(732.431 * 4)


def test_parse_ffmpeg_progress_percent_from_out_time_ms() -> None:
    percent = parse_ffmpeg_progress_percent("out_time_ms=366215500", 732.431)

    assert percent == 50


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


def test_master_audio_mix_retries_with_libx264_when_qsv_fails(monkeypatch, tmp_path: Path) -> None:
    input_video = tmp_path / "final_video_only.mp4"
    master_audio = tmp_path / "master_voice.wav"
    output_video = tmp_path / "final.mp4"
    for path in (input_video, master_audio):
        path.write_bytes(b"media")

    calls = []
    logs = []
    monkeypatch.setattr("render.bgm_mixer._ffprobe_duration", lambda _path: 8.0)

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)

        class Result:
            returncode = 1 if "h264_qsv" in cmd else 0
            stderr = "qsv failed"

        return Result()

    monkeypatch.setattr("render.bgm_mixer._run_ffmpeg_with_optional_progress", fake_run)

    burn_subtitle_mix_master_audio_bgm(
        input_video,
        master_audio,
        None,
        output_video,
        None,
        progress_cb=logs.append,
    )

    assert "h264_qsv" in calls[0]
    assert "libx264" in calls[1]
    assert "h264_qsv failed" in " ".join(logs)


def test_generate_final_ass_uses_bottom_center_karaoke_style(tmp_path: Path) -> None:
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
    assert style.fontname == "iCiel Cadena"
    assert style.fontsize == 80
    assert style.bold is True
    assert style.alignment == pysubs2.Alignment.BOTTOM_CENTER
    assert style.marginv == 80
    assert style.marginl == 150
    assert style.marginr == 150


def test_generate_final_ass_keeps_karaoke_on_one_line(tmp_path: Path) -> None:
    output_path = tmp_path / "final.ass"
    voice_mapping = {
        "scenes": [
            {
                "id": "SCENE-01",
                "is_silent": False,
                "voice_in": 0.0,
                "voice_out": 2.0,
                "render_duration": 2.0,
                "freeze_pause_after": 0.0,
                "subtitle_phrases": [
                    {
                        "start": 0.0,
                        "end": 2.0,
                        "words": [
                            {"word": "Japanese", "start": 0.0, "end": 0.3},
                            {"word": "children", "start": 0.3, "end": 0.6},
                            {"word": "can", "start": 0.6, "end": 0.8},
                            {"word": "wait", "start": 0.8, "end": 1.0},
                            {"word": "quietly", "start": 1.0, "end": 1.3},
                            {"word": "without", "start": 1.3, "end": 1.6},
                            {"word": "yelling", "start": 1.6, "end": 2.0},
                        ],
                    }
                ],
            }
        ]
    }

    generate_final_ass(voice_mapping, output_path, video_width=1920, video_height=1080)

    subs = pysubs2.load(str(output_path))
    assert len(subs.events) == 1
    assert "\\N" not in subs.events[0].text
