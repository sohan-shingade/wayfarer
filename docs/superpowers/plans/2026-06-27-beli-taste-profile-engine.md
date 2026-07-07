# Beli Taste-Profile Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a person's Beli restaurant data (captured as a scroll screen-recording or screenshots) into a structured taste profile any planner can consume, and merge N people into a group profile.

**Architecture:** A two-stage pipeline that preserves wayfarer's spine rule — LLM does perception only, deterministic Python does all logic. Vision extractor (`claude -p`) reads frames/screenshots → `BeliSnapshot` (raw export, persisted). Pure `engine/taste.py` aggregates a snapshot → `TasteProfile` and merges profiles → `GroupTasteProfile`. Frames come from `ffmpeg mpdecimate` (no extra Python image deps). The snapshot schema is the stable seam: the deferred API path (B) will write the same schema.

**Tech Stack:** Python 3.11+, pydantic v2, `ffmpeg` (system binary), `claude -p` via `agents/runtime.py`, pytest.

## Global Constraints

- **Plan-only.** No booking/payment/PII/purchase logic. (CLAUDE.md)
- **Deterministic spine.** `engine/` and orchestration are plain Python — never LLM calls. LLMs only in `agents/`. (CLAUDE.md)
- **Vendor isolation.** Engine depends only on models + provider/runtime interfaces. (CLAUDE.md)
- **Subscription billing.** Vision extraction goes through `agents/runtime.py` (`claude -p`), which strips API keys + aborts on positive `total_cost_usd`. Do not bypass it. (CLAUDE.md)
- **Python floor:** `requires-python = ">=3.11"`. Use `X | None` unions and `from __future__ import annotations`.
- **Personal data:** all artifacts live under `profiles/<name>/`, which is git-ignored. Never commit a real snapshot/taste file.
- **pydantic:** models subclass `pydantic.BaseModel`; mirror existing `models.py` style (`Field(default_factory=...)`, `Literal[...]`, `@computed_field`).
- **No new Python deps.** Frame dedup uses `ffmpeg mpdecimate`, not Pillow/imagehash.

---

### Task 1: Data contracts in `models.py`

**Files:**
- Modify: `src/wayfarer/models.py` (append new models at end of file)
- Test: `tests/test_beli_models.py`

**Interfaces:**
- Consumes: `pydantic.BaseModel`, `Field`, `computed_field`, `Literal` (already imported in `models.py`).
- Produces:
  - `BeliEntry(name: str, score: float|None, rank: int|None, cuisine: str|None, neighborhood: str|None, city: str|None, price: str|None, vibe: list[str], list_type: Literal["been","want_to_try","recs"], notes: str|None, source_shot: str)`
  - `BeliSnapshot(profile_name: str, captured_at: str, source: Literal["screenshots","video","api"], username: str|None, entries: list[BeliEntry])` with computed `counts: dict[str,int]`
  - `CuisineAffinity(cuisine: str, affinity: float, n: int, avg_score: float|None)`
  - `NeighborhoodPref(area: str, n: int, avg_score: float|None)`
  - `Dislike(target: str, kind: Literal["cuisine","spot"], reason: Literal["low_score","low_rank"])`
  - `TasteProfile(profile_name, cuisine_affinity: dict[str,float], top_cuisines: list[CuisineAffinity], favorite_neighborhoods: list[NeighborhoodPref], price_tendency: dict, vibe_tags: list[str], dislikes: list[Dislike], want_to_try: list[str], score_distribution: dict[str,int], generated_at: str, from_snapshot: str)`
  - `GroupCuisine(cuisine: str, affinity: float)`, `GroupWant(name: str, wanted_by: int)`
  - `GroupTasteProfile(members: list[str], consensus_cuisines: list[GroupCuisine], popular_cuisines: list[GroupCuisine], combined_dislikes: list[Dislike], combined_want_to_try: list[GroupWant], shared_neighborhoods: list[str])`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_beli_models.py
from wayfarer.models import BeliEntry, BeliSnapshot, TasteProfile, GroupTasteProfile


def test_snapshot_counts_computed_and_serialized():
    snap = BeliSnapshot(
        profile_name="alice",
        captured_at="2026-06-27T00:00:00",
        source="video",
        entries=[
            BeliEntry(name="Lhasa Fast Food", score=9.0, cuisine="Tibetan",
                      neighborhood="Jackson Heights", list_type="been"),
            BeliEntry(name="Phayul", cuisine="Tibetan", list_type="want_to_try"),
        ],
    )
    assert snap.counts == {"been": 1, "want_to_try": 1, "recs": 0}
    # computed field must survive JSON round-trip
    assert '"counts"' in snap.model_dump_json()


def test_entry_defaults_are_safe():
    e = BeliEntry(name="X")
    assert e.score is None and e.vibe == [] and e.list_type == "been"


