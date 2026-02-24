from __future__ import annotations

import json
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from . import db
from .models import (
    TicketOut, DraftOut, DecisionOut, TicketDetail, ReviewIn, SeedIn,
    KBDocIn, KBDocOut, KBSearchOut, KBSearchHit
)
from .seed import seed_tickets
from .router import route
from .agent import get_agent
from .tools import kb_search as tool_kb_search, kb_get_doc as tool_kb_get
from .rag_seed import seed_invoices


app = FastAPI(title="LLM Support POC + Agentic RAG", version="0.3.0")
templates = Jinja2Templates(directory="src/app/templates")


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _ticket_row_to_out(r) -> TicketOut:
    return TicketOut(
        id=int(r["id"]),
        created_at=_parse_dt(r["created_at"]),
        subject=r["subject"],
        requester_email=r["requester_email"],
        body=r["body"],
        priority=r["priority"],
        status=r["status"],
    )


def _draft_row_to_out(r) -> DraftOut:
    sources = []
    if r["rag_sources"]:
        try:
            sources = json.loads(r["rag_sources"])
        except Exception:
            sources = []
    trace = []
    if r["agent_trace"]:
        try:
            trace = json.loads(r["agent_trace"])
        except Exception:
            trace = []
    return DraftOut(
        id=int(r["id"]),
        ticket_id=int(r["ticket_id"]),
        created_at=_parse_dt(r["created_at"]),
        llm_provider=r["llm_provider"],
        llm_model=r["llm_model"],
        draft_reply=r["draft_reply"],
        risk_score=float(r["risk_score"]),
        routing=r["routing"],
        rag_sources=sources,
        rag_context=r["rag_context"],
        agent_trace=trace,
    )


def _decision_row_to_out(r) -> DecisionOut:
    return DecisionOut(
        id=int(r["id"]),
        ticket_id=int(r["ticket_id"]),
        created_at=_parse_dt(r["created_at"]),
        action=r["action"],
        final_reply=r["final_reply"],
        reviewer=r["reviewer"],
    )


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---- Tickets ----
@app.post("/seed")
def seed(payload: SeedIn):
    created = seed_tickets(count=payload.count)
    return {"created_ids": created}


@app.get("/tickets", response_model=list[TicketOut])
def tickets():
    rows = db.list_tickets(limit=200)
    return [_ticket_row_to_out(r) for r in rows]


@app.get("/tickets/{ticket_id}", response_model=TicketDetail)
def ticket_detail(ticket_id: int):
    t = db.get_ticket(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")

    d = db.get_latest_draft(ticket_id)
    dec = db.get_latest_decision(ticket_id)

    return TicketDetail(
        ticket=_ticket_row_to_out(t),
        latest_draft=_draft_row_to_out(d) if d else None,
        latest_decision=_decision_row_to_out(dec) if dec else None,
    )


@app.post("/tickets/{ticket_id}/draft", response_model=DraftOut)
def generate_draft(ticket_id: int):
    t = db.get_ticket(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")

    agent = get_agent()
    out = agent.run(
        subject=t["subject"],
        body=t["body"],
        requester_email=t["requester_email"],
        priority=t["priority"],
    )

    decision = route(
        subject=t["subject"],
        body=t["body"],
        priority=t["priority"],
        draft_reply=out.draft_reply,
    )

    did = db.insert_draft(
        ticket_id=ticket_id,
        llm_provider=out.provider,
        llm_model=out.model,
        draft_reply=out.draft_reply,
        risk_score=decision.risk_score,
        routing=decision.routing,
        rag_sources=out.rag_sources,
        rag_context=out.rag_context,
        agent_trace=out.agent_trace,
    )

    row = db.get_latest_draft(ticket_id)
    assert row and int(row["id"]) == did
    return _draft_row_to_out(row)


@app.post("/tickets/{ticket_id}/review", response_model=DecisionOut)
def review(ticket_id: int, payload: ReviewIn):
    t = db.get_ticket(ticket_id)
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")

    latest_draft = db.get_latest_draft(ticket_id)

    if payload.action in ("approve_and_send", "edit_and_send") and not latest_draft:
        raise HTTPException(status_code=400, detail="No draft to approve/edit. Generate a draft first.")

    final_reply = None
    if payload.action == "approve_and_send":
        final_reply = latest_draft["draft_reply"] if latest_draft else None
        db.set_ticket_status(ticket_id, "sent")

    elif payload.action == "edit_and_send":
        if not payload.edited_reply or not payload.edited_reply.strip():
            raise HTTPException(status_code=400, detail="edited_reply is required for edit_and_send")
        final_reply = payload.edited_reply.strip()
        db.set_ticket_status(ticket_id, "sent")

    elif payload.action == "reject":
        db.set_ticket_status(ticket_id, "needs_human")

    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    decision_id = db.insert_decision(
        ticket_id=ticket_id,
        action=payload.action,
        final_reply=final_reply,
        reviewer=payload.reviewer,
    )

    row = db.get_latest_decision(ticket_id)
    assert row and int(row["id"]) == decision_id
    return _decision_row_to_out(row)


# ---- Knowledge base (RAG) ----
@app.post("/kb/seed_invoices")
def kb_seed_invoices():
    created = seed_invoices()
    return {"created_ids": created}


@app.post("/kb/docs", response_model=KBDocOut)
def kb_add(payload: KBDocIn):
    doc_id = db.kb_add_doc(payload.source, payload.title, payload.text, payload.metadata)
    r = db.kb_get_doc(doc_id)
    assert r
    return KBDocOut(
        id=int(r["id"]),
        created_at=_parse_dt(r["created_at"]),
        source=r["source"],
        title=r["title"],
        text=r["text"],
        metadata=json.loads(r["metadata_json"] or "{}"),
    )


@app.get("/kb/docs/{doc_id}", response_model=KBDocOut)
def kb_get(doc_id: int):
    r = db.kb_get_doc(doc_id)
    if not r:
        raise HTTPException(status_code=404, detail="Doc not found")
    return KBDocOut(
        id=int(r["id"]),
        created_at=_parse_dt(r["created_at"]),
        source=r["source"],
        title=r["title"],
        text=r["text"],
        metadata=json.loads(r["metadata_json"] or "{}"),
    )


@app.get("/kb/search", response_model=KBSearchOut)
def kb_search(q: str, limit: int = 5):
    out = tool_kb_search(query=q, limit=limit)
    hits = []
    for h in out["hits"]:
        hits.append(KBSearchHit(**h))
    return KBSearchOut(query=out["query"], hits=hits)
