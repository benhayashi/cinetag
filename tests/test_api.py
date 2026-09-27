from fastapi.testclient import TestClient
from src.server.app import app

client = TestClient(app)

def test_api_status():
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "counts" in data
    assert "recent_logs" in data

def test_api_config(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    
    get_res = client.get("/api/config")
    assert get_res.status_code == 200
    
    post_res = client.post("/api/config", json={"port": 9090, "ollama_model": "test-vlm"})
    assert post_res.status_code == 200
    assert post_res.json()["config"]["port"] == 9090

def test_api_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    res = client.get("/api/storage")
    assert res.status_code == 200
    data = res.json()
    assert "locations" in data
    assert "sizes_bytes" in data

def test_api_scan_empty(tmp_path):
    res = client.post("/api/scan", json={"folder_path": str(tmp_path), "recursive": False, "hide_processed": False})
    assert res.status_code == 200
    assert res.json()["total_found"] == 0

def test_api_upload_download_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    # 1. Upload mock video file
    file_content = b"fake video binary stream data"
    response = client.post(
        "/api/upload",
        files={"file": ("remote_vacation.mp4", file_content, "video/mp4")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "uploaded"
    assert data["filename"] == "remote_vacation.mp4"
    uploaded_path = data["path"]

    # 2. List uploads
    list_res = client.get("/api/uploads")
    assert list_res.status_code == 200
    uploads = list_res.json()["uploads"]
    assert any(u["filename"] == "remote_vacation.mp4" for u in uploads)

    # 3. Test download endpoint
    dl_res = client.get(f"/api/download?file_path={uploaded_path}")
    assert dl_res.status_code == 200
    assert dl_res.content == file_content

    # 4. Delete single upload
    del_res = client.delete("/api/uploads/remote_vacation.mp4")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Verify deleted
    list_res2 = client.get("/api/uploads")
    assert not any(u["filename"] == "remote_vacation.mp4" for u in list_res2.json()["uploads"])

def test_api_clear_all_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))

    client.post("/api/upload", files={"file": ("test1.mp4", b"data1", "video/mp4")})
    client.post("/api/upload", files={"file": ("test2.mp4", b"data2", "video/mp4")})

    clear_res = client.post("/api/storage/clear-uploads")
    assert clear_res.status_code == 200
    assert clear_res.json()["freed_bytes"] > 0

    list_res = client.get("/api/uploads")
    assert len(list_res.json()["uploads"]) == 0

def test_api_results(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    import json

    # 1. Create a dummy video and its sidecars
    vid = tmp_path / "dog_park.mp4"
    vid.write_bytes(b"dummy video")

    sidecar_json = tmp_path / "dog_park.info.json"
    sidecar_json.write_text(json.dumps({
        "analysis": {
            "title": "Dog Playing in Park",
            "summary": "A friendly golden retriever fetches a ball in a sunny park.",
            "events": [
                {"timecode": "00:00", "description": "Dog runs towards ball", "is_highlight": True}
            ],
            "tags": ["dog", "park", "fetch"],
            "people_or_subjects": ["Golden Retriever"],
            "suggested_filename": "dog_playing_park"
        }
    }), encoding="utf-8")

    sidecar_txt = tmp_path / "dog_park.mp4.txt"
    sidecar_txt.write_text("Dog Playing in Park\n\nA friendly golden retriever fetches a ball.", encoding="utf-8")

    # 2. Query /api/results
    res = client.get(f"/api/results?file_path={vid}")
    assert res.status_code == 200
    data = res.json()
    assert data["title"] == "Dog Playing in Park"
    assert "golden retriever" in data["summary"]
    assert "dog, park, fetch" in data["tags_string"]
    assert data["sidecars"]["json"]["exists"] is True
    assert data["sidecars"]["txt"]["exists"] is True
    assert "/api/download?file_path=" in data["sidecars"]["txt"]["url"]
    assert "/api/download?file_path=" in data["video"]["url"]

def test_api_fs_browse(tmp_path):
    subfolder = tmp_path / "SubDir"
    subfolder.mkdir()
    video_file = tmp_path / "sample_vacation.mp4"
    video_file.write_bytes(b"dummy")
    text_file = tmp_path / "notes.txt"
    text_file.write_bytes(b"notes")

    res = client.get(f"/api/fs/browse?path={tmp_path}")
    assert res.status_code == 200
    data = res.json()

    assert data["current_path"] == str(tmp_path.resolve())
    assert "quick_locations" in data
    assert len(data["quick_locations"]) > 0

    # SubDir should be in folders
    assert any(f["name"] == "SubDir" for f in data["folders"])

    # sample_vacation.mp4 should be in files
    assert any(f["name"] == "sample_vacation.mp4" for f in data["files"])

    # Non-video files shouldn't be in files
    assert not any(f["name"] == "notes.txt" for f in data["files"])

def test_api_pick_native(monkeypatch):
    # Mock pick_native_directory and pick_native_files
    import src.server.api as api_module
    monkeypatch.setattr(api_module, "pick_native_directory", lambda initial_dir: "/home/user/Videos/Family")
    monkeypatch.setattr(api_module, "pick_native_files", lambda initial_dir: ["/home/user/Videos/Family/clip1.mp4"])

    res1 = client.post("/api/fs/pick-native", json={"target": "folder"})
    assert res1.status_code == 200
    assert res1.json()["status"] == "selected"
    assert res1.json()["path"] == "/home/user/Videos/Family"

    res2 = client.post("/api/fs/pick-native", json={"target": "files"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "selected"
    assert len(res2.json()["paths"]) == 1

def test_api_check_conflicts(tmp_path):
    vid = tmp_path / "trip.mp4"
    vid.write_text("fake video")

    # Initially no conflicts
    res1 = client.post("/api/queue/check-conflicts", json={"file_paths": [str(vid)]})
    assert res1.status_code == 200
    assert res1.json()["has_conflicts"] is False
    assert len(res1.json()["conflicts"]) == 0

    # Create a sidecar file
    sidecar = tmp_path / "trip.info.json"
    sidecar.write_text('{"title": "Prior Trip"}')

    # Now check conflicts
    res2 = client.post("/api/queue/check-conflicts", json={"file_paths": [str(vid)]})
    assert res2.status_code == 200
    assert res2.json()["has_conflicts"] is True
    assert len(res2.json()["conflicts"]) == 1
    assert res2.json()["conflicts"][0]["filename"] == "trip.mp4"
    assert ".info.json" in res2.json()["conflicts"][0]["sidecars"]

    # Test queue add with conflict mode
    res3 = client.post("/api/queue/add", json={"file_paths": [str(vid)], "conflict_mode": "enumerate"})
    assert res3.json()["added_count"] == 1

def test_api_download_srt_existing(tmp_path):
    vid = tmp_path / "lecture.mp4"
    vid.write_bytes(b"dummy video")
    srt = tmp_path / "lecture.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:04,000\nHello lecture\n", encoding="utf-8")

    res = client.get(f"/api/download/srt?file_path={vid}")
    assert res.status_code == 200
    assert "Hello lecture" in res.text

def test_api_download_srt_synthesized(tmp_path):
    import json
    vid = tmp_path / "speech.mp4"
    vid.write_bytes(b"dummy video")
    info = tmp_path / "speech.info.json"
    info.write_text(json.dumps({
        "audio_transcript": "Good morning everyone. Welcome to the conference.",
        "duration_seconds": 12.0
    }), encoding="utf-8")

    res = client.get(f"/api/download/srt?file_path={vid}")
    assert res.status_code == 200
    assert "00:00:00,000 -->" in res.text
    assert "Good morning everyone" in res.text

def test_api_config_face_distance_and_export_srt():
    res = client.post("/api/config", json={
        "face_max_distance": 0.40,
        "export_srt": True
    })
    assert res.status_code == 200
    cfg = client.get("/api/config").json()
    assert cfg["face_max_distance"] == 0.40
    assert cfg["export_srt"] is True

def test_api_rename_preview_with_date_override(tmp_path):
    vid = tmp_path / "20150522_230949_001.mp4"
    vid.write_bytes(b"dummy")

    # 1. Preview with smart extraction from filename
    res1 = client.post("/api/rename/preview", json={
        "file_paths": [str(vid)],
        "date_source": "smart"
    })
    assert res1.status_code == 200
    data1 = res1.json()
    assert len(data1) == 1
    assert data1[0]["date_source_used"] == "filename"
    assert "20150522_230949" in data1[0]["suggested_name"]

    # 2. Preview with manual date override
    res2 = client.post("/api/rename/preview", json={
        "file_paths": [str(vid)],
        "date_override": "2018-11-20 15:30:00",
        "date_source": "override"
    })
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2[0]["date_source_used"] == "override"
    assert "20181120_153000" in data2[0]["suggested_name"]

def test_api_queue_add_with_date_override(tmp_path):
    vid = tmp_path / "sample.mp4"
    vid.write_bytes(b"dummy")

    res = client.post("/api/queue/add", json={
        "file_paths": [str(vid)],
        "conflict_mode": "overwrite",
        "date_override": "2015-05-22T23:09:49",
        "date_source": "override"
    })
    assert res.status_code == 200
    assert res.json()["status"] == "ok"




