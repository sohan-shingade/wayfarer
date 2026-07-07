# Beli Taste-Profile Engine — Design

**Date:** 2026-06-26
**Status:** Approved design, pre-implementation
**Sub-project A** of wayfarer, a **clone-and-go Claude Code harness for itinerary
planning** — vacation trips, food crawls, and similar plan-types on one shared spine.

## Context

Wayfarer is a Claude-Code-native, plan-only **planning harness**: a deterministic
orchestrator + `engine/` spine, LLM agents run via `claude -p` on the user's own
subscription, vendor-isolated providers, run output as JSON + HTML. The vision is a
free resource a Claude Code user clones, adds their own API keys, and gets a
taste-personalized planner that handles multiple **plan-types** — `vacation` (built
today; the Puerto Rico runs are the shape) and `food_crawl` (being added) — that
share one infrastructure: elicit → data providers → engine → agents → output.

**Taste profiles are a shared personalization input across all plan-types**, not a
food-crawl-only feature: the same profile that picks restaurants for a Jackson
Heights crawl also biases dining choices inside a vacation itinerary.

This spec covers **only sub-project A: the Beli taste-profile engine** — turning a
person's Beli restaurant data into a structured taste profile any planner consumes.
It is foundational: personalization across the harness depends on it.

### Roadmap (for reference, not in scope here)
- **A. Beli taste-profile engine** ← this spec (shared personalization module)
- B. Reverse-engineered Beli API ingestion (deferred — mobile-only app, requires
  proxy capture + likely cert-pinning; brittle for clone-and-go)
- C. Food-crawl plan-type (consumes A + a free food-data layer) on the shared spine
- D. Standardize the run/HTML output across plan-types
- (Harness generalization: make `plan-type` a first-class, pluggable concept so
  `vacation` and `food_crawl` share elicit/engine/output and differ only in their
  domain providers + planner agent.)

## Goal

Given a person's Beli data, produce:
1. `beli_snapshot.json` — "your Beli data, exported": the raw, structured list.
2. `taste.json` — a derived `TasteProfile` the planner consumes.

And merge N people's profiles into a `GroupTasteProfile` for group crawls.

## Non-goals
- No Beli API / scraping (that is B, deferred).
- No itinerary planning (that is C).
- No commercial/data-moat concerns — this is a free resource; the data is the
  user's own, supplied willingly.

## Why screenshots/video, not the API

Beli is mobile-first. The web app (`app.beliapp.com`) is a JS SPA that errors out
for general use; its data loads from a non-public API host we cannot discover or
reach without capturing mobile-app traffic through a proxy (and the app likely pins
certs). So the viable, low-friction, clone-and-go path is **the user capturing their
own list visually** and Claude vision reading it. The reverse-engineered API (B)
remains a future optional ingestion that writes the *same* snapshot schema.

## Architecture

```
input  (one of):
  - a scroll screen-recording  .mov/.mp4   ← scalable DEFAULT
  - loose screenshots / pasted images       ← quick path for small lists
        │
        ▼  ffmpeg: sample frames (interval tuned to guarantee row overlap)
        ▼  perceptual-hash dedup → drop near-identical frames
        │
        ▼  Claude vision Extractor  [the ONLY LLM step, in agents/]
        │     batches ~6–10 frames per `claude -p` vision call
        │
        ▼  beli_snapshot.json   (BeliSnapshot)  — perception output, persisted
        │
        ▼  engine/taste.py  [deterministic, pure, unit-tested]
        ▼  taste.json        (TasteProfile)      — derived per person
        │
        ▼  merge(N snapshots) → GroupTasteProfile  — for group crawls
```

**The seam is the snapshot schema, not an extractor interface.** Only one extractor
exists (Claude vision); B later writes the same `beli_snapshot.json` from API JSON.
No backend abstraction is built now (YAGNI).

**Spine rule preserved:** the LLM does perception only (`agents/`). All logic that
must be correct and reproducible — affinity weighting, dislike detection, group
merge — is pure Python in `engine/`.

## Components & repo placement

| Unit | File | Purpose | Depends on |
|---|---|---|---|
| Contracts | `models.py` (extend) | `BeliEntry`, `BeliSnapshot`, `TasteProfile`, `GroupTasteProfile` | pydantic |
| Frame prep | `engine/frames.py` | video → sampled, perceptually-deduped frames | ffmpeg (subprocess), Pillow/imagehash |
| Extractor | `agents/beli_extractor.py` + `agents/prompts/beli_extract.md` | vision `claude -p`: frames/images → `BeliEntry[]` | `agents/runtime.py` |
| Aggregation | `engine/taste.py` | entries → `TasteProfile`; merge → `GroupTasteProfile` | pure Python |
| Entry point | `cli.py` (extend) / chat | run ingestion, write artifacts | above |
| Artifacts | `profiles/<name>/` | `shots/` or `video`, `beli_snapshot.json`, `taste.json` | — |

## Data contracts

### BeliEntry (one restaurant)
- `name: str`
- `score: float | None` — Beli /10
- `rank: int | None` — position in their list if visible
- `cuisine: str | None`
- `neighborhood: str | None`
- `city: str | None`
- `price: str | None` — `$`–`$$$$`
- `vibe: list[str]` — tags if visible (e.g. "date night", "casual")
- `list_type: "been" | "want_to_try" | "recs"`
- `notes: str | None`
- `source_shot: str` — frame/file provenance

