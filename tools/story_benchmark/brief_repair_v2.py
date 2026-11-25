"""Isolated, offline-first chapter Brief repair experiment over synthetic DEV inputs."""
import copy
import json
import re
import time
from pathlib import Path

from tools.llm_infra.telemetry import usage_counts
from tools.story_pipeline import llm, stages
from tools.story_pipeline.profile import load_profile
from tools.story_pipeline.source import Chapter, Passage

FIXTURE = Path(__file__).resolve().parents[2] / "data/dev/brief_repair_v2/workshop.json"
CASES = ("clean", "structure", "uncertainty", "combined", "atomicity")
ARMS = ("C0", "C1", "C2", "C3")
SCHEMA = stages.load_schema("story_brief_v0")
USAGE_KEYS = ("input", "output", "reasoning", "total")


def fixture(kind):
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    initial = copy.deepcopy(data["reference"])
    if kind in ("structure", "combined"):
        initial["unknowns"] = [{"text": text} for text in initial["unknowns"]]
    if kind in ("uncertainty", "combined"):
        initial["events"][1].update(epistemic="EXPLICIT", summary="Mina đã đặt một kệ dự phòng.")
    if kind == "atomicity":
        initial["characters"][0]["facts"][0].update(
            text="Mina đo kệ, và viết nhãn, và đóng hộp.", quote=data["source"][0])
    chapter = Chapter(1, "dev-workshop", "Xưởng mộc", tuple(
        Passage(f"1.{n}", text) for n, text in enumerate(data["source"], 1)))
    return {**data, "name": kind, "chapter": chapter, "initial": initial}


def validate(obj, chapter):
    hard = llm.schema_errors(SCHEMA, obj)
    if not hard:
        hard = stages.brief_semantic_errors(obj, chapter, "ja", "vi")
    soft = [] if hard else stages.brief_atomicity_errors(obj, "vi") + stages.brief_script_errors(obj, "vi")
    return hard, soft


def normalize(obj):
    fixed = copy.deepcopy(obj)
    if isinstance(fixed, dict):
        for key in ("unknowns", "forbidden_inferences"):
            if isinstance(fixed.get(key), list):
                fixed[key] = [value["text"] if isinstance(value, dict) and set(value) == {"text"}
                              and isinstance(value["text"], str) else value for value in fixed[key]]
    return fixed


def targets(obj, errors):
    """Return bounded paths only when every finding can be located unambiguously."""
    paths = set()
    for error in errors:
        shape = re.match(r"schema: at (unknowns|forbidden_inferences)/(\d+):", error)
        event = re.match(r"event (E\d+):", error)
        fact = re.match(r"characters (CH\d+) facts\[\d+\]:", error)
        if shape:
            paths.add((shape[1], int(shape[2])))
        elif event or fact:
            key, identifier = ("events", event[1]) if event else ("characters", fact[1])
            indexes = [i for i, item in enumerate(obj[key]) if item["id"] == identifier]
            if len(indexes) != 1:
                return []
            path = (key, indexes[0])
            paths.add(path if event else (*path, "facts"))
        else:
            return []
    return sorted(paths)


def value_at(obj, path):
    for key in path:
        obj = obj[key]
    return obj


def key_for(path):
    return "/" + "/".join(map(str, path))


def score(obj, case):
    """Strict synthetic event oracle. Human semantic judgements are recorded separately."""
    gold = case["reference"]["events"]
    if not isinstance(obj, dict) or validate(obj, case["chapter"])[0]:
        return 0.0, 0.0
    predicted = obj["events"]
    semantic_keys = ("summary", "participants", "epistemic", "motivation", "consequence", "location")
    correct = covered = 0
    for expected in gold:
        matches = [event for event in predicted if all(event[k] == expected[k] for k in semantic_keys)]
        correct += bool(matches)
        covered += any(e["evidence"] == expected["evidence"] and e["quote"] == expected["quote"] for e in matches)
    return correct / max(len(predicted), 1), covered / len(gold)


