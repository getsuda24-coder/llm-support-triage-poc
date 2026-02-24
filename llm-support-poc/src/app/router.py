from __future__ import annotations

import os
import re
from dataclasses import dataclass


SENSITIVE_PATTERNS = [
    r"chargeback", r"legal", r"lawsuit",
    r"delete my data", r"gdpr", r"privacy", r"ssn", r"passport",
    r"credit card", r"bank", r"wire transfer",
]


@dataclass
class RouteDecision:
    routing: str  # "auto_send" | "needs_human"
    risk_score: float  # 0..1


def _contains_sensitive(text: str) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in SENSITIVE_PATTERNS)


def route(subject: str, body: str, priority: str, draft_reply: str) -> RouteDecision:
    risk = 0.10

    if priority in ("high", "urgent"):
        risk += 0.35

    if _contains_sensitive(subject) or _contains_sensitive(body) or _contains_sensitive(draft_reply):
        risk += 0.45

    if len(draft_reply.strip()) < 180:
        risk += 0.15

    risk = max(0.0, min(1.0, float(risk)))

    max_risk = float(os.getenv("AUTO_SEND_MAX_RISK", "0.30"))
    routing = "auto_send" if risk <= max_risk else "needs_human"
    return RouteDecision(routing=routing, risk_score=risk)
