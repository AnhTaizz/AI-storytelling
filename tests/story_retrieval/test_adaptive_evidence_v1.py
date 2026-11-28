"""Behavioural and adversarial tests for adaptive evidence retrieval and completeness (M6 Sprint 02)."""

from __future__ import annotations

import math
import unittest
import zlib
from typing import Sequence

from tools.story_pipeline.source import Passage
from tools.story_retrieval import adaptive_evidence_v1 as ae
from tools.story_retrieval.retrieval_v0 import StoryCorpus, passage_chapter


class KeywordVectorDense:
    """Deterministic unit-vector dense mock driven by vocabulary dimensions (no ML dependencies)."""

    name = "keyword_dense_mock"
    version = "0"
    VOCAB = (
        "ô", "trả", "mượn", "chìa", "khóa", "sồi", "hộp", "thư", "nặc", "danh", "hà",
        "két", "sắt", "khoa", "trúng", "số", "phẫu", "thuật", "cửa", "sổ", "đóng", "mở",
        "nam", "ga", "tàu", "mùa", "thu", "minh", "cờ", "vua", "bóng", "đá", "phản", "bội", "hải",
        "bánh", "dâu", "tối", "qua", "plum", "梅", "白米", "茶漬け", "mơ", "muối", "cơm",
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
             set(), False, "NO_RELIABLE_EVIDENCE_ABOVE_FLOOR", True),
            ("post_cutoff_spoiler_trap", "Kẻ phản bội trong đội đặc nhiệm chính là ai?", 1,
             set(), False, "DECLARED_UNKNOWN_IN_BRIEF", False),
        ]

        for name, query, cutoff, must_have, exp_suff, exp_flag, exp_empty in scenarios:
            with self.subTest(name):
                res = engine.search(query, cutoff_chapter=cutoff, max_passages=6, token_cap=400, abstain_on_insufficient=True)
                self.assertTrue(all(passage_chapter(p) <= cutoff for p in res.candidate_ids))
                self.assertNotIn("2.5", res.candidate_ids if cutoff == 1 else ())
                self.assertTrue(must_have <= set(res.candidate_ids), f"{name}: {res.candidate_ids}")
                self.assertEqual(res.completeness.sufficient, exp_suff, f"{name}: {res.completeness}")
                if exp_empty:
                    self.assertEqual(res.passage_ids, ())
                if exp_flag is not None:
                    self.assertTrue(
                        any(f.startswith(exp_flag) for f in res.completeness.flags),
                        f"{name}: expected {exp_flag} in {res.completeness.flags}",
                    )

        # Lexical-only mode (dense_retriever=None) and overflow flag coverage
        lex_only = ae.AdaptiveEvidenceEngineV1(corpus, briefs, brief_language="vi", dense_retriever=None)
        res_lex = lex_only.search("Linh giấu chiếc chìa khóa đồng ở đâu?", cutoff_chapter=1, max_passages=2, token_cap=200)
        self.assertIn("1.2", res_lex.passage_ids)
        self.assertEqual(res_lex.query_encodes, 0)
        self.assertEqual(ae.default_token_estimator([], {}), 0)
        rep_ov = ae.assess_evidence_completeness(
            "chìa khóa đồng", ["1.2"], {"1.2": "Linh giấu chiếc chìa khóa đồng"},
            has_content_lexical_hit=True, overflow_count=2,
        )
        self.assertIn("BUDGET_OVERFLOW_DROPPED:2", rep_ov.flags)


if __name__ == "__main__":
    unittest.main()
