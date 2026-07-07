from __future__ import annotations

import json


from wayfarer.agents.runtime import AgentResult, AgentRuntime
from wayfarer.beli_ingest import chunk, build_snapshot, ingest
from wayfarer.models import BeliEntry, BeliSnapshot, TasteProfile


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


class _FakeRuntime(AgentRuntime):
    """Returns a fixed JSON restaurant row without touching the filesystem or network."""

    async def run(self, prompt: str, *, system: str | None = None) -> AgentResult:
        rows = [
            {
                "name": "Lhasa Fast Food",
                "score": 9.0,
                "cuisine": "Tibetan",
                "neighborhood": "Jackson Heights",
                "price": "$",
            }
        ]
        return AgentResult(
            text=json.dumps(rows),
            raw={},
            cost_usd=0,
            session_id=None,
        )


def test_ingest_end_to_end_with_fake_runtime(tmp_path):
    # Create a dummy screenshot so _image_paths has something to iterate.
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "a.png").write_bytes(b"")

    profiles_root = str(tmp_path / "profiles")
    snap, profile = ingest(
        "tester",
        shots_dir=str(shots),
        runtime=_FakeRuntime(),
        profiles_root=profiles_root,
        captured_at="2026-06-27",
        list_type="been",
    )

    # Return types
    assert isinstance(snap, BeliSnapshot)
    assert isinstance(profile, TasteProfile)

    # Files written
    snap_path = tmp_path / "profiles" / "tester" / "beli_snapshot.json"
    taste_path = tmp_path / "profiles" / "tester" / "taste.json"
    assert snap_path.exists(), "beli_snapshot.json not written"
    assert taste_path.exists(), "taste.json not written"

    # Snapshot has the expected entry
    assert any(e.name == "Lhasa Fast Food" for e in snap.entries)

    # Taste profile has Tibetan in cuisine_affinity
    assert "Tibetan" in profile.cuisine_affinity, (
        f"Expected Tibetan in cuisine_affinity; got {profile.cuisine_affinity}"
    )
