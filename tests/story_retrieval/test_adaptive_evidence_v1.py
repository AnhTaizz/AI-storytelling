"""Behavioural and adversarial tests for adaptive evidence retrieval and completeness (M6 Sprint 02)."""

from __future__ import annotations

import contextlib
import io
import json
import math
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Sequence

import yaml

from tools.story_pipeline.source import Passage
from tools.story_retrieval import adaptive_evidence_v1 as ae
from tools.story_retrieval import evaluate_adaptive_v1
from tools.story_retrieval.retrieval_v0 import StoryCorpus, passage_chapter


class KeywordVectorDense:
    """Deterministic unit-vector dense mock driven by vocabulary dimensions (no ML dependencies)."""

    name = "keyword_dense_mock"
    version = "0"
    VOCAB = (
        "ô", "trả", "mượn", "chìa", "khóa", "sồi", "hộp", "thư", "nặc", "danh", "hà",
        "két", "sắt", "khoa", "trúng", "số", "phẫu", "thuật", "cửa", "sổ", "đóng", "mở",
        "nam", "ga", "tàu", "mùa", "thu", "minh", "cờ", "vua", "bóng", "đá", "phản", "bội", "hải",
        "bánh", "dâu", "tối", "qua", "plum", "白米", "茶漬け",
    )

    def __init__(self):
        self._vectors = {}
        self.encode_calls = 0

    def _vec(self, text: str) -> tuple[float, ...]:
        low = text.casefold()
        # Cross-lingual concept aliases so Vietnamese queries bridge to Japanese passages deterministically
        aliases = {
            "plum": ("mơ", "muối", "梅"),
            "白米": ("cơm", "白米"),
            "茶漬け": ("trà", "茶漬け"),
        }
        raw = []
        for term in self.VOCAB:
            triggers = aliases.get(term, (term,))
            raw.append(1.0 if any(t in low for t in triggers) else 0.0)
        bucket = zlib.crc32(low.encode("utf-8")) % 257
        for i in range(257):
            raw.append(0.15 if i == bucket else 0.0)
        norm = math.sqrt(sum(v * v for v in raw))
        return tuple(v / norm for v in raw)

    def _encode(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        self.encode_calls += len(texts)
        return [self._vec(t) for t in texts]

    def index(self, passages: Sequence[Passage]) -> None:
        self._vectors = {p.passage_id: self._vec(p.text) for p in passages}

    def search(self, query: str, allowed_ids, k: int):
        qv = self._vec(query)
        scored = [(pid, sum(a * b for a, b in zip(qv, vec)))
                  for pid, vec in self._vectors.items() if pid in allowed_ids]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]


