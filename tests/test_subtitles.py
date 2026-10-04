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


def test_generate_srt_from_events():
    from src.media.subtitles import generate_srt_from_events
    from src.ai.base import TimestampEvent

    events = [
        TimestampEvent(timecode="00:00", description="Kids running across lawn", is_highlight=False),
        TimestampEvent(timecode="00:15", description="Dog catches frisbee in air", is_highlight=True),
        TimestampEvent(timecode="00:30", description="Family laughing together", is_highlight=False)
    ]

    srt_out = generate_srt_from_events(events, total_duration=45.0)
    assert "1\n00:00:00,000 --> 00:00:06,000\nKids running across lawn" in srt_out
    assert "2\n00:00:15,000 --> 00:00:21,000\nDog catches frisbee in air" in srt_out
    assert "3\n00:00:30,000 --> 00:00:45,000\nFamily laughing together" in srt_out


def test_generate_srt_from_summary_fallback():
    from src.media.subtitles import generate_srt_from_events

    srt_out = generate_srt_from_events([], total_duration=10.0, summary="A scenic sunset over the ocean horizon.")
    assert "1\n00:00:00,000 --> 00:00:10,000\nA scenic sunset over the ocean horizon." in srt_out


def test_queue_manager_exports_txt_and_srt_without_speech(tmp_path: Path, monkeypatch):
    from src.server.queue_manager import QueueManager, TaskItem
    from src.core.config import AppConfig
    from src.ai.base import VideoAnalysisResult, TimestampEvent

    cfg = AppConfig(
        export_txt=True,
        export_srt=True,
        export_info_json=False,
        export_xmp=False,
        export_nfo=False,
        transcribe_audio=False,
        auto_rename=False,
        synthesize_visual_subtitles=True
    )
    monkeypatch.setattr("src.server.queue_manager.load_config", lambda: cfg)
    qm = QueueManager()

    dummy_vid = tmp_path / "silent_home_movie.mp4"
    dummy_vid.write_text("fake video content")

    # Mock probe and frame extractor
    monkeypatch.setattr("src.server.queue_manager.probe_video", lambda *args, **kwargs: {
        "duration": 20.0,
        "width": 1920,
        "height": 1080,
        "has_audio": False,
        "creation_time": "2024-06-01T12:00:00"
    })
    monkeypatch.setattr("src.server.queue_manager.extract_frames", lambda *args, **kwargs: [
        {"path": str(dummy_vid), "timecode": "00:00", "frame_index": 0, "timestamp_seconds": 0.0}
    ])

    analysis_res = VideoAnalysisResult(
        title="Silent Picnic Afternoon",
        summary="A lovely quiet afternoon picnic in the backyard garden.",
        events=[
            TimestampEvent(timecode="00:00", description="Family sits on picnic blanket", is_highlight=False),
            TimestampEvent(timecode="00:10", description="Pouring lemonade into glasses", is_highlight=True)
        ],
        tags=["picnic", "garden"],
        people_or_subjects=["Mom", "Dad"],
        animals_or_pets=[],
        objects=["lemonade", "blanket"],
        suggested_filename="silent_picnic_afternoon"
    )

    class MockProvider:
        def describe_video(self, *args, **kwargs):
            return analysis_res

    monkeypatch.setattr("src.server.queue_manager.OllamaVisionProvider", lambda *args, **kwargs: MockProvider())

    task = TaskItem(file_path=str(dummy_vid), filename=dummy_vid.name)
    qm._process_single_task(task)

    assert task.status == "completed"

    txt_file = tmp_path / "silent_home_movie.mp4.txt"
    srt_file = tmp_path / "silent_home_movie.srt"

    assert txt_file.exists(), "Text sidecar should be created"
    assert srt_file.exists(), "SRT sidecar should be created when synthesize_visual_subtitles is True"

    srt_content = srt_file.read_text(encoding="utf-8")
    assert "Family sits on picnic blanket" in srt_content
    assert "Pouring lemonade into glasses" in srt_content


def test_queue_manager_skips_visual_srt_when_disabled(tmp_path: Path, monkeypatch):
    from src.server.queue_manager import QueueManager, TaskItem
    from src.core.config import AppConfig
    from src.ai.base import VideoAnalysisResult, TimestampEvent

    cfg = AppConfig(
        export_txt=True,
        export_srt=True,
        export_info_json=False,
        export_xmp=False,
        export_nfo=False,
        transcribe_audio=False,
        auto_rename=False,
        synthesize_visual_subtitles=False
    )
    monkeypatch.setattr("src.server.queue_manager.load_config", lambda: cfg)
    qm = QueueManager()

    dummy_vid = tmp_path / "silent_home_movie_2.mp4"
    dummy_vid.write_text("fake video content")

    monkeypatch.setattr("src.server.queue_manager.probe_video", lambda *args, **kwargs: {
        "duration": 20.0,
        "width": 1920,
        "height": 1080,
        "has_audio": False,
        "creation_time": "2024-06-01T12:00:00"
    })
    monkeypatch.setattr("src.server.queue_manager.extract_frames", lambda *args, **kwargs: [
        {"path": str(dummy_vid), "timecode": "00:00", "frame_index": 0, "timestamp_seconds": 0.0}
    ])

    analysis_res = VideoAnalysisResult(
        title="Silent Picnic Afternoon",
        summary="A lovely quiet afternoon picnic in the backyard garden.",
        events=[
            TimestampEvent(timecode="00:00", description="Family sits on picnic blanket", is_highlight=False),
        ],
        tags=["picnic"],
        people_or_subjects=[],
        animals_or_pets=[],
        objects=[],
        suggested_filename="silent_picnic"
    )

    class MockProvider:
        def describe_video(self, *args, **kwargs):
            return analysis_res

    monkeypatch.setattr("src.server.queue_manager.OllamaVisionProvider", lambda *args, **kwargs: MockProvider())

    task = TaskItem(file_path=str(dummy_vid), filename=dummy_vid.name)
    qm._process_single_task(task)

    assert task.status == "completed"

    txt_file = tmp_path / "silent_home_movie_2.mp4.txt"
    srt_file = tmp_path / "silent_home_movie_2.srt"

    assert txt_file.exists(), "Text sidecar should be created"
    assert not srt_file.exists(), "SRT sidecar should NOT be created when synthesize_visual_subtitles is False and there is no speech"


