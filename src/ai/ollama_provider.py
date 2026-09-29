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

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "llama3.2-vision",
        default_num_ctx: int = 16384
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.default_num_ctx = default_num_ctx

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
        prompt_guidance: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        num_ctx: Optional[int] = None,
        **kwargs
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

        # Calculate context window size (num_ctx)
        target_ctx = num_ctx if num_ctx is not None else self.default_num_ctx
        
        # Estimate token requirement:
        # - Vision encoders: ~1000 - 1500 tokens per image frame
        # - Prompt text: ~1 token per 3-4 chars
        # - Generation reserve: 2048 tokens for JSON response
        est_image_tokens = len(b64_images) * 1250
        est_text_tokens = (len(active_system_prompt) + len(user_text)) // 3
        est_needed_tokens = est_image_tokens + est_text_tokens + 2048

        if not target_ctx or target_ctx <= 0:
            # Auto mode: round up to nearest multiple of 4096 (minimum 8192)
            active_ctx = max(8192, ((est_needed_tokens + 4095) // 4096) * 4096)
        else:
            # If user configured a specific ctx, but estimated tokens exceed it, auto-scale up
            if est_needed_tokens > target_ctx:
                scaled_ctx = ((est_needed_tokens + 4095) // 4096) * 4096
                logger.info(
                    f"Estimated prompt tokens ({est_needed_tokens}) exceed configured Ollama num_ctx ({target_ctx}). "
                    f"Auto-adjusting num_ctx to {scaled_ctx}."
                )
                active_ctx = scaled_ctx
            else:
                active_ctx = target_ctx

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
            "format": "json",
            "options": {
                "num_ctx": active_ctx,
                "temperature": 0.2
            }
        }

        # Configurable generous timeout for local vision models (default 600s = 10 min for large 27B+ models)
        timeout_val = float(timeout_seconds if timeout_seconds is not None else 600.0)
        timeout = httpx.Timeout(timeout_val, connect=15.0)
        
        max_attempts = 2
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(max_attempts):
                try:
                    res = client.post(f"{self.base_url}/api/chat", json=payload)
                    
                    # Self-healing: Check for 400 Bad Request caused by context window overflow
                    # e.g., "error: request (4188 tokens) exceeds the available context size (4096 tokens), try increasing it"
                    if getattr(res, "status_code", 200) == 400 and attempt < max_attempts - 1:
                        err_text = ""
                        try:
                            err_text = res.text
                        except Exception:
                            pass
                        
                        import re
                        ctx_match = re.search(r"request \((\d+) tokens\).*?context size \((\d+) tokens\)", err_text, re.IGNORECASE)
                        tokens_found = re.findall(r"(\d+) tokens", err_text)
                        
                        if ctx_match or "exceeds the available context size" in err_text.lower():
                            if ctx_match:
                                req_tokens = int(ctx_match.group(1))
                            elif tokens_found:
                                req_tokens = int(tokens_found[0])
                            else:
                                req_tokens = payload["options"]["num_ctx"] * 2
                            
                            new_ctx = max(req_tokens + 2048, ((req_tokens + 4095) // 4096) * 4096)
                            if new_ctx <= payload["options"]["num_ctx"]:
                                new_ctx = payload["options"]["num_ctx"] + 4096
                                
                            prev_ctx = payload["options"]["num_ctx"]
                            logger.warning(
                                f"Ollama context exceeded: {err_text.strip()}. "
                                f"Auto-scaling num_ctx from {prev_ctx} to {new_ctx} and retrying..."
                            )
                            payload = {**payload, "options": {**payload.get("options", {}), "num_ctx": new_ctx}}
                            continue

                    res.raise_for_status()
                    data = res.json()
                    raw_content = data.get("message", {}).get("content", "")
                    result = parse_ai_response(raw_content)
                    result.provider_name = "ollama"
                    result.model_name = chosen_model
                    result.audio_transcript = audio_transcript
                    return result
                except httpx.HTTPStatusError as e:
                    if attempt == max_attempts - 1:
                        logger.error(f"Ollama vision request failed after retries: {e}")
                        raise
                except Exception as e:
                    logger.error(f"Ollama vision request failed: {e}")
                    raise