def known_sum(values):
    values = list(values)
    return sum(values) if all(value is not None for value in values) else None


def reported_tokens(record):
    counts = usage_counts(record)
    usage = record.get("usage_metadata") or {}
    total = usage.get("total_token_count", usage.get("total_tokens"))
    return {"input": counts["input_tokens"], "output": counts["output_tokens"],
            "reasoning": counts["reasoning_tokens"],
            "total": total if type(total) is int and total >= 0 else None}


def compare(case, arm, respond):
    """Use a common pre-generated initial object. respond receives system/user text only."""
    if arm not in ARMS:
        raise ValueError("unknown arm")
    started = time.perf_counter()
    chapter = case["chapter"]
    obj = copy.deepcopy(case["initial"])
    system = stages.brief_system_prompt(load_profile(), "ja", f"{chapter.order}.12", SCHEMA)
    base = stages.render("brief_user", story_id="dev-workshop", chapter_order=chapter.order,
                         chapter_title=chapter.title, known_characters=stages.known_characters_text([]),
                         facts_block="", chapter_text=chapter.render())
    hard, soft = validate(obj, chapter)
    initial_hard = bool(hard)
    normalized = False
    if arm in ("C2", "C3"):
        fixed = normalize(obj)
        normalized = fixed != obj
        obj = fixed
        hard, soft = validate(obj, chapter)
    best = None if hard else copy.deepcopy(obj)
    best_score = len(soft)
    requests = []
    early = False
    rollbacks = 0
    raw = json.dumps(obj, ensure_ascii=False)
    for _ in range(2):
        if not hard and not soft:
            break
        if arm == "C3" and not hard and len(soft) == 1 and re.fullmatch(
                r"characters CH\d+ facts\[\d+\]: joins \d+ clauses; split it into separate facts, "
                r"each with its own quote, evidence and epistemic", soft[0]):
            early = True
            break
        errors = hard or soft
        paths = targets(obj, errors) if arm != "C0" else []
        if paths:
            payload = {"instruction": "Return one JSON object mapping each specified path to its repaired value. "
                       "Use only the Japanese source. Preserve certainty, actors and all supported facts.",
                       "fields": {key_for(path): value_at(obj, path) for path in paths},
                       "source": chapter.render(), "errors": errors,
                       "dependencies": {k: obj.get(k) for k in ("chapter_summary", "ending_state", "relationships")},
                       "roster": [{k: c.get(k) for k in ("id", "name", "romanized_name")} for c in obj.get("characters", [])
                                  if isinstance(c, dict)],
                       "event_refs": [{k: e.get(k) for k in ("id", "participants", "summary")} for e in obj.get("events", [])
                                      if isinstance(e, dict)]}
            instruction = "Repair only the listed fields. Return JSON keyed by their exact paths."
            payload["field_schemas"] = {key_for(path): schema_at(path) for path in paths}
            prompt = json.dumps(payload, ensure_ascii=False)
        else:
            instruction = system
            prompt = llm.REPAIR_TEMPLATE.format(original=base, previous=raw[:60000],
                                                errors="\n".join("- " + e for e in errors))
        before = time.perf_counter()
        rec = respond({"system": instruction, "user": prompt})
        latency = time.perf_counter() - before
        raw_response = rec["raw_content"]
        try:
            answer = llm.parse_json_object(raw_response)
            if paths:
                if not isinstance(answer, dict) or set(answer) != {key_for(p) for p in paths}:
                    raise ValueError("patch keys must match exactly")
                proposed = copy.deepcopy(obj)
                for path in paths:
                    value_at(proposed, path[:-1])[path[-1]] = answer[key_for(path)]
            else:
                proposed = answer
            if arm in ("C2", "C3"):
                fixed = normalize(proposed)
                normalized |= fixed != proposed
                proposed = fixed
            problems, warnings = validate(proposed, chapter)
        except (ValueError, TypeError) as error:
            proposed, problems, warnings = None, [str(error)], []
        requests.append({"mode": "targeted" if paths else "full", "paths": [key_for(p) for p in paths],
                         "input_chars": len(prompt) + len(instruction), "seconds": latency,
                         "usage": reported_tokens(rec), "hard": problems, "soft": warnings})
        if proposed is not None and not problems and (
                best is None or len(warnings) < best_score or arm == "C0"):
            best, best_score = copy.deepcopy(proposed), len(warnings)
        if best is not None and (problems or (arm != "C0" and len(warnings) > best_score)):
            rollbacks += 1
        if paths and proposed is None:
            continue
        obj, hard, soft = proposed, problems, warnings
        raw = json.dumps(proposed, ensure_ascii=False) if paths else raw_response
    selected = best
    hard, soft = validate(selected, chapter) if selected is not None else (hard, [])
    accuracy, coverage = score(selected, case)
    tokens = {key: known_sum(r["usage"][key] for r in requests) for key in USAGE_KEYS}
    return selected, {"case": case["name"], "arm": arm, "requests": requests, "rollbacks": rollbacks,
                      "rollback_rate": rollbacks / len(requests) if requests else None,
                      "initial_hard": initial_hard, "hard_errors": hard, "soft_errors": soft,
                      "recovered": not hard if initial_hard else None, "early_stop": early,
                      "normalized": normalized, "event_semantic_accuracy": accuracy, "evidence_coverage": coverage,
                      "human_semantic_accuracy": None, "seconds": time.perf_counter() - started,
                      "token_totals": tokens, "tokens": tokens["total"]}


