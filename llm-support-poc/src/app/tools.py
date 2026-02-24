from __future__ import annotations

import json
from typing import Any

from . import db


def kb_search(query: str, limit: int = 5) -> dict[str, Any]:
    rows = db.kb_search(query, limit=limit)
    hits = []
    for r in rows:
        rank = float(r["rank"])
        score = 1.0 / (1.0 + max(0.0, rank))
        hits.append(
            {
                "id": int(r["id"]),
                "title": r["title"],
                "source": r["source"],
                "score": score,
                "snippet": (r["text"][:220] + "...") if len(r["text"]) > 220 else r["text"],
            }
        )
    return {"query": query, "hits": hits}


def kb_get_doc(doc_id: int) -> dict[str, Any]:
    r = db.kb_get_doc(doc_id)
    if not r:
        return {"found": False, "id": doc_id}
    return {
        "found": True,
        "id": int(r["id"]),
        "source": r["source"],
        "title": r["title"],
        "text": r["text"],
        "metadata": json.loads(r["metadata_json"] or "{}"),
    }
