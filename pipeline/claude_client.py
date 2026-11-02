"""Thin wrapper around the Anthropic API used by every reasoning stage."""
import os

import requests
from dotenv import load_dotenv

load_dotenv()


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

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key or api_key == "your_api_key_here":
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Set LLM_PROVIDER=ollama for local reasoning "
                "or configure an Anthropic API key."
            )
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)

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

        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if block.type == "text")
