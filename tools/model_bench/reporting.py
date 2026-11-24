"""Write quality and efficiency summaries from checkpointed results."""
import csv
from pathlib import Path
from statistics import mean

from tools.model_bench.dataset import canonical_json
from tools.model_bench.planning import display

METRICS = ("input_tokens", "output_tokens", "reasoning_tokens", "latency_ms",
           "requests", "retries", "repairs")


def write_text(path, content):
    path.write_text(content, encoding="utf-8", newline="\n")


def _metric(rows, key):
    values = [row[key] for row in rows]
    return sum(values) if values and all(value is not None for value in values) else None


def _summary(group, cases, rows):
    scores = [row["score"] for row in rows if row["score"] is not None]
    complete = sum(row["outcome"] == "complete" for row in rows)
    return {"group": group, "cases": len(cases), "completed": complete,
            "completion_rate": round(complete / len(cases), 4),
            "errors": len(rows) - complete, "scored": len(scores),
            "mean_score": round(mean(scores), 4) if scores else None,
            "human_review_rows": sum(row["review"] is not None for row in rows),
            **{metric: _metric(rows, metric) for metric in METRICS}}


def write_reports(directory: Path, metadata, cases, rows):
    summaries = [_summary("all", cases, rows)]
    for group in dict.fromkeys(case["group"] for case in cases):
        summaries.append(_summary(group, [case for case in cases if case["group"] == group],
                                  [row for row in rows if row["group"] == group]))
    columns = list(summaries[0])
    rendered = [{key: display(value) for key, value in summary.items()} for summary in summaries]
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rendered)
    lines = ["# DEV benchmark report", "", *[f"- **{key}** `{display(value)}`"
                                             for key, value in metadata.items()], "",
             "Scores are averaged over scored responses. Completion rate uses all selected cases.",
             "Efficiency values are totals over checkpointed cases. If a contributing value is missing, "
             "the total is unknown. Human review rows have no automated score.", "",
             "| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |",
             *["| " + " | ".join(row.values()) + " |" for row in rendered]]
    write_text(directory / "report.md", "\n".join(lines) + "\n")
    reviews = [row["review"] for row in rows if row["review"] is not None]
    write_text(directory / "human_review.jsonl", "".join(canonical_json(review) + "\n" for review in reviews))
