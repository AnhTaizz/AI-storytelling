"""Offline K4/K5 measurements for Draft V1.2 on invented Japanese narrative text.

The passages below were written for this measurement. They are not taken from any
corpus, DEV set or holdout. They are short light-novel-style scenes dense in repeated
names, pronouns, honorifics and short dialogue, which is where context anchors are
stressed. Results describe these synthetic passages only.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_builder as fx  # noqa: E402

from tools.story_extraction.contextual_anchor_resolver_v1 import (  # noqa: E402
    candidate_starts,
    minimal_unique_context,
)
from tools.story_extraction.draft_compiler_v1 import DraftCompilerContext  # noqa: E402
from tools.story_extraction.draft_compiler_v1_1 import migrate_draft_v1_to_v1_1  # noqa: E402
from tools.story_extraction.draft_coverage_v1 import canonical_gold_to_draft_v1  # noqa: E402
from tools.story_extraction.draft_v1_2_oracle_projection_v1 import (  # noqa: E402
    project_gold_to_draft_v1_2,
)

PASSAGES = [
    "真白は窓の外を見た。「雨だね」と真白は言った。遥は頷いた。「うん、雨だ」遥は傘を探した。"
    "真白は笑った。「遥、傘ならここにあるよ」",
    "「はい」「はい」と二人は同時に答えた。先生は真白を見て、それから遥を見た。"
    "「真白さん、遥さん、静かに」真白さんは小さく「はい」と言った。",
    "彼は扉を開けた。彼女は振り向かなかった。彼はもう一度呼んだ。「真昼」"
    "真昼は振り向いた。「なに？」「なんでもない」彼は笑った。",
    "真白ちゃんは真白ちゃんだよ、と遥は言った。真白は首を傾げた。「どういう意味？」"
    "「そのままの意味」遥は真白の頭を撫でた。",
    "「行こう」と彼が言った。「行こう」と彼女も言った。二人は駅まで歩いた。"
    "駅で彼は止まった。駅で彼女も止まった。",
    "ああ、と真白は思った。ああ、これは夢だ。夢なら、遥はまだここにいる。"
    "遥は笑っていた。夢の中の遥は、いつも笑っていた。",
]
TARGETS = ["真白", "遥", "真昼", "彼", "彼女", "先生", "真白さん", "遥さん", "真白ちゃん",
           "「はい」", "「行こう」", "はい", "ああ", "夢", "駅", "雨", "傘"]


def k4_resolution_rates() -> dict[str, Any]:
    """Share of repeated-quote occurrences that have a unique context within a limit."""
    totals = {16: [0, 0], 32: [0, 0]}
    unresolvable = []
    for index, text in enumerate(PASSAGES):
        for quote in TARGETS:
            starts = candidate_starts(text, quote)
            if len(starts) < 2:
                continue
            for start in starts:
                for limit in (16, 32):
                    totals[limit][1] += 1
                    if minimal_unique_context(text, start, start + len(quote), limit) is not None:
                        totals[limit][0] += 1
                    elif limit == 32:
                        unresolvable.append({"passage": index + 1, "quote": quote, "start": start})
    return {
        "repeated_occurrences": totals[16][1],
        "unique_within_16": totals[16][0],
        "rate_within_16": totals[16][0] / totals[16][1],
        "unique_within_32": totals[32][0],
        "rate_within_32": totals[32][0] / totals[32][1],
        "no_unique_context_within_32": unresolvable,
    }


def _compact(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


def k5_overhead() -> dict[str, Any]:
    """Draft size (code points of compact JSON) V1.2 vs V1.1 for the same gold content."""
    v11_total = v12_total = 0
    repeated_v11 = repeated_v12 = 0
    unrepresentable = 0
    for name in fx.CASES:
        ingestion, base, gold = fx.build(name)
        scope = gold["scope"]
        context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                       scope["profile_id"], "k5", "v1", name, ingestion)
        v1, _ = canonical_gold_to_draft_v1(gold, context)
        v11_total += _compact(migrate_draft_v1_to_v1_1(v1))
        v12, _, report = project_gold_to_draft_v1_2(gold, context)
        v12_total += _compact(v12)
        unrepresentable += len(report["unrepresentable"])
    for text in PASSAGES:
        ingestion, base = fx.ingest_text(text)
        builder = fx.Builder(ingestion, base)
        for quote in TARGETS:
            if len(candidate_starts(text, quote)) >= 2:
                builder.named(1, quote, kind="OTHER")
        gold = builder.batch()
        scope = gold["scope"]
        context = DraftCompilerContext(base, scope["passage_inputs"], scope["as_of_position"],
                                       scope["profile_id"], "k5", "v1", "ja", ingestion)
        v1, _ = canonical_gold_to_draft_v1(gold, context)
        repeated_v11 += _compact(migrate_draft_v1_to_v1_1(v1))
        v12, _, report = project_gold_to_draft_v1_2(gold, context)
        repeated_v12 += _compact(v12)
        unrepresentable += len(report["unrepresentable"])
    # Builder locates only first occurrences, so measure every repeated occurrence directly:
    # V1.1 locator fields (quote, occurrence, surface_form) vs V1.2 (quote, minimal context).
    v11_locators = v11_bare = v12_locators = locators = 0
    for text in PASSAGES:
        for quote in TARGETS:
            starts = candidate_starts(text, quote)
            if len(starts) < 2:
                continue
            for index, start in enumerate(starts, 1):
                before, after = minimal_unique_context(text, start, start + len(quote))
                v11 = {"passage_handle": "P1", "quote": quote, "occurrence": index,
                       "role": "DEPICTION", "surface_form": quote}
                v12 = {"passage_handle": "P1", "quote": quote, "role": "DEPICTION"}
                if before is not None:
                    v12["context_before"] = before
                if after is not None:
                    v12["context_after"] = after
                v11_locators += _compact(v11)
                v11_bare += _compact({key: value for key, value in v11.items()
                                      if key != "surface_form"})
                v12_locators += _compact(v12)
                locators += 1
    return {
        "every_repeated_occurrence_locator": {
            "locators": locators, "v1_1_code_points": v11_locators,
            "v1_2_code_points": v12_locators,
            "overhead": (v12_locators - v11_locators) / v11_locators,
            "v1_1_without_surface_form_code_points": v11_bare,
            "overhead_vs_v1_1_without_surface_form": (v12_locators - v11_bare) / v11_bare},
        "synthetic_fixture_drafts": {"v1_1_code_points": v11_total, "v1_2_code_points": v12_total,
                                     "overhead": (v12_total - v11_total) / v11_total},
        "repeated_quote_drafts_first_occurrences_only": {"v1_1_code_points": repeated_v11,
                                  "v1_2_code_points": repeated_v12,
                                  "overhead": (repeated_v12 - repeated_v11) / repeated_v11},
        "unrepresentable_locators": unrepresentable,
        "proxy": "compact JSON code points; tokenizer-specific token counts not measured offline",
    }


if __name__ == "__main__":
    print(json.dumps({"k4": k4_resolution_rates(), "k5": k5_overhead()},
                     ensure_ascii=False, indent=2))
