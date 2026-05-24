"""
FAISS-based vector store for semantic retrieval of past conversation context.

Each conversation turn is embedded and stored as a vector. At the start of
each new call, the top-K most semantically relevant past turns are retrieved
and injected into the LLM system prompt as context.

Index is stored on disk at settings.vector_store_path and loaded at startup.
New turns are added at post-call processing time (async via Celery).
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


class FAISSVectorStore:
    """
    FAISS flat L2 index with a metadata sidecar (JSON file).
    Supports per-borrower namespace filtering via borrower_id prefix.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._store_path = Path(settings.vector_store_path)
        self._store_path.mkdir(parents=True, exist_ok=True)
        self._embedding_model = settings.vector_embedding_model
        self._top_k = settings.vector_top_k
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._index: Optional[object] = None          # faiss.IndexFlatL2
        self._metadata: list[dict] = []
        self._dim = 1536   # text-embedding-3-small dimension
        self._load()

    def _index_path(self) -> Path:
        return self._store_path / "index.faiss"

    def _meta_path(self) -> Path:
        return self._store_path / "metadata.pkl"

    def _load(self) -> None:
        try:
            import faiss
            if self._index_path().exists() and self._meta_path().exists():
                self._index = faiss.read_index(str(self._index_path()))
                with open(self._meta_path(), "rb") as f:
                    self._metadata = pickle.load(f)
                logger.info("FAISS index loaded: %d vectors", len(self._metadata))
            else:
                self._index = faiss.IndexFlatL2(self._dim)
                self._metadata = []
                logger.info("FAISS index initialized (empty)")
        except ImportError:
            logger.warning("faiss-cpu not installed — vector store disabled")
            self._index = None

    def _save(self) -> None:
        if self._index is None:
            return
        try:
            import faiss
            faiss.write_index(self._index, str(self._index_path()))
            with open(self._meta_path(), "wb") as f:
                pickle.dump(self._metadata, f)
        except Exception as exc:
            logger.error("Failed to save FAISS index: %s", exc)

    async def _embed(self, text: str) -> np.ndarray:
        response = await self._client.embeddings.create(
            input=text,
            model=self._embedding_model,
        )
        return np.array(response.data[0].embedding, dtype=np.float32)

    async def add_turn(
        self,
        borrower_id: str,
        call_id: str,
        turn_index: int,
        speaker: str,
        text: str,
    ) -> str:
        """Embed and store a conversation turn. Returns a unique embedding_id."""
        if self._index is None:
            return ""
        embedding = await self._embed(text)
        self._index.add(embedding.reshape(1, -1))
        embedding_id = f"{borrower_id}:{call_id}:{turn_index}"
        self._metadata.append({
            "embedding_id": embedding_id,
            "borrower_id": borrower_id,
            "call_id": call_id,
            "turn_index": turn_index,
            "speaker": speaker,
            "text": text,
        })
        self._save()
        return embedding_id

    async def retrieve_context(self, borrower_id: str, query: str) -> str:
        """
        Find the top-K past conversation snippets most relevant to the current
        query text. Returns a formatted string for injection into the system prompt.
        """
        if self._index is None or len(self._metadata) == 0:
            return ""

        query_vec = await self._embed(query)

        import faiss
        distances, indices = self._index.search(query_vec.reshape(1, -1), min(self._top_k * 3, len(self._metadata)))

        results = []
        for idx in indices[0]:
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = self._metadata[idx]
            # Filter to this borrower only
            if meta["borrower_id"] != borrower_id:
                continue
            results.append(meta)
            if len(results) >= self._top_k:
                break

        if not results:
            return ""

        lines = ["Relevant past conversation snippets:"]
        for r in results:
            lines.append(f"  [{r['speaker'].upper()} in call {r['call_id'][:8]}]: {r['text']}")
        return "\n".join(lines)


# Module-level singleton
_store: Optional[FAISSVectorStore] = None


def get_vector_store() -> FAISSVectorStore:
    global _store
    if _store is None:
        _store = FAISSVectorStore()
    return _store
