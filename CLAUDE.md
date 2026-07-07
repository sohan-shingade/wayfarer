# CLAUDE.md - context for Claude Code working in this repo

## What this is
An agentic, budget-bounded, **plan-only** trip planner. Input: one natural-language
vacation request. Output: 4-5 full trip plans (exact flight + hotel + day-by-day
itinerary + budget breakdown + booking deep links). It NEVER books anything.

## Hard rules
- **Plan-only.** Do not add booking, payment, PII capture, or anything that completes
  a purchase. Booking is out of scope by design (legal/operational surface).
- **Deterministic spine.** The orchestrator and `engine/` are plain code. Do NOT turn
  them into LLM calls. LLMs belong only in `agents/` (parse, brainstorm, write, critic).
- **Vendor isolation.** The engine/orchestrator depend only on the interfaces in
  `providers/base.py` and `agents/runtime.py`. Never import a concrete vendor outside
  its adapter file.
- **Caps are load-bearing.** `config.py` caps (max_coarse_calls, coarse_concurrency,
  survivors, final_plans) protect rate limits and spend. Don't quietly raise them.
- **Billing.** Agents run via `claude -p` on the user's subscription. The runtime
  strips ANTHROPIC_API_KEY/AUTH_TOKEN/BASE_URL and aborts if a run reports a positive
  `total_cost_usd`. Keep that guard.

## Where things live
- `agents/runtime.py` - claude -p wrapper (the core of the subscription requirement)
- `agents/llm_agents.py` + `agents/prompts/*.md` - the four agents
- `engine/{coarse_prune,cost_assembly,rank,budget}.py` - deterministic pipeline
- `providers/{base,flights_fli,flights_serpapi,hotels_trvl,hotels_serpapi,hotels_flat,priors,cache}.py`
  (flights: fli default + SerpApi optional; hotels: trvl keyless CLI → SerpApi →
  flat no-key fallback. Amadeus removed — decommissioned 2026-07-17. One SerpApi
  key powers both engines.)
- `orchestrator.py` - the state machine; `cli.py` - entry point; `models.py` - contracts

## Unfinished (intentional)
`StaticPriors.geocode` still raises `NotImplementedError` (unused; SerpApi needs no
coordinates). The data layer (fli flights, SerpApi hotels, priors) is filled in.
Don't change the provider interfaces casually.

## Tests
`pytest` covers budget math and the env-scrub guard with no credentials needed. Add
tests next to new engine logic; keep the engine pure so it stays testable.