def test_profile_and_group_construct():
    p = TasteProfile(profile_name="alice")
    assert p.cuisine_affinity == {} and p.dislikes == []
    g = GroupTasteProfile(members=["a", "b"])
    assert g.consensus_cuisines == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_beli_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'BeliEntry'`.

- [ ] **Step 3: Append the models to `src/wayfarer/models.py`**

```python
# ---------------------------------------------------------------------------
# Beli taste-profile contracts (sub-project A). Snapshot = raw export;
# TasteProfile = derived; GroupTasteProfile = N people merged.
# ---------------------------------------------------------------------------
class BeliEntry(BaseModel):
    """One restaurant as read off a Beli screen (perception output)."""
    name: str
    score: float | None = None           # Beli /10
    rank: int | None = None              # position in their list, if visible
    cuisine: str | None = None
    neighborhood: str | None = None
    city: str | None = None
    price: str | None = None             # "$".."$$$$"
    vibe: list[str] = Field(default_factory=list)
    list_type: Literal["been", "want_to_try", "recs"] = "been"
    notes: str | None = None
    source_shot: str = ""                # frame/file provenance


class BeliSnapshot(BaseModel):
    """\"Your Beli data, exported.\" The stable seam: path B writes this too."""
    profile_name: str
    captured_at: str = ""
    source: Literal["screenshots", "video", "api"] = "video"
    username: str | None = None
    entries: list[BeliEntry] = Field(default_factory=list)

    @computed_field
    @property
    def counts(self) -> dict[str, int]:
        out = {"been": 0, "want_to_try": 0, "recs": 0}
        for e in self.entries:
            out[e.list_type] = out.get(e.list_type, 0) + 1
        return out


class CuisineAffinity(BaseModel):
    cuisine: str
    affinity: float                      # 0..1
    n: int
    avg_score: float | None = None


class NeighborhoodPref(BaseModel):
    area: str
    n: int
    avg_score: float | None = None


class Dislike(BaseModel):
    target: str
    kind: Literal["cuisine", "spot"]
    reason: Literal["low_score", "low_rank"]


class TasteProfile(BaseModel):
    """Derived per-person taste signal a planner consumes."""
    profile_name: str
    cuisine_affinity: dict[str, float] = Field(default_factory=dict)
    top_cuisines: list[CuisineAffinity] = Field(default_factory=list)
    favorite_neighborhoods: list[NeighborhoodPref] = Field(default_factory=list)
    price_tendency: dict = Field(default_factory=dict)   # {median_tier, distribution}
    vibe_tags: list[str] = Field(default_factory=list)
    dislikes: list[Dislike] = Field(default_factory=list)
    want_to_try: list[str] = Field(default_factory=list)
    score_distribution: dict[str, int] = Field(default_factory=dict)
    generated_at: str = ""
    from_snapshot: str = ""


class GroupCuisine(BaseModel):
    cuisine: str
    affinity: float


class GroupWant(BaseModel):
    name: str
    wanted_by: int


class GroupTasteProfile(BaseModel):
    """N people merged, for group crawls."""
    members: list[str] = Field(default_factory=list)
    consensus_cuisines: list[GroupCuisine] = Field(default_factory=list)
    popular_cuisines: list[GroupCuisine] = Field(default_factory=list)
    combined_dislikes: list[Dislike] = Field(default_factory=list)
    combined_want_to_try: list[GroupWant] = Field(default_factory=list)
    shared_neighborhoods: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_beli_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/wayfarer/models.py tests/test_beli_models.py
