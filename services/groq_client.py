from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


class GroqProviderError(Exception):
    pass


class GroqClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = "llama-3.3-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1/chat/completions",
    ) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.base_url = base_url

    async def generate_lesson_idea(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.api_key:
            raise GroqProviderError("GROQ_API_KEY가 설정되지 않아 자료 기반 추천으로 전환합니다.")

        payload = {
            "model": self.model,
            "stream": False,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise GroqProviderError(self._format_error(response))

        data = response.json()
        message = data["choices"][0]["message"]["content"]
        return self._extract_json(str(message))

    def _format_error(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            return f"Groq 요청이 실패했습니다. 상태 코드: {response.status_code}"

        message = payload.get("error", {}).get("message") or payload.get("message")
        if message:
            return f"Groq 요청 실패: {message}"
        return f"Groq 요청이 실패했습니다. 상태 코드: {response.status_code}"

    def _extract_json(self, text: str) -> dict[str, Any]:
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise GroqProviderError("Groq 응답을 JSON으로 해석하지 못했습니다.")
            return json.loads(match.group(0))
