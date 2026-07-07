# Wayfarer — Planning Harness Vision

**Date:** 2026-06-27
**Status:** Vision / architecture framing (not an implementation spec)
**Purpose:** Frame the umbrella that sub-projects A–D plug into. Each sub-project
gets its own spec → plan → build cycle; this doc says how they fit together.

## One-line

A **free, clone-and-go Claude Code harness for itinerary planning** — you clone the
repo, add your own API keys, and get a taste-personalized planner that handles
multiple plan-types (vacation trips, food crawls, …) on one shared spine. Plan-only:
it never books anything.

## Who it's for

Claude Code users. Not a product, not a SaaS, no accounts, no billing. Agents run
via `claude -p` on the user's own subscription; data providers use the user's own
API keys. The repo *is* the app.

## What it is / isn't

- **Is:** a deterministic orchestration spine + LLM agents + vendor-isolated data
  providers that turn a natural-language request into full, costed, deep-linked
  plans rendered as JSON + HTML.
- **Isn't:** a booking/payment system (plan-only by design), a hosted service, or a
  data-resale product. No PII capture, no purchase completion.

## Core idea: plan-types on a shared spine

Today wayfarer hard-codes one plan-type (vacation). The harness generalizes
`plan-type` into a **first-class, pluggable concept**. A plan-type is the *minimum*
that varies between domains; everything else is shared.

```
                         SHARED SPINE (plan-type-agnostic)
  ┌──────────────────────────────────────────────────────────────────┐
  │ elicit (NL request + clarifying gate)                             │
  │ orchestrator (deterministic state machine, caps)                  │
  │ engine/ (pure logic: budget, rank, assembly, taste aggregation)  │
  │ agents/runtime.py (claude -p wrapper, env-scrub, cost guard)     │
  │ personalization: TASTE PROFILES (shared across plan-types)        │
  │ output (JSON + standardized HTML: index + per-plan walkthrough)   │
  └──────────────────────────────────────────────────────────────────┘
                         ▲                         ▲
            ┌────────────┘                         └────────────┐
   PLAN-TYPE: vacation                      PLAN-TYPE: food_crawl
   - providers: flights, hotels            - providers: free food data
     (fli, SerpApi, trvl)                    (OSM, Foursquare Open,
   - planner agent: trip itinerary           Overture, NYC DOHMH, Reddit)
   - elicit fields: origins, dates,        - planner agent: crawl sequencer
     pax, budget, vibe                       (pacing, variety, dishes)
                                            - elicit fields: neighborhood,
                                              party, # stops, dietary
```

**What a plan-type supplies:** its domain data providers, its planner agent, and its
elicit fields. **What it inherits:** orchestrator, engine, runtime, taste profiles,
output. Adding a plan-type should not require touching the spine.

## Personalization is shared, not per-domain

**Taste profiles (sub-project A) are a spine feature.** The same `TasteProfile` that
sequences a Jackson Heights food crawl also biases dining choices inside a vacation
itinerary. One person → one profile; N people → a `GroupTasteProfile`. Plan-types
consume `cuisine_affinity`, `want_to_try`, and `combined_dislikes` however they like.

## Inherited hard rules (from CLAUDE.md — non-negotiable)

- **Plan-only.** No booking/payment/PII/purchase completion.
- **Deterministic spine.** Orchestrator + `engine/` are plain code, never LLM calls.
  LLMs live only in `agents/` (parse, brainstorm, write, critic, perceive).
- **Vendor isolation.** Engine/orchestrator depend only on provider interfaces
  (`providers/base.py`) + `agents/runtime.py`. No concrete vendor outside its adapter.
- **Caps are load-bearing.** `config.py` caps protect rate limits + spend.
- **Subscription billing.** Runtime strips API keys + aborts on positive
  `total_cost_usd`.

## Roadmap

