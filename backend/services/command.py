"""Natural-language console interpreter (powers the dashboard command box).

Pure functions — no DB access — so the parsing is unit-testable. The
/api/command route resolves the returned action against live data.
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s.strip().lower())
    return s.rstrip("?!.,")


def match_nodes(query: str, nodes: list[dict]) -> list[dict]:
    """Fuzzy place match: exact > prefix > word-boundary > substring."""
    q = _norm(query)
    if not q:
        return []
    exact, prefix, word, sub = [], [], [], []
    for n in nodes:
        name = n["name"].lower()
        if name == q:
            exact.append(n)
        elif name.startswith(q):
            prefix.append(n)
        elif re.search(rf"(^|\W){re.escape(q)}", name):
            word.append(n)
        elif q in name:
            sub.append(n)
    by_len = lambda lst: sorted(lst, key=lambda n: len(n["name"]))  # noqa: E731
    return exact or by_len(prefix) or by_len(word) or by_len(sub)


def interpret(text: str, nodes: list[dict]) -> dict:
    """Parse console input into an action dict for the API route to execute."""
    raw = text.strip()
    q = _norm(raw)
    if not q:
        return {"action": "help"}

    if q in ("help", "?", "examples"):
        return {"action": "help"}
    if q in ("stats", "status", "overview", "metrics"):
        return {"action": "stats"}
    if q in ("congested", "jams", "traffic", "where is it jammed",
             "show congestion", "congestion"):
        return {"action": "congested"}
    if q in ("reset", "free flow", "clear traffic", "clear"):
        return {"action": "reset"}

    m = re.match(r"^(?:route|fastest|directions?)\s+(.+?)\s+(?:to|->|→)\s+(.+)$", q)
    if m:
        a, b = match_nodes(m.group(1), nodes), match_nodes(m.group(2), nodes)
        if len(a) == 1 and len(b) == 1 and a[0]["id"] != b[0]["id"]:
            return {"action": "route", "src": a[0], "dst": b[0]}
        return {"action": "clarify_route", "src_options": a[:5], "dst_options": b[:5]}

    m = re.match(r"^(?:jam|choke|block)\s+(.+?)(?:\s+(\d+))?$", q)
    if m:
        return {"action": "jam_request", "query": m.group(1).strip(),
                "count": int(m.group(2)) if m.group(2) else 30}

    m = re.match(r"^(?:traffic|congestion)(?:\s+on)?\s+(.+)$", q)
    if m:
        return {"action": "traffic_request", "query": m.group(1).strip()}

    # Bare "A to B" also routes.
    m = re.match(r"^(.+?)\s+(?:to|->|→)\s+(.+)$", q)
    if m and len(m.group(1)) > 1 and len(m.group(2)) > 1:
        a, b = match_nodes(m.group(1), nodes), match_nodes(m.group(2), nodes)
        if len(a) == 1 and len(b) == 1 and a[0]["id"] != b[0]["id"]:
            return {"action": "route", "src": a[0], "dst": b[0]}
        return {"action": "clarify_route", "src_options": a[:5], "dst_options": b[:5]}

    hits = match_nodes(q, nodes)
    if hits:
        return {"action": "place", "options": hits[:5]}

    return {"action": "unknown", "text": raw}
