from fastapi.testclient import TestClient
from PIL import Image

from src.server.app import app
from src.media.faces import FaceRegistry

client = TestClient(app)

def test_api_faces_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.server.api import face_registry

    # Re-initialize registry with tmp_path
    face_registry._data = {}
    face_registry.faces_dir = tmp_path / "faces"
    face_registry.registry_file = face_registry.faces_dir / "registry.json"
    face_registry.thumbs_dir = face_registry.faces_dir / "thumbs"
    face_registry.thumbs_dir.mkdir(parents=True, exist_ok=True)

    dummy_crop = Image.new("RGB", (60, 60), color="blue")
    pid, name = face_registry.register_or_update([1.0] * 128, dummy_crop, "/vid.mp4")

    # 1. GET /api/faces
    res = client.get("/api/faces")
    assert res.status_code == 200
    faces = res.json()["faces"]
    assert len(faces) >= 1
    assert faces[0]["id"] == pid

    # 2. POST /api/faces/{pid}/rename
    ren_res = client.post(f"/api/faces/{pid}/rename", json={"new_name": "Uncle Bob", "update_sidecars": False})
    assert ren_res.status_code == 200
    assert ren_res.json()["new_name"] == "Uncle Bob"

    # 3. GET thumbnail
    thumb_res = client.get(f"/api/faces/thumbnail/{pid}.jpg")
    assert thumb_res.status_code == 200
    assert thumb_res.headers["content-type"] == "image/jpeg"

    # 4. DELETE face
    del_res = client.delete(f"/api/faces/{pid}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

def test_api_faces_clear(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.server.api import face_registry

    face_registry._data = {}
    face_registry.faces_dir = tmp_path / "faces"
    face_registry.registry_file = face_registry.faces_dir / "registry.json"
    face_registry.thumbs_dir = face_registry.faces_dir / "thumbs"
    face_registry.thumbs_dir.mkdir(parents=True, exist_ok=True)

    dummy_crop = Image.new("RGB", (60, 60), color="blue")
    face_registry.register_or_update([1.0] * 128, dummy_crop, "/vid1.mp4")
    face_registry.register_or_update([0.0] * 128, dummy_crop, "/vid2.mp4")
    assert len(face_registry.get_all()) == 2

    # POST /api/faces/clear
    res = client.post("/api/faces/clear")
    assert res.status_code == 200
    assert res.json()["status"] == "cleared"
    assert res.json()["cleared_count"] == 2

    # Verify empty
    res2 = client.get("/api/faces")
    assert res2.status_code == 200
    assert len(res2.json()["faces"]) == 0

def test_api_faces_reindex(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.server.api import face_registry

    face_registry._data = {}
    face_registry.faces_dir = tmp_path / "faces"
    face_registry.registry_file = face_registry.faces_dir / "registry.json"
    face_registry.thumbs_dir = face_registry.faces_dir / "thumbs"
    face_registry.thumbs_dir.mkdir(parents=True, exist_ok=True)

    dummy_crop = Image.new("RGB", (60, 60), color="blue")
    # Register 2 identities that are fairly similar
    face_registry.register_or_update([1.0] * 64 + [0.0] * 64, dummy_crop, "/vid1.mp4", threshold=0.99)
    face_registry.register_or_update([0.85] * 64 + [0.15] * 64, dummy_crop, "/vid2.mp4", threshold=0.99)
    assert len(face_registry.get_all()) == 2

    # POST /api/faces/reindex
    res = client.post("/api/faces/reindex")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["merged_count"] >= 1
    assert data["total_identities"] == 1


def test_api_faces_backfill_thumbnails(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.server.api import face_registry
    from unittest.mock import patch

    with patch.object(face_registry, "backfill_missing_thumbnails", return_value=3):
        res = client.post("/api/faces/backfill-thumbnails")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
        assert res.json()["backfilled_count"] == 3


