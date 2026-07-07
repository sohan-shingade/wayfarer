<p align="center">
  <img src="assets/logo.svg" width="130" alt="wayfarer logo" />
</p>

<h1 align="center">wayfarer</h1>

<p align="center">
  <em>One sentence in. Five bookable trips out. Never books anything.</em>
</p>

<p align="center">
  <a href="https://github.com/sohan-shingade/wayfarer/actions/workflows/ci.yml">
    <img src="https://github.com/sohan-shingade/wayfarer/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
  <a href="https://www.python.org/">
    <img src="https://img.shields.io/badge/python-3.11%2B-3776ab.svg?logo=python&logoColor=white" alt="Python 3.11+" /></a>
  <a href="LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-22c55e.svg" alt="MIT license" /></a>
  <a href="#-billing-read-this-before-your-first-run">
    <img src="https://img.shields.io/badge/agents-run%20on%20your%20Claude%20subscription-d97706.svg" alt="Runs on your Claude subscription" /></a>
  <a href="#contributing">
    <img src="https://img.shields.io/badge/PRs-welcome-8b5cf6.svg" alt="PRs welcome" /></a>
</p>

<div align="center">
  <a href="#-quickstart">Quickstart</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-how-it-works">How it works</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-providers">Providers</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#-billing-read-this-before-your-first-run">Billing</a>
  <span>&nbsp;&nbsp;•&nbsp;&nbsp;</span>
  <a href="#contributing">Contributing</a>
</div>

<br/>

<div align="center">
  <figure>
    <img src="viewer.png" alt="wayfarer's trip viewer — ranked plan cards with budget bars, itineraries, and a hotel map" />
    <p align="center"><sub>Every run ships a self-contained HTML viewer: ranked cards, budget bars, day-by-day itineraries, and a map pinning each hotel.</sub></p>
  </figure>
</div>

## What is wayfarer?

Wayfarer is an **agentic, budget-bounded, plan-only trip planner**. You give it one natural-language request:

```bash
wayfarer "vacation for 2, budget 3k total, anytime in august, want insane landscapes"
```

It answers with 4–5 **complete, priced, bookable trip plans** — the exact flight, the exact hotel, a day-by-day itinerary, a budget breakdown against your ceiling, and deep links to book each piece. The last click is always yours: wayfarer **never** books, pays, or touches PII. That's a design decision, not a roadmap gap.

Under the hood it's four small LLM agents wrapped around a fully deterministic pipeline — the interesting parts (pruning, costing, ranking) are plain, testable code.

## Features

