import io
import json
import zipfile
from pathlib import Path
from fastapi.testclient import TestClient

from src.media.faces import FaceRegistry
from src.server.app import app

client = TestClient(app)

def test_face_export_and_import(tmp_path, monkeypatch):
    # Set faces dir in tmp_path
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    reg = FaceRegistry()

    # Create dummy subject
    pid, name = reg.register_named_subject("Grandma Betty", "/fake/path.mp4")
    assert pid.startswith("person_")
    assert name == "Grandma Betty"
    assert len(reg.get_all()) == 1

    # Export to zip
    export_zip = tmp_path / "faces_export.zip"
    reg.export_database_zip(export_zip)
    assert export_zip.exists()
    assert zipfile.is_zipfile(export_zip)

    # Check zip contents
    with zipfile.ZipFile(export_zip, "r") as zf:
        assert "registry.json" in zf.namelist()
        data = json.loads(zf.read("registry.json"))
        assert pid in data
        assert data[pid]["name"] == "Grandma Betty"

    # Now simulate fresh registry and import
    fresh_tmp = tmp_path / "fresh"
    fresh_tmp.mkdir()
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(fresh_tmp))
    fresh_reg = FaceRegistry()
    assert len(fresh_reg.get_all()) == 0

    count = fresh_reg.import_database_zip(export_zip, merge=True)
    assert count == 1
    imported_faces = fresh_reg.get_all()
    assert len(imported_faces) == 1
    assert imported_faces[0]["name"] == "Grandma Betty"

def test_api_face_export_and_import(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    from src.media.faces import face_registry
    face_registry.register_named_subject("Uncle Bob", "/path/vid.mp4")

    # API Export
    res = client.get("/api/faces/export")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    zip_bytes = res.content
    assert len(zip_bytes) > 0

    # API Import
    files = {"file": ("backup.zip", io.BytesIO(zip_bytes), "application/zip")}
    import_res = client.post("/api/faces/import?merge=true", files=files)
    assert import_res.status_code == 200
    assert import_res.json()["status"] == "ok"