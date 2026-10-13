import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from src.server.app import app
from src.server.queue_manager import manager
from src.ai.whisper_service import sanitize_repetitive_text, sanitize_repetitive_segments
from src.ai.base import VideoAnalysisResult

client = TestClient(app)

def test_sanitize_repetitive_text():
    # Phrase level repetition loop
    phrase_loop = "Thank you. Thank you. Thank you. Thank you."
    cleaned = sanitize_repetitive_text(phrase_loop)
    assert cleaned == "Thank you. Thank you."

    # Single word repetition loop
    word_loop = "yeah yeah yeah yeah yeah"
    cleaned_words = sanitize_repetitive_text(word_loop)
    assert cleaned_words == "yeah yeah"

    # Clean text without loops unchanged
    normal_text = "Good morning everyone. Welcome to the show."
    assert sanitize_repetitive_text(normal_text) == normal_text

    # Empty text
    assert sanitize_repetitive_text("") == ""

def test_sanitize_repetitive_segments():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello world."},
        {"start": 2.0, "end": 4.0, "text": "Repeating line."},
        {"start": 4.0, "end": 6.0, "text": "Repeating line."},
        {"start": 6.0, "end": 8.0, "text": "Repeating line."},
        {"start": 8.0, "end": 10.0, "text": "Repeating line."},
        {"start": 10.0, "end": 12.0, "text": "Thank you. Thank you. Thank you. Thank you."},
        {"start": 12.0, "end": 14.0, "text": "Final words."}
    ]
    cleaned = sanitize_repetitive_segments(segments, max_consecutive_repeats=2)
    # Consecutive duplicate "Repeating line." capped at 2
    repeats = [s for s in cleaned if "Repeating line" in s["text"]]
    assert len(repeats) == 2
    # In-segment repetition sanitized
    ty_seg = [s for s in cleaned if "Thank you" in s["text"]][0]
    assert ty_seg["text"] == "Thank you. Thank you."
    # Total segments cleaned down
    assert len(cleaned) == 5

def test_api_review_save_manual(tmp_path):
    video_file = tmp_path / "summer_beach.mp4"
    video_file.write_bytes(b"dummy mp4 content")

    # Seed an existing .info.json
    info_json = tmp_path / "summer_beach.info.json"
    info_json.write_text(json.dumps({
        "file": {"name": "summer_beach.mp4", "path": str(video_file), "size_bytes": 100, "metadata": {}},
        "analysis": {
            "title": "Old Title",
            "summary": "Old Summary",
            "tags": ["beach"],
            "people_or_subjects": ["Tom"],
            "animals_or_pets": [],
            "objects": []
        }
    }), encoding="utf-8")

    payload = {
        "file_path": str(video_file),
        "title": "Summer Beach Vacation 2023",
        "summary": "Tom and Sarah playing frisbee with their golden retriever.",
        "tags": ["beach", "summer", "frisbee"],
        "people": ["Tom", "Sarah"],
        "animals": ["Golden Retriever"],
        "objects": ["frisbee"],
        "audio_transcript": "Throw the frisbee over here!"
    }

    res = client.post("/api/review/save-manual", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["analysis"]["title"] == "Summer Beach Vacation 2023"
    assert "Golden Retriever" in data["analysis"]["animals_or_pets"]

    # Verify .info.json was updated
    updated_info = json.loads(info_json.read_text(encoding="utf-8"))
    assert updated_info["analysis"]["title"] == "Summer Beach Vacation 2023"
    assert updated_info["analysis"]["audio_transcript"] == "Throw the frisbee over here!"
    assert updated_info["analysis"]["people_or_subjects"] == ["Tom", "Sarah"]

    # Verify .txt sidecar was written
    txt_sidecar = tmp_path / "summer_beach.txt"
    assert txt_sidecar.exists()
    txt_content = txt_sidecar.read_text(encoding="utf-8")
    assert "Summer Beach Vacation 2023" in txt_content
    assert "Golden Retriever" in txt_content

    # Verify .xmp sidecar was written
    xmp_sidecar = tmp_path / "summer_beach.xmp"
    assert xmp_sidecar.exists()

def test_api_review_refine_ai(tmp_path):
    video_file = tmp_path / "party.mp4"
    video_file.write_bytes(b"dummy mp4 content")

    mock_analysis = VideoAnalysisResult(
        title="Betty 80th Birthday Party",
        summary="Family celebrating Grandma Betty's milestone 80th birthday with cake and singing.",
        tags=["birthday", "family", "party", "cake"],
        people_or_subjects=["Grandma Betty", "Uncle Bob"],
        animals_or_pets=[],
        objects=["birthday cake", "candles"],
        suggested_filename="betty_80th_birthday_party",
        audio_transcript="Happy birthday to you!"
    )

    with patch("src.server.api.get_ai_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.describe_video.return_value = mock_analysis
        mock_get_provider.return_value = mock_provider

        payload = {
            "file_path": str(video_file),
            "user_guidance": "Add Uncle Bob and mention it was Grandma Betty's 80th birthday.",
            "current_title": "Family Party",
            "current_summary": "People eating cake.",
            "tags": ["party"],
            "people": ["Grandma Betty"],
            "audio_transcript": "Happy birthday to you!"
        }

        res = client.post("/api/review/refine-ai", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["analysis"]["title"] == "Betty 80th Birthday Party"
        assert "Uncle Bob" in data["analysis"]["people"]

        # Verify sidecars updated
        info_json = tmp_path / "party.info.json"
        assert info_json.exists()
        info_data = json.loads(info_json.read_text(encoding="utf-8"))
        assert info_data["analysis"]["title"] == "Betty 80th Birthday Party"

def test_api_review_retranscribe(tmp_path):
    video_file = tmp_path / "speech.mp4"
    video_file.write_bytes(b"dummy video")

    dummy_wav = tmp_path / "speech.wav"
    dummy_wav.write_bytes(b"RIFF" + b"\x00" * 40)

    with patch("src.server.api.extract_audio", return_value=dummy_wav), \
         patch("src.server.api.WhisperTranscriptionService") as mock_whisper_cls:

        mock_instance = MagicMock()
        mock_instance.transcribe_detailed.return_value = {
            "text": "Welcome to our family holiday celebration.",
            "segments": [
                {"start": 0.0, "end": 3.5, "text": "Welcome to our family holiday celebration."}
            ]
        }
        mock_whisper_cls.return_value = mock_instance

        res = client.post("/api/review/retranscribe", json={
            "file_path": str(video_file),
            "task": "transcribe"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["audio_transcript"] == "Welcome to our family holiday celebration."
        assert len(data["segments"]) == 1

        # Check SRT sidecar generated
        srt_file = tmp_path / "speech.srt"
        assert srt_file.exists()
        assert "Welcome to our family holiday celebration." in srt_file.read_text(encoding="utf-8")
