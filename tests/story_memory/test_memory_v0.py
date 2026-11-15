"""Tests for the story memory prototype v0 (tools/story_memory/memory_v0.py).

Synthetic briefs only; no model, API or network.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.story_memory import memory_v0 as mem  # noqa: E402


def character(cid, name, romanized, aliases=(), facts=()):
    return {"id": cid, "name": name, "romanized_name": romanized, "aliases": list(aliases),
            "facts": [{"text": t, "evidence": ["1.1"], "quote": "q"} for t in facts]}


def event(eid, summary, importance="CORE"):
    return {"id": eid, "summary": summary, "participants": [], "location": None, "importance": importance,
            "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
            "evidence": ["1.1"], "quote": "q"}


def brief(order, characters, relationships=(), events=None):
    return {"chapter_order": order, "chapter_summary": f"summary {order}", "characters": characters,
            "relationships": [{"between": list(pair), "state": state, "evidence": [f"{order}.1"], "quote": "q"}
                              for pair, state in relationships],
            "events": events or [event("E1", f"core event of {order}"), event("E2", f"minor {order}", "MINOR")],
            "unknowns": [f"unknown {order}"], "forbidden_inferences": [], "ending_state": f"end {order}"}


BRIEFS = [
    brief(1, [character("CH1", "藤宮周", "Amane", facts=["first-year student"]),
              character("CH2", "椎名真昼", "Mahiru", ["Angel"])],
          [(("CH1", "CH2"), "neighbours who have not spoken")]),
    brief(2, [character("CH1", "真昼", "Shiina Mahiru", ["angel", "Mahiru"]),
              character("CH2", "周", "Fujimiya Amane", ["Amane"]),
              character("CH3", "樹", "Itsuki")],
          [(("CH2", "CH1"), "she returns his umbrella"), (("CH2", "CH3"), "close friends")]),
    brief(3, [character("CH1", "周", "Amane")], [], [event("E1", "a later reveal")]),
]


class StoreTests(unittest.TestCase):
    def test_put_get_and_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = mem.StoryMemory(tmp, "story-1")
            self.assertEqual(store.stored_chapters(), [])
            store.put_brief(2, "src-v1", "fp-1", BRIEFS[1], "fake-model")
            self.assertEqual(store.get_brief(2, "src-v1", "fp-1"), BRIEFS[1])
            self.assertEqual(store.stored_chapters(), [2])
            cases = {"source changed": (2, "src-v2", "fp-1"), "brief setup changed": (2, "src-v1", "fp-2"),
                     "other chapter": (3, "src-v1", "fp-1")}
            for label, args in cases.items():
                with self.subTest(label):
                    self.assertIsNone(store.get_brief(*args))
            record = json.loads((store.directory / "chapter_002.json").read_text(encoding="utf-8"))
            self.assertEqual((record["format"], record["producer"]), (mem.MEMORY_FORMAT, "fake-model"))
            (store.directory / "chapter_002.json").write_text("{broken", encoding="utf-8")
            self.assertIsNone(store.get_brief(2, "src-v1", "fp-1"))
            self.assertEqual(list(store.directory.glob("*.tmp")), [])

    def test_rejects_bad_ids_and_mismatched_brief(self):
        for bad in ("", "a/b", ".hidden"):
            with self.subTest(story_id=bad), self.assertRaises(ValueError):
                mem.StoryMemory("/tmp", bad)
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            mem.StoryMemory(tmp, "s").put_brief(1, "v", "f", BRIEFS[1], "m")


class ViewTests(unittest.TestCase):
    def test_roster_merges_names_and_aliases_across_chapters(self):
        roster = mem.build_roster(BRIEFS)
        names = [(e["romanized_name"], e["chapters"], e["first_chapter"]) for e in roster["characters"]]
        self.assertEqual(names, [("Amane", [1, 2, 3], 1), ("Mahiru", [1, 2], 1), ("Itsuki", [2], 2)])
        mahiru = roster["characters"][1]
        self.assertIn("Shiina Mahiru", mahiru["aliases"])
        self.assertEqual(mahiru["refs"], ["c1.CH2", "c2.CH1"])
        self.assertEqual(roster["characters"][0]["facts"][0]["chapter"], 1)
        self.assertEqual(roster["warnings"], [])
        self.assertEqual(mem.ref_index(roster)["c2.CH2"], "P1")

    def test_shared_alias_is_reported(self):
        briefs = [brief(1, [character("CH1", "A", "Aoi", ["the senpai"]), character("CH2", "B", "Ren", ["Ren-kun"])]),
                  brief(2, [character("CH1", "C", "Ren", ["the senpai"])])]
        roster = mem.build_roster(briefs)
        self.assertEqual(len(roster["characters"]), 2)
        self.assertEqual(len(roster["warnings"]), 1)
        self.assertIn("matches several characters", roster["warnings"][0])

    def test_relationship_timeline_follows_chapters(self):
        roster = mem.build_roster(BRIEFS)
        timeline = mem.relationship_timeline(BRIEFS, roster)
        amane_mahiru = next(t for t in timeline if sorted(t["names"]) == ["Amane", "Mahiru"])
        self.assertEqual([s["chapter"] for s in amane_mahiru["states"]], [1, 2])
        self.assertEqual(amane_mahiru["states"][-1]["state"], "she returns his umbrella")
        self.assertEqual(len(timeline), 2)

    def test_recap_never_contains_the_episode_or_later_chapters(self):
        self.assertIsNone(mem.recap_context(BRIEFS, 1))
        recap = mem.recap_context(BRIEFS, 3)
        self.assertEqual(recap["covers_chapters"], [1, 2])
        text = json.dumps(recap, ensure_ascii=False)
        self.assertNotIn("a later reveal", text)
        self.assertNotIn("summary 3", text)
        self.assertEqual(mem.recap_event_refs(recap), {"c1.E1", "c2.E1"})  # CORE only, MINOR left out
        latest = {tuple(sorted(r["between"])): r for r in recap["relationships_latest"]}
        self.assertEqual(latest[("Amane", "Mahiru")]["as_of_chapter"], 2)
        self.assertEqual(mem.recap_event_refs(None), set())

    def test_as_of_orders_and_cuts(self):
        self.assertEqual([b["chapter_order"] for b in mem.as_of(list(reversed(BRIEFS)), 2)], [1, 2])


if __name__ == "__main__":
    unittest.main()
