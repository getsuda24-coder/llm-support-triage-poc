from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from .tools import kb_search, kb_get_doc


INVOICE_ID_RE = re.compile(r"\bINV[-\s]?(\d{3,6})\b", re.IGNORECASE)


@dataclass
class AgentOutput:
    provider: str
    model: str
    draft_reply: str
    rag_sources: list[str]
    rag_context: Optional[str]
    agent_trace: list[dict[str, Any]]


def _make_sources_from_docs(docs: list[dict[str, Any]]) -> list[str]:
    sources = []
    for d in docs:
        meta = d.get("metadata") or {}
        if meta.get("invoice_id"):
            sources.append(f"invoice:{meta['invoice_id']}")
        else:
            sources.append(f"kb:{d.get('source','unknown')}:{d.get('title','doc')}")
    # dedupe preserving order
    seen = set()
    out = []
    for s in sources:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _build_context(docs: list[dict[str, Any]], max_chars: int = 1400) -> str:
    chunks = []
    used = 0
    for d in docs:
        src = "invoice:" + d.get("metadata", {}).get("invoice_id", "") if d.get("metadata", {}).get("invoice_id") else f"kb:{d.get('source')}:{d.get('title')}"
        text = d.get("text", "")
        snippet = " ".join(text.strip().split())
        if len(snippet) > 350:
            snippet = snippet[:347] + "..."
        chunk = f"[{src}] {d.get('title')} — {snippet}"
        if used + len(chunk) + 2 > max_chars:
            break
        chunks.append(chunk)
        used += len(chunk) + 2
    return "\n\n".join(chunks)


class MockToolCallingAgent:
    """A deterministic agent that *behaves like* a tool-calling LLM.
    Great for local demos without external APIs.
    """
    def __init__(self) -> None:
        self.provider = "mock"
        self.model = "mock-agent-v1"

    def run(self, subject: str, body: str, requester_email: str, priority: str) -> AgentOutput:
        trace: list[dict[str, Any]] = []
        docs: list[dict[str, Any]] = []

        invoice_match = INVOICE_ID_RE.search(subject) or INVOICE_ID_RE.search(body)
        if invoice_match:
            inv = f"INV-{invoice_match.group(1)}"
            q = f"inv AND {invoice_match.group(1)}"
            trace.append({"tool": "kb_search", "args": {"query": q, "limit": 4}})
            search_res = kb_search(q, limit=4)
            trace.append({"tool_result": "kb_search", "hits": len(search_res.get("hits", []))})

            # fetch top docs
            for hit in search_res.get("hits", [])[:2]:
                doc_id = int(hit["id"])
                trace.append({"tool": "kb_get_doc", "args": {"doc_id": doc_id}})
                doc = kb_get_doc(doc_id)
                trace.append({"tool_result": "kb_get_doc", "found": bool(doc.get("found")), "id": doc_id})
                if doc.get("found"):
                    docs.append(doc)

        # Compose grounded reply
        if invoice_match and docs:
            ctx = _build_context(docs, max_chars=int(os.getenv("RAG_MAX_CHARS", "1400")))
            sources = _make_sources_from_docs(docs)
            # Pull invoice totals if present
            inv_meta = docs[0].get("metadata", {}) if docs else {}
            inv_id = inv_meta.get("invoice_id", "the invoice")
            total = inv_meta.get("total")
            currency = inv_meta.get("currency", "")
            total_str = f"{total:.2f} {currency}" if isinstance(total, (int, float)) and currency else None

            draft = (
                "Hi,\n\n"
                f"Thanks for your message regarding {inv_id}. I looked up the invoice details and here is what I see:\n\n"
                f"{ctx}\n\n"
            )
            if total_str:
                draft += f"**Invoice total:** {total_str}\n\n"

            draft += (
                "If you believe you were charged twice, please confirm:\n"
                "1) the billing period in question, and\n"
                "2) the last 4 digits of the payment method (if applicable).\n\n"
                "Once confirmed, we can validate the duplicate charge and advise on the next steps.\n\n"
                "Best regards,\nSupport Team"
            )
            return AgentOutput(
                provider=self.provider,
                model=self.model,
                draft_reply=draft,
                rag_sources=sources,
                rag_context=ctx,
                agent_trace=trace,
            )

        # No invoice or no docs: ask for missing details
        if "invoice" in (subject + " " + body).lower() or "billing" in (subject + " " + body).lower():
            draft = (
                "Hi,\n\n"
                "Thanks for contacting support. I can help with your billing question. "
                "Could you please share the invoice number (e.g., INV-XXXX) and the billing period?\n\n"
                "Once I have that, I’ll provide a precise breakdown and next steps.\n\n"
                "Best regards,\nSupport Team"
            )
        else:
            draft = (
                "Hi there,\n\n"
                f"Thanks for reaching out about: “{subject}”.\n\n"
                "Could you share any screenshots and the exact time it occurred? "
                "That will help us investigate quickly.\n\n"
                "Best regards,\nSupport Team"
            )

        return AgentOutput(
            provider=self.provider,
            model=self.model,
            draft_reply=draft,
            rag_sources=[],
            rag_context=None,
            agent_trace=trace,
        )


