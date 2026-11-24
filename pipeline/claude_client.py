"""Thin wrapper around the Anthropic API used by every reasoning stage."""
import base64
import hashlib
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


class ClaudeClient:
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
        self.model = os.getenv(
            "LLM_MODEL",
            os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        )
        if self.provider == "ollama":
            self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
            self.temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
            self._client = None
            return
        if self.provider == "openai_compat":
            # OpenAI-compatible endpoint (Ollama /v1 behind a zrok share) with HTTP Basic auth.
            self.base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
            basic_auth = os.getenv("ZROK_BASIC_AUTH", "")
            if not self.base_url or ":" not in basic_auth:
                raise RuntimeError(
                    "LLM_PROVIDER=openai_compat requires LLM_BASE_URL and ZROK_BASIC_AUTH=user:password."
                )
            user, _, password = basic_auth.partition(":")
            # Tolerate a copied "<password>" placeholder shape or quoted value in .env.
            self.auth = (user.strip(), password.strip().strip("<>\"'"))
            self.temperature = float(os.getenv("LLM_TEMPERATURE", "0"))
            self._client = None
            return

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_api_key_here":
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set LLM_PROVIDER=ollama for local reasoning "
                "or configure an Anthropic API key."
            )
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)

    @staticmethod
    def cache_path(model: str, system_prompt: str, user_prompt: str) -> Path:
        digest = hashlib.sha256("\0".join((model, system_prompt, user_prompt)).encode("utf-8")).hexdigest()
        return Path(os.getenv("LLM_CACHE_DIR", ".llm_cache")) / f"{digest}.txt"

    def _call_openai_compat(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        # Responses are cached on disk (temperature 0) so a failed run resumes without repeating slow calls.
        cache_file = self.cache_path(self.model, system_prompt, user_prompt)
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
        content = self._request_openai_compat(system_prompt, user_prompt, max_tokens)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(content, encoding="utf-8")
        return content

    def _request_openai_compat(
        self, system_prompt: str, user_prompt: str, max_tokens: int, images: list[tuple[str, str]] | None = None
    ) -> str:
        # Reasoning models spend tokens on hidden thinking before the answer, so add headroom.
        headroom = int(os.getenv("LLM_REASONING_HEADROOM", "8192"))
        budget_cap = int(os.getenv("LLM_MAX_TOTAL_TOKENS", "65536"))
        budget = max_tokens + headroom
        user_content: str | list = user_prompt
        if images:
            user_content = [{"type": "text", "text": user_prompt}] + [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}}
                for media_type, data in images
            ]
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": budget,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        attempts = int(os.getenv("LLM_RETRIES", "3"))
        last_error: Exception = RuntimeError("no attempt made")
        for attempt in range(attempts):
            started = time.time()
            try:
                # Streaming keeps the tunnel connection active while the model reasons,
                # avoiding gateway timeouts on long prompts.
                with requests.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    auth=self.auth,
                    stream=True,
                    timeout=(30, int(os.getenv("OLLAMA_TIMEOUT", "600"))),
                ) as response:
                    if response.status_code >= 500:
                        raise RuntimeError(f"LLM server error {response.status_code}")
                    response.raise_for_status()
                    # SSE responses carry no charset, so requests would decode UTF-8 text as latin-1.
                    response.encoding = "utf-8"
                    parts = []
                    finish = None
                    for line in response.iter_lines(decode_unicode=True):
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        choices = json.loads(data).get("choices") or []
                        if choices:
                            piece = (choices[0].get("delta") or {}).get("content")
                            if piece:
                                parts.append(piece)
                            finish = choices[0].get("finish_reason") or finish
                content = "".join(parts)
                if finish is None:
                    raise RuntimeError("LLM stream ended without a finish signal (connection dropped).")
                if finish == "length":
                    # An identical retry would truncate again, so give the next attempt more headroom.
                    next_budget = min(max_tokens + headroom * 2, budget_cap)
                    message = f"LLM output truncated at {budget} tokens"
                    if next_budget > budget:
                        headroom *= 2
                        budget = next_budget
                        body["max_tokens"] = budget
                        message += f"; retrying with a {budget}-token budget"
                    else:
                        message += "; raise LLM_MAX_TOTAL_TOKENS or LLM_REASONING_HEADROOM"
                    raise RuntimeError(message)
                if not content.strip():
                    raise RuntimeError("LLM returned no message content (token budget may be exhausted by reasoning).")
                return content
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                last_error = exc
                print(
                    f"[LLM] attempt {attempt + 1}/{attempts} failed after {time.time() - started:.0f}s "
                    f"(prompt {len(system_prompt) + len(user_prompt)} chars): {exc}",
                    flush=True,
                )
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"LLM call failed after {attempts} attempts: {last_error}")

    def extract_image_text(self, system_prompt: str, user_prompt: str, image_path: Path, max_tokens: int = 4096) -> str:
        """Transcribe a requirement image with the model's vision input (results are cached by the caller)."""
        media_type = IMAGE_MEDIA_TYPES[image_path.suffix.lower()]
        data = base64.b64encode(image_path.read_bytes()).decode("ascii")

        if self.provider == "ollama":
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt, "images": [data]},
                    ],
                    "options": {"temperature": self.temperature, "num_predict": max_tokens},
                },
                timeout=int(os.getenv("OLLAMA_TIMEOUT", "600")),
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Ollama returned no text for the image; use a vision-capable model.")
            return content

        if self.provider == "openai_compat":
            return self._request_openai_compat(system_prompt, user_prompt, max_tokens, [(media_type, data)])

        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": user_prompt},
                ],
            }],
        )
        return "".join(block.text for block in response.content if block.type == "text")

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        if self.provider == "ollama":
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "options": {"temperature": self.temperature, "num_predict": max_tokens},
                },
                timeout=int(os.getenv("OLLAMA_TIMEOUT", "600")),
            )
            response.raise_for_status()
            payload = response.json()
            content = payload.get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise RuntimeError("Ollama returned no message content.")
            return content

        if self.provider == "openai_compat":
            return self._call_openai_compat(system_prompt, user_prompt, max_tokens)

        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