### BeliSnapshot (the export)
- `profile_name: str`
- `captured_at: str` — ISO, passed in
- `source: "screenshots" | "video" | "api"`
- `username: str | None`
- `entries: list[BeliEntry]`
- `counts: {been: int, want_to_try: int, recs: int}`

### TasteProfile (derived, per person)
- `profile_name: str`
- `cuisine_affinity: dict[str, float]` — 0–1, **normalized to this person's own
  score distribution** (see weighting)
- `top_cuisines: list[{cuisine, affinity, n, avg_score}]`
- `favorite_neighborhoods: list[{area, n, avg_score}]`
- `price_tendency: {median_tier, distribution}`
- `vibe_tags: list[str]`
- `dislikes: list[{target, kind: "cuisine" | "spot", reason: "low_score" | "low_rank"}]`
- `want_to_try: list[str]` — explicit wishlist; highest-signal planner input
- `score_distribution: dict` — histogram
- `generated_at: str`, `from_snapshot: str`

### GroupTasteProfile (N people)
- `members: list[str]`
- `consensus_cuisines: list[{cuisine, affinity}]` — **min** affinity across members
  ("safe for everyone"; center the crawl here)
- `popular_cuisines: list[{cuisine, affinity}]` — **mean** affinity ("generally liked")
- `combined_dislikes: list[...]` — **union** (if anyone strongly dislikes → avoid)
- `combined_want_to_try: list[{name, wanted_by: int}]` — union, boosted by overlap
- `shared_neighborhoods: list[str]`

## Weighting & normalization (engine/taste.py)

Beli scores are **personal and relative** — one person's 8.5 ≠ another's. Therefore:

1. Per person, compute affinity from the **been** list only:
   `affinity(cuisine) = norm(avg_score_for_cuisine vs personal_mean) * weight(count)`
   where `norm` maps the cuisine's mean score, relative to the person's own mean and
   spread, into 0–1, and `weight(count)` is a saturating function (e.g.
   `log(1+count)` normalized) so one 9.5 doesn't outrank a consistently-loved cuisine.
2. `dislike` when a cuisine/spot scores well below the person's personal mean, or is
   ranked in their bottom tier.
3. Normalize **before** any cross-person merge so a harsh rater doesn't drag the
   group down.

Exact `norm`/`weight` formulas are an implementation detail; they live behind unit
tests against fixture snapshots so they can be tuned without breaking consumers.

## Ingestion flows

**Video (default):** user drops `profiles/<name>/list.mov` (a slow, steady scroll of
their Beli list) → `engine/frames.py` samples + dedups frames → extractor → snapshot
→ taste. One capture rule surfaced to the user: **scroll slow and steady** (fast
scroll skips rows).

**Screenshots / paste (quick path):** user drops images in `profiles/<name>/shots/`
or pastes them into Claude chat → extractor → snapshot → taste. Same downstream.

**Multi-profile:** one folder per person under `profiles/`. `merge` runs over the
selected profiles to produce a `GroupTasteProfile`.

## Cost note

Vision must *see* every row once: ~500 spots ≈ ~100 screens ≈ ~100 frames read,
regardless of capture method. Video removes capture tedium, not read count;
frame-batching (~6–10 frames/call) cuts call overhead. Cost scales with list size,
is one-time per person, and runs on the user's own `claude -p` subscription. This is
the strongest future argument for B (one API call returns the whole list, no vision).

## Error handling & edge cases (in engine, must not crash)
- Overlapping frames/screenshots → dedup entries by `name`+`neighborhood`.
- Fast scroll skipped rows → surfaced as a warning if frame gaps look too large;
  user re-records. Not silently dropped.
- Null `score`/`cuisine` tolerated; entry kept with available fields.
- Wishlist-only profile (no ratings) → profile leans on `want_to_try` + cuisine
  counts; affinity falls back to count-based with a low-confidence flag.
- Corrupt/unreadable frame → skip with a logged warning, continue.
- ffmpeg missing → clear actionable error (`brew install ffmpeg`).

## Testing
- `engine/taste.py` and `engine/frames.py` are pure → assert-based unit tests, no
  creds, mirroring wayfarer's existing budget tests.
  - fixture `BeliSnapshot` → expected `TasteProfile` (affinity ordering, dislikes,
    wishlist passthrough, per-person normalization).
  - 2–3 fixture profiles → expected `GroupTasteProfile` (consensus = min, popular =
    mean, dislike union, want-to-try overlap boost).
  - frame dedup: synthetic near-duplicate frames → expected unique set.
- The vision extractor is not unit-tested for content (LLM); it is exercised via a
  recorded-fixture path if practical, otherwise manually.

## Dependencies
- `ffmpeg` (system, `brew install ffmpeg`) — frame extraction.
- `Pillow` + `imagehash` (or equivalent) — perceptual frame dedup.
- Existing: pydantic, `agents/runtime.py` (`claude -p`).

## Future (out of scope, noted for seam-stability)
- **B — Beli API ingestion:** writes the same `BeliSnapshot` schema from captured
  API JSON; everything downstream is unchanged.
- **C — planner consumption:** planner reads `TasteProfile` / `GroupTasteProfile`
  (`cuisine_affinity`, `want_to_try`, `combined_dislikes`) to rank/sequence crawl
  stops.

## Open items
- Exact `norm`/`weight` formula for affinity (tune behind tests).
- Frame-sampling interval + perceptual-hash threshold defaults (tune on a real
  recording).
- Whether `cuisine` should be a single value or a small list per entry (start
  single; revisit if Beli shows multi-tags).