def summarize(rows):
    summary = []
    for arm in ARMS:
        cases = [row for row in rows if row["arm"] == arm]
        if not cases:
            continue
        requests = [request for row in cases for request in row["requests"]]
        initially_invalid = [row for row in cases if row["initial_hard"]]
        recovered = sum(row["recovered"] for row in initially_invalid)
        invalid = sum(bool(row["hard_errors"]) for row in cases)
        rollbacks = sum(row["rollbacks"] for row in cases)
        summary.append({
            "arm": arm, "cases": len(cases), "model_calls": len(requests),
            "final_hard_invalid": invalid, "hard_error_rate": invalid / len(cases),
            "initial_hard_invalid": len(initially_invalid), "recovered": recovered,
            "repair_success_rate": recovered / len(initially_invalid) if initially_invalid else None,
            "rollbacks": rollbacks, "rollback_rate": rollbacks / len(requests) if requests else None,
            "event_semantic_accuracy": sum(row["event_semantic_accuracy"] for row in cases) / len(cases),
            "evidence_coverage": sum(row["evidence_coverage"] for row in cases) / len(cases),
            "token_totals": {key: known_sum(row["token_totals"][key] for row in cases) for key in USAGE_KEYS},
            "model_seconds": sum(request["seconds"] for request in requests),
            "wall_seconds": sum(row["seconds"] for row in cases),
        })
    return summary


def schema_at(path):
    schema = SCHEMA
    for part in path:
        schema = schema["items"] if isinstance(part, int) else schema["properties"][part]
    return schema


def demo():
    rows = []
    for kind in CASES:
        case = fixture(kind)
        def scripted(request):
            if request["system"].startswith("Repair only"):
                fields = json.loads(request["user"])["fields"]
                result = {}
                for key in fields:
                    parts = [int(x) if x.isdigit() else x for x in key.split("/")[1:]]
                    result[key] = value_at(case["reference"], parts)
            else:
                result = case["reference"]
            return {"raw_content": json.dumps(result, ensure_ascii=False)}
        for arm in ARMS:
            _, result = compare(case, arm, scripted)
            rows.append(result)
    return rows


if __name__ == "__main__":
    results = demo()
    print(json.dumps({"mode": "offline_scripted", "summary": summarize(results), "cases": results},
                     ensure_ascii=False, indent=2))
