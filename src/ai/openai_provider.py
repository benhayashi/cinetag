import base64
import logging
from pathlib import Path
from typing import List, Optional
import httpx

from src.ai.base import BaseVisionProvider, FrameItem, VideoAnalysisResult
from src.ai.prompt import SYSTEM_PROMPT, get_system_prompt, build_user_prompt, parse_ai_response

logger = logging.getLogger(__name__)

class OpenAICompatibleVisionProvider(BaseVisionProvider):
    """Client for LM Studio, LocalAI, vLLM, or standard OpenAI-compatible vision servers."""

    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        api_key: str = "lm-studio",
        default_model: str = "local-model"
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key or 'placeholder'}",
            "Content-Type": "application/json"
        }

    def is_available(self) -> bool:
        """Check reachability of the endpoint."""
        try:
            with httpx.Client(timeout=3.0) as client:
                res = client.get(f"{self.base_url}/models", headers=self._headers())
                return res.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """Fetch list of available models."""
        try:
            with httpx.Client(timeout=5.0) as client:
                res = client.get(f"{self.base_url}/models", headers=self._headers())
                if res.status_code == 200:
                    data = res.json()
                    return [m.get("id") for m in data.get("data", []) if "id" in m]
        except Exception as e:
            logger.warning(f"Failed to query models from {self.base_url}: {e}")
        return []

    def describe_video(
        self,
        frames: List[FrameItem],
        audio_transcript: Optional[str] = None,
        context_prompt: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_guidance: Optional[str] = None,
        slug_guidance: Optional[str] = None,
        timeout_seconds: Optional[int] = None
    ) -> VideoAnalysisResult:
        chosen_model = model or self.default_model
        timestamps = [f.timecode for f in frames]
        user_text = build_user_prompt(timestamps, audio_transcript, context_prompt, prompt_guidance=prompt_guidance, slug_guidance=slug_guidance)
        active_system_prompt = get_system_prompt(system_prompt)

        content_parts = [{"type": "text", "text": user_text}]

        for f in frames:
            p = Path(f.path)
            if p.exists():
                with open(p, "rb") as img_file:
                    b64 = base64.b64encode(img_file.read()).decode("utf-8")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}"
                        }
                    })

        payload = {
            "model": chosen_model,
            "messages": [
                {"role": "system", "content": active_system_prompt},
                {"role": "user", "content": content_parts}
            ],
            "temperature": 0.2
        }

        # Configurable generous timeout for local vision models (default 600s = 10 min for large 27B+ models)
        timeout_val = float(timeout_seconds if timeout_seconds is not None else 600.0)
        timeout = httpx.Timeout(timeout_val, connect=15.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                res = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload
                )
                res.raise_for_status()
                data = res.json()
                raw_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                result = parse_ai_response(raw_text)
                result.provider_name = "openai_compatible"
                result.model_name = chosen_model
                result.audio_transcript = audio_transcript
                return result
        except Exception as e:
            logger.error(f"OpenAI-compatible request failed: {e}")
            raise
