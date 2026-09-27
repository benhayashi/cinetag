import pytest
from pathlib import Path
from src.media.subtitles import clean_srt_content, parse_srt_file, find_accompanying_srt, get_video_subtitles

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:04,500
Hello everyone, welcome to our family picnic!

2
00:00:05,200 --> 00:00:08,900
<i>Look at the dog running across the lawn.</i>
[Laughter]

3
01:15:10,000 --> 01:15:14,000
Time for birthday cake!
"""

def test_clean_srt_content():
    dialogue = clean_srt_content(SAMPLE_SRT)
    lines = dialogue.splitlines()
    assert len(lines) == 3
    assert "[00:01] Hello everyone, welcome to our family picnic!" in lines[0]
    assert "[00:05] Look at the dog running across the lawn." in lines[1]
    assert "[01:15:10] Time for birthday cake!" in lines[2]

def test_find_accompanying_srt(tmp_path: Path):
    video = tmp_path / "vacation_2023.mp4"
    video.touch()
    
    # Non-existent srt
    assert find_accompanying_srt(video) is None

    # Matching srt
    srt = tmp_path / "vacation_2023.srt"
    srt.write_text(SAMPLE_SRT, encoding="utf-8")
    
    found = find_accompanying_srt(video)
    assert found is not None
    assert found.name == "vacation_2023.srt"

    # Reading file
    parsed = parse_srt_file(found)
    assert "family picnic" in parsed

def test_get_video_subtitles_external(tmp_path: Path):
    video = tmp_path / "home_movie.mov"
    video.touch()
    srt = tmp_path / "home_movie.srt"
    srt.write_text(SAMPLE_SRT, encoding="utf-8")

    info = get_video_subtitles(video)
    assert info["has_subtitles"] is True
    assert info["source"] == "external_srt"
    assert info["srt_path"] == str(srt.resolve())
    assert "family picnic" in info["dialogue_text"]

def test_get_video_subtitles_none(tmp_path: Path):
    video = tmp_path / "silent.mp4"
    video.touch()

    info = get_video_subtitles(video)
    assert info["has_subtitles"] is False
    assert info["source"] == "none"
    assert info["dialogue_text"] is None

def test_generate_and_write_srt(tmp_path: Path):
    from src.media.subtitles import format_timestamp_srt, generate_srt_from_text, write_srt_sidecar

    assert format_timestamp_srt(0) == "00:00:00,000"
    assert format_timestamp_srt(65.5) == "00:01:05,500"
    assert format_timestamp_srt(3661.123) == "01:01:01,123"

    # From segments
    segments = [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 3.0, "end": 6.2, "text": "Testing SRT generation"}
    ]
    srt_out = generate_srt_from_text("Hello world Testing SRT generation", segments=segments)
    assert "00:00:00,000 --> 00:00:02,500" in srt_out
    assert "Hello world" in srt_out
    assert "00:00:03,000 --> 00:00:06,200" in srt_out
    assert "Testing SRT generation" in srt_out

    # Write sidecar
    video = tmp_path / "clip.mp4"
    video.touch()
    out_file = write_srt_sidecar(video, srt_out)
    assert out_file.exists()
    assert out_file.name == "clip.srt"
    assert "Testing SRT generation" in out_file.read_text(encoding="utf-8")
