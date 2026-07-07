"""The four LLM agents. Each is a thin wrapper: load a prompt template, fill it,
call the runtime, parse JSON into a typed model. No business logic lives here.
"""
from __future__ import annotations

import json
from importlib import resources

from ..models import Brief, Candidate, DayPlan, PricedCandidate, Plan
from .runtime import AgentRuntime, parse_json_block

_PROMPTS = resources.files("wayfarer.agents.prompts")


def _tmpl(name: str) -> str:
    return _PROMPTS.joinpath(name).read_text(encoding="utf-8")


async def parse_brief(runtime: AgentRuntime, request: str, model: str) -> dict:
    """Returns a dict (not Brief) because origin may be null and needs elicitation."""
    res = await runtime.run(_tmpl("brief_parser.md") + request, system=None)
    return parse_json_block(res.text)


async def brainstorm(
    runtime: AgentRuntime, brief: Brief, max_candidates: int
) -> list[Candidate]:
    # NB: the template contains literal JSON braces, so str.format() would choke on
    # them -- substitute the one placeholder by name instead.
    prompt = _tmpl("brainstormer.md").replace("{max_candidates}", str(max_candidates))
    prompt += "\n" + brief.model_dump_json(indent=2)
    res = await runtime.run(prompt)
    rows = parse_json_block(res.text)
    return [Candidate(**r) for r in rows][:max_candidates]


async def write_itinerary(
    runtime: AgentRuntime, brief: Brief, priced: PricedCandidate,
    flight_json: str, hotel_json: str, model: str,
) -> tuple[str, list[DayPlan]]:
    payload = {
        "brief": brief.model_dump(),
        "destination": priced.quote.candidate.model_dump(),
        "flight": json.loads(flight_json),
        "hotel": json.loads(hotel_json),
        "budget": priced.budget.model_dump(),
    }
    prompt = _tmpl("itinerary_writer.md") + json.dumps(payload, indent=2)
    res = await runtime.run(prompt)
    out = parse_json_block(res.text)
    return out["summary"], [DayPlan(**d) for d in out["itinerary"]]


async def critique(runtime: AgentRuntime, brief: Brief, plan: Plan, model: str) -> dict:
    payload = {"brief": brief.model_dump(), "plan": plan.model_dump()}
    res = await runtime.run(_tmpl("critic.md") + json.dumps(payload, indent=2))
    return parse_json_block(res.text)
