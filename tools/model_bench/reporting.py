"""Write quality and efficiency summaries from checkpointed results."""
import csv
from pathlib import Path
from statistics import mean

from tools.model_bench.dataset import canonical_json
from tools.model_bench.planning import display

TOKEN_METRICS = ("input_tokens", "output_tokens", "reasoning_tokens")
METRICS = ("input_tokens", "output_tokens", "reasoning_tokens", "latency_ms",
           "requests", "retries", "repairs")


def write_text(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")


def _metric(rows, key):
    values = [row[key] for row in rows]
    return sum(values) if values and all(value is not None for value in values) else None


def efficiency(values, successes):
    requests = values.get("requests")
    inputs, outputs = values.get("input_tokens"), values.get("output_tokens")
    used, cap = values.get("budget_used"), values.get("budget_cap")
    return {"requests_per_success": round(requests / successes, 4) if successes and requests is not None else None,
            "tokens_per_success": round((inputs + outputs) / successes, 4)
            if successes and inputs is not None and outputs is not None else None,
            "budget_fraction_used": round(used / cap, 4) if used is not None and cap else None}


def _summary(group, cases, rows):
    scores = [row["score"] for row in rows if row["score"] is not None]
    complete = sum(row["outcome"] == "complete" for row in rows)
    counts = {metric: _metric(rows, metric) for metric in METRICS}
    sources = {row.get("tokens_source", "unknown") for row in rows}
    tokens_source = "unknown"
    if any(counts[key] is not None for key in TOKEN_METRICS):
        tokens_source = "estimated" if "estimated" in sources else "reported"
    errors = sorted({code for row in rows for code in row.get("error_codes", ())})
    return {"group": group, "cases": len(cases), "completed": complete,
            "completion_rate": round(complete / len(cases), 4),
            "errors": len(rows) - complete, "scored": len(scores),
            "mean_score": round(mean(scores), 4) if scores else None,
            "human_review_rows": sum(row["review"] is not None for row in rows),
            **counts, "tokens_source": tokens_source, "error_codes": ", ".join(errors) if rows else None,
            "draft_cases": sum(row.get("gold_tier") == "draft" for row in rows),
            **efficiency(counts, complete)}


def write_reports(directory: Path, metadata, cases, rows):
    summaries = [_summary("all", cases, rows)]
    for group in dict.fromkeys(case["group"] for case in cases):
        summaries.append(_summary(group, [case for case in cases if case["group"] == group],
                                  [row for row in rows if row["group"] == group]))
    for summary in summaries:
        summary.update(budget_used=None, budget_cap=None)
    summaries[0].update({key: metadata.get(key) for key in ("budget_used", "budget_cap")})
    summaries[0].update(efficiency(summaries[0], summaries[0]["completed"]))
    columns = list(summaries[0])
    rendered = [{key: display(value) for key, value in summary.items()} for summary in summaries]
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rendered)
    lines = ["# DEV benchmark report", "", *[f"- **{key}** `{display(value)}`"
                                             for key, value in metadata.items() if key != "gold_statuses"], "",
             "Scores are averaged over scored responses. Completion rate uses all selected cases.",
             "Efficiency totals cover checkpointed cases. Token usage covers available response counters. "
             "Tokens per success uses input + output. Reasoning is shown separately because some providers "
             "include it in output. A missing contributing value makes the total unknown. The budget is "
             "shared by all runs for this plan and model.", "",
             "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |",
             *["| " + " | ".join(row.values()) + " |" for row in rendered]]
    if rows and all("case_id" in row for row in rows):
        fields = ("case_id", "gold_tier", "score", "outcome", *METRICS, "tokens_source", "error_codes",
                  "requests_per_success", "tokens_per_success", "budget_used", "budget_cap",
                  "budget_fraction_used")
        lines.extend(["", "## Cases", "", "| " + " | ".join(fields) + " |",
                      "| " + " | ".join("---" for _ in fields) + " |"])
        for row in rows:
            values = row | {"error_codes": ", ".join(row.get("error_codes", ()))}
            lines.append("| " + " | ".join(display(values.get(key)) for key in fields) + " |")
    write_text(directory / "report.md", "\n".join(lines) + "\n")
    reviews = [row["review"] for row in rows if row["review"] is not None]
    write_text(directory / "human_review.jsonl", "".join(canonical_json(review) + "\n" for review in reviews))
