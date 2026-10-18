import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.media.sony_xml import find_sony_xml_sidecar, parse_sony_xml, format_sony_context_prompt
from src.media.renamer import resolve_unique_rename_target, execute_rename, undo_last_rename
from src.media.probe import probe_video
from src.exporters.sidecars import write_txt_sidecar, write_info_json_sidecar
from src.exporters.nfo import write_nfo_sidecar
from src.ai.base import VideoAnalysisResult
from src.server.app import app
from src.server.api import find_existing_sidecars

SAMPLE_SONY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20"
                 xmlns:lib="urn:schemas-professionalDisc:lib:ver.2.00"
                 lastUpdate="2024-05-18T14:22:10-04:00">
    <TargetMaterial dci="urn:smpte:umid:060a2b340101010501010d4313000000"/>
    <CreationDate value="2024-05-18T14:22:10-04:00"/>
    <Device manufacturer="Sony" modelName="ILCE-7M4" serialNo="3018241"/>
    <RecordingMode type="normal" cacheRec="false"/>
    <VideoFormat>
        <VideoFrame videoCodec="AVC_3840_2160_HP@L51" captureFps="59.94p" formatFps="59.94p"/>
        <VideoLayout pixel="3840" numOfVerticalLine="2160" aspectRatio="16:9"/>
    </VideoFormat>
    <AudioFormat numOfChannel="2">
        <AudioRecPort port="1" audioCodec="LPCM_48000_16_2CH"/>
        <AudioRecPort port="2" audioCodec="LPCM_48000_16_2CH"/>
    </AudioFormat>
    <LensModel value="FE 24-70mm F2.8 GM II"/>
