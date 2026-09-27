from pathlib import Path
from src.core.privacy import get_storage_stats, clear_cache, clear_history

def test_privacy_clear_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.core.paths import get_cache_dir, get_history_path

    cache = get_cache_dir()
    dummy_frame = cache / "test_frame.jpg"
    dummy_frame.write_text("fake image data")

    assert dummy_frame.exists()
    freed = clear_cache()
    assert freed > 0
    assert not dummy_frame.exists()

def test_privacy_clear_history(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.core.paths import get_history_path

    hist = get_history_path()
    dummy_log = hist / "renames.json"
    dummy_log.write_text("[{'test': 1}]")

    assert dummy_log.exists()
    freed = clear_history()
    assert freed > 0
    assert not dummy_log.exists()

def test_cleanup_video_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.core.paths import get_cache_dir
    from src.core.privacy import cleanup_video_cache

    vid = tmp_path / "sample.mp4"
    vid.write_bytes(b"dummy video")

    cache_dir = get_cache_dir()
    video_hash = f"{vid.stem}_{int(vid.stat().st_mtime)}"
    frame_dir = cache_dir / "frames" / video_hash
    frame_dir.mkdir(parents=True, exist_ok=True)
    (frame_dir / "frame_0001.jpg").write_text("frame data")

    audio_file = cache_dir / "audio" / f"{video_hash}.wav"
    audio_file.parent.mkdir(parents=True, exist_ok=True)
    audio_file.write_text("audio data")

    assert frame_dir.exists()
    assert audio_file.exists()

    freed = cleanup_video_cache(vid)
    assert freed > 0
    assert not frame_dir.exists()
    assert not audio_file.exists()

def test_purge_expired_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    import os
    import time
    from src.core.paths import get_cache_dir
    from src.core.privacy import purge_expired_cache

    cache_dir = get_cache_dir()
    audio_dir = cache_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    old_audio = audio_dir / "old.wav"
    old_audio.write_text("old sound")

    # Set mtime to 2 days ago
    old_time = time.time() - (2 * 86400)
    os.utime(old_audio, (old_time, old_time))

    freed = purge_expired_cache("1_day")
    assert freed > 0
    assert not old_audio.exists()