git commit -m "feat(beli): add taste-profile data contracts"
```

---

### Task 2: Entry dedup + profile aggregation in `engine/taste.py`

**Files:**
- Create: `src/wayfarer/engine/taste.py`
- Test: `tests/test_taste.py`

**Interfaces:**
- Consumes: `BeliEntry`, `BeliSnapshot`, `TasteProfile`, `CuisineAffinity`, `NeighborhoodPref`, `Dislike` from Task 1.
- Produces:
  - `dedup_entries(entries: list[BeliEntry]) -> list[BeliEntry]` — dedup by `(name.lower().strip(), neighborhood or "")`; on collision prefer a `been` entry over `want_to_try`/`recs`, else keep the first seen.
  - `build_profile(snapshot: BeliSnapshot, *, generated_at: str = "") -> TasteProfile`

Aggregation rules (deterministic, all hand-computable):
- Work from `been` entries with a non-null `score`.
- Min-max normalize across those scores: `norm(x) = (x - lo) / (hi - lo)` if `hi > lo` else `0.5`.
- Per cuisine: `n`, `avg_score`, `affinity = round(norm(avg_score), 3)`.
- `cuisine_affinity` = `{cuisine: affinity}`; `top_cuisines` sorted by affinity desc then n desc.
- `dislikes`: one `Dislike(target=cuisine, kind="cuisine", reason="low_score")` for each cuisine whose `affinity < 0.25`.
- `favorite_neighborhoods`: group `been` (any score) by `neighborhood`, sorted by avg_score desc (None last) then n desc.
- `want_to_try`: `[e.name for e in entries if e.list_type == "want_to_try"]` (order preserved).
- `price_tendency`: `{"median_tier": <median of price strings by length, or None>, "distribution": {price: count}}` over entries with a price.
- `score_distribution`: histogram keyed by `str(int(floor(score)))` over `been` scored entries.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_taste.py
import math
from wayfarer.models import BeliEntry, BeliSnapshot
from wayfarer.engine.taste import dedup_entries, build_profile


def _snap():
    return BeliSnapshot(
        profile_name="alice", captured_at="2026-06-27", source="video",
        entries=[
            BeliEntry(name="Lhasa Fast Food", score=9.0, cuisine="Tibetan",
                      neighborhood="Jackson Heights", price="$", list_type="been"),
            BeliEntry(name="Phayul", score=8.5, cuisine="Tibetan",
                      neighborhood="Jackson Heights", price="$", list_type="been"),
            BeliEntry(name="Adda", score=8.0, cuisine="Indian",
                      neighborhood="Long Island City", price="$$", list_type="been"),
            BeliEntry(name="Ayada", score=6.0, cuisine="Thai",
                      neighborhood="Elmhurst", price="$$", list_type="been"),
            BeliEntry(name="Some Spot", score=4.0, cuisine="Colombian",
                      neighborhood="Jackson Heights", price="$", list_type="been"),
            BeliEntry(name="Raja's", cuisine="Indian", list_type="want_to_try"),
        ],
    )


def test_dedup_prefers_been_and_collapses_repeats():
    e1 = BeliEntry(name="Lhasa Fast Food", neighborhood="Jackson Heights",
                   list_type="want_to_try")
    e2 = BeliEntry(name="lhasa fast food ", score=9.0, neighborhood="Jackson Heights",
                   list_type="been")
    out = dedup_entries([e1, e2])
    assert len(out) == 1 and out[0].list_type == "been"


def test_build_profile_affinity_and_dislikes():
    p = build_profile(_snap(), generated_at="2026-06-27")
    # scores span lo=4.0 hi=9.0; Tibetan avg=8.75 -> norm=(8.75-4)/5=0.95
    assert p.cuisine_affinity["Tibetan"] == 0.95
    assert p.cuisine_affinity["Indian"] == 0.8
    assert p.cuisine_affinity["Thai"] == 0.4
    assert p.cuisine_affinity["Colombian"] == 0.0
    # top cuisine is Tibetan
    assert p.top_cuisines[0].cuisine == "Tibetan" and p.top_cuisines[0].n == 2
    # Colombian affinity < 0.25 -> dislike
    assert any(d.target == "Colombian" and d.kind == "cuisine" for d in p.dislikes)
    assert all(d.target != "Thai" for d in p.dislikes)
    # wishlist passthrough
    assert p.want_to_try == ["Raja's"]
    # score histogram floors
    assert p.score_distribution == {"9": 1, "8": 2, "6": 1, "4": 1}
    assert p.from_snapshot == "alice" and p.generated_at == "2026-06-27"


def test_build_profile_empty_been_does_not_crash():
    snap = BeliSnapshot(profile_name="x", entries=[
        BeliEntry(name="Wishlist Only", list_type="want_to_try")])
    p = build_profile(snap)
    assert p.cuisine_affinity == {} and p.want_to_try == ["Wishlist Only"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_taste.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wayfarer.engine.taste'`.

- [ ] **Step 3: Write the implementation**

