"""Vision extractor: claude -p reads Beli screenshots -> BeliEntry rows.

Perception only (the spine rule). All aggregation lives in engine/taste.py.
"""
from __future__ import annotations

from importlib import resources

from ..models import BeliEntry
from .runtime import AgentRuntime, parse_json_block

_PROMPTS = resources.files("wayfarer.agents.prompts")
_ENTRY_KEYS = {"name", "score", "rank", "cuisine", "neighborhood", "city",
               "price", "notes"}


def entries_from_rows(rows: list[dict], list_type: str = "been",
                      source_shot: str = "") -> list[BeliEntry]:
    out: list[BeliEntry] = []
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        clean = {k: r.get(k) for k in _ENTRY_KEYS if k in r}
        clean["name"] = name
        out.append(BeliEntry(list_type=list_type, source_shot=source_shot, **clean))
    return out


async def extract_entries(runtime: AgentRuntime, image_paths: list[str],
                          list_type: str = "been") -> list[BeliEntry]:
    prompt = _PROMPTS.joinpath("beli_extract.md").read_text(encoding="utf-8")
    prompt += "\n" + "\n".join(image_paths)
    res = await runtime.run(prompt)
    rows = parse_json_block(res.text)
    return entries_from_rows(rows, list_type=list_type)
