"""Synthetic Japanese copy-noise cases; no corpus or provider access."""
from copy import deepcopy
import unittest

from tools.story_extraction import draft_quote_resolution_v1 as resolution
from tools.story_extraction import draft_compiler_v1 as compiler
from tests.story_extraction import fixture_builder as fx


class QuoteResolutionTests(unittest.TestCase):
    def resolve(self, text, quote, **extra):
        draft = {"evidence": [{"passage_handle": "P1", "quote": quote, **extra}],
                 "mentions": [], "unrelated": {"quote": "preserve"}}
        prepared = {"passages": [{"handle": "P1", "text": text}]}
        before = deepcopy((draft, prepared))
        result, report = resolution.resolve_quotes(draft, prepared)
        self.assertEqual((draft, prepared), before)
        self.assertEqual(result["unrelated"], draft["unrelated"])
        self.assertIsNot(result["unrelated"], draft["unrelated"])
        return result["evidence"][0], report["evidence"]

    def test_copy_noise_returns_exact_original_substrings(self):
        cases = [("ＡＢＣ１２", "ABC12"), ("ｶﾞｯﾂ", "ガッツ"),
                 ("彼は　静かに\n\t言った", "彼は静かに言った"),
                 ("「本当」", "“本当”"), ("『本当』", "'本当'"),
                 ("待て…", "待て..."), ("待て‥", "待て…"),
                 ("待て...", "待て‥"), ("声―声", "声-声"),
                 ("声—声", "声–声"), ("声‐声", "声—声"),
                 ("空〜海", "空～海"), ("空～海", "空〜海"),
                 ("か\u3099", "が"), ("\u1100\u1161\u11a8", "각"),
                 ("㍍", "メートル"), ("e\u0301", "é")]
        for exact, noisy in cases:
            with self.subTest(exact=exact, noisy=noisy):
                item, report = self.resolve("前。" + exact + "。後", noisy, occurrence=9, role="STATEMENT")
                self.assertEqual(item, {"passage_handle": "P1", "quote": exact, "role": "STATEMENT"})
                self.assertEqual(report["RESOLVED_NORMALIZED"], 1)

    def test_exact_quotes_and_occurrences_are_preserved(self):
        for text, occurrence in [("同じ同じ", None), ("同じ同じ", 2),
                                 ("同じ同じ", 9), ("同じ", 1), ("同じ", None)]:
            with self.subTest(text=text, occurrence=occurrence):
                extra = {} if occurrence is None else {"occurrence": occurrence}
                item, counts = self.resolve(text, "同じ", **extra)
                self.assertEqual(item, {"passage_handle": "P1", "quote": "同じ", **extra})
                self.assertEqual(counts["EXACT"], 1)
        # Ellipsis token boundaries can hide an exact substring in the global
        # normalized index. Retain an authored occurrence only if it selects the
        # one mapped span; never supply a missing occurrence for the new quote.
        for occurrence in (None, 1, 2, 9):
            with self.subTest(normalized_occurrence=occurrence):
                extra = {} if occurrence is None else {"occurrence": occurrence}
                item, counts = self.resolve("....声 と ...声", "‥声", **extra)
                if occurrence == 2:
                    self.assertEqual(item["quote"], "...声")
                    self.assertEqual(item["occurrence"], 2)
                    self.assertEqual(counts["RESOLVED_NORMALIZED"], 1)
                else:
                    self.assertEqual(item, {"passage_handle": "P1", "quote": "‥声", **extra})
                    self.assertEqual(counts["UNRESOLVED_MULTIPLE"], 1)

    def test_ambiguous_absent_partial_expansions_and_invalid_items_stay_unchanged(self):
        for text, quote, expected in [("ＡＢとAB", "ＡB", "UNRESOLVED_MULTIPLE"),
                ("あ ああ", "あ　あ", "UNRESOLVED_MULTIPLE"),
                ("何もない", "消えた", "UNRESOLVED_NO_MATCH"),
                ("㍍", "メート", "UNRESOLVED_NO_MATCH"),
                ("…", "..", "RESOLVED_NORMALIZED"),
                ("文章", " \n", "UNRESOLVED_NO_MATCH"), ("文章", "", "UNRESOLVED_NO_MATCH")]:
            for occurrence in (None, 1, 2):
                with self.subTest(text=text, quote=quote, occurrence=occurrence):
                    extra = {} if occurrence is None else {"occurrence": occurrence}
                    item, counts = self.resolve(text, quote, **extra)
                    self.assertEqual(counts[expected], 1)
                    if expected != "RESOLVED_NORMALIZED":
                        self.assertEqual(item, {"passage_handle": "P1", "quote": quote, **extra})
        for draft in (None, [], {"evidence": None}, {"evidence": [None, {}, {"quote": 4},
                      {"quote": "彼", "passage_handle": []}]},
                      {"mentions": [{"quote": "彼", "passage_handle": "missing"}]}):
            with self.subTest(draft=draft):
                result, _ = resolution.resolve_quotes(draft, {"passages": []})
                self.assertEqual(result, draft)

    def test_reports_are_counts_per_kind_and_repeat_calls_are_deterministic(self):
        items = [{"passage_handle": "P1", "quote": quote} for quote in ("真", "ＡB", "？", "CＤ", "CＤ")]
        draft = {"evidence": items, "mentions": deepcopy(items)}
        prepared = {"passages": [{"handle": "P1", "text": "真。AB。ＡＢ。ＣＤ"}]}
        result, report = resolution.resolve_quotes(draft, prepared)
        self.assertEqual(report, {kind: {"EXACT": 1, "RESOLVED_NORMALIZED": 2,
            "RESOLVED_OTHER_PASSAGE": 0, "RESOLVED_ORDERED": 0,
            "UNRESOLVED_NO_MATCH": 1, "UNRESOLVED_MULTIPLE": 1} for kind in ("evidence", "mentions")})
        self.assertEqual(resolution.resolve_quotes(draft, prepared), (result, report))

    def test_other_passage_requires_one_matching_eligible_target(self):
        # Uniqueness includes normalized and context-only matches, regardless of
        # passage order. Missing/unknown use is never evidence eligibility.
        cases = [
            ([('P2', 'ABC', 'EVIDENCE_ELIGIBLE')], 'ABC', {}, 'ABC'),
            ([('P2', 'ＡＢＣ', 'EVIDENCE_ELIGIBLE')], 'ABC', {'occurrence': 9}, 'ＡＢＣ'),
            ([('P2', 'ABC', 'EVIDENCE_ELIGIBLE')], 'ABC', {'occurrence': 9}, 'ABC'),
            ([('P2', 'ABC ABC', 'EVIDENCE_ELIGIBLE')], 'ABC', {'occurrence': 2}, 'ABC'),
            ([('P2', 'ABC ABC', 'EVIDENCE_ELIGIBLE')], 'ABC', {'occurrence': 9}, None),
            ([('P2', 'ＡＢＣ ＡＢＣ', 'EVIDENCE_ELIGIBLE')], 'ABC', {}, None),
            ([('P2', 'ABC', 'CONTEXT_ONLY')], 'ABC', {}, None),
            ([('P2', 'ABC', None)], 'ABC', {}, None),
            ([('P2', 'ABC', 'OTHER')], 'ABC', {}, None),
            ([('P2', 'ABC', 'EVIDENCE_ELIGIBLE'), ('P3', 'ＡＢＣ', 'EVIDENCE_ELIGIBLE')],
             'ABC', {}, None),
            ([('P2', 'ABC', 'EVIDENCE_ELIGIBLE'), ('P3', 'ABC', 'CONTEXT_ONLY')],
             'ABC', {}, None),
            ([('P2', 'unrelated', 'EVIDENCE_ELIGIBLE')], 'ABC', {}, None),
            ([('P2', 'ABC', 'EVIDENCE_ELIGIBLE')], ' \n', {}, None),
        ]
        for targets, quote, extra, exact in cases:
            for kind in ('evidence', 'mentions'):
                with self.subTest(targets=targets, kind=kind, extra=extra):
                    item = {'handle': 'M9', 'passage_handle': 'P1', 'quote': quote,
                            'role': 'STATEMENT', 'unrelated': {'value': 7}, **extra}
                    draft = {kind: [item], 'other': ['preserve']}
                    prepared = {'passages': [{'handle': 'P1', 'text': 'absent',
                                              'use': 'EVIDENCE_ELIGIBLE'}] + [
                        {'handle': h, 'text': text, 'use': use} for h, text, use in targets]}
                    before = deepcopy((draft, prepared))
                    result, report = resolution.resolve_quotes(draft, prepared)
                    self.assertEqual((draft, prepared), before)
                    expected = deepcopy(draft)
                    if exact is not None:
                        expected[kind][0].update(passage_handle='P2', quote=exact)
                        if targets[0][1].count(exact) == 1:
                            expected[kind][0].pop('occurrence', None)
                        if kind == 'mentions' and targets[0][1].count(exact) == 1:
                            expected[kind][0]['occurrence'] = 1
                    self.assertEqual(result, expected)
                    outcome = ('RESOLVED_ORDERED' if kind == 'mentions' and exact is not None
                               and targets[0][1].count(exact) == 1 else 'RESOLVED_OTHER_PASSAGE')
                    self.assertEqual(report[kind][outcome], int(exact is not None))
                    self.assertEqual(sum(report[kind].values()), 1)
                    self.assertEqual(resolution.resolve_quotes(draft, prepared), (result, report))

    def test_ordered_mentions_require_all_occurrences_and_no_authored_index(self):
        for text, count, existing, eligible in [
                ('Ada Ada Ada', 3, None, True), ('Ada Ada', 1, None, True),
                ('Ada Ada', 3, None, True), ('Ada Ada', 2, 1, True),
                ('Ada Ada', 2, None, False), ('Ada', 1, None, True),
                ('aaa', 2, None, True)]:
            with self.subTest(text=text, count=count, existing=existing, eligible=eligible):
                quote = 'aa' if text == 'aaa' else 'Ada'
                items = [{'handle': f'M{9-i}', 'passage_handle': 'P1', 'quote': quote,
                          'role': 'NAME'} for i in range(count)]
                if existing is not None:
                    items[-1]['occurrence'] = existing
                # A different quote and malformed records never join the group.
                draft = {'mentions': items + [None, {'quote': [], 'passage_handle': 'P1'},
                                              {'quote': 'absent', 'passage_handle': []}],
                         'evidence': deepcopy(items), 'other': {'occurrence': 99}}
                prepared = {'passages': [{'handle': 'P1', 'text': text,
                    'use': 'EVIDENCE_ELIGIBLE' if eligible else 'CONTEXT_ONLY'}]}
                before = deepcopy((draft, prepared))
                result, report = resolution.resolve_quotes(draft, prepared)
                self.assertEqual((draft, prepared), before)
                expected = deepcopy(draft)
                occurrences = 2 if text == 'aaa' else text.count(quote)
                changed = existing is None and eligible and occurrences == count
                if changed:
                    for index, item in enumerate(expected['mentions'][:count], 1):
                        item['occurrence'] = index
                self.assertEqual(result, expected)
                self.assertEqual(report['mentions']['RESOLVED_ORDERED'], count if changed else 0)
                self.assertEqual(report['evidence']['RESOLVED_ORDERED'], 0)

    def test_pass_order_preserves_local_matches_then_orders_moved_mentions(self):
        prepared = {'passages': [
            {'handle': 'P1', 'text': 'ＡＢ ＡＢ', 'use': 'EVIDENCE_ELIGIBLE'},
            {'handle': 'P2', 'text': 'AB', 'use': 'EVIDENCE_ELIGIBLE'},
            {'handle': 'P3', 'text': 'gone', 'use': 'EVIDENCE_ELIGIBLE'}]}
        # Local ambiguous normalization wins over a unique exact match elsewhere.
        for quote in ('ＡＢ', 'AB', 'ＡB'):
            draft = {'evidence': [{'passage_handle': 'P1', 'quote': quote}]}
            result, _ = resolution.resolve_quotes(draft, prepared)
            self.assertEqual(result, draft)
        prepared['passages'][0]['text'] = 'ＡＢ'
        result, report = resolution.resolve_quotes(
            {'evidence': [{'passage_handle': 'P1', 'quote': 'AB'}]}, prepared)
        self.assertEqual(result['evidence'][0], {'passage_handle': 'P1', 'quote': 'ＡＢ'})
        self.assertEqual(report['evidence']['RESOLVED_NORMALIZED'], 1)
        prepared['passages'][0]['text'] = 'ＡＢ ＡＢ'
        prepared['passages'][1]['text'] = 'Ada Ada'
        draft = {'mentions': [{'handle': 'M9', 'passage_handle': 'P3', 'quote': 'Ada'},
                              {'handle': 'M1', 'passage_handle': 'P2', 'quote': 'Ada'}],
                 'evidence': [{'passage_handle': 'P3', 'quote': 'Ada'}]}
        result, report = resolution.resolve_quotes(draft, prepared)
        self.assertEqual([m['passage_handle'] for m in result['mentions']], ['P2', 'P2'])
        self.assertEqual([m['occurrence'] for m in result['mentions']], [1, 2])
        self.assertNotIn('occurrence', result['evidence'][0])
        self.assertEqual(report['mentions']['RESOLVED_ORDERED'], 2)
        self.assertEqual(report['evidence']['RESOLVED_OTHER_PASSAGE'], 1)

    def test_resolved_substring_compiles_to_precise_source_positions(self):
        text = "前。ＡＢ　「ガッツ…」―波〜後。"
        ingestion, base = fx.ingest_text(text)
        segment = base["source_segments"][0]
        passage = ingestion.passage_ref(segment["id"], 1, len(text) - 1)
        context = compiler.DraftCompilerContext(base, [{"use": "EVIDENCE_ELIGIBLE", "passage_ref": passage}],
            passage["position"], "SYNTHETIC", "SYNTHETIC", "v1.1", "SYNTHETIC", ingestion)
        prepared = compiler.prepare_story_extraction_draft_v1(context)
        draft = {"evidence": [], "mentions": [{"passage_handle": "P1", "quote": 'AB"ｶﾞｯﾂ..."-波～'}]}
        resolved, report = resolution.resolve_quotes(draft, prepared)
        record = resolved["mentions"][0]
        self.assertEqual(record["quote"], "ＡＢ　「ガッツ…」―波〜")
        passages, _ = compiler._context_maps(context)
        ref = compiler._quote_ref(record, passages, context)
        self.assertEqual((ref["span"]["char_start"], ref["span"]["char_end_exclusive"]),
                         (text.index("Ａ"), text.index("後")))
        self.assertEqual(ingestion.resolve_passage_text(ref), record["quote"])
        self.assertEqual(report["mentions"]["RESOLVED_ORDERED"], 1)


if __name__ == "__main__":
    unittest.main()