- 💸 **Budget is a hard constraint, not a suggestion.** Plans are assembled bottom-up — flights + lodging + per-diem + buffer — and must clear your ceiling with margin. A critic agent re-verifies every sum before you see it.
- 🤖 **LLM at the edges, code in the middle.** Parse → brainstorm → write → critique are agents; prune → cost → rank is deterministic code. Cheap, reproducible, and it won't melt a provider's rate limit.
- 🆓 **Zero API keys to start.** Free Google Flights data via [`fli`](https://pypi.org/project/flights/), keyless hotel data via [`trvl`](https://github.com/MikkoParkkola/trvl), agents on your existing Claude subscription.
- 🗺️ **A real deliverable.** Each run writes Markdown, JSON, and a self-contained HTML viewer with a map — artifacts you can save, share, or diff.
- 🔥 **Deal detection.** Standout-cheap fares get flagged in every run for free; an opt-in mode hunts fares below their historical range.
- 🍜 **Taste profiles.** Ingest your Beli restaurant lists via vision into per-person and group taste profiles that can flavor itineraries.
- ♻️ **Reproducible runs.** Run directories are keyed by a hash of the brief; provider responses cache to SQLite with a TTL. Same request, same data.
- 🧢 **Hard caps everywhere.** Max provider calls, concurrency, quota ceilings — `config.py` bounds spend and API pressure by design.

## 🧭 How it works

```
prompt
  → [LLM]  brief parser       structure the request, infer origin      (cheap)
  → [gate] elicit             ask: origin? long-haul? ceiling?         (pre-spend)
  → [LLM]  brainstormer       ~40 in-season, vibe-matched destinations
  → [code] coarse prune       1 flight call each, drop pricey → ~12
  → [code] cost assembly      + hotel + per-diem buffer, keep ≤ budget → ~6
  → [code] rank               vibe × headroom × season → top 5
  → [code] exact pricing      lock specific flights + hotels
  → [LLM]  itinerary writer   day-by-day plans
  → [LLM]  critic             verify sums ≤ budget, no hallucinations
  → present                   ranked plans + booking deep links
```

Only four nodes are LLM calls — the two ends. The spine is deterministic on purpose.

<details>
<summary><b>📁 Repository layout</b></summary>
<br/>

```
src/wayfarer/
├── orchestrator.py      the deterministic state machine
├── cli.py               entry points (wayfarer, wayfarer-deals, wayfarer-beli)
├── models.py            typed contracts between every stage
├── agents/
│   ├── runtime.py       claude -p wrapper: env scrub + billing guard
│   ├── llm_agents.py    the four agents
│   └── prompts/*.md     their prompts + JSON contracts
├── engine/              coarse prune, cost assembly, rank, budget, taste, deals
└── providers/           swappable adapters behind base.py interfaces
```

</details>

<details>
<summary><b>📦 Run artifacts</b></summary>
<br/>

Each run is saved to <code>runs/&lt;month&gt;_&lt;vibe&gt;_&lt;pax&gt;pax_&lt;hash&gt;/</code> (local only, gitignored):

- `run.json` — the structured brief + metadata
- `summary.md` — ranked index of all options
- `plan-NN-<dest>.{json,md}` — each trip as a saveable file
- `index.html` — the self-contained visual viewer (Leaflet map, budget bars, itineraries)

The directory is keyed by a hash of the brief, so re-running the same scenario overwrites in place instead of piling up copies.

</details>

## 🚀 Quickstart

```bash
# 1. Claude Code, logged in with a Pro/Max subscription (NOT an API key)
npm install -g @anthropic-ai/claude-code
claude login

# 2. Install
git clone https://github.com/sohan-shingade/wayfarer && cd wayfarer
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# 3. (Optional but recommended) keyless hotel data
go install github.com/MikkoParkkola/trvl/cmd/trvl@latest
#   or: brew install MikkoParkkola/tap/trvl

# 4. Confirm you're on subscription auth, not API billing
./scripts/preflight.sh

# 5. Plan a trip
wayfarer "vacation for 2, budget 3k total, anytime in august, want insane landscapes"
```

Structured flags override the parsed brief; multi-origin checks every airport and keeps the cheapest:

```bash
wayfarer "adventurous, insane landscapes, backpacking" \
  --pax 2 --budget 2000 --month 2026-08 --nights 4 --origins SFO,OAK,SJC --open
```

`--open` launches the HTML viewer when the run finishes.

## 🔌 Providers

| Layer   | Default                             | Alternatives                                         |
|---------|-------------------------------------|------------------------------------------------------|
| Flights | `fli` — free Google Flights, no key | SerpApi `google_flights` (needs `SERPAPI_API_KEY`)   |
| Hotels  | `trvl` — free, keyless CLI          | SerpApi `google_hotels` → labeled flat-rate estimate |
| Agents  | `claude -p` on your subscription    | implement `AgentRuntime` for API-key billing         |

Hotel preference is `trvl` → SerpApi → flat estimate; force one with `WAYFARER_HOTELS=trvl|serpapi|flat`. One SerpApi key (free tier ~250 searches/mo) powers both engines — copy `.env.example` to `.env` and set `SERPAPI_API_KEY` if you want it.

> [!NOTE]
> Provider responses cache to a local SQLite DB (`~/.cache/wayfarer/providers.db`) with a TTL, so identical requests reproduce the same flight and hotel data. Force fresh data with `WAYFARER_CACHE=off`. The optional `trvl` binary is PolyForm Noncommercial — fine for personal, plan-only use.

## 💳 Billing: read this before your first run

The agents shell out to `claude -p`, which runs on your **Claude Pro/Max subscription** — not per-token API billing. Two guards keep it that way:

- The runtime **strips `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_BASE_URL`** from every agent subprocess. If a key were set, the CLI would silently bill your API account instead.
- There have been reports of `claude -p` billing as API usage even with no key set, so the runtime also reads `total_cost_usd` from every result and **aborts the run if it is positive** (`fail_on_api_billing=True`).

> [!WARNING]
> Before real use, run `scripts/preflight.sh` and check `/status` inside an interactive `claude` session — the Auth token field should read `CLAUDE_CODE_OAUTH_TOKEN`. Watch your billing dashboards on the first runs.

> [!IMPORTANT]
> Running `claude -p` on your own subscription for your own local use is fine. Subscription OAuth may **not** power a product served to other people — if you productize this, swap `ClaudeCLIRuntime` for an API-key runtime (the `AgentRuntime` interface exists for exactly that).

## 🔥 Deal detection

- **Relative (free, always on):** within a normal run, any fare ≤65% of the median gets tagged `🔥 deal` in the output, summary, and viewer. No extra API calls.
- **Absolute (opt-in):** `wayfarer-deals` scans aspirational destinations from your origins for fares below their typical historical range (SerpApi `price_insights`) — real error-fare hunting. It spends metered quota, so it's **off by default**:

  ```bash
  wayfarer-deals --origins SFO,OAK --month 2026-10 --nights 7 --enable
  ```

  A hard cap (`deal_hunt_max_calls`, default 24) clamps `targets × origins` so a scan can't blow your quota. Results save to `runs/deals_*/`.

## 🍜 Beli taste profiles

Turn your [Beli](https://beliapp.com/) restaurant lists into a taste profile that can flavor trip planning. Record a slow scroll of a list (or grab screenshots); a vision agent extracts places and cuisine tags, deduplicates, and scores them by your rating pattern.

```bash
# ingest your "been" list from a screen recording
wayfarer-beli alice --video recordings/beli_been.mov --list-type been
# alice: 47 places -> 12 cuisines, 0 on wishlist
# wrote profiles/alice/beli_snapshot.json + taste.json

# second pass for the wishlist — appends to the same snapshot, dedup handles overlap
wayfarer-beli alice --video recordings/beli_wants.mov --list-type want_to_try

# screenshots instead of video
wayfarer-beli alice --shots shots/ --list-type been

# merge profiles into a group (consensus scores, shared wants, union of dislikes)
wayfarer-beli group --merge alice,bob,charlie
```

Profiles land in `profiles/` (local only, gitignored). Video ingestion needs the `ffmpeg` system binary; scroll slowly with brief pauses so mpdecimate can dedupe frames.

## 🧪 Testing

```bash
pytest          # FAST: offline, no network or claude. Deterministic logic + provider
                # parsers run against recorded real responses in tests/fixtures/.
pytest -m live  # LIVE: genuine end-to-end (real fli + SerpApi + claude -p). Skips
                # unless creds + network are present; keep ANTHROPIC_API_KEY unset.
```

Regenerate fixtures with `python scripts/record_fixtures.py` (needs creds + network).

## Contributing

PRs welcome! Ground rules (see [`CLAUDE.md`](CLAUDE.md) for the full contributor context):

- 🚫 **Plan-only, forever.** No booking, payments, or PII capture.
- 🧠 **Keep the spine deterministic.** LLM calls belong in `agents/` only.
- 🔌 **Vendor isolation.** Concrete providers stay behind the `providers/base.py` interfaces.
- 🧢 **Don't raise the caps quietly.** The limits in `config.py` protect rate limits and spend.
- ✅ Add tests next to new engine logic; `pytest` must pass offline with no credentials.

---

<p align="center">
  Released under the <a href="LICENSE">MIT License</a>.
  <br/>
  <sub>The optional <code>trvl</code> hotel binary is separately licensed (PolyForm Noncommercial) and is not distributed with this project.</sub>
</p>
