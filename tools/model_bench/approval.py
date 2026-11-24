"""Validate owner plans and durably reserve their shared request budget."""
from contextlib import contextmanager
from datetime import date, datetime, timezone
import json
import os
import re
from uuid import uuid4

from tools.model_bench.dataset import canonical_json, digest
from tools.model_bench.planning import MAX_TRANSPORT_CALLS


class LiveRefusal(ValueError):
    """An operator-facing refusal with no provider or filesystem details."""


def content_sha256(document):
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    return digest(canonical_json(payload).encode("utf-8"))


def _unique_object(pairs):
    document = dict(pairs)
    if len(document) != len(pairs):
        raise ValueError("Duplicate JSON key")
    return document


def _unexpired(expires_on):
    if expires_on < datetime.now(timezone.utc).date():
        raise LiveRefusal("Kế hoạch phê duyệt đã hết hạn (UTC).")


def load_approval(path, metadata):
    try:
        doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        expires = date.fromisoformat(doc["expires_on"])
        if (set(doc) != {"plan_id", "dataset_sha256", "case_ids", "models", "expires_on",
                         "approved_by", "content_sha256"}
                or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", doc["plan_id"])
                or doc["expires_on"] != expires.isoformat()
                or not doc["approved_by"].strip()
                or doc["content_sha256"] != content_sha256(doc)
                or doc["dataset_sha256"] != metadata["dataset_sha256"]
                or doc["case_ids"] != metadata["case_ids"]
                or not isinstance(doc["models"], list)):
            raise ValueError
        models = {}
        for item in doc["models"]:
            key = item["provider"], item["model"]
            cap = item["request_cap"]
            if (set(item) != {"provider", "model", "request_cap", "plan_sha256"}
                    or key in models or not all(isinstance(part, str) and part for part in key)
                    or type(cap) is not int or cap <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", item["plan_sha256"])):
                raise ValueError
            models[key] = item
        selected = models[metadata["provider"], metadata["model"]]
        if selected["plan_sha256"] != metadata["plan_sha256"]:
            raise ValueError
    except (OSError, ValueError, AttributeError, KeyError, TypeError) as error:
        raise LiveRefusal("Kế hoạch phê duyệt không khớp nội dung, bộ dữ liệu hoặc cấu hình chạy.") from error
    _unexpired(expires)
    return doc, expires, selected["request_cap"]


class RequestBudget:
    def __init__(self, path, model, cap, expires):
        self.path, self.model, self.cap, self.expires = path, model, cap, expires
        self.used = 0

    def restore(self, entries, allowed_models):
        reservations = {}
        totals = dict.fromkeys(allowed_models, 0)
        for entry in entries:
            model, reservation, charge = tuple(entry["model"]), entry["reservation"], entry["charge"]
            if type(charge) is not int or model not in totals:
                raise LiveRefusal("Sổ ngân sách phê duyệt không hợp lệ.")
            if charge == MAX_TRANSPORT_CALLS and reservation not in reservations:
                reservations[reservation] = model
            elif -MAX_TRANSPORT_CALLS <= charge <= 0 and reservations.get(reservation) == model:
                reservations[reservation] = None
            else:
                raise LiveRefusal("Sổ ngân sách phê duyệt không hợp lệ.")
            totals[model] += charge
            if not 0 <= totals[model] <= allowed_models[model]:
                raise LiveRefusal("Sổ ngân sách phê duyệt không hợp lệ.")
        self.used = totals[self.model]

    def _append(self, entry):
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(entry) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def reserve(self):
        _unexpired(self.expires)
        if self.cap - self.used < MAX_TRANSPORT_CALLS:
            return None
        reservation = uuid4().hex
        self._charge(reservation, MAX_TRANSPORT_CALLS)
        return reservation

    def settle(self, reservation, requests):
        if requests is not None:
            self._charge(reservation, requests - MAX_TRANSPORT_CALLS)

    def _charge(self, reservation, charge):
        self._append({"model": self.model, "reservation": reservation, "charge": charge})
        self.used += charge


@contextmanager
def approval_budget(directory, approval, metadata, *, resume):
    doc, expires, cap = approval
    directory.mkdir(parents=True, exist_ok=True)
    # Normalize case and avoid Windows reserved device names even for owner-chosen IDs.
    if re.fullmatch(r"con|prn|aux|nul|(?:com|lpt)[0-9]", doc["plan_id"]):
        raise LiveRefusal("Mã kế hoạch phê duyệt không hợp lệ.")
    path = directory / (doc["plan_id"] + ".json")
    lock = path.with_suffix(".lock")
    try:
        with lock.open("x"):
            pass
    except FileExistsError as error:
        raise LiveRefusal("Sổ ngân sách đang được sử dụng. Kiểm tra tiến trình trước khi gỡ khóa.") from error
    try:
        model = metadata["provider"], metadata["model"]
        budget = RequestBudget(path, model, cap, expires)
        binding = {"content_sha256": doc["content_sha256"]}
        if path.exists():
            raw = path.read_bytes()
            if not raw.endswith(b"\n"):
                raise LiveRefusal("Sổ ngân sách ghi dở. Cần đối chiếu trước khi chạy tiếp.")
            header, *entries = map(json.loads, raw.splitlines())
            if header != binding:
                raise LiveRefusal("Mã kế hoạch đã được dùng với nội dung phê duyệt khác.")
            budget.restore(entries, {(item["provider"], item["model"]): item["request_cap"]
                                     for item in doc["models"]})
        elif resume:
            raise LiveRefusal("Thiếu sổ ngân sách của lần chạy cần tiếp tục.")
        else:
            budget._append(binding)
        yield budget
    finally:
        lock.unlink()
