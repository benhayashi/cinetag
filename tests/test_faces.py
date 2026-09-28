import pytest
from pathlib import Path
from PIL import Image
import numpy as np

from src.media.faces import FaceRegistry, cosine_similarity, LocalFaceEngine

def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]

    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0
    assert pytest.approx(cosine_similarity(v1, v3), 0.001) == 0.0

def test_face_registry_auto_naming_and_matching(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()

    dummy_crop = Image.new("RGB", (100, 100), color="pink")
    emb1 = [1.0] + [0.0] * 127
    emb1_similar = [0.95] + [0.05] * 127
    emb2_different = [0.0] * 64 + [1.0] + [0.0] * 63

    # 1. Register first unknown face -> should get Person_01
    pid1, name1 = registry.register_or_update(emb1, dummy_crop, "/videos/vid1.mp4")
    assert name1 == "Person_01"
    assert pid1 == "person_001"

    # 2. Register similar face -> should match Person_01
    pid1_match, name1_match = registry.register_or_update(emb1_similar, dummy_crop, "/videos/vid2.mp4", threshold=0.7)
    assert pid1_match == "person_001"
    assert name1_match == "Person_01"

    # 3. Register different face -> should get Person_02
    pid2, name2 = registry.register_or_update(emb2_different, dummy_crop, "/videos/vid1.mp4", threshold=0.7)
    assert name2 == "Person_02"
    assert pid2 == "person_002"

    faces = registry.get_all()
    assert len(faces) == 2
    assert faces[0]["video_count"] == 2  # seen in vid1 and vid2

def test_face_rename_and_sidecar_sync(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    import json
    registry = FaceRegistry()

    dummy_crop = Image.new("RGB", (100, 100), color="pink")
    emb = [1.0] * 128
    vid_file = tmp_path / "family_vacation.mp4"
    vid_file.write_bytes(b"dummy")

    # Mock sidecars
    sidecar_json = tmp_path / "family_vacation.info.json"
    sidecar_json.write_text(json.dumps({
        "analysis": {
            "title": "Family Trip",
            "summary": "Great day",
            "people_or_subjects": ["Person_01"]
        }
    }), encoding="utf-8")

    sidecar_nfo = tmp_path / "family_vacation.nfo"
    sidecar_nfo.write_text("<movie><actor><name>Person_01</name></actor></movie>", encoding="utf-8")

    sidecar_xmp = tmp_path / "family_vacation.xmp"
    sidecar_xmp.write_text("<rdf:li>Person_01</rdf:li><rdf:li>Person:Person_01</rdf:li>", encoding="utf-8")

    pid, _ = registry.register_or_update(emb, dummy_crop, str(vid_file))
    assert pid == "person_001"

    # Rename Person_01 -> Aunt Sarah
    res = registry.rename_person(pid, "Aunt Sarah", update_sidecars=True)
    assert res["status"] == "renamed"
    assert res["new_name"] == "Aunt Sarah"
    assert res["updated_sidecars_count"] >= 3

    # Check updated contents
    assert "Aunt Sarah" in sidecar_json.read_text(encoding="utf-8")
    assert "Aunt Sarah" in sidecar_nfo.read_text(encoding="utf-8")
    assert "Aunt Sarah" in sidecar_xmp.read_text(encoding="utf-8")

def test_local_face_engine_rejects_non_face_patches(tmp_path):
    """Ensure non-face skin tones (hands, elbows, knees) are not recognized as faces."""
    skin_img_path = tmp_path / "skin_patch.jpg"
    # Create an image that mimics human skin chrominance (hand / elbow / arm)
    arr = np.full((320, 320, 3), (210, 150, 130), dtype=np.uint8)
    Image.fromarray(arr).save(skin_img_path)

    detections = LocalFaceEngine.detect_and_embed(skin_img_path, confidence=0.70)
    assert len(detections) == 0, "Non-face skin patch should have 0 face detections"

def test_register_named_subject_avoids_fake_thumbnail(tmp_path, monkeypatch):
    """Ensure subject registration does not create dummy thumbnails from non-face frames."""
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()

    # Create frame without a face (e.g., solid background)
    blank_frame = tmp_path / "blank_frame.jpg"
    Image.new("RGB", (320, 240), color="blue").save(blank_frame)

    pid, name = registry.register_named_subject("Uncle Bob", "/videos/trip.mp4", frame_path=blank_frame)
    assert pid == "person_001"
    assert name == "Uncle Bob"
    faces = registry.get_all()
    assert len(faces) == 1
    # Thumbnail should be None because no human face was detected in blank_frame
    assert faces[0]["thumbnail"] is None

def test_exemplar_clustering_coherence(tmp_path, monkeypatch):
    """Ensure multi-exemplar clustering links varied shots of the same person together."""
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()
    dummy_crop = Image.new("RGB", (100, 100), color="pink")

    # Base embedding
    emb_base = [1.0] * 64 + [0.0] * 64
    pid1, name1 = registry.register_or_update(emb_base, dummy_crop, "/videos/vid1.mp4", threshold=0.55)
    assert pid1 == "person_001"

    # Angled pose / lighting drift: ~0.60 similarity with emb_base
    # (Matches with distance <= 0.45, threshold 0.55)
    emb_shot2 = [0.8] * 64 + [0.4] * 64
    pid2, name2 = registry.register_or_update(emb_shot2, dummy_crop, "/videos/vid1.mp4", threshold=0.55)
    assert pid2 == "person_001", "Second shot should cluster into same person with balanced distance"

    # Third shot close to shot2:
    emb_shot3 = [0.7] * 64 + [0.5] * 64
    pid3, name3 = registry.register_or_update(emb_shot3, dummy_crop, "/videos/vid1.mp4", threshold=0.55)
    assert pid3 == "person_001", "Third shot should link via multi-exemplar coherence"

def test_multishot_face_storage_up_to_10(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()
    dummy_crop = Image.new("RGB", (80, 80), color="green")
    emb = [1.0] * 128

    # Register 12 shots of the same person with varying confidence
    for i in range(12):
        conf = 0.5 + (i * 0.04)  # 0.50 to 0.94
        registry.register_or_update(emb, dummy_crop, f"/videos/vid_{i}.mp4", confidence=conf)

    faces = registry.get_all()
    assert len(faces) == 1
    # Max shots is 10
    assert faces[0]["shots_count"] == 10
    assert len(faces[0]["face_shots"]) == 10
    # Lowest confidences should have been replaced
    confs = [s["confidence"] for s in faces[0]["face_shots"]]
    assert min(confs) >= 0.57

def test_recluster_and_reindex(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()
    dummy_crop = Image.new("RGB", (80, 80), color="yellow")

    # Person 1 and Person 2 initially registered with very strict threshold (e.g. 0.99)
    emb1 = [1.0] * 64 + [0.0] * 64
    emb2 = [0.85] * 64 + [0.15] * 64
    pid1, _ = registry.register_or_update(emb1, dummy_crop, "/videos/vid1.mp4", threshold=0.99)
    pid2, _ = registry.register_or_update(emb2, dummy_crop, "/videos/vid2.mp4", threshold=0.99)
    assert pid1 != pid2
    assert len(registry.get_all()) == 2

    # Now recluster with threshold 0.70
    res = registry.recluster_and_reindex(threshold=0.70)
    assert res["status"] == "ok"
    assert res["merged_count"] == 1
    assert res["total_identities"] == 1
    faces = registry.get_all()
    assert len(faces) == 1
    assert faces[0]["video_count"] == 2


def test_register_named_subject_with_candidate_frames(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()

    # Create dummy frame image
    frame1 = tmp_path / "frame1.jpg"
    img = Image.new("RGB", (200, 200), color="blue")
    img.save(frame1)

    from unittest.mock import patch
    fake_face = {
        "box": (10, 10, 50, 50),
        "crop": Image.new("RGB", (60, 60), color="pink"),
        "embedding": [0.5] * 128,
        "confidence": 0.88
    }

    with patch.object(LocalFaceEngine, "detect_and_embed", return_value=[fake_face]):
        pid, name = registry.register_named_subject(
            name="Alice",
            video_path="/videos/vacation.mp4",
            frame_path=frame1,
            candidate_frames=[frame1]
        )
    assert name == "Alice"
    assert pid == "person_001"

    person = registry.get_all()[0]
    assert person["name"] == "Alice"
    assert person["thumbnail"] is not None
    assert (registry.thumbs_dir / person["thumbnail"]).exists()


def test_backfill_missing_thumbnails(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_DESCRIBER_DATA_DIR", str(tmp_path))
    registry = FaceRegistry()

    # Create a registered person with missing thumbnail
    now_iso = "2026-09-27T10:00:00"
    registry._data["person_001"] = {
        "id": "person_001",
        "name": "Kaylee",
        "thumbnail": None,
        "embedding": [0.0] * 128,
        "video_count": 1,
        "video_paths": [str(tmp_path / "video1.mp4")],
        "created_at": now_iso,
        "last_seen": now_iso
    }
    registry._save()

    test_frame = tmp_path / "extracted_frame.jpg"
    Image.new("RGB", (200, 200), color="red").save(test_frame)

    from unittest.mock import patch
    fake_face = {
        "box": (10, 10, 50, 50),
        "crop": Image.new("RGB", (60, 60), color="pink"),
        "embedding": [0.5] * 128,
        "confidence": 0.88
    }

    with patch("src.media.sampler.extract_frames", return_value=[{"path": test_frame}]), \
         patch.object(LocalFaceEngine, "detect_and_embed", return_value=[fake_face]), \
         patch("pathlib.Path.exists", autospec=True, side_effect=lambda self: True):
        count = registry.backfill_missing_thumbnails()

    assert count == 1
    person = registry.get_all()[0]
    assert person["thumbnail"] == "person_001.jpg"
    assert (registry.thumbs_dir / "person_001.jpg").exists()



