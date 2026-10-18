import pytest
from pathlib import Path
import json
from src.media.location import (
    resolve_location,
    reverse_geocode,
    format_iso6709,
    parse_iso6709,
    _haversine_distance_km,
)
from src.ai.base import VideoAnalysisResult, TimestampEvent
from src.core.config import AppConfig
from src.exporters.sidecars import write_info_json_sidecar, write_txt_sidecar, write_xmp_sidecar
from src.exporters.nfo import write_nfo_sidecar
from fastapi.testclient import TestClient
from src.server.app import app

client = TestClient(app)

def test_format_and_parse_iso6709():
    # Test San Francisco
    lat, lon = 37.7749, -122.4194
    iso = format_iso6709(lat, lon)
    assert iso.startswith("+37.7749-122.4194")
    assert iso.endswith("/")

    parsed = parse_iso6709(iso)
    assert parsed is not None
    p_lat, p_lon = parsed
    assert abs(p_lat - lat) < 0.001
    assert abs(p_lon - lon) < 0.001

    # Test negative lat, positive lon (Sydney)
    s_lat, s_lon = -33.8688, 151.2093
    s_iso = format_iso6709(s_lat, s_lon)
    assert s_iso.startswith("-33.8688+151.2093")
    p_s_lat, p_s_lon = parse_iso6709(s_iso)
    assert abs(p_s_lat - s_lat) < 0.001
    assert abs(p_s_lon - s_lon) < 0.001

    # Invalid string
    assert parse_iso6709("invalid_location") is None

def test_resolve_location_offline():
    # Direct city lookup
    tokyo = resolve_location("Tokyo", allow_online=False)
    assert tokyo is not None
    assert tokyo["city"] == "Tokyo"
    assert tokyo["country"] == "Japan"
    assert abs(tokyo["latitude"] - 35.6762) < 0.1
    assert abs(tokyo["longitude"] - 139.6503) < 0.1

    # Landmark lookup
    eiffel = resolve_location("Eiffel Tower", allow_online=False)
    assert eiffel is not None
    assert "Paris" in eiffel["city"] or eiffel["country"] == "France"
    assert abs(eiffel["latitude"] - 48.8584) < 0.1

    # Raw coordinate string
    coords = resolve_location("37.7749, -122.4194", allow_online=False)
    assert coords is not None
    assert abs(coords["latitude"] - 37.7749) < 0.001
    assert abs(coords["longitude"] - (-122.4194)) < 0.001

    # Unknown query offline
    unknown = resolve_location("NonExistentAtlantisXYZ999", allow_online=False)
    assert unknown is None

def test_reverse_geocode_offline():
    # London coordinates
    lon_lat = 51.5074, -0.1278
    res = reverse_geocode(lon_lat[0], lon_lat[1], allow_online=False)
    assert res is not None
    assert res["city"] == "London"
    assert res["country"] == "United Kingdom"

def test_sidecars_export_location(tmp_path: Path):
    dummy_video = tmp_path / "vacation_clip.mp4"
    dummy_video.write_bytes(b"dummy video data")

    loc = {
        "city": "Rome",
        "state": "Lazio",
        "country": "Italy",
        "latitude": 41.9028,
        "longitude": 12.4964
    }

    result = VideoAnalysisResult(
        title="Colosseum Tour",
        summary="Walking around the ancient Colosseum in Rome.",
        tags=["rome", "travel", "colosseum"],
        detected_location=loc
    )
    cfg = AppConfig()

    # 1. Info JSON
    json_path = write_info_json_sidecar(dummy_video, result, video_meta={"location": loc})
    assert json_path.exists()
    with open(json_path, "r", encoding="utf-8") as jf:
        data = json.load(jf)
        assert data["analysis"]["detected_location"]["city"] == "Rome"
        assert data["file"]["metadata"]["location"]["country"] == "Italy"
        assert abs(data["file"]["metadata"]["location"]["latitude"] - 41.9028) < 0.001

    # 2. TXT sidecar
    txt_path = write_txt_sidecar(dummy_video, result, video_meta={"location": loc})
    assert txt_path.exists()
    txt_content = txt_path.read_text(encoding="utf-8")
    assert "location: Rome, Lazio, Italy" in txt_content
    assert "41.9028" in txt_content

    # 3. XMP sidecar
    xmp_path = write_xmp_sidecar(dummy_video, result, video_meta={"location": loc})
    assert xmp_path.exists()
    xmp_content = xmp_path.read_text(encoding="utf-8")
    assert "<photoshop:City>Rome</photoshop:City>" in xmp_content
    assert "<photoshop:Country>Italy</photoshop:Country>" in xmp_content
    assert "<exif:GPSLatitude>41.9028" in xmp_content
    assert "<exif:GPSLongitude>12.4964" in xmp_content

    # 4. NFO sidecar
    nfo_path = write_nfo_sidecar(dummy_video, result, video_meta={"location": loc})
    assert nfo_path.exists()
    nfo_content = nfo_path.read_text(encoding="utf-8")
    assert "<city>Rome</city>" in nfo_content
    assert "<country>Italy</country>" in nfo_content
    assert "<tag>Location: Rome, Lazio, Italy</tag>" in nfo_content