class OpenAIToolCallingAgent:
    """Real tool-calling agent (optional).
    Requires `pip install openai` and OPENAI_API_KEY.
    """
    def __init__(self) -> None:
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("OpenAI tool-calling agent requires: pip install openai") from e

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        self._client = OpenAI(api_key=api_key)
        self.provider = "openai"
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        self._tools = [
            {
                "type": "function",
                "function": {
                    "name": "kb_search",
                    "description": "Search the knowledge base (invoices, policies, docs) by text query.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "kb_get_doc",
                    "description": "Fetch a knowledge base document by id.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "doc_id": {"type": "integer", "minimum": 1},
                        },
                        "required": ["doc_id"],
                    },
                },
            },
        ]

    def run(self, subject: str, body: str, requester_email: str, priority: str) -> AgentOutput:
        max_turns = int(os.getenv("AGENT_MAX_TURNS", "4"))
        trace: list[dict[str, Any]] = []
        retrieved_docs: list[dict[str, Any]] = []

        system = (
            "You are a customer support agent. "
            "Use tools when needed to retrieve factual billing/invoice details. "
            "Do not invent invoice numbers or amounts. "
            "If you cannot find enough information, ask for missing details. "
            "When you use tools, keep tool calls minimal."
        )
        user = (
            f"Ticket\nSubject: {subject}\nPriority: {priority}\nRequester: {requester_email}\n\nMessage:\n{body}\n\n"
            "Draft a support reply."
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for _ in range(max_turns):
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self._tools,
                tool_choice="auto",
                temperature=0.2,
            )
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                # record assistant message with tool calls
                messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": tool_calls})
                for tc in tool_calls:
                    name = tc.function.name
                    args = json.loads(tc.function.arguments or "{}")
                    trace.append({"tool": name, "args": args})

                    if name == "kb_search":
                        out = kb_search(query=args.get("query", ""), limit=int(args.get("limit", 5)))
                        trace.append({"tool_result": "kb_search", "hits": len(out.get("hits", []))})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "name": name, "content": json.dumps(out)})
                    elif name == "kb_get_doc":
                        out = kb_get_doc(doc_id=int(args.get("doc_id")))
                        if out.get("found"):
                            retrieved_docs.append(out)
                        trace.append({"tool_result": "kb_get_doc", "found": bool(out.get("found")), "id": out.get("id")})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "name": name, "content": json.dumps(out)})
                    else:
                        messages.append({"role": "tool", "tool_call_id": tc.id, "name": name, "content": json.dumps({"error": "unknown tool"})})
                continue

            # no tool calls => final answer
            final = (msg.content or "").strip()
            ctx = _build_context(retrieved_docs, max_chars=int(os.getenv("RAG_MAX_CHARS", "1400"))) if retrieved_docs else None
            sources = _make_sources_from_docs(retrieved_docs) if retrieved_docs else []
            return AgentOutput(
                provider=self.provider,
                model=self.model,
                draft_reply=final,
                rag_sources=sources,
                rag_context=ctx,
                agent_trace=trace,
            )

        # If agent ran out of turns, fallback
        ctx = _build_context(retrieved_docs, max_chars=int(os.getenv("RAG_MAX_CHARS", "1400"))) if retrieved_docs else None
        sources = _make_sources_from_docs(retrieved_docs) if retrieved_docs else []
        return AgentOutput(
            provider=self.provider,
            model=self.model,
            draft_reply="Hi,\n\nThanks for contacting support. Could you please provide the invoice number and billing period so I can assist?\n\nBest regards,\nSupport Team",
            rag_sources=sources,
            rag_context=ctx,
            agent_trace=trace + [{"note": "max_turns_exceeded"}],
        )


def get_agent():
    provider = os.getenv("LLM_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return MockToolCallingAgent()
    if provider == "openai":
        return OpenAIToolCallingAgent()
    raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r} (expected 'mock' or 'openai')")
