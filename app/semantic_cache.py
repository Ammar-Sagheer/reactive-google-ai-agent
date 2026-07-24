import time
from dataclasses import dataclass, field

from google.genai import types

EMBEDDING_MODEL = "gemini-embedding-2"
EMBEDDING_DIMENSIONS = 768
SIMILARITY_THRESHOLD = 0.87
MAX_ENTRIES = 500


@dataclass
class CacheEntry:
    question: str
    embedding: list[float]
    answer: str
    sql_used: str | None
    rows: list[dict] | None
    created_at: float = field(default_factory=time.time)


# In-memory only: cleared on restart, not shared across instances.
# Fine for a single-process test deployment; swap for Redis + vector search
# if/when this runs behind multiple instances.
_cache: list[CacheEntry] = []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def embed(client, text: str) -> list[float]:
    result = await client.aio.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
    )
    return result.embeddings[0].values


def find(query_embedding: list[float]) -> CacheEntry | None:
    best_entry = None
    best_score = 0.0
    for entry in _cache:
        score = _cosine_similarity(query_embedding, entry.embedding)
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_entry and best_score >= SIMILARITY_THRESHOLD:
        return best_entry
    return None


def store(
    question: str,
    embedding: list[float],
    answer: str,
    sql_used: str | None,
    rows: list[dict] | None,
) -> None:
    _cache.append(
        CacheEntry(question=question, embedding=embedding, answer=answer, sql_used=sql_used, rows=rows)
    )
    if len(_cache) > MAX_ENTRIES:
        _cache.pop(0)