def build_adversarial_fixture():
    passages = [
        Passage("1.1", "Mùa đông tại ga tàu trung tâm, Nam đứng nhìn đoàn tàu rời bến trong tuyết trắng."),
        Passage("1.2", "Linh lặng lẽ giấu chiếc chìa khóa đồng vào hốc rễ dưới gốc cây sồi cổ thụ sau vườn."),
        Passage("1.3", "Học sinh quanh trường xôn xao đồn rằng thầy Khoa nghỉ dạy đột xuất vì trúng số độc đắc."),
        Passage("1.4", "Lan nhẹ nhàng đặt hộp bánh dâu lên mặt bàn gỗ trước mặt Hùng."),
        Passage("1.5", "\"Làm từ tối qua đấy, ăn thử đi cho nóng.\""),
        Passage("1.6", "Bảo vệ Tùng khẳng định cửa sổ phòng đọc sách đã khóa chặt từ lúc 9 giờ tối."),
        Passage("1.7", "Trần Minh lớp 10A giành huy chương vàng giải cờ vua toàn thành phố."),
        Passage("1.8", "Lê Minh lớp 10B bị bong gân cổ chân khi bắt bóng ở trận chung kết bóng đá."),
        Passage("1.9", "Cuộc điều tra nội bộ bắt đầu nhưng kẻ phản bội trong đội đặc nhiệm vẫn chưa lộ diện."),
        Passage("1.10", "Tuấn trao phong bì niêm phong cho Quỳnh ở hành lang tầng ba."),
        Passage("1.11", "\"Đọc kỹ trang cuối trước buổi họp sáng mai nhé.\""),
        Passage("2.1", "Hồ sơ bưu điện xác nhận người gửi bức thư nặc danh màu xám chính là thư ký Hà."),
        Passage("2.2", "Bệnh viện thành phố xác nhận thầy Khoa nhập viện để phẫu thuật dây thanh quản chứ không hề mua vé số."),
        Passage("2.3", "Thủ thư Mai làm chứng rằng cửa sổ phòng đọc sách mở toang lúc 9 giờ tối khi cô đi kiểm tra."),
        Passage("2.4", "Ba tháng trước vào hồi mùa thu, cuộc cãi vã dữ dội với gia đình đã khiến Nam quyết định rời quê lên tàu."),
        Passage("2.5", "Kẻ phản bội trong đội đặc nhiệm chính là Đội phó Hải, người đã sao chép mật lệnh."),
        Passage("3.1", "Đêm mưa tạnh, Linh quay lại đào chiếc chìa khóa đồng dưới gốc cây sồi lên nhưng chiếc hộp gỗ bên dưới đã biến mất."),
    ]
    briefs = [
        {
            "chapter_order": 1,
            "characters": [
                {"id": "CH1", "name": "Trần Minh", "romanized_name": "Trần Minh", "aliases": ["Minh"],
                 "facts": [{"text": "Đội trưởng cờ vua lớp 10A, giành huy chương vàng cờ vua.", "evidence": ["1.7"], "quote": "huy chương vàng", "epistemic": "EXPLICIT"}]},
                {"id": "CH2", "name": "Lê Minh", "romanized_name": "Lê Minh", "aliases": ["Minh"],
                 "facts": [{"text": "Thủ môn lớp 10B, bị bong gân cổ chân khi bắt bóng.", "evidence": ["1.8"], "quote": "bong gân cổ chân", "epistemic": "EXPLICIT"}]},
                {"id": "CH3", "name": "Thầy Khoa", "romanized_name": "Thầy Khoa", "aliases": [],
                 "facts": [{"text": "Nghe đồn nghỉ dạy đột xuất vì trúng số độc đắc.", "evidence": ["1.3"], "quote": "đồn rằng", "epistemic": "REPORTED"}]},
                {"id": "CH4", "name": "Linh", "romanized_name": "Linh", "aliases": [], "facts": []},
                {"id": "CH5", "name": "Lan", "romanized_name": "Lan", "aliases": [], "facts": []},
                {"id": "CH6", "name": "Hùng", "romanized_name": "Hùng", "aliases": [], "facts": []},
                {"id": "CH7", "name": "Nam", "romanized_name": "Nam", "aliases": [], "facts": []},
            ],
            "relationships": [],
            "events": [
                {"id": "E1", "summary": "Nam đứng ở ga tàu mùa đông nhìn tàu rời bến.", "participants": ["CH7"], "location": "Ga tàu", "importance": "CORE",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["1.1"], "quote": "ga tàu", "epistemic": "EXPLICIT"},
                {"id": "E2", "summary": "Linh giấu chiếc chìa khóa đồng dưới gốc cây sồi sau vườn.", "participants": ["CH4"], "location": "Sau vườn", "importance": "CORE",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["1.2"], "quote": "chìa khóa đồng", "epistemic": "EXPLICIT"},
                {"id": "E3", "summary": "Lan đặt hộp bánh dâu lên bàn trước mặt Hùng.", "participants": ["CH5", "CH6"], "location": "Phòng ăn", "importance": "MINOR",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["1.4"], "quote": "hộp bánh dâu", "epistemic": "EXPLICIT"},
            ],
            "unknowns": ["Danh tính kẻ phản bội trong đội đặc nhiệm vẫn chưa lộ diện ở chương 1."],
        },
        {
            "chapter_order": 2,
            "characters": [
                {"id": "CH3", "name": "Thầy Khoa", "romanized_name": "Thầy Khoa", "aliases": [],
                 "facts": [{"text": "Thực tế nhập viện phẫu thuật dây thanh quản.", "evidence": ["2.2"], "quote": "phẫu thuật", "epistemic": "EXPLICIT"}]},
                {"id": "CH7", "name": "Nam", "romanized_name": "Nam", "aliases": [], "facts": []},
            ],
            "relationships": [],
            "events": [
                {"id": "E1", "summary": "Xác nhận thư ký Hà là người gửi bức thư nặc danh màu xám.", "participants": [], "location": "Bưu điện", "importance": "CORE",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["2.1"], "quote": "thư nặc danh", "epistemic": "EXPLICIT"},
                {"id": "E2", "summary": "Hồi tưởng mùa thu ba tháng trước: Nam cãi vã với gia đình trước khi rời quê.", "participants": ["CH7"], "location": "Quê nhà", "importance": "CORE",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["2.4"], "quote": "hồi mùa thu", "epistemic": "EXPLICIT"},
                {"id": "E3", "summary": "Lộ diện Đội phó Hải là kẻ phản bội sao chép mật lệnh.", "participants": [], "location": "Căn cứ", "importance": "CORE",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["2.5"], "quote": "Đội phó Hải", "epistemic": "EXPLICIT"},
            ],
            "unknowns": ["Mật mã mở chiếc két sắt tầng hầm chưa được tiết lộ."],
        },
        {
            "chapter_order": 3,
            "characters": [{"id": "CH4", "name": "Linh", "romanized_name": "Linh", "aliases": [], "facts": []}],
            "relationships": [],
            "events": [
                {"id": "E1", "summary": "Linh đào chìa khóa đồng dưới gốc cây sồi nhưng hộp gỗ đã biến mất.", "participants": ["CH4"], "location": "Sau vườn", "importance": "CORE",
                 "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None, "evidence": ["3.1"], "quote": "biến mất", "epistemic": "EXPLICIT"},
            ],
            "unknowns": [],
        },
    ]
    return StoryCorpus(passages, story_id="adv-fixture-v1", source_language="vi"), briefs


class AdaptiveSelectionTests(unittest.TestCase):
    def test_complementary_selection_recovers_non_brief_source_and_packs_knapsack_budget(self):
        passages = {
            "1.1": "Amane gặp Mahiru dưới mưa ở công viên.",
            "1.2": "Một đoạn mô tả rất dài chiếm nhiều ngân sách token " * 8,
            "1.3": "Gương mặt nhợt nhạt xanh xao của cô dưới mưa.",
            "2.1": "Đoạn chương sau không được phép lọt qua cutoff.",
        }
        # Concave utility keeps rank-1 source-only '1.3' alongside brief '1.1', skipping oversized '1.2' under tight cap
        ids, used = ae.select_complementary_evidence(
            "công viên dưới mưa và gương mặt xanh xao",
            [["1.1", "1.2"], ["1.1", "1.3"]],
            passages,
            cutoff_chapter=1,
            max_passages=3,
            token_cap=60,
            co_cited_groups=[("1.1", "1.2")],
        )
        self.assertEqual(ids, ["1.1", "1.3"])
        self.assertLessEqual(used, 60)

        # Validation & cutoff rejection cases
        bad_cases = {
            "post-cutoff candidate": ({"channels": [["2.1"]], "cutoff_chapter": 1}, ValueError),
            "bad cutoff": ({"channels": [["1.1"]], "cutoff_chapter": 0}, ValueError),
            "bad cap": ({"channels": [["1.1"]], "cutoff_chapter": 1, "token_cap": 0}, ValueError),
        }
        for label, (kwargs, err) in bad_cases.items():
            with self.subTest(label), self.assertRaises(err):
                ae.select_complementary_evidence("mưa", passages_by_id=passages, **kwargs)
        self.assertEqual(ae.select_complementary_evidence("mưa", [[]], passages, cutoff_chapter=1), ([], 0))

    def test_cross_lingual_japanese_source_uses_single_shared_query_encode(self):
        ja_passages = StoryCorpus(
            [Passage("1.1", "公園で傘を差し出した。"), Passage("1.2", "梅干しを白米と茶漬けで食べたい。")],
            story_id="ja-story",
            source_language="ja",
        )
        briefs = [{
            "chapter_order": 1,
            "characters": [{"id": "CH1", "name": "周", "romanized_name": "Amane", "aliases": [], "facts": []}],
            "relationships": [],
            "events": [{"id": "E1", "summary": "Amane đưa ô ở công viên.", "participants": ["CH1"], "location": "Công viên",
                        "importance": "CORE", "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
                        "evidence": ["1.1"], "quote": "傘", "epistemic": "EXPLICIT"}],
        }]
        dense = KeywordVectorDense()
        engine = ae.AdaptiveEvidenceEngineV1(ja_passages, briefs, brief_language="vi", dense_retriever=dense, dense_floor=0.5)
        dense.encode_calls = 0
        # Passage 1.2 is omitted from the brief, yet shared-query dense passage search recovers it with 1 query encode!
        res = engine.search("Amane muốn ăn mơ muối với cơm và trà", cutoff_chapter=1, max_passages=4, token_cap=200)
        self.assertIn("1.2", res.passage_ids)
        self.assertEqual(res.query_encodes, 1)
        self.assertEqual(dense.encode_calls, 1)

        for bad_q, bad_cut in [("", 1), ("   ", 1), ("mơ muối", 0)]:
            with self.subTest(q=bad_q, c=bad_cut), self.assertRaises(ValueError):
                engine.search(bad_q, cutoff_chapter=bad_cut)

    def test_adversarial_narrative_scenarios_and_abstention(self):
        corpus, briefs = build_adversarial_fixture()
        dense = KeywordVectorDense()
        engine = ae.AdaptiveEvidenceEngineV1(corpus, briefs, brief_language="vi", dense_retriever=dense, dense_floor=0.80)

        scenarios = [
            ("homonym_characters", "Minh giành huy chương cờ vua hay bị bong gân bóng đá?", 1,
             {"1.7", "1.8"}, False, "AMBIGUOUS_HOMONYM_ENTITY", False),
            ("subject_dropped_anchored_by_brief", "Ai là người nói câu làm từ tối qua đấy ăn thử đi?", 1,
             {"1.4", "1.5"}, True, None, False),
            ("subject_dropped_unanchored", "Ai là người nói câu đọc kỹ trang cuối trước buổi họp sáng mai nhé?", 1,
             {"1.11"}, False, "UNANCHORED_DIALOGUE_PASSAGE", False),
            ("multi_chapter_event", "Linh giấu chiếc chìa khóa đồng ở đâu, và chuyện gì xảy ra khi đào chiếc chìa khóa đồng lên?", 3,
             {"1.2", "3.1"}, True, None, False),
            ("relevant_but_insufficient", "Ai gửi bức thư nặc danh màu xám, và mật mã mở chiếc két sắt tầng hầm là số mấy?", 2,
             {"2.1"}, False, "UNCOVERED_QUERY_FACETS", False),
            ("rumor_only_at_cutoff_1", "Vì sao thầy Khoa nghỉ dạy đột xuất?", 1,
             {"1.3"}, False, "NON_FACTUAL_EPISTEMIC_ONLY", False),
            ("rumor_vs_explicit_fact", "Lời đồn trúng số và sự thật thầy Khoa phẫu thuật dây thanh quản thế nào?", 2,
             {"1.3", "2.2"}, False, "MIXED_RUMOR_AND_EXPLICIT_EVIDENCE", False),
            ("inverted_chronology_flashback", "Cảnh Nam ở ga tàu mùa đông, và cuộc cãi vã hồi mùa thu ba tháng trước ra sao?", 2,
             {"1.1", "2.4"}, True, "NON_MONOTONIC_FLASHBACK_CHRONOLOGY", False),
            ("contradictory_witnesses", "Cửa sổ phòng đọc sách lúc 9 giờ tối khóa chặt hay mở toang?", 2,
             {"1.6", "2.3"}, False, "POTENTIAL_CONTRADICTORY_CLAIMS", False),
            ("unanswerable_abstention", "Biển kiểm soát tàu vũ trụ ở thiên hà Andromeda là gì?", 3,
             set(), False, "NO_RELIABLE_EVIDENCE_ABOVE_FLOOR", "ABSTAIN"),
            ("post_cutoff_spoiler_trap", "Kẻ phản bội trong đội đặc nhiệm chính là ai?", 1,
             set(), False, "DECLARED_UNKNOWN_IN_BRIEF", "PARTIAL"),
        ]

        for row in scenarios:
            name, query, cutoff, must_have, exp_suff, exp_flag = row[:6]
            exp_status = row[6] if isinstance(row[6], str) else None
            with self.subTest(name):
                res = engine.search(query, cutoff_chapter=cutoff, max_passages=6, token_cap=400)
                self.assertTrue(res.completeness.advisory_only)
                # Advisory-only policy: completeness flags never drop retrieved candidate passages
                self.assertEqual(res.passage_ids, res.candidate_ids)
                self.assertTrue(all(passage_chapter(p) <= cutoff for p in res.passage_ids))
                self.assertNotIn("2.5", res.passage_ids if cutoff == 1 else ())
                self.assertTrue(must_have <= set(res.passage_ids), f"{name}: {res.passage_ids}")
                self.assertEqual(res.completeness.sufficient, exp_suff, f"{name}: {res.completeness}")
                if exp_status is not None:
                    self.assertEqual(res.completeness.status, exp_status)
                if exp_flag is not None:
                    self.assertTrue(
                        any(f.startswith(exp_flag) for f in res.completeness.flags),
                        f"{name}: expected {exp_flag} in {res.completeness.flags}",
                    )

        # Lexical-only mode (dense_retriever=None), exact vs estimated token modes, and overflow flag
        lex_only = ae.AdaptiveEvidenceEngineV1(corpus, briefs, brief_language="vi", dense_retriever=None)
        res_lex = lex_only.search("Linh giấu chiếc chìa khóa đồng ở đâu?", cutoff_chapter=1, max_passages=2, token_cap=200)
        self.assertIn("1.2", res_lex.passage_ids)
        self.assertEqual(res_lex.query_encodes, 0)
        self.assertEqual(res_lex.token_budget_mode, ae.TOKEN_BUDGET_ESTIMATED)

        corpus_map = {p.passage_id: p.text for p in corpus}
        exact_engine = ae.AdaptiveEvidenceEngineV1(
            corpus, briefs, brief_language="vi", dense_retriever=dense,
            token_counter=lambda rows: sum(len(corpus_map[p].split()) + 3 for p, _, _ in rows),
        )
        res_exact = exact_engine.search("Linh giấu chiếc chìa khóa đồng ở đâu?", cutoff_chapter=1, max_passages=2, token_cap=200)
        self.assertEqual(res_exact.token_budget_mode, ae.TOKEN_BUDGET_EXACT)
        self.assertEqual(ae.render_delivery_context([], {}), "")
        self.assertEqual(ae.default_token_estimator([], {}), 0)
        rep_ov = ae.assess_evidence_completeness(
            "chìa khóa đồng", ["1.2"], {"1.2": "Linh giấu chiếc chìa khóa đồng"},
            has_content_lexical_hit=True, overflow_count=2,
        )
        self.assertIn("BUDGET_OVERFLOW_DROPPED:2", rep_ov.flags)

    def test_high_dense_facet_never_masks_ungrounded_second_facet(self):
        ja_passages = StoryCorpus(
            [
                Passage("1.1", "公園のベンチで傘を差し出した。"),
                Passage("1.2", "梅干しを白米と茶漬けで食べたいと周は言った。"),
                Passage("1.3", "放課後の教室は静かだった。"),
            ],
            story_id="ja-facet-test",
            source_language="ja",
        )
        briefs = [{
            "chapter_order": 1,
            "characters": [{"id": "CH1", "name": "周", "romanized_name": "Amane", "aliases": [], "facts": []}],
            "relationships": [],
            "events": [{"id": "E1", "summary": "Amane đưa chiếc ô ở công viên.", "participants": ["CH1"],
                        "location": "Công viên", "importance": "CORE",
                        "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
                        "evidence": ["1.1"], "quote": "傘", "epistemic": "EXPLICIT"}],
        }]
        dense = KeywordVectorDense()
        engine = ae.AdaptiveEvidenceEngineV1(ja_passages, briefs, brief_language="vi", dense_retriever=dense, dense_floor=0.45)

        # Facet 1 ("Amane muốn ăn mơ muối với cơm và trà") has high dense score on 1.2 (>0.70 > dense_floor),
        # while Facet 2 ("mật mã két sắt Thụy Sĩ là gì") has zero evidence anywhere.
        q = "Amane muốn ăn mơ muối với cơm và trà, và mật mã két sắt Thụy Sĩ là gì?"
        res_default = engine.search(q, cutoff_chapter=1, max_passages=3, token_cap=200)
        self.assertIn("1.2", res_default.passage_ids)
        self.assertFalse(res_default.completeness.sufficient)
        self.assertEqual(res_default.completeness.status, "PARTIAL")
        self.assertTrue(any(f.startswith("UNCOVERED_QUERY_FACETS:") for f in res_default.completeness.flags))

        res_verified = engine.search(q, cutoff_chapter=1, max_passages=3, token_cap=200, verify_uncovered_facets_dense=True)
        self.assertIn("1.2", res_verified.passage_ids)
        self.assertEqual(res_verified.completeness.facet_coverage, 0.5)
        self.assertIn("UNCOVERED_QUERY_FACETS:1/2", res_verified.completeness.flags)
        self.assertFalse(res_verified.completeness.sufficient)
        self.assertTrue(res_verified.completeness.advisory_only)

    def test_future_chapters_never_alter_pre_cutoff_retrieval(self):
        corpus_full, briefs_full = build_adversarial_fixture()
        passages_ch1_2 = [p for p in corpus_full if passage_chapter(p.passage_id) <= 2]
        briefs_ch1_2 = [b for b in briefs_full if b["chapter_order"] <= 2]
        corpus_early = StoryCorpus(passages_ch1_2, story_id="adv-fixture-v1", source_language="vi")

        # Append heavy future chapters 3-4 with repeated keywords ("chìa khóa đồng", "kẻ phản bội", "cửa sổ")
        # that would shift un-scoped BM25 IDF/avgdl and tempt un-scoped dense retrieval.
        future_extra = [
            *list(corpus_full),
            Passage("4.1", "Chiếc chìa khóa đồng dưới gốc cây sồi mở chiếc hộp chứa mật mã két sắt tầng hầm 9876."),
            Passage("4.2", "Kẻ phản bội trong đội đặc nhiệm bị bắt cùng chiếc chìa khóa đồng và bức thư nặc danh."),
        ]
        briefs_extra = [
            *briefs_full,
            {
                "chapter_order": 4,
                "characters": [{"id": "CH4", "name": "Linh", "romanized_name": "Linh", "aliases": ["Người giữ khóa"], "facts": []}],
                "relationships": [],
                "events": [{"id": "E1", "summary": "Mật mã két sắt tầng hầm 9876 được tìm thấy nhờ chìa khóa đồng.",
                            "participants": ["CH4"], "location": "Tầng hầm", "importance": "CORE",
                            "motivation": {"text": None, "status": "UNKNOWN"}, "consequence": None,
                            "evidence": ["4.1", "4.2"], "quote": "9876", "epistemic": "EXPLICIT"}],
                "unknowns": [],
            },
        ]
        corpus_future = StoryCorpus(future_extra, story_id="adv-fixture-v1", source_language="vi")

        eng_early = ae.AdaptiveEvidenceEngineV1(corpus_early, briefs_ch1_2, brief_language="vi", dense_retriever=KeywordVectorDense())
        eng_future = ae.AdaptiveEvidenceEngineV1(corpus_future, briefs_extra, brief_language="vi", dense_retriever=KeywordVectorDense())

        for cutoff, q in [
            (1, "Linh giấu chiếc chìa khóa đồng ở đâu?"),
            (1, "Kẻ phản bội trong đội đặc nhiệm chính là ai?"),
            (2, "Ai gửi bức thư nặc danh màu xám, và mật mã mở chiếc két sắt tầng hầm là số mấy?"),
            (2, "Cửa sổ phòng đọc sách lúc 9 giờ tối khóa chặt hay mở toang?"),
        ]:
            with self.subTest(cutoff=cutoff, q=q):
                r_early = eng_early.search(q, cutoff_chapter=cutoff, max_passages=5, token_cap=300)
                r_future = eng_future.search(q, cutoff_chapter=cutoff, max_passages=5, token_cap=300)
                self.assertEqual(r_early.passage_ids, r_future.passage_ids)
                self.assertEqual(r_early.brief_item_refs, r_future.brief_item_refs)
                self.assertEqual(r_early.tokens_used, r_future.tokens_used)
                self.assertEqual(r_early.completeness, r_future.completeness)

    def test_committed_benchmark_runner_and_pareto_frontiers(self):
        # 1. Verify Pareto logic properly distinguishes minimizing mean_tokens vs hard-cap-only
        sprint02_summary = {
            "A0": {"all_success": 23, "all_recall": 0.7833, "all_hit": 24, "query_encodes_per_probe": 0, "warm_latency_p50_ms": 71.9, "mean_tokens": 342.83},
            "H1": {"all_success": 23, "all_recall": 0.8333, "all_hit": 27, "query_encodes_per_probe": 1, "warm_latency_p50_ms": 813.0, "mean_tokens": 316.57},
            "H2_s01_bm25": {"all_success": 26, "all_recall": 0.9167, "all_hit": 29, "query_encodes_per_probe": 1, "warm_latency_p50_ms": 818.7, "mean_tokens": 327.87},
            "H2_causal_bm25": {"all_success": 25, "all_recall": 0.8833, "all_hit": 28, "query_encodes_per_probe": 1, "warm_latency_p50_ms": 820.3, "mean_tokens": 327.83},
            "C1_symmetric_rrf": {"all_success": 25, "all_recall": 0.8833, "all_hit": 28, "query_encodes_per_probe": 1, "warm_latency_p50_ms": 858.7, "mean_tokens": 339.80},
            "C2_complementary_quota": {"all_success": 26, "all_recall": 0.9167, "all_hit": 29, "query_encodes_per_probe": 1, "warm_latency_p50_ms": 864.1, "mean_tokens": 332.20},
            "C3_adaptive_submodular": {"all_success": 28, "all_recall": 0.9667, "all_hit": 30, "query_encodes_per_probe": 1, "warm_latency_p50_ms": 757.3, "mean_tokens": 334.30},
        }
        pareto = evaluate_adaptive_v1.compute_pareto_frontier(sprint02_summary)
        # Under hard token cap only, only A0 (0 encodes) and C3 remain non-dominated.
        self.assertEqual(pareto["pareto_under_hard_token_cap_only"], ["A0", "C3_adaptive_submodular"])
        # When mean_tokens is also minimized, H1 (316.6 tok) and H2 (327.9 tok) are NOT dominated by C3 (334.3 tok)!
        self.assertIn("H2_s01_bm25", pareto["pareto_with_mean_tokens_minimized"])
        self.assertIn("H1", pareto["pareto_with_mean_tokens_minimized"])
        self.assertNotIn("C1_symmetric_rrf", pareto["pareto_with_mean_tokens_minimized"])

        # 2. Run evaluate_adaptive_v1 on a compact 2-probe (cutoff 1 & 2) slice of the committed DEV v1 fixture
        full_probes = yaml.safe_load(evaluate_adaptive_v1.DEFAULT_PROBES.read_text(encoding="utf-8"))["probes"]
        sample_probes = [
            next(p for p in full_probes if p["language"] == "ja" and p["cutoff_chapter"] == 1),
            next(p for p in full_probes if p["language"] == "vi" and p["cutoff_chapter"] == 2),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            p_file = Path(tmp) / "probes_sub.yaml"
            out_file = Path(tmp) / "out.json"
            p_file.write_text(yaml.safe_dump({"probes": sample_probes}, allow_unicode=True), encoding="utf-8")

            # Dense-injected evaluation exercises all 8 arms + future-chapter invariance check
            res_dense = evaluate_adaptive_v1.evaluate(
                probes_path=p_file, dense_retriever=KeywordVectorDense(), budget_caps=(200, 400), check_invariance=True
            )
            self.assertEqual(res_dense["probe_count"], 2)
            self.assertTrue(res_dense["future_chapter_invariance"]["invariant"])
            self.assertIn("C3_adaptive_submodular", res_dense["primary_summary"])
            self.assertIn("H2_causal_bm25", res_dense["primary_summary"])

            # CLI lexical mode (table & JSON output)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = evaluate_adaptive_v1.main(["--probes", str(p_file), "--out", str(out_file)])
            self.assertEqual(rc, 0)
            self.assertIn("C3_adaptive_submodular", buf.getvalue())
            self.assertTrue(out_file.exists())
            saved = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(saved["token_budget_mode"], ae.TOKEN_BUDGET_ESTIMATED)

            with self.assertRaises(ValueError):
                evaluate_adaptive_v1.evaluate(probes_path=p_file, max_passages=0)


if __name__ == "__main__":
    unittest.main()
