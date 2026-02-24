from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Literal, Any
from datetime import datetime


class TicketOut(BaseModel):
    id: int
    created_at: datetime
    subject: str
    requester_email: str
    body: str
    priority: str
    status: str


class DraftOut(BaseModel):
    id: int
    ticket_id: int
    created_at: datetime
    llm_provider: str
    llm_model: str
    draft_reply: str
    risk_score: float = Field(ge=0.0, le=1.0)
    routing: Literal["auto_send", "needs_human"]
    rag_sources: list[str] = Field(default_factory=list)
    rag_context: Optional[str] = None
    agent_trace: list[dict[str, Any]] = Field(default_factory=list)


class ReviewIn(BaseModel):
    action: Literal["approve_and_send", "edit_and_send", "reject"]
    edited_reply: Optional[str] = None
    reviewer: str = "agent"


class DecisionOut(BaseModel):
    id: int
    ticket_id: int
    created_at: datetime
    action: str
    final_reply: Optional[str]
    reviewer: str


class TicketDetail(BaseModel):
    ticket: TicketOut
    latest_draft: Optional[DraftOut] = None
    latest_decision: Optional[DecisionOut] = None


class SeedIn(BaseModel):
    count: int = Field(default=6, ge=1, le=50)


# RAG / KB models
class KBDocIn(BaseModel):
    source: str = "manual"
    title: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KBDocOut(BaseModel):
    id: int
    created_at: datetime
    source: str
    title: str
    text: str
    metadata: dict[str, Any]


class KBSearchHit(BaseModel):
    id: int
    title: str
    source: str
    score: float
    snippet: str


class KBSearchOut(BaseModel):
    query: str
    hits: list[KBSearchHit]
