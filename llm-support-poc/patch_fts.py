import re
from pathlib import Path

db_py = Path("src/app/db.py")
agent_py = Path("src/app/agent.py")

# --- Patch db.py: add normalize + retry in kb_search ---
txt = db_py.read_text(encoding="utf-8")

if "_normalize_fts_query" not in txt:
    txt = txt.replace(
        "# Knowledge base (RAG)\n",
        """# Knowledge base (RAG)
import re as _re

_FTS_TOKEN_RE = _re.compile(r'"[^"]*"|\\(|\\)|\\S+')

def _normalize_fts_query(q: str) -> str:
    # Make FTS5 query safe: quote special tokens, and convert INV-1042 -> INV 1042
    parts = []
    for m in _FTS_TOKEN_RE.finditer(q.strip()):
        tok = m.group(0)
        if tok in ("(", ")"):
            parts.append(tok); continue
        if tok.startswith('"') and tok.endswith('"'):
            parts.append(tok); continue
        up = tok.upper()
        if up in ("AND", "OR", "NOT", "NEAR"):
            parts.append(up); continue
        if _re.fullmatch(r"[A-Za-z0-9_]+", tok):
            parts.append(tok); continue
        # convert hyphens to spaces (tokenizer splits anyway)
        tok2 = tok.replace("-", " ")
        tok2 = tok2.replace('"', '""')
        parts.append(f'"{tok2}"')
    return " ".join(parts).strip()

"""
    )

# Replace kb_search implementation
txt = re.sub(
    r"def kb_search\(query: str, limit: int = 5\) -> list\[sqlite3\.Row\]:.*?return list\(cur\.fetchall\(\)\)\n",
    """def kb_search(query: str, limit: int = 5) -> list[sqlite3.Row]:
    sql = \"\"\"SELECT d.id, d.source, d.title, d.text, d.metadata_json, bm25(kb_docs_fts) AS rank
               FROM kb_docs_fts
               JOIN kb_docs d ON d.id = kb_docs_fts.rowid
               WHERE kb_docs_fts MATCH ?
               ORDER BY rank
               LIMIT ?\"\"\"
    with db() as conn:
        try:
            cur = conn.execute(sql, (query, limit))
        except sqlite3.OperationalError:
            q2 = _normalize_fts_query(query)
            cur = conn.execute(sql, (q2, limit))
        return list(cur.fetchall())
""",
    txt,
    flags=re.S,
)
db_py.write_text(txt, encoding="utf-8")

# --- Patch agent query to avoid INV-XXXX raw token (FTS special chars) ---
a = agent_py.read_text(encoding="utf-8")
a = a.replace(
    'q = f\'"{inv}" "{requester_email}"\'',
    'q = f"inv AND {invoice_match.group(1)}"'
)
a = a.replace(
    'q = f"{inv} {requester_email} invoice OR billing OR charged"',
    'q = f"inv AND {invoice_match.group(1)}"'
)
agent_py.write_text(a, encoding="utf-8")

print("Patched src/app/db.py and src/app/agent.py")