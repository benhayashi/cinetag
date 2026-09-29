import base64
import logging
from pathlib import Path
from typing import List, Optional
import httpx

from src.ai.base import BaseVisionProvider, FrameItem, VideoAnalysisResult
from src.ai.prompt import SYSTEM_PROMPT, get_system_prompt, build_user_prompt, parse_ai_response

logger = logging.getLogger(__name__)

class OllamaVisionProvider(BaseVisionProvider):
    """Client for local or networked Ollama instances supporting vision models."""

    def __init__(self, base_url: str = "http://localhost:11434", default_model: str = "llama3.2-vision"):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def is_available(self) -> bool:
        """Check if Ollama server is running and responding."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Fetch list of all models installed in Ollama."""
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = [m.get("name") for m in data.get("models", []) if "name" in m]
                    return models
        except Exception as e:
            logger.warning(f"Failed to query Ollama models: {e}")
        return []

    def describe_video(
        self,
        frames: List[FrameItem],
        audio_transcript: Optional[str] = None,
        context_prompt: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_guidance: Optional[str] = None
    ) -> VideoAnalysisResult:
        chosen_model = model or self.default_model
        timestamps = [f.timecode for f in frames]
        user_text = build_user_prompt(timestamps, audio_transcript, context_prompt, prompt_guidance=prompt_guidance)
        active_system_prompt = get_system_prompt(system_prompt)

        # Encode frames as base64 strings
        b64_images: List[str] = []
        for f in frames:
            p = Path(f.path)
            if p.exists():
                with open(p, "rb") as img_file:
                    b64_images.append(base64.b64encode(img_file.read()).decode("utf-8"))

        payload = {
            "model": chosen_model,
            "messages": [
                {
                    "role": "system",
                    "content": active_system_prompt
                },
                {
                    "role": "user",
                    "content": user_text,
                    "images": b64_images
                }
            ],
            "stream": False,
            "format": "json"
        }

        # Generous timeout for local vision models (can take 20-60s on complex batches)
        timeout = httpx.Timeout(180.0, connect=10.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(f"{self.base_url}/api/chat", json=payload)
                res.raise_for_status()
                data = res.json()
                raw_content = data.get("message", {}).get("content", "")
                result = parse_ai_response(raw_content)
                result.provider_name = "ollama"
                result.model_name = chosen_model
                result.audio_transcript = audio_transcript
                return result
        except Exception as e:
            logger.error(f"Ollama vision request failed: {e}")
            raise
