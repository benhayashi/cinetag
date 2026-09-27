import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.media.tagger import apply_metadata_tags, apply_exiftool_tags

def test_apply_exiftool_tags(tmp_path):
    mp4_file = tmp_path / "sample.mp4"
    mp4_file.write_bytes(b"dummy")

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/exiftool"), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        res = apply_exiftool_tags(
            mp4_file,
            {
                "title": "My Title",
                "description": "My Description",
                "keywords": "dog, golden retriever, park"
            }
        )
        assert res is True
        args = mock_run.call_args[0][0]
        cmd_str = " ".join(args)
        assert "-Microsoft:Category=dog; golden retriever; park" in cmd_str
        assert "-ItemList:Keyword=dog; golden retriever; park" in cmd_str
        assert "-Title=My Title" in cmd_str

def test_apply_metadata_tags_invokes_exiftool(tmp_path):
    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"dummy_content" * 100)

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("src.media.tagger.probe_video", return_value={"duration": 10.0}), \
         patch("src.media.tagger.apply_exiftool_tags") as mock_exif, \
         patch("subprocess.run") as mock_run:
        
        def fake_ffmpeg(cmd, **kwargs):
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"dummy_content" * 100)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        res = apply_metadata_tags(
            vid,
            {"title": "Tagged Title", "keywords": "tag1; tag2"},
            create_backup=False,
            verify_integrity=False
        )

        assert res["status"] == "success"
        mock_exif.assert_called_once()

def test_apply_metadata_tags_detects_3gp_codecs(tmp_path):
    vid = tmp_path / "legacy.mp4"
    vid.write_bytes(b"dummy_content" * 100)

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("src.media.tagger.probe_video", return_value={
             "duration": 15.0,
             "video_codec": "h263",
             "audio_codec": "amr_nb",
             "tags": {"major_brand": "3gp5"}
         }), \
         patch("src.media.tagger.apply_exiftool_tags"), \
         patch("subprocess.run") as mock_run:

        def fake_ffmpeg(cmd, **kwargs):
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"dummy_content" * 100)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        res = apply_metadata_tags(
            vid,
            {"title": "Legacy 3GP Mobile Video"},
            create_backup=False,
            verify_integrity=False
        )

        assert res["status"] == "success"
        # Check that -f 3gp was automatically included in the FFmpeg command
        called_cmd = mock_run.call_args[0][0]
        assert "-f" in called_cmd
        assert "3gp" in called_cmd

def test_apply_metadata_tags_retries_with_3gp_on_codec_error(tmp_path):
    vid = tmp_path / "legacy2.mp4"
    vid.write_bytes(b"dummy_content" * 100)

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("src.media.tagger.probe_video", return_value={"duration": 10.0, "video_codec": "unknown"}), \
         patch("src.media.tagger.apply_exiftool_tags"), \
         patch("subprocess.run") as mock_run:

        calls = []
        def fake_ffmpeg(cmd, **kwargs):
            calls.append(list(cmd))
            if len(calls) == 1:
                # First run fails with typical ISO mp4 rejection of h263
                return MagicMock(
                    returncode=1,
                    stderr="[mp4 @ 0x123] Could not find tag for codec h263 in stream #0, codec not currently supported in container"
                )
            else:
                # Retry succeeds
                out_p = Path(cmd[-1])
                out_p.write_bytes(b"dummy_content" * 100)
                return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_ffmpeg

        res = apply_metadata_tags(
            vid,
            {"title": "Retry Test"},
            create_backup=False,
            verify_integrity=False
        )

        assert res["status"] == "success"
        assert len(calls) == 2
        assert "-f" not in calls[0]
        assert "-f" in calls[1]
        assert "3gp" in calls[1]

