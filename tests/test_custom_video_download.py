import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.server.app import app
from src.media.tagger import create_custom_download_video

client = TestClient(app)

def test_create_custom_download_video_mkv_subtitles(tmp_path):
    """
    Verify MKV container supports embedding soft subtitles (-c:s srt) and metadata tags.
    """
    dummy_source = tmp_path / "home_movie.mkv"
    dummy_source.write_bytes(b"dummy_mkv")

    dummy_srt = tmp_path / "home_movie.srt"
    dummy_srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nHello world!\n", encoding="utf-8")

    out_file = tmp_path / "out_home_movie.mkv"

    recorded_cmds = []

    with patch("src.media.tagger.find_binary") as mock_bin, \
         patch("subprocess.run") as mock_sub:

        def fake_find(bin_name, custom_path=None):
            return f"/usr/bin/{bin_name}"

        mock_bin.side_effect = fake_find

        def fake_run(cmd, **kwargs):
            recorded_cmds.append(cmd)
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"tagged_subtitled_mkv")
            return MagicMock(returncode=0)

        mock_sub.side_effect = fake_run

        meta = {
            "title": "Summer Beach Party",
            "description": "Family fun at the beach",
            "keywords": "beach; summer; volleyball"
        }

        result_path = create_custom_download_video(
            source_video_path=dummy_source,
            output_path=out_file,
            metadata_tags=meta,
            srt_path=dummy_srt,
            embed_tags=True,
            embed_subtitles=True,
            target_format="mkv"
        )

        assert result_path == out_file
        # Check ffmpeg command args:
        ffmpeg_cmd = recorded_cmds[0]
        cmd_str = " ".join(ffmpeg_cmd)
        assert "-c:s srt" in cmd_str
        assert "Summer Beach Party" in cmd_str
        assert "beach; summer; volleyball" in cmd_str


def test_create_custom_download_video_mp4_skips_soft_subtitles(tmp_path):
    """
    Verify MP4 container does not attempt to embed soft srt subtitles to prevent corruption,
    and applies extended OS metadata via ExifTool.
    """
    dummy_source = tmp_path / "clip.mp4"
    dummy_source.write_bytes(b"dummy_mp4")

    dummy_srt = tmp_path / "clip.srt"
    dummy_srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nHello!\n", encoding="utf-8")

    out_file = tmp_path / "out_clip.mp4"

    recorded_cmds = []

    with patch("src.media.tagger.find_binary") as mock_bin, \
         patch("subprocess.run") as mock_sub:

        def fake_find(bin_name, custom_path=None):
            return f"/usr/bin/{bin_name}"

        mock_bin.side_effect = fake_find

        def fake_run(cmd, **kwargs):
            recorded_cmds.append(cmd)
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"tagged_mp4")
            return MagicMock(returncode=0)

        mock_sub.side_effect = fake_run

        meta = {"title": "Backyard Games", "description": "Fun", "keywords": "games; lawn"}

        create_custom_download_video(
            source_video_path=dummy_source,
            output_path=out_file,
            metadata_tags=meta,
            srt_path=dummy_srt,
            embed_tags=True,
            embed_subtitles=True,
            target_format="original"  # Stays MP4
        )

        # First call is FFmpeg stream copy
        ffmpeg_cmd = recorded_cmds[0]
        cmd_str = " ".join(ffmpeg_cmd)
        assert "-c:s srt" not in cmd_str
        assert "-c copy" in cmd_str
        assert "Backyard Games" in cmd_str

        # Second call is ExifTool for Windows/macOS tags
        assert len(recorded_cmds) >= 2
        exif_cmd_str = " ".join(recorded_cmds[1])
        assert "-Microsoft:Category=games; lawn" in exif_cmd_str
        assert "-ItemList:Keyword=games; lawn" in exif_cmd_str


