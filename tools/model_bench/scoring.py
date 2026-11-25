"""Deterministic scores on [0, 1] and an unscored human review row."""
import json
from collections import Counter

from jsonschema import Draft202012Validator

METHODS = ("exact", "set_f1", "order_kendall", "json_schema", "rubric_human")


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _set_f1(prediction, gold):
    if not isinstance(prediction, list):
        return 0.0
    actual, expected = ({_canonical(item) for item in values} for values in (prediction, gold))
    size = len(actual) + len(expected)
    return 2 * len(actual & expected) / size if size else 1.0


def _order_kendall(prediction, gold):
    """Rescale Kendall tau: concordant pair fraction on an exact, tie-free permutation."""
    if not isinstance(prediction, list):
        return 0.0
    actual, expected = [list(map(_canonical, values)) for values in (prediction, gold)]
    if len(actual) != len(expected) or set(actual) != set(expected):
        return 0.0
    ranks = {item: index for index, item in enumerate(actual)}
    pairs = len(expected) * (len(expected) - 1) // 2
    concordant = sum(ranks[left] < ranks[right] for index, left in enumerate(expected)
                     for right in expected[index + 1:])
    return concordant / pairs if pairs else 1.0


def score(case, prediction):
    method, gold = case["scoring_method"], case["gold"]
    if method == "rubric_human":
        return {"score": None, "review": {"case_id": case["id"], "candidate": prediction,
                                          "rubric": case["rubric"], "human_score": None, "notes": ""}}
    if method == "exact":
        value = float(_canonical(prediction) == _canonical(gold))
    elif method == "set_f1":
        value = _set_f1(prediction, gold)
    elif method == "order_kendall":
        value = _order_kendall(prediction, gold)
    elif method == "json_schema":
        value = float(Draft202012Validator(gold["schema"]).is_valid(prediction))
    else:
        raise ValueError("Unknown scoring method")
    result = {"score": value, "review": None}
    if method in {"set_f1", "order_kendall"}:
        counts = Counter(map(_canonical, prediction)) if isinstance(prediction, list) else {}
        result["duplicate_predictions"] = [
            {"item": json.loads(item), "count": count} for item, count in counts.items() if count > 1
        ]
    return result
