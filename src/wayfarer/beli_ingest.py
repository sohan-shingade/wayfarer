"""Pipeline: screen-recording or screenshots -> beli_snapshot.json -> taste.json.

Wires the vision extractor (agents/) to the deterministic aggregator (engine/).
Artifacts live under profiles/<name>/ (git-ignored personal data).
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

from .agents.beli_extractor import extract_entries
from .agents.runtime import AgentRuntime, ClaudeCLIRuntime
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
           batch: int = 4, list_type: str = "been") -> tuple[BeliSnapshot, TasteProfile]:
    # Fix 3: 12 turns to handle the multiple Read tool round-trips per batch.
    runtime = runtime or ClaudeCLIRuntime(model=model, max_turns=12)
    captured_at = captured_at or datetime.now().isoformat(timespec="seconds")
    work = Path(profiles_root) / name
    work.mkdir(parents=True, exist_ok=True)

    paths = _image_paths(video, shots_dir, work)
    source = "video" if video else "screenshots"

    # Fix 2: accumulate across runs — load any prior snapshot first so both list
    # types build up in one file over successive ingest calls.
    prior_entries: list[BeliEntry] = []
    prior_snap_path = work / "beli_snapshot.json"
    if prior_snap_path.exists():
        prior_snap = BeliSnapshot.model_validate_json(
            prior_snap_path.read_text(encoding="utf-8")
        )
        prior_entries = prior_snap.entries

    new_entries: list[BeliEntry] = []
    for group in chunk(paths, batch):
        new_entries += asyncio.run(extract_entries(runtime, group, list_type=list_type))

    # dedup_entries (called inside build_snapshot) prefers 'been' on collision.
    snap = build_snapshot(name, prior_entries + new_entries,
                          source=source, captured_at=captured_at)
    prior_snap_path.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    profile = build_profile(snap, generated_at=captured_at)
    (work / "taste.json").write_text(profile.model_dump_json(indent=2),
                                     encoding="utf-8")
    return snap, profile


def _load_profile(name: str, profiles_root: str) -> TasteProfile:
    raw = (Path(profiles_root) / name / "taste.json").read_text(encoding="utf-8")
    return TasteProfile.model_validate_json(raw)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build a Beli taste profile (plan-only).")
    ap.add_argument("name", help="profile name (folder under profiles/)")
    ap.add_argument("--video", help="path to a Beli scroll screen-recording")
    ap.add_argument("--shots", help="directory of Beli screenshots")
    ap.add_argument("--merge", help="comma-separated profile names to merge into a group")
    ap.add_argument("--profiles-root", default="profiles")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument(
        "--list-type", default="been", choices=["been", "want_to_try", "recs"],
        help="Which Beli list you are capturing. Run once per list type; "
             "each run accumulates into the same snapshot.",
    )
    args = ap.parse_args()

    if args.merge:
        names = [n.strip() for n in args.merge.split(",") if n.strip()]
        profiles: list[TasteProfile] = []
        for n in names:
            taste_path = Path(args.profiles_root) / n / "taste.json"
            if not taste_path.exists():
                ap.error(f"taste.json not found for profile '{n}' (expected {taste_path}). "
                         f"Run 'wayfarer-beli {n} --shots ...' first.")
            profiles.append(_load_profile(n, args.profiles_root))
        group = merge_profiles(profiles)
        out = Path(args.profiles_root) / f"group_{'_'.join(names)}.json"
        out.write_text(group.model_dump_json(indent=2), encoding="utf-8")
        print(f"wrote {out}")
        return

    if not (args.video or args.shots):
        ap.error("provide --video or --shots")
    snap, profile = ingest(args.name, video=args.video, shots_dir=args.shots,
                           profiles_root=args.profiles_root, model=args.model,
                           list_type=args.list_type)
    print(f"{args.name}: {len(snap.entries)} places -> "
          f"{len(profile.top_cuisines)} cuisines, "
          f"{len(profile.want_to_try)} on wishlist")
    print(f"wrote profiles/{args.name}/beli_snapshot.json + taste.json")