</NonRealTimeMeta>
"""

def test_parse_sony_xml(tmp_path):
    xml_file = tmp_path / "C0001M01.XML"
    xml_file.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    meta = parse_sony_xml(xml_file)
    assert meta["is_sony_nrtm"] is True
    assert meta["camera_make"] == "Sony"
    assert meta["camera_model"] == "ILCE-7M4"
    assert meta["camera_serial"] == "3018241"
    assert meta["creation_date"] == "2024-05-18T14:22:10-04:00"
    assert meta["capture_fps"] == "59.94p"
    assert meta["format_fps"] == "59.94p"
    assert meta["audio_channels"] == 2
    assert meta["lens_model"] == "FE 24-70mm F2.8 GM II"
    assert "ILCE-7M4" in meta["summary"]
    assert "4K UHD" in meta["summary"]

def test_find_sony_xml_sidecar(tmp_path):
    # Test standard Sony M01 naming
    video1 = tmp_path / "C0001.MP4"
    video1.write_bytes(b"video data")
    xml1 = tmp_path / "C0001M01.XML"
    xml1.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    found1 = find_sony_xml_sidecar(video1)
    assert found1 is not None
    assert found1.name == "C0001M01.XML"

    # Test lowercase naming
    video2 = tmp_path / "c0002.mp4"
    video2.write_bytes(b"video data")
    xml2 = tmp_path / "c0002m01.xml"
    xml2.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    found2 = find_sony_xml_sidecar(video2)
    assert found2 is not None
    assert found2.name == "c0002m01.xml"

    # Test exact stem match
    video3 = tmp_path / "C0003.MP4"
    video3.write_bytes(b"video data")
    xml3 = tmp_path / "C0003.XML"
    xml3.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    found3 = find_sony_xml_sidecar(video3)
    assert found3 is not None
    assert found3.name == "C0003.XML"

    # Test no sidecar
    video4 = tmp_path / "C0004.MP4"
    video4.write_bytes(b"video data")
    assert find_sony_xml_sidecar(video4) is None

def test_format_sony_context_prompt(tmp_path):
    xml_file = tmp_path / "C0001M01.XML"
    xml_file.write_text(SAMPLE_SONY_XML, encoding="utf-8")
    meta = parse_sony_xml(xml_file)

    prompt = format_sony_context_prompt(meta)
    assert "Sony ILCE-7M4" in prompt
    assert "2024-05-18T14:22:10-04:00" in prompt
    assert "59.94p" in prompt
    assert "FE 24-70mm F2.8 GM II" in prompt

def test_sony_xml_rename_and_undo(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    video = tmp_path / "C0001.MP4"
    video.write_bytes(b"video data")
    xml = tmp_path / "C0001M01.XML"
    xml.write_text(SAMPLE_SONY_XML, encoding="utf-8")
    txt = tmp_path / "C0001.txt"
    txt.write_text("existing description", encoding="utf-8")

    # Perform rename
    res = execute_rename(video, "2024-05-18_Beach_Walk.mp4")
    assert res["status"] == "success"

    new_video = Path(res["renamed_to"])
    assert new_video.exists()
    assert not video.exists()

    # Check sidecars renamed properly
    new_xml = tmp_path / "2024-05-18_Beach_WalkM01.XML"
    new_txt = tmp_path / "2024-05-18_Beach_Walk.txt"
    assert new_xml.exists()
    assert not xml.exists()
    assert new_txt.exists()
    assert not txt.exists()

    # Perform undo
    undo_res = undo_last_rename()
    assert undo_res is not None
    assert undo_res["restored_to"] == str(video)
    assert video.exists()
    assert xml.exists()
    assert txt.exists()
    assert not new_video.exists()
    assert not new_xml.exists()
    assert not new_txt.exists()

def test_sony_xml_collision_enumeration(tmp_path):
    # Setup existing target video and XML
    existing_video = tmp_path / "2024-05-18_Beach_Walk.mp4"
    existing_video.write_bytes(b"existing video")
    existing_xml = tmp_path / "2024-05-18_Beach_WalkM01.XML"
    existing_xml.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    # New video to rename
    video2 = tmp_path / "C0002.MP4"
    video2.write_bytes(b"new video")
    xml2 = tmp_path / "C0002M01.XML"
    xml2.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    target_path, sidecars = resolve_unique_rename_target(video2, "2024-05-18_Beach_Walk.mp4")
    assert target_path.name == "2024-05-18_Beach_Walk_01.mp4"

    # Ensure sidecars map to _01M01.XML
    xml_mapping = next((new_s for old_s, new_s in sidecars if old_s.name == "C0002M01.XML"), None)
    assert xml_mapping is not None
    assert xml_mapping.name == "2024-05-18_Beach_Walk_01M01.XML"

def test_probe_video_with_sony_xml(tmp_path):
    video = tmp_path / "C0001.MP4"
    video.write_bytes(b"dummy video data")
    xml = tmp_path / "C0001M01.XML"
    xml.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    info = probe_video(video)
    assert info["has_sony_xml"] is True
    assert info["camera_make"] == "Sony"
    assert info["camera_model"] == "ILCE-7M4"
    assert info["capture_fps"] == "59.94p"
    assert info["creation_time"] == "2024-05-18T14:22:10-04:00"

def test_exporters_with_sony_metadata(tmp_path):
    video = tmp_path / "C0001.MP4"
    video.write_bytes(b"dummy video data")

    analysis = VideoAnalysisResult(
        title="Family Beach Walk",
        summary="A family walking down the beach at golden hour.",
        events=[],
        tags=["beach", "sunset"],
        people_or_subjects=["Dad", "Daughter"],
        animals_or_pets=[],
        objects=["Sony ILCE-7M4"],
        suggested_filename="family_beach_walk"
    )

    meta = {
        "duration": 45.2,
        "width": 3840,
        "height": 2160,
        "camera_make": "Sony",
        "camera_model": "ILCE-7M4",
        "capture_fps": "59.94p",
        "creation_time": "2024-05-18T14:22:10-04:00",
        "video_codec": "h264"
    }

    txt_path = write_txt_sidecar(video, analysis, meta)
    txt_content = txt_path.read_text(encoding="utf-8")
    assert "camera: Sony ILCE-7M4" in txt_content
    assert "fps: 59.94p" in txt_content

    nfo_path = write_nfo_sidecar(video, analysis, meta)
    nfo_content = nfo_path.read_text(encoding="utf-8")
    assert "<tag>Camera: Sony ILCE-7M4</tag>" in nfo_content

def test_api_results_with_sony_xml(tmp_path):
    video = tmp_path / "C0001.MP4"
    video.write_bytes(b"dummy video data")
    xml = tmp_path / "C0001M01.XML"
    xml.write_text(SAMPLE_SONY_XML, encoding="utf-8")

    # Test find_existing_sidecars
    existing = find_existing_sidecars(video)
    assert ".xml" in existing

    # Test /api/results endpoint
    client = TestClient(app)
    res = client.get(f"/api/results?file_path={str(video.resolve())}")
    assert res.status_code == 200
    data = res.json()
    assert data["has_sony_xml"] is True
    assert data["camera_model"] == "ILCE-7M4"
    assert data["creation_time"] == "2024-05-18T14:22:10-04:00"
    assert data["sidecars"]["xml"]["exists"] is True
    assert "C0001M01.XML" in data["sidecars"]["xml"]["filename"]
    assert "/api/download?file_path=" in data["sidecars"]["xml"]["url"]