| # | Sub-project | Status |
|---|---|---|
| **A** | Beli taste-profile engine (shared personalization module) | designed, pre-build |
| **B** | Reverse-engineered Beli API ingestion (writes same snapshot schema) | deferred (mobile-only, proxy + cert-pinning) |
| **C** | `food_crawl` plan-type: free food-data layer + crawl sequencer | next after A |
| **D** | Standardize run/HTML output across plan-types | the Puerto Rico runs are the shape |
| **E** | Harness generalization: make `plan-type` first-class/pluggable | folds A–D together |

Build order is roughly A → **Places KB + RAG layer** (component 1; C needs it
anyway) → C (with D's output standardization alongside) → tool registry + verifier
(component 2) + constraint solver (component 4) → E to formalize the abstraction once
two plan-types exist → B if/when someone wants full-list automation.

## Harness components (build map)

What a "harness" is here: the reusable scaffolding around the LLM that makes
planning reliable + agentic, so each plan-type only brings domain data + a planner
agent. Have today: spine, `claude -p` runtime, providers, output. Components to add,
by layer:

1. **Knowledge / memory**
   - *Places KB* — one local store of normalized, deduped POIs from free providers
     (OSM, Foursquare Open, Overture, NYC DOHMH). Canonical entity layer. **High.**
   - *RAG database* — local embedded vector store (`sqlite-vec` / LanceDB, no server)
     over curated text (editorial guides, Reddit, Beli snapshots, reviews); planner
     grounds recs in real text. Embeddings via BYO key (Voyage). **High.**
   - *User memory* — persisted prefs/constraints/past-plan feedback. Medium.
2. **Tools (shared registry, like `providers/base.py`)** — geocode, distance/time
   matrix, opening-hours, weather, currency, maps deep-links, web search/fetch; plus
   *verifier tools* (does this place exist / open that day?) as a hallucination guard.
   **High (verifier).**
3. **Source connectors** — generalize Beli's `connector → snapshot → KB`: Google Maps
   Takeout, TikTok/IG saved, Reddit miner, editorial. Cheap once Beli (A) exists.
4. **Reasoning / quality (stays deterministic, in `engine/`)** — *constraint solver*
   (time-windows, hours, geo-clustering, budget, crawl pacing) and a *scoring module*
   (`taste × quality × freshness × distance`); upgrade the critic to multi-vote
   adversarial verification. **High (solver).**
5. **Personalization (extends A)** — reusable Beli-style pairwise/ELO *taste graph*;
   *feedback loop* (post-trip ratings update the profile). After A proves out.
6. **Output / interaction** — standardized renderers (D) + exports (`.ics`, Google
   Maps list, GPX; Google Calendar MCP already connected); conversational refine loop.

**Priority (compounding):** KB + RAG (1) → tool registry + verifier (2) → constraint
solver + scoring (4). Those three lift every plan-type. Defer: connector zoo (3
beyond Beli), taste graph (5), refine loop until output is standardized.

**Guards:** nothing that books/captures payment (plan-only); never move solver/
ranking into an LLM (spine rule); no hosted vector server (kills clone-and-go).

## Why this shape

- **Two plan-types prove the abstraction.** Generalize *after* `vacation` and
  `food_crawl` both work (E), not speculatively — avoids a framework with one user.
- **The spine already exists.** Wayfarer's orchestrator/engine/runtime/providers are
  the reusable parts; food crawls mostly need new providers + a new planner agent.
- **Free + clone-and-go forces low friction.** Favors the user's own keys + Claude
  vision over hosted models or brittle scrapers (see A's screenshot/video path; B
  deferred for exactly this reason).

## Open questions

- Where does the `plan-type` boundary live in code — a registry + a `PlanType`
  protocol (providers + planner + elicit schema), or lighter convention? Decide in E,
  informed by building C.
- How much of `elicit` is shareable vs plan-type-specific?
- Output: one standardized template parameterized per plan-type, or per-type
  templates sharing components? (sub-project D)
