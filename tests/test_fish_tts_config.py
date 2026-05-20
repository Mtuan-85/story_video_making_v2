from voice.fish_tts import voice_settings_from_project_data


def test_voice_settings_prefers_meta_over_legacy_settings():
    data = {
        "meta": {
            "voice_model_id": "meta-voice",
            "voice_speed": 1.25,
            "voice_volume": 4,
        },
        "settings": {
            "voice_model_id": "legacy-voice",
            "voice_speed": 0.8,
            "voice_volume": -3,
        },
    }
    settings = voice_settings_from_project_data(data)
    assert settings["voice_model_id"] == "meta-voice"
    assert settings["voice_speed"] == 1.25
    assert settings["voice_volume"] == 4


def test_voice_settings_falls_back_to_legacy_settings():
    data = {
        "meta": {},
        "settings": {
            "voice_model_id": "legacy-voice",
            "voice_speed": 0.8,
            "voice_volume": -3,
        },
    }
    settings = voice_settings_from_project_data(data)
    assert settings["voice_model_id"] == "legacy-voice"
    assert settings["voice_speed"] == 0.8
    assert settings["voice_volume"] == -3
