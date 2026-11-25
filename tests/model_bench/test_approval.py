from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.model_bench.approval import LiveRefusal, approval_budget, content_sha256, load_approval
from tools.model_bench.planning import MAX_TRANSPORT_CALLS


class ApprovalTests(unittest.TestCase):
    META = {"dataset_sha256": "d" * 64, "case_ids": ["case-1"], "provider": "groq",
            "model": "openai/gpt-oss-20b", "plan_sha256": "a" * 64}
    DOC = {"plan_id": "screening", "dataset_sha256": META["dataset_sha256"], "case_ids": META["case_ids"],
           "approved_by": "Owner", "expires_on": date.max.isoformat(),
           "models": [{"provider": META["provider"], "model": META["model"],
                       "plan_sha256": META["plan_sha256"], "request_cap": MAX_TRANSPORT_CALLS}]}

    def test_content_binding_expiry_and_selection(self):
        signed = self.DOC | {"content_sha256": content_sha256(self.DOC)}
        with TemporaryDirectory() as temp:
            path = Path(temp) / "plan.json"
            path.write_text(json.dumps(signed, indent=2), encoding="utf-8")
            self.assertEqual(load_approval(path, self.META)[2], MAX_TRANSPORT_CALLS)
            for update, metadata, rehash, message in (
                ({"approved_by": "Edited"}, self.META, False, "không khớp"),
                ({"expires_on": "2000-01-01"}, self.META, True, "hết hạn"),
                ({"dataset_sha256": "old"}, self.META, True, "không khớp"),
                ({"case_ids": ["other"]}, self.META, True, "không khớp"),
                ({"models": self.DOC["models"] + [
                    self.DOC["models"][0] | {"provider": "openrouter", "model": "openrouter/free"},
                ]}, self.META, True, "không khớp"),
                ({}, self.META | {"plan_sha256": "b" * 64}, False, "không khớp"),
            ):
                with self.subTest(update=update, metadata=metadata):
                    candidate = signed | update
                    if rehash:
                        candidate["content_sha256"] = content_sha256(candidate)
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    with self.assertRaisesRegex(LiveRefusal, message):
                        load_approval(path, metadata)

    def test_ledger_binds_rehashed_plan_and_keeps_unsettled_reservation(self):
        doc = self.DOC | {"content_sha256": content_sha256(self.DOC)}
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            approval = doc, date.max, MAX_TRANSPORT_CALLS
            with approval_budget(directory, approval, self.META, resume=False) as budget:
                self.assertIsNotNone(budget.reserve())
                with self.assertRaisesRegex(LiveRefusal, "đang được sử dụng"):
                    with approval_budget(directory, approval, self.META, resume=False):
                        self.fail("Concurrent budget opened")
            path = directory / "screening.json"
            previous = path.read_bytes()
            with approval_budget(directory, approval, self.META, resume=False) as budget:
                self.assertEqual(budget.used, MAX_TRANSPORT_CALLS)
                self.assertIsNone(budget.reserve())
            changed = doc | {"expires_on": "2999-01-01"}
            changed["content_sha256"] = content_sha256(changed)
            with self.assertRaisesRegex(LiveRefusal, "nội dung phê duyệt khác"):
                with approval_budget(directory, (changed, date.max, MAX_TRANSPORT_CALLS), self.META, resume=False):
                    self.fail("Rehashed plan reopened its old ledger")
            self.assertEqual(path.read_bytes(), previous)
