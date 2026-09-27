import pytest
from pathlib import Path
from src.core.config import AppConfig
from src.media.subtitles import clean_srt_content
from src.ai.prompt import build_user_prompt

def test_pipeline_config_defaults():
    cfg = AppConfig()
    assert cfg.processing_execution_mode == "serial"
    assert cfg.use_subtitles is True
    assert cfg.prefer_subtitles_over_whisper is True
    assert cfg.full_transcription_if_no_subtitles is True

def test_build_user_prompt_with_subtitles():
    timestamps = ["00:00", "00:10"]
    subtitles = "[00:01] Hello Grandma!\n[00:05] Happy birthday!"
    prompt = build_user_prompt(
        timestamps=timestamps,
        audio_transcript=None,
        context=None,
        subtitle_dialogue=subtitles
    )
    assert "Subtitles dialogue" in prompt
    assert "Hello Grandma!" in prompt
    assert "00:00, 00:10" in prompt

def test_build_user_prompt_with_both_audio_and_subtitles():
    timestamps = ["00:00"]
    subtitles = "[00:02] We are going fishing"
    transcript = "we are going fishing"
    prompt = build_user_prompt(
        timestamps=timestamps,
        audio_transcript=transcript,
        context="Lake Tahoe trip",
        subtitle_dialogue=subtitles
    )
    assert "Subtitles dialogue" in prompt
    assert "Audio transcript" in prompt
    assert "Lake Tahoe trip" in prompt
