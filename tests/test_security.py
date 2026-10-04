import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.server.app import app
from src.server import api as api_mod
from src.core.config import (
    AppConfig, load_config, save_config, SECRET_MASK, apply_config_update,
)
from src.core.paths import get_uploads_dir, get_config_path

client = TestClient(app)


def test_upload_traversal_is_neutralized():
    res = client.post("/api/upload", files={"file": ("../../evil.mp4", b"x", "video/mp4")})
    if res.status_code == 200:
        assert not (get_uploads_dir().parent.parent / "evil.mp4").exists()
        assert (get_uploads_dir() / "evil.mp4").exists()
        (get_uploads_dir() / "evil.mp4").unlink()


def test_download_outside_allowlist_is_forbidden(tmp_path):
    f = tmp_path / "secret.txt"
    f.write_text("nope")
    assert client.get("/api/download", params={"file_path": str(f)}).status_code == 403
    assert client.get("/api/download", params={"file_path": "/etc/passwd"}).status_code == 403


def test_download_allowed_for_queue_file(tmp_path, allow_path):
    f = tmp_path / "ok.mp4"
    f.write_bytes(b"data")
    allow_path(f)
    assert client.get("/api/download", params={"file_path": str(f)}).status_code == 200


def test_delete_upload_keeps_siblings():
    up = get_uploads_dir()
    up.mkdir(parents=True, exist_ok=True)
    (up / "clip.mp4").write_bytes(b"a")
    (up / "clip2.mp4").write_bytes(b"b")
    (up / "clip.srt").write_text("s")
    client.delete("/api/uploads/clip.mp4")
    assert not (up / "clip.mp4").exists()
    assert (up / "clip2.mp4").exists()
    (up / "clip2.mp4").unlink()


def test_delete_upload_rejects_path_components():
    res = client.delete("/api/uploads/..%2F..%2Fx")
    assert res.status_code in (400, 404)


def test_bad_config_rejected_and_unchanged():
    before = get_config_path().read_text() if get_config_path().exists() else None
    res = client.post("/api/config", json={"port": "not-a-number"})
    assert res.status_code == 422
    after = get_config_path().read_text() if get_config_path().exists() else None
    assert before == after


def test_secrets_masked_and_round_trip():
    cfg = load_config()
    cfg.openai_compatible_api_key = "sk-real"
    save_config(cfg)
    got = client.get("/api/config").json()
    assert got["openai_compatible_api_key"] == SECRET_MASK
    assert "sk-real" not in json.dumps(got)
    client.post("/api/config", json={"openai_compatible_api_key": SECRET_MASK, "ollama_model": "m"})
    assert load_config().openai_compatible_api_key == "sk-real"
    exp = client.get("/api/config/export").text
    assert "sk-real" not in exp
    cfg.openai_compatible_api_key = ""
    save_config(cfg)


def test_apply_config_update_drops_readonly():
    cur = AppConfig()
    new = apply_config_update(cur, {"access_token": "hacked", "bogus": 1})
    assert new.access_token == cur.access_token


def test_foreign_origin_blocked_on_post():
    res = client.post("/api/config", json={"ollama_model": "x"}, headers={"Origin": "http://evil.example"})
    assert res.status_code == 403
    res = client.post("/api/config", json={"ollama_model": "x"}, headers={"Origin": "null"})
    assert res.status_code == 403


def test_cors_not_echoed():
    res = client.get("/api/status", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in res.headers}


def test_bad_host_header_rejected():
    res = client.get("/api/status", headers={"Host": "attacker.example"})
    assert res.status_code == 421


def test_token_required_when_not_loopback():
    old = (app.state.bind_loopback, app.state.access_token)
    app.state.bind_loopback, app.state.access_token = False, "tok123"
    try:
        c = TestClient(app)
        assert c.get("/api/status").status_code == 401
        assert c.get("/health").status_code == 200
        assert c.get("/api/status", headers={"Authorization": "Bearer tok123"}).status_code == 200
        assert c.get("/api/status", headers={"X-CineTag-Token": "bad"}).status_code == 401
        r = c.get("/?token=tok123", follow_redirects=False)
        assert r.status_code in (302, 303, 307)
        assert c.get("/api/status").status_code == 200  # cookie now set
    finally:
        app.state.bind_loopback, app.state.access_token = old


def test_corrupt_config_backed_up_and_partial_recovery():
    p = get_config_path()
    p.write_text(json.dumps({"port": "bad", "ollama_model": "keepme"}))
    cfg = load_config()
    assert cfg.ollama_model == "keepme"
    assert cfg.port == AppConfig().port
    assert list(p.parent.glob("config.json.corrupt-*"))
    p.write_text("{not json")
    assert load_config().port == AppConfig().port


def test_queue_manager_has_os():
    from src.server import queue_manager
    assert hasattr(queue_manager, "os")


def test_renamer_imports():
    from src.media import renamer
    assert hasattr(renamer, "defaultdict")
