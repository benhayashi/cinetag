import base64
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
import httpx

from src.ai.base import BaseVisionProvider, FrameItem, VideoAnalysisResult
from src.ai.prompt import SYSTEM_PROMPT, get_system_prompt, build_user_prompt, parse_ai_response
from src.ai.openai_provider import OpenAICompatibleVisionProvider

logger = logging.getLogger(__name__)

# Standard recommendations for vision-capable models by provider
RECOMMENDED_MODELS: Dict[str, List[str]] = {
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-2.0-flash"
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
        "gpt-4.5-preview"
    ],
    "anthropic": [
        "claude-3-5-sonnet-20241022",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-haiku-20241022"
    ],
    "openrouter": [
        "google/gemini-2.5-flash",
        "openai/gpt-4o",
        "anthropic/claude-3.5-sonnet",
        "qwen/qwen-2.5-vl-72b-instruct",
        "meta-llama/llama-3.2-11b-vision-instruct"
    ],
    "custom_openai": [
        "gpt-4o",
        "qwen2.5-vl",
        "llama-3.2-vision"
    ]
}

class CloudVisionProvider(BaseVisionProvider):
    """
    Cloud provider supporting Google Gemini, OpenAI, Anthropic Claude,
    OpenRouter, and custom OpenAI-standard API endpoints.
    """

    def __init__(
        self,
        provider: str = "gemini",
        api_keys: Optional[Dict[str, str]] = None,
        default_model: Optional[str] = None,
        custom_endpoint: Optional[str] = None
    ):
        self.provider = (provider or "gemini").lower()
        self.api_keys = api_keys or {}
        self.default_model = default_model
        self.custom_endpoint = (custom_endpoint or "").strip()

    def get_api_key(self) -> str:
        """Resolve API key for the active provider."""
        key = self.api_keys.get(self.provider, "")
        if not key and self.provider == "custom_openai":
            key = self.api_keys.get("custom", "")
        return (key or "").strip()

    def is_available(self) -> bool:
        key = self.get_api_key()
        return bool(key)

    def list_models(self) -> List[str]:
        return RECOMMENDED_MODELS.get(self.provider, RECOMMENDED_MODELS.get("gemini", []))

    def describe_video(
        self,
        frames: List[FrameItem],
        audio_transcript: Optional[str] = None,
        context_prompt: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt_guidance: Optional[str] = None,
        slug_guidance: Optional[str] = None,
        filename_context: Optional[str] = None,
        timeout_seconds: Optional[int] = None
    ) -> VideoAnalysisResult:
        chosen_model = model or self.default_model

        if self.provider == "gemini":
            return self._call_gemini(
                frames, audio_transcript, context_prompt,
                chosen_model or "gemini-2.5-flash",
                system_prompt, prompt_guidance, slug_guidance=slug_guidance,
                filename_context=filename_context,
                timeout_seconds=timeout_seconds
            )
        elif self.provider == "anthropic":
            return self._call_anthropic(
                frames, audio_transcript, context_prompt,
                chosen_model or "claude-3-5-sonnet-20241022",
                system_prompt, prompt_guidance, slug_guidance=slug_guidance,
                filename_context=filename_context,
                timeout_seconds=timeout_seconds
            )
        elif self.provider == "openai":
            return self._call_openai(
                frames, audio_transcript, context_prompt,
                chosen_model or "gpt-4o",
                system_prompt, prompt_guidance, slug_guidance=slug_guidance,
                filename_context=filename_context,
                timeout_seconds=timeout_seconds
            )
        elif self.provider == "openrouter":
            return self._call_openrouter(
                frames, audio_transcript, context_prompt,
                chosen_model or "google/gemini-2.5-flash",
                system_prompt, prompt_guidance, slug_guidance=slug_guidance,
                filename_context=filename_context,
                timeout_seconds=timeout_seconds
            )
        elif self.provider in ("custom_openai", "custom"):
            return self._call_custom_openai(
                frames, audio_transcript, context_prompt,
                chosen_model or "gpt-4o",
                system_prompt, prompt_guidance, slug_guidance=slug_guidance,
                filename_context=filename_context,
                timeout_seconds=timeout_seconds
            )
        else:
            raise ValueError(f"Unsupported cloud provider: {self.provider}")

    def _call_gemini(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, filename_context=None, timeout_seconds=None):
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("Google Gemini API key is missing. Configure it in Settings > Cloud Provider.")

        timestamps = [f.timecode for f in frames]
        user_text = build_user_prompt(
            timestamps,
            audio_transcript,
            context_prompt,
            prompt_guidance=prompt_guidance,
            slug_guidance=slug_guidance,
            filename_context=filename_context
        )
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

    def _call_anthropic(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, filename_context=None, timeout_seconds=None):
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("Anthropic API key is missing. Configure it in Settings > Cloud Provider.")

        timestamps = [f.timecode for f in frames]
        user_text = build_user_prompt(
            timestamps,
            audio_transcript,
            context_prompt,
            prompt_guidance=prompt_guidance,
            slug_guidance=slug_guidance,
            filename_context=filename_context
        )
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

    def _call_openai(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, filename_context=None, timeout_seconds=None):
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("OpenAI API key is missing. Configure it in Settings > Cloud Provider.")

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
            filename_context=filename_context,
            timeout_seconds=timeout_seconds
        )
        res_obj.provider_name = "openai"
        return res_obj

    def _call_openrouter(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, filename_context=None, timeout_seconds=None):
        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("OpenRouter API key is missing. Configure it in Settings > Cloud Provider.")

        provider = OpenAICompatibleVisionProvider(
            base_url="https://openrouter.ai/api/v1",
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
            filename_context=filename_context,
            timeout_seconds=timeout_seconds
        )
        res_obj.provider_name = "openrouter"
        return res_obj

    def _call_custom_openai(self, frames, audio_transcript, context_prompt, model, system_prompt=None, prompt_guidance=None, slug_guidance=None, filename_context=None, timeout_seconds=None):
        api_key = self.get_api_key()
        endpoint = self.custom_endpoint or "https://api.openai.com/v1"

        provider = OpenAICompatibleVisionProvider(
            base_url=endpoint,
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
            filename_context=filename_context,
            timeout_seconds=timeout_seconds
        )
        res_obj.provider_name = "custom_openai"
        return res_obj

    def probe_connection(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        endpoint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Probe credentials and connectivity against the target cloud provider.
        Returns a diagnostic dictionary with connection status and available models.
        """
        prov = (provider or self.provider).lower()
        key = api_key if api_key is not None else self.get_api_key()
        ep = (endpoint or self.custom_endpoint or "").strip()
        active_model = model or self.default_model

        if not key:
            return {
                "connected": False,
                "provider": prov,
                "model": active_model,
                "models": RECOMMENDED_MODELS.get(prov, []),
                "error": f"API key is missing for {prov}."
            }

        try:
            if prov == "gemini":
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        fetched = [
                            m.get("name", "").replace("models/", "")
                            for m in data.get("models", [])
                            if "generateContent" in m.get("supportedGenerationMethods", [])
                        ]
                        return {
                            "connected": True,
                            "provider": "gemini",
                            "model": active_model or "gemini-2.5-flash",
                            "models": fetched if fetched else RECOMMENDED_MODELS["gemini"]
                        }
                    elif resp.status_code in (400, 401, 403):
                        return {
                            "connected": False,
                            "provider": "gemini",
                            "error": f"Invalid Gemini API key (HTTP {resp.status_code})"
                        }
                    else:
                        resp.raise_for_status()

            elif prov == "anthropic":
                headers = {
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01"
                }
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get("https://api.anthropic.com/v1/models", headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        fetched = [m.get("id") for m in data.get("data", []) if "id" in m]
                        return {
                            "connected": True,
                            "provider": "anthropic",
                            "model": active_model or "claude-3-5-sonnet-20241022",
                            "models": fetched if fetched else RECOMMENDED_MODELS["anthropic"]
                        }
                    elif resp.status_code in (401, 403):
                        return {
                            "connected": False,
                            "provider": "anthropic",
                            "error": f"Invalid Anthropic API key (HTTP {resp.status_code})"
                        }
                    else:
                        resp.raise_for_status()

            elif prov == "openai":
                headers = {
                    "Authorization": f"Bearer {key}"
                }
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get("https://api.openai.com/v1/models", headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        all_models = [m.get("id") for m in data.get("data", []) if "id" in m]
                        v_models = [m for m in all_models if "gpt-4" in m or "o1" in m]
                        return {
                            "connected": True,
                            "provider": "openai",
                            "model": active_model or "gpt-4o",
                            "models": v_models if v_models else RECOMMENDED_MODELS["openai"]
                        }
                    elif resp.status_code in (401, 403):
                        return {
                            "connected": False,
                            "provider": "openai",
                            "error": f"Invalid OpenAI API key (HTTP {resp.status_code})"
                        }
                    else:
                        resp.raise_for_status()

            elif prov == "openrouter":
                headers = {
                    "Authorization": f"Bearer {key}"
                }
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get("https://openrouter.ai/api/v1/models", headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        fetched = [m.get("id") for m in data.get("data", []) if "id" in m]
                        return {
                            "connected": True,
                            "provider": "openrouter",
                            "model": active_model or "google/gemini-2.5-flash",
                            "models": fetched[:20] if fetched else RECOMMENDED_MODELS["openrouter"]
                        }
                    elif resp.status_code in (401, 403):
                        return {
                            "connected": False,
                            "provider": "openrouter",
                            "error": f"Invalid OpenRouter API key (HTTP {resp.status_code})"
                        }
                    else:
                        resp.raise_for_status()

            elif prov in ("custom_openai", "custom"):
                target_base = ep or "https://api.openai.com/v1"
                headers = {
                    "Authorization": f"Bearer {key}"
                }
                with httpx.Client(timeout=8.0) as client:
                    models_url = f"{target_base.rstrip('/')}/models"
                    resp = client.get(models_url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        fetched = [m.get("id") for m in data.get("data", []) if "id" in m]
                        return {
                            "connected": True,
                            "provider": "custom_openai",
                            "model": active_model or "gpt-4o",
                            "models": fetched if fetched else RECOMMENDED_MODELS["custom_openai"]
                        }
                    elif resp.status_code in (401, 403):
                        return {
                            "connected": False,
                            "provider": "custom_openai",
                            "error": f"Unauthorized on custom endpoint (HTTP {resp.status_code})"
                        }
                    else:
                        return {
                            "connected": True,
                            "provider": "custom_openai",
                            "model": active_model or "gpt-4o",
                            "models": RECOMMENDED_MODELS["custom_openai"]
                        }

            return {
                "connected": False,
                "provider": prov,
                "error": f"Unknown cloud provider: {prov}"
            }

        except Exception as e:
            return {
                "connected": False,
                "provider": prov,
                "model": active_model,
                "models": RECOMMENDED_MODELS.get(prov, []),
                "error": f"Connection check failed: {str(e)}"
            }
