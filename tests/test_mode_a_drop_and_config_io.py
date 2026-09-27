import io
import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from src.server.app import app
from src.core.config import AppConfig, load_config, save_config
from src.server.queue_manager import QueueManager, TaskItem
from src.ai.base import VideoAnalysisResult

client = TestClient(app)

def test_resolve_local_paths_file_uri(tmp_path):
    video_file = tmp_path / "clip_001.mp4"
    video_file.write_bytes(b"dummy mp4 content")

    file_uri = f"file://{video_file.resolve()}"
    res = client.post("/api/files/resolve-local", json={"uris": [file_uri]})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["count"] == 1
    assert data["resolved_paths"] == [str(video_file.resolve())]

def test_resolve_local_paths_directory(tmp_path):
    sub = tmp_path / "subfolder"
    sub.mkdir()
    vid1 = sub / "v1.mkv"
    vid1.write_bytes(b"mock video 1")
    vid2 = sub / "v2.webm"
    vid2.write_bytes(b"mock video 2")
    txt = sub / "notes.txt"
    txt.write_text("not a video")

    res = client.post("/api/files/resolve-local", json={"uris": [str(sub)]})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["count"] == 2
    assert str(vid1.resolve()) in data["resolved_paths"]
    assert str(vid2.resolve()) in data["resolved_paths"]
    assert str(txt.resolve()) not in data["resolved_paths"]

def test_resolve_local_paths_current_folder_fallback(tmp_path):
    vid = tmp_path / "dropped_file.mp4"
    vid.write_bytes(b"mock video")

    res = client.post("/api/files/resolve-local", json={
        "filenames": ["dropped_file.mp4"],
        "current_folder": str(tmp_path)
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["count"] == 1
    assert data["resolved_paths"] == [str(vid.resolve())]

def test_config_export_and_import(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    # 1. Update config with distinct settings
    cfg = load_config()
    cfg.auto_rename = True
    cfg.rename_scheme = "compact_zulu_title"
    cfg.max_title_length = 42
    save_config(cfg)

    # 2. Export config
    export_res = client.get("/api/config/export")
    assert export_res.status_code == 200
    export_data = export_res.json()
    assert "version" in export_data
    assert "exported_at" in export_data
    assert "config" in export_data
    assert export_data["config"]["auto_rename"] is True
    assert export_data["config"]["rename_scheme"] == "compact_zulu_title"
    assert export_data["config"]["max_title_length"] == 42

    # 3. Change current config to something else
    cfg.auto_rename = False
    cfg.max_title_length = 99
    save_config(cfg)
    assert load_config().max_title_length == 99

    # 4. Import the exported config back via multipart file upload
    file_bytes = json.dumps(export_data).encode("utf-8")
    import_res = client.post(
        "/api/config/import",
        files={"file": ("exported_config.json", file_bytes, "application/json")}
    )
    assert import_res.status_code == 200
    import_result = import_res.json()
    assert import_result["status"] == "ok"
    assert import_result["config"]["max_title_length"] == 42
    assert import_result["config"]["auto_rename"] is True

    # Verify loaded config matches imported
    reloaded = load_config()
    assert reloaded.max_title_length == 42
    assert reloaded.auto_rename is True

def test_auto_rename_updates_task_state(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    orig_file = tmp_path / "original_clip.mp4"
    orig_file.write_bytes(b"dummy video data")

    qm = QueueManager()

    task = TaskItem(
        id="task_test_rename",
        file_path=str(orig_file),
        filename=orig_file.name
    )

    analysis = VideoAnalysisResult(
        title="Birthday Party",
        summary="A fun party with cake",
        tags=["party", "fun"],
        people_or_subjects=["Alice"],
        events=[]
    )

    cfg = load_config()
    cfg.auto_rename = True
    cfg.transcribe_audio = False
    cfg.face_recognition_enabled = False
    save_config(cfg)

    def fake_execute_rename(path, new_name):
        new_path = path.parent / new_name
        path.rename(new_path)
        return {"status": "success", "renamed_to": str(new_path), "original": str(path)}

    monkeypatch.setattr("src.server.queue_manager.probe_video", lambda p, **kwargs: {"duration": 10.0, "creation_time": "2024-05-18T10:00:00"})
    monkeypatch.setattr("src.server.queue_manager.extract_frames", lambda *args, **kwargs: [{"path": str(tmp_path / "f1.jpg"), "timestamp_seconds": 1.0, "timecode": "00:00:01.000", "frame_index": 0}])
    monkeypatch.setattr("src.ai.ollama_provider.OllamaVisionProvider.describe_video", lambda *args, **kwargs: analysis)
    monkeypatch.setattr("src.server.queue_manager.write_nfo_sidecar", lambda *args, **kwargs: tmp_path / "mock.nfo")
    monkeypatch.setattr("src.server.queue_manager.execute_rename", fake_execute_rename)
    monkeypatch.setattr("src.server.queue_manager.generate_suggested_name", lambda *args, **kwargs: "Birthday_Party.mp4")

    qm._process_single_task(task)

    assert task.status == "completed"
    assert task.filename == "Birthday_Party.mp4"
    assert task.file_path == str(tmp_path / "Birthday_Party.mp4")
    assert task.result["final_file_path"] == str(tmp_path / "Birthday_Party.mp4")
    assert (tmp_path / "Birthday_Party.mp4").exists()
    assert not orig_file.exists()

def test_resolve_local_paths_dropped_folder_by_name(tmp_path):
    sub = tmp_path / "vacation_2024"
    sub.mkdir()
    v1 = sub / "clip1.mp4"
    v1.write_bytes(b"content 1")
    v2 = sub / "clip2.mov"
    v2.write_bytes(b"content 2")
    txt = sub / "readme.txt"
    txt.write_text("info")

    res = client.post("/api/files/resolve-local", json={
        "filenames": ["vacation_2024"],
        "current_folder": str(tmp_path)
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["count"] == 2
    assert str(v1.resolve()) in data["resolved_paths"]
    assert str(v2.resolve()) in data["resolved_paths"]
    assert str(txt.resolve()) not in data["resolved_paths"]

def test_pick_native_cancelled_response(monkeypatch):
    import src.server.api as api_module
    monkeypatch.setattr(api_module, "pick_native_directory", lambda initial_dir: {"status": "cancelled"})
    monkeypatch.setattr(api_module, "pick_native_files", lambda initial_dir: {"status": "cancelled"})

    res1 = client.post("/api/fs/pick-native", json={"target": "folder"})
    assert res1.status_code == 200
    assert res1.json()["status"] == "cancelled"

    res2 = client.post("/api/fs/pick-native", json={"target": "files"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "cancelled"

