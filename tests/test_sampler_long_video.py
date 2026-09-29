import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.media.sampler import extract_frames

def test_long_video_interval_sampling_decimation(tmp_path):
    """
    Simulate a 2-hour (7200s) video with 60s sampling interval.
    Ensure smart decimation caps at max_frames (30) while spanning start to finish.
    """
    dummy_video = tmp_path / "long_vacation.mp4"
    dummy_video.write_bytes(b"dummy")

    mock_probe = {"duration": 7200.0, "width": 1920, "height": 1080}
    
    with patch("src.media.sampler.probe_video", return_value=mock_probe), \
         patch("src.media.sampler.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_sub:
        
        # Mock subprocess creating dummy frame file
        def fake_ffmpeg(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake_frame_data")
            return MagicMock(returncode=0)

        mock_sub.side_effect = fake_ffmpeg

        frames = extract_frames(
            dummy_video,
            interval_seconds=60,
            max_frames=30,
            strategy="interval"
        )

        assert len(frames) <= 30
        assert len(frames) == 30
        # First frame should be near start (0.0s)
        assert frames[0]["timestamp_seconds"] == 0.0
        # Last frame should be near the end of 7200s
        assert frames[-1]["timestamp_seconds"] > 6500.0

def test_long_video_key_moments_sampling(tmp_path):
    """
    Simulate milestone key moments across a 1-hour video.
    """
    dummy_video = tmp_path / "key_moments_event.mp4"
    dummy_video.write_bytes(b"dummy")

    mock_probe = {"duration": 3600.0, "width": 1920, "height": 1080}

    with patch("src.media.sampler.probe_video", return_value=mock_probe), \
         patch("src.media.sampler.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_sub:
        
        def fake_ffmpeg(cmd, **kwargs):
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_bytes(b"fake_frame_data")
            return MagicMock(returncode=0)

        mock_sub.side_effect = fake_ffmpeg

        frames = extract_frames(
            dummy_video,
            max_frames=15,
            strategy="key_moments",
            key_moments_count=10
        )

        assert len(frames) == 10
        assert frames[0]["timestamp_seconds"] == 0.0
        assert frames[-1]["timestamp_seconds"] > 3000.0


def test_flv_video_fallback_frame_extraction(tmp_path):
    """
    Ensure FLV videos that fail input seeking (-ss before -i) automatically
    recover via output seeking (-i before -ss).
    """
    flv_video = tmp_path / "legacy.flv"
    flv_video.write_bytes(b"dummy_flv")

    mock_probe = {"duration": 12.0, "width": 640, "height": 480}

    with patch("src.media.sampler.probe_video", return_value=mock_probe), \
         patch("src.media.sampler.find_binary", return_value="/usr/bin/ffmpeg"), \
         patch("subprocess.run") as mock_sub:

        attempts = []

        def fake_ffmpeg(cmd, **kwargs):
            attempts.append(list(cmd))
            out_file = Path(cmd[-1])
            out_file.parent.mkdir(parents=True, exist_ok=True)
            # If -ss is before -i (input seeking), simulate FLV seek failure by not writing file
            if cmd.index("-ss") < cmd.index("-i"):
                return MagicMock(returncode=0)
            # If -i is before -ss (output seeking), simulate success
            out_file.write_bytes(b"flv_frame_data")
            return MagicMock(returncode=0)

        mock_sub.side_effect = fake_ffmpeg

        frames = extract_frames(
            flv_video,
            interval_seconds=5,
            max_frames=2,
            strategy="interval"
        )

        assert len(frames) > 0
        # Check that fallback commands with -i before -ss were executed
        assert any(cmd.index("-i") < cmd.index("-ss") for cmd in attempts)

