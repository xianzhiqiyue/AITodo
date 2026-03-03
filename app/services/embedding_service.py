from __future__ import annotations

import structlog
import httpx

from app.config import Settings

logger = structlog.get_logger()


class EmbeddingService:
    def __init__(self, settings: Settings):
        self._api_key = settings.embedding_api_key
        self._base_url = settings.embedding_base_url.rstrip("/")
        self._model = "text-embedding-3-small"

    async def generate_embedding(self, text: str) -> list[float] | None:
        if not self._api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "input": text[:8000],
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
        except Exception:
            logger.warning("embedding_generation_failed", text_length=len(text), exc_info=True)
            return None