```python
# src/wayfarer/engine/taste.py
"""Deterministic taste aggregation. No LLM here: correctness must be testable.

Input is a BeliSnapshot (perception output); output is a TasteProfile a planner
consumes. Beli scores are personal/relative, so affinity is min-max normalized
against the person's own score spread before anything cross-person happens
(see merge_profiles).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict

from ..models import (
    BeliEntry, BeliSnapshot, CuisineAffinity, Dislike, NeighborhoodPref, TasteProfile,
)

_DISLIKE_AFFINITY = 0.25


def _key(e: BeliEntry) -> tuple[str, str]:
    return (e.name.lower().strip(), (e.neighborhood or "").lower().strip())


def dedup_entries(entries: list[BeliEntry]) -> list[BeliEntry]:
    """Collapse the same place seen on overlapping frames. Prefer a `been` row."""
    chosen: dict[tuple[str, str], BeliEntry] = {}
    for e in entries:
        k = _key(e)
        prev = chosen.get(k)
        if prev is None:
            chosen[k] = e
        elif prev.list_type != "been" and e.list_type == "been":
            chosen[k] = e
    return list(chosen.values())


def _norm_fn(scores: list[float]):
    lo, hi = min(scores), max(scores)
    if hi <= lo:
        return lambda x: 0.5
    return lambda x: (x - lo) / (hi - lo)


def build_profile(snapshot: BeliSnapshot, *, generated_at: str = "") -> TasteProfile:
    entries = dedup_entries(snapshot.entries)
    been = [e for e in entries if e.list_type == "been"]
    scored = [e for e in been if e.score is not None]

    cuisine_affinity: dict[str, float] = {}
    top_cuisines: list[CuisineAffinity] = []
    dislikes: list[Dislike] = []
    score_distribution: dict[str, int] = {}

    if scored:
        norm = _norm_fn([e.score for e in scored])  # type: ignore[arg-type]
        by_cuisine: dict[str, list[float]] = defaultdict(list)
        for e in scored:
            if e.cuisine:
                by_cuisine[e.cuisine].append(e.score)  # type: ignore[arg-type]
        for cuisine, vals in by_cuisine.items():
            avg = round(statistics.mean(vals), 3)
            aff = round(norm(avg), 3)
            cuisine_affinity[cuisine] = aff
            top_cuisines.append(CuisineAffinity(cuisine=cuisine, affinity=aff,
                                                n=len(vals), avg_score=avg))
            if aff < _DISLIKE_AFFINITY:
                dislikes.append(Dislike(target=cuisine, kind="cuisine",
                                        reason="low_score"))
        top_cuisines.sort(key=lambda c: (-c.affinity, -c.n))
        for e in scored:
            b = str(int(math.floor(e.score)))  # type: ignore[arg-type]
            score_distribution[b] = score_distribution.get(b, 0) + 1

    # neighborhoods (any been entry)
    nb: dict[str, list[float]] = defaultdict(list)
    nb_count: dict[str, int] = defaultdict(int)
    for e in been:
        if e.neighborhood:
            nb_count[e.neighborhood] += 1
            if e.score is not None:
                nb[e.neighborhood].append(e.score)
    favorite_neighborhoods = [
        NeighborhoodPref(
            area=area, n=nb_count[area],
            avg_score=round(statistics.mean(nb[area]), 3) if nb[area] else None,
        )
        for area in nb_count
    ]
    favorite_neighborhoods.sort(
        key=lambda p: (-(p.avg_score if p.avg_score is not None else -1), -p.n))

    # price tendency
    prices = [e.price for e in entries if e.price]
    price_dist: dict[str, int] = {}
    for p in prices:
        price_dist[p] = price_dist.get(p, 0) + 1
    median_tier = None
    if prices:
        median_tier = sorted(prices, key=len)[len(prices) // 2]
    price_tendency = {"median_tier": median_tier, "distribution": price_dist}

    # vibe tags (most common)
    vibe_count: dict[str, int] = defaultdict(int)
    for e in entries:
        for v in e.vibe:
            vibe_count[v] += 1
    vibe_tags = [v for v, _ in sorted(vibe_count.items(), key=lambda kv: -kv[1])]

    want_to_try = [e.name for e in entries if e.list_type == "want_to_try"]

    return TasteProfile(
        profile_name=snapshot.profile_name,
        cuisine_affinity=cuisine_affinity,
        top_cuisines=top_cuisines,
        favorite_neighborhoods=favorite_neighborhoods,
        price_tendency=price_tendency,
        vibe_tags=vibe_tags,
        dislikes=dislikes,
        want_to_try=want_to_try,
        score_distribution=score_distribution,
        generated_at=generated_at,
        from_snapshot=snapshot.profile_name,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_taste.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/wayfarer/engine/taste.py tests/test_taste.py
git commit -m "feat(beli): entry dedup + per-person taste aggregation"
```

---

### Task 3: Multi-profile merge in `engine/taste.py`

**Files:**
- Modify: `src/wayfarer/engine/taste.py` (append `merge_profiles`)
- Test: `tests/test_taste_merge.py`

**Interfaces:**
- Consumes: `TasteProfile`, `Dislike` (Task 1); `build_profile` (Task 2).
- Produces: `merge_profiles(profiles: list[TasteProfile]) -> GroupTasteProfile`

Merge rules:
- `members` = each `profile_name`.
- `consensus_cuisines`: cuisines present in **every** profile's `cuisine_affinity`; affinity = **min** across members; sorted by affinity desc.
- `popular_cuisines`: cuisines present in **any** profile; affinity = **mean** over the members that have it (rounded 3); sorted by affinity desc.
- `combined_dislikes`: **union** of all `dislikes`, deduped by `(target, kind)`, order by first appearance.
- `combined_want_to_try`: union of `want_to_try` names → `GroupWant(name, wanted_by=count)`, sorted by `wanted_by` desc then name asc.
- `shared_neighborhoods`: areas appearing in **every** member's `favorite_neighborhoods`, order by first member's ranking.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_taste_merge.py
from wayfarer.models import BeliEntry, BeliSnapshot
from wayfarer.engine.taste import build_profile, merge_profiles


def _person(name, rows):
    return build_profile(BeliSnapshot(profile_name=name, entries=[
        BeliEntry(**r) for r in rows]))