def test_update_video_objects_endpoint(tmp_path, monkeypatch):
    """
    Test updating object tags via /api/results/update-objects endpoint.
    """
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    
    vid_file = tmp_path / "tennis.mp4"
    vid_file.write_bytes(b"dummy")

    sidecar_json = tmp_path / "tennis.info.json"
    sidecar_json.write_text(json.dumps({
        "analysis": {
            "title": "Tennis Match",
            "tags": ["sports"],
            "objects": ["tennis ball"]
        }
    }), encoding="utf-8")

    sidecar_xmp = tmp_path / "tennis.xmp"
    sidecar_xmp.write_text("<x:xmpmeta><rdf:Bag><rdf:li>Object:tennis ball</rdf:li></rdf:Bag></x:xmpmeta>", encoding="utf-8")

    payload = {
        "file_path": str(vid_file),
        "objects": ["tennis racket", "sports visor", "lawn chair"]
    }

    res = client.post("/api/results/update-objects", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert len(data["objects"]) == 3

    # Check that .info.json has new objects
    updated_json = json.loads(sidecar_json.read_text(encoding="utf-8"))
    assert "tennis racket" in updated_json["analysis"]["objects"]
    assert "tennis racket" in updated_json["analysis"]["tags"]

    # Check that .xmp has new Object: entries
    updated_xmp = sidecar_xmp.read_text(encoding="utf-8")
    assert "<rdf:li>Object:tennis racket</rdf:li>" in updated_xmp


def test_custom_download_extracts_tags_without_error(tmp_path):
    """
    Ensure POST /api/download/custom-video extracts all tags, people, and objects
    from .info.json without NameError and passes metadata_tags to FFmpeg.
    """
    vid_file = tmp_path / "#test_video.webm"
    vid_file.write_bytes(b"webm_dummy")

    info_json = tmp_path / "#test_video.info.json"
    info_json.write_text(json.dumps({
        "analysis": {
            "title": "Cooking Video",
            "summary": "Making delicious noodles",
            "tags": ["cooking", "noodles"],
            "people_or_subjects": ["Alice", "Bob"],
            "objects": ["pot", "bowl"],
            "animals_or_pets": ["cat"],
            "audio_transcript": "We are making noodles today."
        },
        "file": {
            "metadata": {
                "creation_time": "2026-09-27T15:00:00Z"
            }
        }
    }), encoding="utf-8")

    payload = {
        "file_path": str(vid_file),
        "output_filename": "cooking.webm",
        "embed_tags": True,
        "embed_subtitles": False,
        "target_format": "original"
    }

    with patch("src.media.tagger.create_custom_download_video") as mock_tagger:
        mock_tagger.side_effect = lambda **kwargs: kwargs["output_path"].write_bytes(b"done")

        res = client.post("/api/download/custom-video", json=payload)
        assert res.status_code == 200

        # Verify metadata_tags passed to create_custom_download_video
        call_kwargs = mock_tagger.call_args[1]
        meta = call_kwargs["metadata_tags"]
        assert meta["title"] == "Cooking Video"
        assert meta["description"] == "Making delicious noodles"
        assert "cooking" in meta["keywords"]
        assert "Person: Alice" in meta["keywords"]
        assert "pot" in meta["keywords"]
        assert "cat" in meta["keywords"]


def test_api_results_encodes_special_chars_in_urls(tmp_path):
    """
    Ensure /api/results properly URL-encodes file paths with '#' and other special chars
    so client browsers don't truncate download links.
    """
    vid_file = tmp_path / "#wedding#celebration.webm"
    vid_file.write_bytes(b"webm_data")

    srt_file = tmp_path / "#wedding#celebration.srt"
    srt_file.write_text("1\n00:00:00,000 --> 00:00:02,000\nCongratulations!\n", encoding="utf-8")

    info_file = tmp_path / "#wedding#celebration.info.json"
    info_file.write_text(json.dumps({
        "analysis": {
            "title": "Wedding Celebration",
            "summary": "Lovely wedding ceremony",
            "tags": ["wedding"]
        }
    }), encoding="utf-8")

    import urllib.parse
    res = client.get(f"/api/results?file_path={urllib.parse.quote(str(vid_file))}")
    assert res.status_code == 200
    data = res.json()

    # Verify that URLs do not contain unencoded '#' characters in the query parameter
    srt_url = data["sidecars"]["srt"]["url"]
    assert "%23" in srt_url
    assert "/api/download?file_path=" in srt_url

    video_url = data["video"]["url"]
    assert "%23" in video_url


def test_execute_rename_renames_all_stem_sidecars(tmp_path):
    """
    Ensure execute_rename renames .info.json, .srt, .xmp, and .nfo along with the video.
    """
    from src.media.renamer import execute_rename

    vid = tmp_path / "vacation.webm"
    vid.write_bytes(b"video")

    info = tmp_path / "vacation.info.json"
    info.write_text("{}", encoding="utf-8")

    srt = tmp_path / "vacation.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")

    txt = tmp_path / "vacation.webm.txt"
    txt.write_text("description", encoding="utf-8")

    res = execute_rename(vid, "20260927_vacation.webm")
    assert res["status"] == "success"

    # Verify all sidecars renamed
    assert not vid.exists()
    assert (tmp_path / "20260927_vacation.webm").exists()

    assert not info.exists()
    assert (tmp_path / "20260927_vacation.info.json").exists()

    assert not srt.exists()
    assert (tmp_path / "20260927_vacation.srt").exists()

    assert not txt.exists()
    assert (tmp_path / "20260927_vacation.webm.txt").exists()

