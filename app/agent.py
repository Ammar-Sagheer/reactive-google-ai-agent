import json
import logging

from google import genai
from google.genai import types
from pydantic import BaseModel

from app import semantic_cache
from app.config import settings
from app.db import run_select
from app.schema import SCHEMA_DESCRIPTION
from app.sql_guard import UnsafeQueryError

logger = logging.getLogger("agent")

_client = genai.Client(api_key=settings.gemini_api_key)

_SQL_SYSTEM_PROMPT = f"""You are the product-catalog assistant for an e-commerce storefront called Saamjh Store.
You answer visitor questions about products, categories, prices, stock, and featured items.

{SCHEMA_DESCRIPTION}

If the visitor's question requires looking up product data, set `needs_sql` to true and put a
SELECT query in `sql`.
If the question is general conversation (greetings, "what can you help with", etc.) and needs no
database lookup, set `needs_sql` to false and put a short friendly answer in `direct_answer`.
Never invent product data yourself; always query for it.
"""


class SqlDecision(BaseModel):
    needs_sql: bool
    sql: str = ""
    direct_answer: str = ""


class ChatResponse(BaseModel):
    answer: str
    sql_used: str | None = None
    rows: list[dict] | None = None
    from_cache: bool = False


async def _generate_sql_decision(question: str, history: list[dict]) -> SqlDecision:
    contents = _history_to_contents(history) + [
        types.Content(role="user", parts=[types.Part(text=question)])
    ]
    response = await _client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_SQL_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SqlDecision,
            temperature=0,
        ),
    )
    return SqlDecision.model_validate_json(response.text)


async def _self_heal_sql(question: str, failed_sql: str, error: str) -> SqlDecision:
    heal_prompt = (
        f"Your previous SQL failed.\n\nOriginal question: {question}\n"
        f"Failed SQL: {failed_sql}\nDatabase error: {error}\n\n"
        "Produce a corrected SELECT query following the same rules."
    )
    response = await _client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Content(role="user", parts=[types.Part(text=heal_prompt)])],
        config=types.GenerateContentConfig(
            system_instruction=_SQL_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=SqlDecision,
            temperature=0,
        ),
    )
    return SqlDecision.model_validate_json(response.text)


async def _summarize(question: str, rows: list[dict]) -> str:
    summary_prompt = (
        "You are a friendly storefront assistant. Given the visitor's question and the "
        "database rows below (JSON), write a concise, natural-language answer. If the rows "
        "are empty, say the store doesn't have anything matching. Do not mention SQL or tables. "
        "If a row represents a product being recommended or referenced, include a link to it "
        "as /products/<slug> (using that row's slug field) in the answer text. Never link to "
        "an image_url as if it were the product page.\n\n"
        f"Question: {question}\nRows: {json.dumps(rows, default=str)}"
    )
    response = await _client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[types.Content(role="user", parts=[types.Part(text=summary_prompt)])],
        config=types.GenerateContentConfig(temperature=0.3),
    )
    return response.text.strip()


def _history_to_contents(history: list[dict]) -> list[types.Content]:
    contents = []
    for turn in history[-6:]:
        role = "user" if turn.get("role") == "user" else "model"
        contents.append(types.Content(role=role, parts=[types.Part(text=turn.get("content", ""))]))
    return contents


async def answer_question(question: str, history: list[dict] | None = None) -> ChatResponse:
    history = history or []

    query_embedding = await semantic_cache.embed(_client, question)
    cached = semantic_cache.find(query_embedding, question)
    if cached is not None:
        return ChatResponse(
            answer=cached.answer,
            sql_used=cached.sql_used,
            rows=cached.rows,
            from_cache=True,
        )

    decision = await _generate_sql_decision(question, history)

    if not decision.needs_sql or not decision.sql:
        response = ChatResponse(answer=decision.direct_answer or "I'm not sure how to help with that.")
        semantic_cache.store(question, query_embedding, response.answer, response.sql_used, response.rows)
        return response

    sql = decision.sql
    try:
        rows = await run_select(sql)
    except (UnsafeQueryError, Exception) as first_error:  # noqa: BLE001
        logger.warning("SQL failed, attempting self-heal: %s", first_error)
        try:
            healed = await _self_heal_sql(question, sql, str(first_error))
            if not healed.needs_sql or not healed.sql:
                # Not cached: a fixable rephrase later shouldn't be stuck with this answer.
                return ChatResponse(answer="I couldn't find an answer to that in the store's catalog.")
            sql = healed.sql
            rows = await run_select(sql)
        except (UnsafeQueryError, Exception) as second_error:  # noqa: BLE001
            logger.error("Self-heal failed: %s", second_error)
            # Not cached: a transient failure shouldn't be locked in as the answer.
            return ChatResponse(
                answer="Sorry, I couldn't look that up right now. Try rephrasing your question."
            )

    answer_text = await _summarize(question, rows)
    semantic_cache.store(question, query_embedding, answer_text, sql, rows)
    return ChatResponse(answer=answer_text, sql_used=sql, rows=rows)
