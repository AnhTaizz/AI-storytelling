"""Build a reproducible, offline request and quota plan."""
from math import ceil

from tools.llm_infra.model_capabilities_v1 import UNKNOWN_CONTEXT_TOKENS
from tools.llm_infra.neuron_ledger import estimate_neurons
from tools.llm_infra.pipeline_clients import JSON_PROMPT, MAX_TRANSPORT_CALLS
from tools.llm_infra.token_estimate import estimate_input_tokens

from tools.model_bench.dataset import canonical_json, digest

PROMPT_VERSION = "model_bench_dev_v1"
SYSTEM = ('Answer the task using only the supplied passage. Return one JSON object with exactly '
          'one key "answer". Put the requested value inside that key, including arrays or strings. '
          'For a writing task, put the full text in a JSON string.')
REPEATS = 1
TEMPERATURE = 0.0
DEFAULT_MAX_OUTPUT = 512
SCREENING_CASES = (
    "event_extraction-01", "disambiguation-04", "causal_relation-07", "event_ordering-04",
    "hallucination_detection-07", "spoiler_detection-01", "narrative_plan-02",
    "vietnamese_script-03", "script_correction-07", "structured_output-01",
)
SCREENING_REQUEST_CAP = 40
SCREENING_WAVES = (
    ("Wave 1", (
        ("groq", "openai/gpt-oss-20b", "Utility · smaller GPT-OSS candidate"),
        ("groq", "openai/gpt-oss-120b", "Quality-critical · larger GPT-OSS candidate"),
        ("cloudflare", "@cf/qwen/qwen3-30b-a3b-fp8", "Quality-critical · Qwen candidate with Neuron quota"),
        ("openrouter", "google/gemma-4-31b-it:free", "Utility · named Gemma free variant"),
    )),
    ("Wave 2 — after M9 finishes and the owner confirms Gemini quota", (
        ("gemini", "gemini-3.5-flash-lite", "Utility · Flash-Lite candidate"),
        ("gemini", "gemini-3.6-flash", "Quality-critical · Flash candidate on the M9 provider"),
    )),
)


def display(value):
    return "unknown" if value is None else str(value)


def user_prompt(case):
    inputs = case["input"]
    return f'Đoạn trích:\n{inputs["passage"]}\n\nYêu cầu:\n{inputs["instruction"]}'


def make_plan(model, cases, max_output):
    context = model["context_tokens"]
    limits = model["limits"]
    extra = JSON_PROMPT if model["json_mode"] == "prompt" else ""
    case_plans = []
    for case in cases:
        prompt = user_prompt(case)
        tokens = estimate_input_tokens(SYSTEM, prompt, extra)
        total = tokens + max_output
        neurons = (estimate_neurons(model["model_id"], tokens, max_output)
                   if model["provider"] == "cloudflare" else None)
        flags = []
        if total > (context if context is not None else UNKNOWN_CONTEXT_TOKENS):
            flags.append("context" if context is not None else "adapter_context_guard")
        if limits["tpm"] is not None and total > limits["tpm"]:
            flags.append("tpm")
        if model["max_output_tokens"] is not None and max_output > model["max_output_tokens"]:
            flags.append("max_output_tokens")
        if neurons is not None and neurons > limits["neurons_per_day"]:
            flags.append("neurons_per_day")
        if limits["tpd"] is not None and total > limits["tpd"]:
            flags.append("tpd")
        prompt_hash = digest(canonical_json([SYSTEM, prompt, extra]).encode("utf-8"))
        case_plans.append({"case_id": case["id"], "group": case["group"], "input": tokens,
                           "prompt_sha256": prompt_hash,
                           "reserved_output": max_output, "neurons": neurons, "flags": flags})
    return case_plans


def approval_sha256(metadata, model, case_plans):
    payload = {"run": {key: value for key, value in metadata.items() if key != "mode"},
               "registry_entry": model, "case_plans": case_plans, "repeats": REPEATS,
               "max_transport_calls_per_case": MAX_TRANSPORT_CALLS}
    return digest(canonical_json(payload).encode("utf-8"))


