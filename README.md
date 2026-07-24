# Saamjh Store AI Agent (test build)

Natural-language product Q&A backend for the Saamjh Store storefront chatbot. Given a visitor's
question, it generates a SQL query (Gemini), runs it read-only against the store's Supabase
Postgres database through a restricted `chatbot_readonly` role, and returns a natural-language
answer.

This is the minimal-slice version: NL question -> semantic cache check -> SQL generation ->
execute -> self-heal once on error -> summarize -> cache the answer. No RAG, voice, or tracing
yet — those can be layered on once this core loop is proven out.

## Semantic cache

Before calling Gemini, the question is embedded (`gemini-embedding-2`) and compared against past
questions by cosine similarity (`app/semantic_cache.py`). A match at or above 0.87 similarity
returns the cached answer directly — no SQL generation, no DB query, no summarization call. Only
genuinely successful answers are cached; error/fallback responses (self-heal failed, no SQL
produced) are never cached, so a transient failure can't get "stuck" as the answer to a question
that would otherwise succeed.

The cache is in-memory per process — cleared on restart, not shared across multiple instances.
That's fine for this single-instance test deployment; swap in Redis + a vector index if this ever
runs behind more than one instance.

## Security model

- The backend connects as `chatbot_readonly`, a Postgres role granted `SELECT` only on
  `products`, `categories`, `product_images`. It cannot read or write any other table
  (orders, addresses, contacts, profiles, wishlist_items), regardless of what SQL the LLM
  generates.
- `app/sql_guard.py` adds a defense-in-depth check that rejects anything that isn't a single
  read-only `SELECT` against the allowed tables, before it ever reaches the database.
- The `/chat` endpoint requires a shared-secret `X-API-Key` header (`CHATBOT_API_KEY`) and CORS
  is restricted to `ALLOWED_ORIGINS`.

## Setup

```bash
cp .env.example .env   # fill in DATABASE_URL, GEMINI_API_KEY, CHATBOT_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

## API

`POST /chat`

Headers: `X-API-Key: <CHATBOT_API_KEY>`

```json
{
  "message": "Do you have any featured products under $50?",
  "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello! How can I help?"}]
}
```

Response:

```json
{
  "answer": "Yes, we have ...",
  "sql_used": "SELECT ... FROM products WHERE ...",
  "rows": [...]
}
```

`GET /health` for a liveness check.

## Docker

```bash
docker build -t saamjh-ai-agent .
docker run --env-file .env -p 8080:8080 saamjh-ai-agent
```