def test_merge_consensus_popular_dislikes_wishlist():
    a = _person("a", [
        {"name": "T1", "score": 9.0, "cuisine": "Tibetan",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "I1", "score": 7.0, "cuisine": "Indian",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "C1", "score": 4.0, "cuisine": "Colombian",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "Raja's", "cuisine": "Indian", "list_type": "want_to_try"},
    ])
    b = _person("b", [
        {"name": "T2", "score": 8.0, "cuisine": "Tibetan",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "M2", "score": 9.0, "cuisine": "Mexican",
         "neighborhood": "Corona", "list_type": "been"},
        {"name": "C2", "score": 5.0, "cuisine": "Colombian",
         "neighborhood": "Jackson Heights", "list_type": "been"},
        {"name": "Raja's", "cuisine": "Indian", "list_type": "want_to_try"},
    ])
    g = merge_profiles([a, b])
    assert g.members == ["a", "b"]
    # Tibetan + Colombian are in BOTH -> consensus; Tibetan ranks first
    cons = {c.cuisine for c in g.consensus_cuisines}
    assert cons == {"Tibetan", "Colombian"}
    assert g.consensus_cuisines[0].cuisine == "Tibetan"
    # popular includes union (Indian, Mexican present in one each)
    pop = {c.cuisine for c in g.popular_cuisines}
    assert {"Tibetan", "Indian", "Mexican", "Colombian"} <= pop
    # both wanted Raja's -> wanted_by 2
    assert g.combined_want_to_try[0].name == "Raja's"
    assert g.combined_want_to_try[0].wanted_by == 2
    # Jackson Heights is a favorite for both -> shared
    assert "Jackson Heights" in g.shared_neighborhoods
    # Colombian is a dislike for both (low affinity) -> appears once
    targets = [(d.target, d.kind) for d in g.combined_dislikes]
    assert targets.count(("Colombian", "cuisine")) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_taste_merge.py -v`
Expected: FAIL with `ImportError: cannot import name 'merge_profiles'`.

- [ ] **Step 3: Append the implementation to `src/wayfarer/engine/taste.py`**

```python
def merge_profiles(profiles: list[TasteProfile]) -> "GroupTasteProfile":
    from ..models import GroupCuisine, GroupTasteProfile, GroupWant

    members = [p.profile_name for p in profiles]
    affinity_maps = [p.cuisine_affinity for p in profiles]

    all_cuisines: list[str] = []
    for m in affinity_maps:
        for c in m:
            if c not in all_cuisines:
                all_cuisines.append(c)

    consensus: list[GroupCuisine] = []
    popular: list[GroupCuisine] = []
    for c in all_cuisines:
        present = [m[c] for m in affinity_maps if c in m]
        popular.append(GroupCuisine(cuisine=c, affinity=round(sum(present) / len(present), 3)))
        if len(present) == len(affinity_maps) and affinity_maps:
            consensus.append(GroupCuisine(cuisine=c, affinity=round(min(present), 3)))
    consensus.sort(key=lambda g: -g.affinity)
    popular.sort(key=lambda g: -g.affinity)

    seen: set[tuple[str, str]] = set()
    combined_dislikes: list[Dislike] = []
    for p in profiles:
        for d in p.dislikes:
            k = (d.target, d.kind)
            if k not in seen:
                seen.add(k)
                combined_dislikes.append(d)

    want_count: dict[str, int] = {}
    for p in profiles:
        for name in p.want_to_try:
            want_count[name] = want_count.get(name, 0) + 1
    combined_want_to_try = [
        GroupWant(name=n, wanted_by=c)
        for n, c in sorted(want_count.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    nb_sets = [{np.area for np in p.favorite_neighborhoods} for p in profiles]
    shared_neighborhoods: list[str] = []
    if nb_sets:
        first_order = [np.area for np in profiles[0].favorite_neighborhoods]
        for area in first_order:
            if all(area in s for s in nb_sets):
                shared_neighborhoods.append(area)

    return GroupTasteProfile(
        members=members,
        consensus_cuisines=consensus,
        popular_cuisines=popular,
        combined_dislikes=combined_dislikes,
        combined_want_to_try=combined_want_to_try,
        shared_neighborhoods=shared_neighborhoods,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_taste_merge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wayfarer/engine/taste.py tests/test_taste_merge.py
git commit -m "feat(beli): multi-profile merge into GroupTasteProfile"
```

---

### Task 4: Frame extraction in `engine/frames.py`

**Files:**
- Create: `src/wayfarer/engine/frames.py`
- Test: `tests/test_frames.py`

**Interfaces:**
- Consumes: stdlib only (`subprocess`, `pathlib`, `shutil`).
- Produces:
  - `ffmpeg_cmd(video: str, out_pattern: str, fps: int = 2) -> list[str]` (pure; the command list)
  - `extract_frames(video, out_dir, fps: int = 2) -> list[Path]` (runs ffmpeg; integration)

ffmpeg uses the `mpdecimate` filter to drop near-duplicate frames (handles scroll pauses), after sampling to `fps` frames/sec, with `-vsync vfr` so dropped frames don't become duplicates.

- [ ] **Step 1: Write the failing test (pure command builder only)**

```python
# tests/test_frames.py
from wayfarer.engine.frames import ffmpeg_cmd


def test_ffmpeg_cmd_has_mpdecimate_and_paths():
    cmd = ffmpeg_cmd("in.mov", "out/frame_%04d.png", fps=2)
    assert cmd[0] == "ffmpeg"
    assert "in.mov" in cmd
    assert "out/frame_%04d.png" in cmd
    # mpdecimate + fps in the filter chain, vfr sync
    joined = " ".join(cmd)
    assert "mpdecimate" in joined and "fps=2" in joined
    assert "vfr" in joined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_frames.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wayfarer.engine.frames'`.

- [ ] **Step 3: Write the implementation**

```python
# src/wayfarer/engine/frames.py
"""Turn a Beli scroll screen-recording into a small set of frames to read.

Uses ffmpeg's mpdecimate filter to drop near-duplicate frames (a slow scroll
with brief pauses yields roughly one frame per screen), so we don't need any
Python image libraries. Residual overlap is handled downstream by
engine.taste.dedup_entries.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_cmd(video: str, out_pattern: str, fps: int = 2) -> list[str]:
    return [
        "ffmpeg", "-i", video,
        "-vf", f"fps={fps},mpdecimate",
        "-vsync", "vfr",
        out_pattern,
    ]


def extract_frames(video: str | Path, out_dir: str | Path, fps: int = 2) -> list[Path]:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH. Install it (`brew install ffmpeg`).")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pattern = str(out / "frame_%04d.png")
    proc = subprocess.run(
        ffmpeg_cmd(str(video), pattern, fps=fps),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-500:]}")
    return sorted(out.glob("frame_*.png"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_frames.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/wayfarer/engine/frames.py tests/test_frames.py
git commit -m "feat(beli): ffmpeg frame extraction with mpdecimate dedup"
```

---

### Task 5: Vision extractor agent

**Files:**
- Create: `src/wayfarer/agents/prompts/beli_extract.md`
- Create: `src/wayfarer/agents/beli_extractor.py`
- Test: `tests/test_beli_extractor.py`

**Interfaces:**
- Consumes: `AgentRuntime`, `parse_json_block` (`agents/runtime.py`); `BeliEntry` (Task 1).
- Produces:
  - `entries_from_rows(rows: list[dict], list_type: str, source_shot: str = "") -> list[BeliEntry]` (pure; tested)
  - `async extract_entries(runtime: AgentRuntime, image_paths: list[str], list_type: str = "been") -> list[BeliEntry]` (calls runtime; integration)

The prompt tells `claude -p` to Read each image path and emit a JSON array of entry objects (no prose). `entries_from_rows` validates/coerces rows into `BeliEntry`, ignoring unknown keys and tolerating missing fields.

- [ ] **Step 1: Write the failing test (pure row parser)**

```python
# tests/test_beli_extractor.py
from wayfarer.agents.beli_extractor import entries_from_rows


def test_entries_from_rows_coerces_and_sets_list_type():
    rows = [
        {"name": "Lhasa Fast Food", "score": 9.0, "cuisine": "Tibetan",
         "neighborhood": "Jackson Heights", "price": "$", "bogus_key": 1},
        {"name": "Phayul"},  # sparse row tolerated
    ]
    out = entries_from_rows(rows, list_type="been", source_shot="frame_0001.png")
    assert len(out) == 2
    assert out[0].name == "Lhasa Fast Food" and out[0].score == 9.0
    assert out[0].list_type == "been" and out[0].source_shot == "frame_0001.png"
    assert out[1].score is None and out[1].cuisine is None


def test_entries_from_rows_skips_nameless():
    out = entries_from_rows([{"score": 8.0}, {"name": "  "}], list_type="been")
    assert out == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_beli_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wayfarer.agents.beli_extractor'`.

- [ ] **Step 3a: Write the prompt template**

```markdown
<!-- src/wayfarer/agents/prompts/beli_extract.md -->
You are a precise data extractor reading screenshots of a user's Beli restaurant
list. Beli shows restaurants with a name, a /10 score (for visited "been" places),
a cuisine, a neighborhood/city, and a price tier ($-$$$$).

Use your Read tool to open EACH image path listed at the end of this message and
read every restaurant row visible across all of them.

Return ONLY a JSON array (no prose, no code fence) of objects with these keys:
- name (string, required)
- score (number or null)   // the /10 number if shown
- rank (integer or null)   // list position if shown
- cuisine (string or null)
- neighborhood (string or null)
- city (string or null)
- price (string or null)   // "$".."$$$$"
- notes (string or null)

Rules:
- One object per distinct restaurant. If the same restaurant appears on multiple
  frames (overlapping scroll), include it once.
- Do not invent fields you cannot see; use null.
- Output the JSON array and nothing else.

Image paths to read:
```

- [ ] **Step 3b: Write the extractor module**

```python
# src/wayfarer/agents/beli_extractor.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_beli_extractor.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/wayfarer/agents/beli_extractor.py src/wayfarer/agents/prompts/beli_extract.md tests/test_beli_extractor.py
git commit -m "feat(beli): vision extractor agent + prompt"
```

---

### Task 6: Pipeline wiring + CLI

**Files:**
- Create: `src/wayfarer/beli_ingest.py`
- Modify: `pyproject.toml` (add console script)
- Test: `tests/test_beli_ingest.py`

**Interfaces:**
- Consumes: `extract_entries` (Task 5), `extract_frames` (Task 4), `dedup_entries`/`build_profile` (Tasks 2), `BeliSnapshot` (Task 1), `ClaudeCLIRuntime`/`run_sync` (`agents/runtime.py`).
- Produces:
  - `chunk(items: list, n: int) -> list[list]` (pure; tested)
  - `build_snapshot(name, entries, *, source, captured_at, username=None) -> BeliSnapshot` (pure; tested)
  - `ingest(name, *, video=None, shots_dir=None, runtime=None, profiles_root="profiles", captured_at="", model="sonnet", batch=8) -> tuple[BeliSnapshot, TasteProfile]` (integration; orchestrates frames → extract → snapshot.json → build_profile → taste.json)
  - `main()` — CLI entry: `wayfarer-beli <name> (--video PATH | --shots DIR) [--merge name1,name2]`

- [ ] **Step 1: Write the failing test (pure helpers)**

```python
# tests/test_beli_ingest.py
from wayfarer.models import BeliEntry
from wayfarer.beli_ingest import chunk, build_snapshot


def test_chunk_splits_evenly_and_remainder():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert chunk([], 3) == []


def test_build_snapshot_dedups_and_sets_meta():
    entries = [
        BeliEntry(name="A", neighborhood="JH", list_type="want_to_try"),
        BeliEntry(name="a", score=9.0, neighborhood="JH", list_type="been"),
        BeliEntry(name="B", list_type="been"),
    ]
    snap = build_snapshot("alice", entries, source="video",
                          captured_at="2026-06-27")
    assert snap.profile_name == "alice" and snap.source == "video"
    assert snap.captured_at == "2026-06-27"
    # A/a collapsed -> 2 entries, the been row kept
    assert len(snap.entries) == 2
    assert any(e.name == "a" and e.list_type == "been" for e in snap.entries)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_beli_ingest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wayfarer.beli_ingest'`.

- [ ] **Step 3: Write the implementation**

```python
# src/wayfarer/beli_ingest.py
"""Pipeline: screen-recording or screenshots -> beli_snapshot.json -> taste.json.

Wires the vision extractor (agents/) to the deterministic aggregator (engine/).
Artifacts live under profiles/<name>/ (git-ignored personal data).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .agents.beli_extractor import extract_entries
from .agents.runtime import AgentRuntime, ClaudeCLIRuntime, run_sync
from .engine.frames import extract_frames
from .engine.taste import build_profile, dedup_entries, merge_profiles
from .models import BeliEntry, BeliSnapshot, TasteProfile


def chunk(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def build_snapshot(name: str, entries: list[BeliEntry], *, source: str,
                   captured_at: str, username: str | None = None) -> BeliSnapshot:
    return BeliSnapshot(
        profile_name=name, source=source, captured_at=captured_at,
        username=username, entries=dedup_entries(entries),
    )


def _image_paths(video: str | None, shots_dir: str | None, work: Path) -> list[str]:
    if video:
        frames = extract_frames(video, work / "frames")
        return [str(p) for p in frames]
    if shots_dir:
        shots = sorted(Path(shots_dir).glob("*.png")) + sorted(Path(shots_dir).glob("*.jpg"))
        return [str(p) for p in shots]
    raise ValueError("provide either video= or shots_dir=")


def ingest(name: str, *, video: str | None = None, shots_dir: str | None = None,
           runtime: AgentRuntime | None = None, profiles_root: str = "profiles",
           captured_at: str = "", model: str = "sonnet",
           batch: int = 8) -> tuple[BeliSnapshot, TasteProfile]:
    runtime = runtime or ClaudeCLIRuntime(model=model)
    captured_at = captured_at or datetime.now().isoformat(timespec="seconds")
    work = Path(profiles_root) / name
    work.mkdir(parents=True, exist_ok=True)

    paths = _image_paths(video, shots_dir, work)
    source = "video" if video else "screenshots"

    entries: list[BeliEntry] = []
    for group in chunk(paths, batch):
        res = run_sync(runtime, "")  # placeholder replaced below
        # NB: extract_entries is async; call it directly via run_sync helper pattern.
        # We use asyncio through the runtime's own loop:
        import asyncio
        entries += asyncio.run(extract_entries(runtime, group))

    snap = build_snapshot(name, entries, source=source, captured_at=captured_at)
    (work / "beli_snapshot.json").write_text(snap.model_dump_json(indent=2),
                                             encoding="utf-8")
    profile = build_profile(snap, generated_at=captured_at)
    (work / "taste.json").write_text(profile.model_dump_json(indent=2),
                                     encoding="utf-8")
    return snap, profile


def _load_profile(name: str, profiles_root: str) -> TasteProfile:
    raw = (Path(profiles_root) / name / "taste.json").read_text(encoding="utf-8")
    return TasteProfile(**json.loads(raw))


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a Beli taste profile (plan-only).")
    ap.add_argument("name", help="profile name (folder under profiles/)")
    ap.add_argument("--video", help="path to a Beli scroll screen-recording")
    ap.add_argument("--shots", help="directory of Beli screenshots")
    ap.add_argument("--merge", help="comma-separated profile names to merge into a group")
    ap.add_argument("--profiles-root", default="profiles")
    ap.add_argument("--model", default="sonnet")
    args = ap.parse_args()

    if args.merge:
        names = [n.strip() for n in args.merge.split(",") if n.strip()]
        group = merge_profiles([_load_profile(n, args.profiles_root) for n in names])
        out = Path(args.profiles_root) / f"group_{'_'.join(names)}.json"
        out.write_text(group.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote {out}")
        return

    if not (args.video or args.shots):
        ap.error("provide --video or --shots")
    snap, profile = ingest(args.name, video=args.video, shots_dir=args.shots,
                           profiles_root=args.profiles_root, model=args.model)
    print(f"{args.name}: {len(snap.entries)} places -> "
          f"{len(profile.top_cuisines)} cuisines, "
          f"{len(profile.want_to_try)} on wishlist")
    print(f"wrote profiles/{args.name}/beli_snapshot.json + taste.json")
```

Note: replace the placeholder loop body with the clean async call — the implementer should write exactly:

```python
    import asyncio
    entries: list[BeliEntry] = []
    for group in chunk(paths, batch):
        entries += asyncio.run(extract_entries(runtime, group))
```

(Delete the `run_sync(runtime, "")` placeholder line; it was only to flag where the call goes.)

- [ ] **Step 4: Add the console script to `pyproject.toml`**

Modify the `[project.scripts]` table (currently has `wayfarer` and `wayfarer-deals`) to add:

```toml
wayfarer-beli = "wayfarer.beli_ingest:main"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_beli_ingest.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Full suite + commit**

Run: `.venv/bin/python -m pytest -q`
Expected: existing tests still pass + new Beli tests pass.

```bash
git add src/wayfarer/beli_ingest.py pyproject.toml tests/test_beli_ingest.py
git commit -m "feat(beli): ingest pipeline + wayfarer-beli CLI"
```

---

### Task 7: Live smoke test + README (manual, no automated test)

**Files:**
- Modify: `README.md` (add a "Beli taste profiles" section)

**Interfaces:** none new.

- [ ] **Step 1: Manual live smoke (requires `claude login` + a real recording)**

Record a slow scroll of your Beli "been" list to `profiles/alice/list.mov`, then:

Run: `.venv/bin/wayfarer-beli alice --video profiles/alice/list.mov`
Expected: prints a places/cuisines/wishlist summary; `profiles/alice/beli_snapshot.json` and `taste.json` exist and look right (spot-check 5 entries against the app).

- [ ] **Step 2: Document usage in `README.md`**

Add a section covering: capture rule ("scroll slow/steady, brief pauses help"), `--video` vs `--shots`, where artifacts land, multi-profile `--merge a,b`, and the `ffmpeg` dependency.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(beli): usage for taste-profile ingestion"
```

---

## Self-Review

**Spec coverage:**
- Two artifacts (snapshot + taste.json) → Tasks 1, 2, 6. ✓
- BeliEntry/BeliSnapshot/TasteProfile/GroupTasteProfile contracts → Task 1. ✓
- Per-person normalization before merge → Task 2 (`_norm_fn` min-max). ✓
- Multi-profile merge (consensus=min, popular=mean, dislike union, want overlap, shared neighborhoods) → Task 3. ✓
- Video-first ingestion + frame sample/dedup → Task 4 (ffmpeg mpdecimate; supersedes spec's Pillow/imagehash — fewer deps, noted in Global Constraints). ✓
- Screenshots/paste quick path → Task 6 (`--shots`; paste = run extractor on provided image paths). ✓
- Vision extractor = perception only, via runtime → Task 5. ✓
- Edge cases: dedup overlap (Task 2), null score/cuisine (Tasks 2/5), wishlist-only (Task 2 test), ffmpeg missing (Task 4). ✓
- Pure-engine tests, no creds → Tasks 1–6. ✓
- Future seam (B writes same snapshot) → snapshot schema in Task 1 is source-tagged. ✓

**Placeholder scan:** Task 6 Step 3 intentionally flags one placeholder line and Step "Note" gives the exact replacement — implementer deletes it. No other TBDs.

**Type consistency:** `BeliSnapshot.entries`, `cuisine_affinity: dict[str,float]`, `build_profile(snapshot, *, generated_at)`, `merge_profiles(list[TasteProfile])`, `extract_entries(runtime, image_paths, list_type)`, `entries_from_rows(rows, list_type, source_shot)`, `chunk`, `build_snapshot` — names/signatures match across tasks. ✓

## Notes / deviations from spec
- Frame dedup uses `ffmpeg mpdecimate` instead of Pillow+imagehash (no new Python deps; entry-level dedup remains the correctness layer).
- `cuisine` is a single string per entry (spec open item resolved to single; revisit if Beli shows multi-tags).
- Affinity formula = min-max normalization of the person's own scores (simple, exactly testable); can be tuned behind the Task 2 tests without breaking consumers.
