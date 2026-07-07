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
    BeliEntry, BeliSnapshot, CuisineAffinity, Dislike, GroupTasteProfile,
    NeighborhoodPref, TasteProfile,
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


def merge_profiles(profiles: list[TasteProfile]) -> GroupTasteProfile:
    from ..models import GroupCuisine, GroupWant

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

    nb_sets = [{hood.area for hood in p.favorite_neighborhoods} for p in profiles]
    shared_neighborhoods: list[str] = []
    if nb_sets:
        first_order = [hood.area for hood in profiles[0].favorite_neighborhoods]
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
