from pathlib import Path
import xml.etree.ElementTree as ET

from src.ai.base import VideoAnalysisResult, TimestampEvent
from src.exporters.nfo import write_nfo_sidecar

def test_nfo_exporter(tmp_path):
    vid = tmp_path / "home_movie.mp4"
    vid.write_bytes(b"dummy")

    result = VideoAnalysisResult(
        title="Kids Playing in Snow",
        summary="A fun winter afternoon building a snowman and sledding down the hill.",
        events=[
            TimestampEvent(timecode="00:00", description="Building snowman", is_highlight=True),
            TimestampEvent(timecode="00:15", description="Sledding down hill", is_highlight=False),
        ],
        tags=["winter", "snow", "kids", "sledding"],
        people_or_subjects=["Tommy", "Emma"],
        suggested_filename="kids_playing_snow"
    )

    meta = {
        "duration": 45.2,
        "width": 1920,
        "height": 1080,
        "video_codec": "h264",
        "audio_codec": "aac",
        "has_audio": True,
        "creation_time": "2023-01-15T14:30:00.000000Z"
    }

    nfo_path = write_nfo_sidecar(vid, result, meta)
    assert nfo_path.exists()
    assert nfo_path.name == "home_movie.nfo"

    # Parse and validate XML
    tree = ET.parse(nfo_path)
    root = tree.getroot()
    assert root.tag == "movie"

    assert root.find("title").text == "Kids Playing in Snow"
    assert root.find("originaltitle").text == "home_movie.mp4"
    assert "snowman" in root.find("plot").text
    assert root.find("premiered").text == "2023-01-15"
    assert root.find("year").text == "2023"

    tags = [t.text for t in root.findall("tag")]
    assert "snow" in tags
    assert "sledding" in tags

    actors = [a.find("name").text for a in root.findall("actor")]
    assert "Tommy" in actors
    assert "Emma" in actors

    streamdetails = root.find("fileinfo").find("streamdetails")
    assert streamdetails.find("video").find("codec").text == "h264"
    assert streamdetails.find("audio").find("codec").text == "aac"
