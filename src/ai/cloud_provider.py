import base64
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict
import httpx

from src.ai.base import BaseVisionProvider, FrameItem, VideoAnalysisResult
from src.ai.prompt import SYSTEM_PROMPT, get_system_prompt, build_user_prompt, parse_ai_response

logger = logging.getLogger(__name__)

class CloudVisionProvider(BaseVisionProvider):
    """Optional cloud provider fallback supporting Gemini, Anthropic, and OpenAI."""

    def __init__(self, provider: str = "gemini", api_keys: Optional[Dict[str, str]] = None):
        self.provider = provider.lower()
        self.api_keys = api_keys or {}

    def is_available(self) -> bool:
        key = self.api_keys.get(self.provider, "")
        return bool(key and key.strip())

    def list_models(self) -> List[str]:
        if self.provider == "gemini":
            return ["gemini-2.5-flash", "gemini-2.5-pro"]
        elif self.provider == "anthropic":
            return ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]
        elif self.provider == "openai":
            return ["gpt-4o", "gpt-4o-mini"]
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
        if self.provider == "gemini":
            return self._call_gemini(frames, audio_transcript, context_prompt, model or "gemini-2.5-flash", system_prompt, prompt_guidance, slug_guidance=slug_guidance, timeout_seconds=timeout_seconds)
        elif self.provider == "anthropic":
            return self._call_anthropic(frames, audio_transcript, context_prompt, model or "claude-3-5-sonnet-20241022", system_prompt, prompt_guidance, slug_guidance=slug_guidance, timeout_seconds=timeout_seconds)
        elif self.provider == "openai":
            return self._call_openai(frames, audio_transcript, context_prompt, model or "gpt-4o-mini", system_prompt, prompt_guidance, slug_guidance=slug_guidance, timeout_seconds=timeout_seconds)
        else:
            raise ValueError(f"Unsupported cloud provider: {self.provider}")

    def _call_gemini(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, timeout_seconds=None):
        api_key = self.api_keys.get("gemini")
        if not api_key:
            raise ValueError("Gemini API key is missing.")

        timestamps = [f.timecode for f in frames]
        user_text = build_user_prompt(timestamps, audio_transcript, context_prompt, prompt_guidance=prompt_guidance, slug_guidance=slug_guidance)
        active_system_prompt = get_system_prompt(system_prompt)

        parts = []
        for f in frames:
            p = Path(f.path)
            if p.exists():
                with open(p, "rb") as img:
                    b64 = base64.b64encode(img.read()).decode("utf-8")
                    parts.append({
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64
                        }
                    })
        parts.append({"text": f"{active_system_prompt}\n\n{user_text}"})

        timeout_val = float(timeout_seconds if timeout_seconds is not None else 300.0)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        with httpx.Client(timeout=timeout_val) as client:
            res = client.post(url, json={"contents": [{"parts": parts}]})
            res.raise_for_status()
            data = res.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            res_obj = parse_ai_response(raw_text)
            res_obj.provider_name = "gemini"
            res_obj.model_name = model
            res_obj.audio_transcript = audio_transcript
            return res_obj

    def _call_anthropic(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, timeout_seconds=None):
        api_key = self.api_keys.get("anthropic")
        if not api_key:
            raise ValueError("Anthropic API key is missing.")

        timestamps = [f.timecode for f in frames]
        user_text = build_user_prompt(timestamps, audio_transcript, context_prompt, prompt_guidance=prompt_guidance, slug_guidance=slug_guidance)
        active_system_prompt = get_system_prompt(system_prompt)

        content = []
        for f in frames:
            p = Path(f.path)
            if p.exists():
                with open(p, "rb") as img:
                    b64 = base64.b64encode(img.read()).decode("utf-8")
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64
                        }
                    })
        content.append({"type": "text", "text": user_text})

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": model,
            "max_tokens": 2048,
            "system": active_system_prompt,
            "messages": [{"role": "user", "content": content}]
        }
        timeout_val = float(timeout_seconds if timeout_seconds is not None else 300.0)
        with httpx.Client(timeout=timeout_val) as client:
            res = client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
            res.raise_for_status()
            raw_text = res.json()["content"][0]["text"]
            res_obj = parse_ai_response(raw_text)
            res_obj.provider_name = "anthropic"
            res_obj.model_name = model
            res_obj.audio_transcript = audio_transcript
            return res_obj

    def _call_openai(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, timeout_seconds=None):
        api_key = self.api_keys.get("openai")
        if not api_key:
            raise ValueError("OpenAI API key is missing.")

        from src.ai.openai_provider import OpenAICompatibleVisionProvider
        provider = OpenAICompatibleVisionProvider(
            base_url="https://api.openai.com/v1",
            api_key=api_key,
            default_model=model
        )
        res_obj = provider.describe_video(
            frames,
            audio_transcript,
            context_prompt,
            model=model,
            system_prompt=system_prompt,
            prompt_guidance=prompt_guidance,
            slug_guidance=slug_guidance,
            timeout_seconds=timeout_seconds
        )
        res_obj.provider_name = "openai"
        return res_obj
