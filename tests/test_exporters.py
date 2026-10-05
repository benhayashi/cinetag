import json
from pathlib import Path
from src.ai.base import VideoAnalysisResult, TimestampEvent
from src.exporters.sidecars import write_txt_sidecar, write_info_json_sidecar, write_xmp_sidecar
from src.exporters.nle import write_edl_markers

def test_exporters(tmp_path):
    video = tmp_path / "sample.mp4"
    video.write_text("fake video content")

    analysis = VideoAnalysisResult(
        title="Birthday Party",
        summary="Children enjoying cake and balloons outdoors.",
        events=[
            TimestampEvent(timecode="00:10", description="Cake brought out", is_highlight=True),
            TimestampEvent(timecode="00:45", description="Blowing candles", is_highlight=False)
        ],
        tags=["birthday", "family", "party"],
        people_or_subjects=["Alice", "Bob"],
        provider_name="ollama",
        model_name="llama3.2-vision"
    )

    # 1. Text sidecar
    txt_file = write_txt_sidecar(video, analysis)
    assert txt_file.exists()
    content = txt_file.read_text(encoding="utf-8")
    assert "Birthday Party" in content
    assert "★ 00:10" in content
    assert "Tags: birthday, family, party" in content

    # 2. JSON sidecar
    json_file = write_info_json_sidecar(video, analysis)
    assert json_file.exists()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    assert data["analysis"]["title"] == "Birthday Party"
    assert len(data["analysis"]["events"]) == 2

    # 3. XMP sidecar
    xmp_file = write_xmp_sidecar(video, analysis)
    assert xmp_file.exists()
    xmp_text = xmp_file.read_text(encoding="utf-8")
    assert "<dc:title>" in xmp_text
    assert "<rdf:li>birthday</rdf:li>" in xmp_text

    # 4. EDL Markers
    edl_file = write_edl_markers(video, analysis.events)
    assert edl_file.exists()
    edl_text = edl_file.read_text(encoding="utf-8")
    assert "ResolveColorGreen" in edl_text  # Highlighted marker
    assert "Cake brought out" in edl_text

def test_sidecar_conflict_resolution(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_text("fake video content")

    analysis = VideoAnalysisResult(
        title="First Run",
        summary="First analysis summary.",
        events=[],
        tags=["nature"],
        people_or_subjects=[],
        provider_name="mock",
        model_name="mock"
    )

    # First write creates normal files
    txt1 = write_txt_sidecar(video, analysis, conflict_mode="overwrite")
    assert txt1.name == "clip.txt"
    json1 = write_info_json_sidecar(video, analysis, conflict_mode="overwrite")
    assert json1.name == "clip.info.json"

    # Second write with overwrite replaces existing
    analysis.title = "Overwritten Run"
    txt2 = write_txt_sidecar(video, analysis, conflict_mode="overwrite")
    assert txt2.name == "clip.txt"
    assert "Overwritten Run" in txt2.read_text(encoding="utf-8")

    # Third write with enumerate creates _01
    analysis.title = "Enumerated Run 1"
    txt3 = write_txt_sidecar(video, analysis, conflict_mode="enumerate")
    assert txt3.name == "clip_01.txt"
    assert txt3.exists()

    json3 = write_info_json_sidecar(video, analysis, conflict_mode="enumerate")
    assert json3.name == "clip_01.info.json"
    assert json3.exists()

    # Fourth write with enumerate creates _02
    json4 = write_info_json_sidecar(video, analysis, conflict_mode="enumerate")
    assert json4.name == "clip_02.info.json"
    assert json4.exists()