def quota_text(model):
    return ", ".join(f"{key} {display(value)} [{model['status'][f'limits.{key}']}]"
                     for key, value in model["limits"].items())


def _window_floor(limits, loads):
    return display(max((ceil(load / limits[key]) for key, load in loads.items() if limits[key] is not None),
                       default=None))


def plan_markdown(plans, *, wave=None):
    """Render one common case selection with per-model caps and configuration hashes."""
    case_ids = ", ".join(f"`{item['case_id']}`" for item in plans[0][1])
    lines = [f"## {wave or 'Owner approval table'}", "", f"Cases in execution order: {case_ids}", "",
             f"One run per model. Reserve {MAX_TRANSPORT_CALLS} requests before every case. "
             "The run can stop early when the remaining cap cannot cover that reserve.",
             "Token estimates use input plus reserved output. At the cap, use the largest case estimate "
             "for every request as a conservative planning figure. Quota windows are lower bounds from "
             "known limits only. Allow for shared quota, retry bursts and actual provider counters."]
    if wave:
        lines.extend(["", "**Shared-quota check.** No other pipeline may use the same provider during this wave. "
                      "M9 uses Gemini only."])
    lines.extend(["", "| Provider / model | Screening tier and reason | Cases × runs | Base requests | Request cap | "
                  "Est. input + output (base) | Est. input + output (at cap) | Quota scope and limits | Min / days ≥ |",
                  "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |"])
    details = []
    total_cases = total_requests = total_inputs = total_outputs = total_cap_inputs = total_cap_outputs = 0
    for model, items, fingerprint, cap, reason in plans:
        name = f"{model['provider']} / {model['model_id']}"
        inputs = sum(item["input"] for item in items)
        outputs = sum(item["reserved_output"] for item in items)
        cap_inputs = cap * max(item["input"] for item in items)
        cap_outputs = cap * max(item["reserved_output"] for item in items)
        cap_tokens = cap_inputs + cap_outputs
        neurons = cap * max((item["neurons"] or 0 for item in items))
        limits = model["limits"]
        minutes = _window_floor(limits, {"rpm": cap, "tpm": cap_tokens})
        days = _window_floor(limits, {"free_requests_per_day": cap, "rpd": cap, "tpd": cap_tokens,
                                      "neurons_per_day": neurons})
        lines.append(f"| {name} | {reason} | {len(items)} × {REPEATS} | {len(items)} | {cap} | "
                     f"{inputs} + {outputs} | {cap_inputs} + {cap_outputs} | {model['quota_scope']}. "
                     f"{quota_text(model)} | "
                     f"{minutes} / {days} |")
        total_cases += len(items)
        total_requests += cap
        total_inputs += inputs
        total_outputs += outputs
        total_cap_inputs += cap_inputs
        total_cap_outputs += cap_outputs
        details.append(f"- {name} plan SHA-256 `{fingerprint}`")
        if wave:
            unverified = ", ".join(f"{key} [{status}]" for key, status in model["status"].items()
                                   if status != "verified")
            details.append(f"- {name} unverified fields: {unverified or 'none'}. Confirm current quota and usage.")
            if model.get("note"):
                details.append(f"- {name}: {model['note']}.")
        if model["provider"] == "cloudflare":
            details.append(f"- {name} estimated Neurons at cap {neurons}")
        details.extend(f"- {name}, {item['case_id']} exceeds {', '.join(item['flags'])}"
                       for item in items if item["flags"])
    if wave:
        lines.append(f"| **Wave total** |  | {total_cases} | {total_cases} | {total_requests} | "
                     f"{total_inputs} + {total_outputs} | {total_cap_inputs} + {total_cap_outputs} | "
                     "Per-model caps and quota scopes apply |  |")
    lines.extend(["", *details])
    return "\n".join(lines) + "\n"
