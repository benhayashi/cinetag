import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.media.tagger import (
    apply_metadata_tags,
    apply_exiftool_tags,
    safe_copy_file,
    safe_replace_file,
    flush_orphaned_backups,
    MetadataIntegrityError,
)

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


def test_safe_copy_file_fallback_on_oserror(tmp_path):
    src = tmp_path / "source.txt"
    dst = tmp_path / "dest.txt"
    src.write_text("hello world")

    with patch("shutil.copy2", side_effect=OSError(95, "Operation not supported")) as mock_copy2, \
         patch("shutil.copyfile", wraps=safe_copy_file.__globals__["shutil"].copyfile) as mock_copyfile:
        safe_copy_file(src, dst)
        assert mock_copy2.called
        assert mock_copyfile.called
        assert dst.read_text() == "hello world"


def test_safe_replace_file_fallback_on_oserror(tmp_path):
    src = tmp_path / "temp.txt"
    dst = tmp_path / "target.txt"
    src.write_text("new content")
    dst.write_text("old content")

    with patch("os.replace", side_effect=OSError(95, "Operation not supported")) as mock_replace:
        safe_replace_file(src, dst)
        assert mock_replace.called
        assert not src.exists()
        assert dst.read_text() == "new content"


def test_apply_metadata_tags_flushes_backup_on_success(tmp_path):
    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"dummy_content" * 100)
    bak = tmp_path / "video.mp4.bak"

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("src.media.tagger.probe_video", return_value={"duration": 10.0}), \
         patch("src.media.tagger.apply_exiftool_tags"), \
         patch("subprocess.run") as mock_run:

        def fake_ffmpeg(cmd, **kwargs):
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"dummy_content" * 100)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        res = apply_metadata_tags(
            vid,
            {"title": "Flush Test"},
            create_backup=True,
            flush_backup=True,
            verify_integrity=False
        )

        assert res["status"] == "success"
        assert res["backup_flushed"] is True
        # The temporary .bak must be automatically unlinked upon verified success
        assert not bak.exists()


def test_apply_metadata_tags_retains_backup_when_flush_disabled(tmp_path):
    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"dummy_content" * 100)
    bak = tmp_path / "video.mp4.bak"

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("src.media.tagger.probe_video", return_value={"duration": 10.0}), \
         patch("src.media.tagger.apply_exiftool_tags"), \
         patch("subprocess.run") as mock_run:

        def fake_ffmpeg(cmd, **kwargs):
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"dummy_content" * 100)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        res = apply_metadata_tags(
            vid,
            {"title": "Retain Test"},
            create_backup=True,
            flush_backup=False,
            verify_integrity=False
        )

        assert res["status"] == "success"
        assert res["backup_flushed"] is False
        assert bak.exists()


def test_apply_metadata_tags_retains_backup_on_failure(tmp_path):
    vid = tmp_path / "video.mp4"
    vid.write_bytes(b"original_payload_bytes" * 50)
    bak = tmp_path / "video.mp4.bak"

    with patch("src.media.tagger.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("src.media.tagger.probe_video", side_effect=[
             {"duration": 10.0},  # Original probe
             {"duration": 1.0}    # New probe -> triggers MetadataIntegrityError duration mismatch
         ]), \
         patch("subprocess.run") as mock_run:

        def fake_ffmpeg(cmd, **kwargs):
            out_p = Path(cmd[-1])
            out_p.write_bytes(b"corrupted_stream" * 50)
            return MagicMock(returncode=0)

        mock_run.side_effect = fake_ffmpeg

        with pytest.raises(MetadataIntegrityError):
            apply_metadata_tags(
                vid,
                {"title": "Fail Test"},
                create_backup=True,
                flush_backup=True,
                verify_integrity=True
            )

        # Since integrity check failed BEFORE replace/flush, original file and backup safety are preserved
        assert vid.read_bytes() == b"original_payload_bytes" * 50


def test_flush_orphaned_backups_file_and_dir(tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"video")
    bak1 = tmp_path / "test.mp4.bak"
    bak1.write_bytes(b"bak1")
    bak2 = tmp_path / "test.mp4.bak1"
    bak2.write_bytes(b"bak2")
    other_bak = tmp_path / "other.mov.bak"
    other_bak.write_bytes(b"other")

    # Flush for single video file
    flushed = flush_orphaned_backups(video)
    assert flushed == 2
    assert not bak1.exists()
    assert not bak2.exists()
    assert other_bak.exists()

    # Flush directory
    dir_flushed = flush_orphaned_backups(tmp_path)
    assert dir_flushed == 1
    assert not other_bak.exists()