def test_api_location_lookup():
    # POST /api/location/lookup
    res = client.post("/api/location/lookup", json={"query": "Seattle"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["location"]["city"] == "Seattle"
    assert "Washington" in data["location"]["state"]

    # Unknown
    res2 = client.post("/api/location/lookup", json={"query": "ZZZNonexistentCityXYZ"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "not_found"
    assert data2["location"] is None

def test_api_manual_review_location(tmp_path: Path):
    dummy_video = tmp_path / "test_vid.mp4"
    dummy_video.write_bytes(b"dummy")

    # Save manual review with location
    payload = {
        "file_path": str(dummy_video),
        "title": "Kyoto Temple Visit",
        "summary": "Exploring temples in Kyoto.",
        "tags": ["temple", "japan"],
        "location": {
            "city": "Kyoto",
            "country": "Japan",
            "latitude": 35.0116,
            "longitude": 135.7681
        }
    }
    res = client.post("/api/review/save-manual", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["analysis"]["location"]["city"] == "Kyoto"

    # Verify sidecar was created and contains location
    info_json = tmp_path / "test_vid.info.json"
    assert info_json.exists()
    with open(info_json, "r") as jf:
        saved = json.load(jf)
        assert saved["analysis"]["detected_location"]["city"] == "Kyoto"
        assert abs(saved["analysis"]["detected_location"]["latitude"] - 35.0116) < 0.001

    # Now call GET /api/results
    res_get = client.get(f"/api/results?file_path={str(dummy_video)}")
    assert res_get.status_code == 200
    get_data = res_get.json()
    assert get_data["location"] is not None
    assert get_data["location"]["city"] == "Kyoto"
    assert abs(get_data["location"]["latitude"] - 35.0116) < 0.001

def test_sony_xml_gps_probe(tmp_path: Path):
    from src.media.sony_xml import parse_sony_xml
    from src.media.probe import probe_video
    import unittest.mock as mock

    xml_p = tmp_path / "C0012M01.XML"
    xml_p.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20">
    <CreationDate value="2024-06-15T10:00:00Z"/>
    <Device manufacturer="Sony" modelName="ILCE-7M4"/>
    <ExifGPS latitude="35.6762" longitude="139.6503"/>
</NonRealTimeMeta>
""", encoding="utf-8")

    meta = parse_sony_xml(xml_p)
    assert meta["gps"] == {"latitude": "35.6762", "longitude": "139.6503"}

    vid_p = tmp_path / "C0012.MP4"
    vid_p.write_bytes(b"dummy")

    with mock.patch("subprocess.run") as mock_sub:
        mock_sub.return_value = mock.Mock(
            stdout=json.dumps({
                "format": {
                    "duration": "10.0",
                    "tags": {}
                },
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}]
            })
        )
        info = probe_video(vid_p)
        assert info["has_gps"] is True
        assert abs(info["gps_latitude"] - 35.6762) < 0.001
        assert abs(info["gps_longitude"] - 139.6503) < 0.001
        assert info["location"] is not None
        assert info["location"]["city"] == "Tokyo"

def test_probe_quicktime_iso6709(tmp_path: Path):
    from src.media.probe import probe_video
    import unittest.mock as mock

    vid_p = tmp_path / "iphone_video.mov"
    vid_p.write_bytes(b"dummy")

    with mock.patch("subprocess.run") as mock_sub:
        mock_sub.return_value = mock.Mock(
            stdout=json.dumps({
                "format": {
                    "duration": "15.0",
                    "tags": {
                        "location": "+48.8566+002.3522/",
                        "location-eng": "+48.8566+002.3522/"
                    }
                },
                "streams": [{"codec_type": "video", "width": 1920, "height": 1080}]
            })
        )
        info = probe_video(vid_p)
        assert info["has_gps"] is True
        assert abs(info["gps_latitude"] - 48.8566) < 0.001
        assert abs(info["gps_longitude"] - 2.3522) < 0.001
        assert info["location"] is not None
        assert info["location"]["city"] == "Paris"
        assert info["location"]["country"] == "France"

