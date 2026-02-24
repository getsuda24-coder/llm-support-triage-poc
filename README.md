# LLM Support Triage POC — Agentic RAG (Local, Docker)

A local, Dockerized Proof of Concept showing an end-to-end **support workflow powered by an LLM agent**:

**Tickets → Agent decides tool calls (RAG) → Grounded draft → Auto vs Human routing → Human edits/approval → Audit log**

✅ Everything is **synthetic / generic** (safe to publish).  
✅ Runs **fully locally** with **SQLite** (including search via **FTS5**).  
✅ Default LLM is **mock** (no external API). Optional OpenAI tool calling can be enabled later.

---

## Why this project

Many teams want to use LLMs in production, but the hard part isn’t “calling a model” — it’s building the **workflow**:

- When to retrieve facts (RAG)?
- How to keep responses grounded?
- When to auto-send vs require a human?
- How to log decisions and edits?

This POC demonstrates a clean, minimal baseline for those concerns.

---

## Features

### ✅ Ticket lifecycle
- Seed synthetic tickets (`POST /seed`)
- List and inspect tickets (`GET /tickets`, `GET /tickets/{id}`)

### ✅ Agentic RAG (tool calling)
The agent can call:
- `kb_search(query)` — retrieve relevant KB entries
- `kb_get_doc(doc_id)` — fetch exact documents for grounding

The result includes:
- `rag_sources` (what was used)
- `rag_context` (retrieved snippets)
- `agent_trace` (tool call log, for debugging & transparency)

### ✅ Draft generation + routing
- Generate a draft reply (`POST /tickets/{id}/draft`)
- Route decision based on a risk score:
  - `auto_send` (low risk)
  - `needs_human` (high risk / sensitive)

### ✅ Human-in-the-loop
- Approve and send
- Edit and send (edits are stored)
- Reject (forces manual handling)

### ✅ Minimal UI
A lightweight HTML page on `/` to demo the flow quickly.
Swagger docs available on `/docs`.

---

## Tech stack

- **FastAPI** (API + docs)
- **SQLite** (storage)
- **SQLite FTS5** (RAG retrieval via full-text search)
- **Docker Compose** (one command to run)
- **Mock agent** by default (deterministic tool-calling behavior)

---

## Quick start (Docker)

```bash
cp .env.example .env
docker compose up --build
```

Open:
- UI: http://localhost:8000
- API docs: http://localhost:8000/docs

Data persists in:
- `./data/app.db`

---

## Demo flow

### 1) Seed knowledge base (synthetic invoices)
```bash
curl -X POST http://localhost:8000/kb/seed_invoices
```

### 2) Seed tickets
```bash
curl -X POST http://localhost:8000/seed \
  -H "Content-Type: application/json" \
  -d '{"count": 8}'
```

### 3) Generate a draft (agent + tool calls)
```bash
curl -X POST http://localhost:8000/tickets/1/draft
```

Look for:
- `rag_sources`
- `rag_context`
- `agent_trace`

### 4) Human review (approve / edit / reject)
```bash
curl -X POST http://localhost:8000/tickets/1/review \
  -H "Content-Type: application/json" \
  -d '{"action":"edit_and_send","edited_reply":"(your edited reply)","reviewer":"mickael"}'
```

---

## API overview

### Tickets
- `POST /seed` — create synthetic tickets
- `GET /tickets` — list tickets
- `GET /tickets/{id}` — ticket details (latest draft + decision)
- `POST /tickets/{id}/draft` — agent generates grounded draft + routing
- `POST /tickets/{id}/review` — human decision (approve/edit/reject)

### Knowledge base (RAG)
- `POST /kb/seed_invoices` — seed synthetic invoice docs
- `POST /kb/docs` — add a doc manually
- `GET /kb/search?q=...` — search KB

---

## Project structure

```text
llm-support-poc/
  docker-compose.yml
  Dockerfile
  requirements.txt
  .env.example
  data/                  # persisted SQLite DB (app.db)
  src/
    app/
      main.py             # FastAPI routes
      db.py               # SQLite schema + queries (+ FTS5 search)
      agent.py            # agent (tool calling) - mock + optional OpenAI
      tools.py            # kb_search / kb_get_doc tools used by the agent
      router.py           # risk scoring & auto/human routing
      seed.py             # synthetic tickets generator
      rag_seed.py         # synthetic invoice KB seed
      templates/
        index.html        # minimal UI
```

---

## Configuration (.env)

Key vars:

- `LLM_PROVIDER=mock` *(default)*
- `AUTO_SEND_MAX_RISK=0.30`
- `RAG_TOP_K=4`
- `RAG_MAX_CHARS=1400`

Database path (inside container):
- `DB_PATH=/app/data/app.db`

---

## Notes on “Mock” vs “OpenAI”

### Default: mock
No external calls. The agent behaves like a tool-calling model:
- detects invoice/billing signals
- searches KB
- fetches docs
- drafts a grounded reply

### Optional: real tool calling (later)
`src/app/agent.py` already contains an `OpenAIToolCallingAgent` implementation.
To enable:
1) add `openai` to requirements
2) set:
   - `LLM_PROVIDER=openai`
   - `OPENAI_API_KEY=...`
   - `OPENAI_MODEL=...`

---

## Extending this POC

Easy upgrades:
- Replace FTS retrieval with embeddings (FAISS/Chroma)
- Add more tools (SQL queries, user profile lookup, refund policy, etc.)
- Add a real “send email” integration (kept out intentionally)
- Add tests + CI
- Improve routing (model-based classifier, SLA handling, etc.)

---

## Disclaimer

This repository uses **synthetic tickets and synthetic invoices** only.
It is not connected to any real customer data or proprietary systems.

---

## License

MIT (or choose your preferred license)
