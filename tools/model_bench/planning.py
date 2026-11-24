"""Build a reproducible, offline request and quota plan."""
from collections import defaultdict
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
REPEATS = 3
TEMPERATURE = 0.0
DEFAULT_MAX_OUTPUT = 512


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


def plan_markdown(model, case_plans, fingerprint):
    groups = defaultdict(list)
    for item in case_plans:
        groups[item["group"]].append(item)
    provider_model = f"{model['provider']} / {model['model_id']}"
    limits = model["limits"]
    lines = ["## Owner approval table", "",
             f"Plan SHA-256: `{fingerprint}`",
             f"Quota scope: {model['quota_scope']}. {REPEATS} independent repeats.",
             f"Request estimates assume one dispatch per case per repeat. The adapter can make up to "
             f"{MAX_TRANSPORT_CALLS} dispatches per case including retries.",
             "Tokens include input estimates and output reserves. Days are lower bounds from known daily "
             "quotas for each row. Rows share quota and require an owner-confirmed schedule.", "",
             "| Model | Group | Cases per repeat | Requests | Est. input + reserved output | Quota limit | Days ≥ |",
             "| --- | --- | ---: | ---: | ---: | --- | ---: |"]
    for group, items in groups.items():
        requests = len(items) * REPEATS
        input_tokens = sum(item["input"] for item in items) * REPEATS
        output_tokens = sum(item["reserved_output"] for item in items) * REPEATS
        loads = {"rpd": requests, "free_requests_per_day": requests, "tpd": input_tokens + output_tokens,
                 "neurons_per_day": sum(item["neurons"] or 0 for item in items) * REPEATS}
        days = max((ceil(load / limits[key]) for key, load in loads.items() if limits[key] is not None),
                   default=None)
        lines.append(f"| {provider_model} | {group} | {len(items)} | {requests} | "
                     f"{input_tokens} + {output_tokens} | {quota_text(model)} | {display(days)} |")
    flagged = [f"{item['case_id']}: {', '.join(item['flags'])}" for item in case_plans if item["flags"]]
    if flagged:
        lines.extend(["", "Flagged cases", "", *[f"- {item}" for item in flagged]])
    return "\n".join(lines) + "\n"
