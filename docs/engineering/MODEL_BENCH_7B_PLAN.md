# Phase 7B · First screening round

The six candidates span all four providers and both routing tiers. The tiers describe
the intended screening roles. The same ten DEV cases cover all ten task groups and
all three difficulties, with eight deterministic golds and two human rubrics. Each
candidate gets one run with a 512-token output reserve per case. The owner reviews
all ten golds or rubrics before authorizing the screening. Wave 1 uses Groq,
Cloudflare and OpenRouter. Wave 2 uses Gemini after M9 finishes and the owner
confirms Gemini quota.

```powershell
python -m tools.model_bench.run --screening --dry-run --plan-md
```

The generated sample below is illustrative. After merge, regenerate the dry-run
plan on `main` and use the new per-model fingerprints in the owner plan. The
Git revision at generation is part of each fingerprint.

<!-- BEGIN GENERATED SCREENING SAMPLE -->

Revision at generation: `3b57a5d621d6f89400364d08247552476ed15dbd`

**Pending on `main` after merge.** Regenerate the dry-run plan and per-model fingerprints.

## Wave 1

Cases in execution order: `event_extraction-01`, `disambiguation-04`, `causal_relation-07`, `event_ordering-04`, `hallucination_detection-07`, `spoiler_detection-01`, `narrative_plan-02`, `vietnamese_script-03`, `script_correction-07`, `structured_output-01`

One run per model. Reserve 24 requests before every case. The run can stop early when the remaining cap cannot cover that reserve.
Token estimates use input plus reserved output. At the cap, use the largest case estimate for every request as a conservative planning figure. Quota windows are lower bounds from known limits only. Allow for shared quota, retry bursts and actual provider counters.

**Shared-quota check.** No other pipeline may use the same provider during this wave. M9 uses Gemini only.

| Provider / model | Screening tier and reason | Cases × runs | Base requests | Request cap | Est. input + output (base) | Est. input + output (at cap) | Quota scope and limits | Min / days ≥ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| groq / openai/gpt-oss-20b | Utility · smaller GPT-OSS candidate | 10 × 1 | 10 | 40 | 1582 + 5120 | 8520 + 20480 | organization_model. rpm unknown [unknown], tpm 8000 [verified], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | 4 / unknown |
| groq / openai/gpt-oss-120b | Quality-critical · larger GPT-OSS candidate | 10 × 1 | 10 | 40 | 1582 + 5120 | 8520 + 20480 | organization_model. rpm unknown [unknown], tpm 8000 [verified], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | 4 / unknown |
| cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 | Quality-critical · Qwen candidate with Neuron quota | 10 × 1 | 10 | 40 | 1692 + 5120 | 8960 + 20480 | account_neurons. rpm 300 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day 10000 [verified], free_requests_per_day unknown [unknown] | 1 / 1 |
| openrouter / google/gemma-4-31b-it:free | Utility · named Gemma free variant | 10 × 1 | 10 | 40 | 1582 + 5120 | 8520 + 20480 | account. rpm 20 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day 50 [estimated] | 2 / 1 |
| **Wave total** |  | 40 | 40 | 160 | 6438 + 20480 | 34520 + 81920 | Per-model caps and quota scopes apply |  |

- groq / openai/gpt-oss-20b plan SHA-256 `a3e3d9936c5a4dd5e0c32820ec9cfbb5b9d49393492140f5b2424401b96dff22`
- groq / openai/gpt-oss-20b unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], limits.rpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- groq / openai/gpt-oss-120b plan SHA-256 `8fffacb0b8bb847e8e3249aa9bb472ed2ee03a8e79ef9e00cb16117ebccbd0b4`
- groq / openai/gpt-oss-120b unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], limits.rpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 plan SHA-256 `5a5d5f7b4245e066be92b2f68ef5a338a0924d48f1c5e23e15894ecb5630e879`
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [estimated], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 estimated Neurons at cap 680
- openrouter / google/gemma-4-31b-it:free plan SHA-256 `b68d580b5f4acc1061284a235c0670fb93bf2853905401f2f75e233daf10fead`
- openrouter / google/gemma-4-31b-it:free unverified fields: max_output_tokens [unknown], limits.rpm [estimated], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [estimated]. Confirm current quota and usage.
- openrouter / google/gemma-4-31b-it:free: catalog snapshot; free variants can disappear — re-check before each live run.

## Wave 2 — after M9 finishes and the owner confirms Gemini quota

Cases in execution order: `event_extraction-01`, `disambiguation-04`, `causal_relation-07`, `event_ordering-04`, `hallucination_detection-07`, `spoiler_detection-01`, `narrative_plan-02`, `vietnamese_script-03`, `script_correction-07`, `structured_output-01`

One run per model. Reserve 24 requests before every case. The run can stop early when the remaining cap cannot cover that reserve.
Token estimates use input plus reserved output. At the cap, use the largest case estimate for every request as a conservative planning figure. Quota windows are lower bounds from known limits only. Allow for shared quota, retry bursts and actual provider counters.

**Shared-quota check.** No other pipeline may use the same provider during this wave. M9 uses Gemini only.

| Provider / model | Screening tier and reason | Cases × runs | Base requests | Request cap | Est. input + output (base) | Est. input + output (at cap) | Quota scope and limits | Min / days ≥ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| gemini / gemini-3.5-flash-lite | Utility · Flash-Lite candidate | 10 × 1 | 10 | 40 | 1582 + 5120 | 8520 + 20480 | project_model. rpm unknown [unknown], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | unknown / unknown |
| gemini / gemini-3.6-flash | Quality-critical · Flash candidate on the M9 provider | 10 × 1 | 10 | 40 | 1582 + 5120 | 8520 + 20480 | project_model. rpm unknown [unknown], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | unknown / unknown |
| **Wave total** |  | 20 | 20 | 80 | 3164 + 10240 | 17040 + 40960 | Per-model caps and quota scopes apply |  |

- gemini / gemini-3.5-flash-lite plan SHA-256 `7f93fbccae47de2c12a295e4ee2f7a1e675036dc207064934f23e46f7f6998ea`
- gemini / gemini-3.5-flash-lite unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [unknown], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- gemini / gemini-3.6-flash plan SHA-256 `cf687d6c79de90d8299a8250d2fa0d660c16efdce6cda6336f574f2660db117e`
- gemini / gemini-3.6-flash unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [unknown], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.

<!-- END GENERATED SCREENING SAMPLE -->

The 40-request cap leaves retry headroom above the ten base requests and fits the
repository's estimated OpenRouter daily quota of 50 if the account has enough free
capacity. With a 24-request reserve per case, more than seven retries before the last
case may cut screening short. The table estimates tokens against the coded Groq TPM
limit, OpenRouter's account request limits, and Cloudflare's request and Neuron limits.
Unknown limits require owner confirmation. The owner's 2026-11-24 catalog
snapshot recorded 262,144 context tokens, zero prompt and completion prices, and
support for `response_format` and `reasoning` for the named Gemma free variant.
The registry records native JSON mode and no structured-output support.
Re-check free variant availability before each live run.

Schedule Wave 2 after M9 finishes and the owner confirms Gemini quota. For live Gemini,
point `--seasons-dir` at the
directory containing the real season runs if they live outside `.local/story_seasons`.
A recent season file (under six hours old) blocks Gemini. A gate lock also blocks it
unless its season is `COMPLETED` or has been `FAILED` for over 24 hours. Missing or
unreadable season status beside a lock blocks Gemini. Use
`--m9-clear-attested-by-owner` only with explicit owner clearance. The manifest records
the flag. Other providers can screen in separate quota windows ahead of Gemini.

## Owner approval file

Save a private UTF-8 JSON plan with a fresh lowercase `plan_id`, the dataset hash from
`data/model_bench_dev/v1/MANIFEST.json`, all ten case IDs in the printed order, and a
model entry for each approved row. Use an inclusive UTC expiry date. This example
shows the shape for a single model.

```json
{
  "plan_id": "7b-screening-01",
  "approved_by": "<Project Owner>",
  "dataset_sha256": "<dataset hash>",
  "case_ids": ["<all ten IDs in execution order>"],
  "models": [
    {
      "provider": "groq",
      "model": "openai/gpt-oss-20b",
      "request_cap": 40,
      "plan_sha256": "<model fingerprint from the regenerated table>"
    }
  ],
  "expires_on": "YYYY-MM-DD"
}
```

After the owner has finalized the fields, add `content_sha256` using the canonical
JSON digest. It covers the complete document with the hash field omitted. The
following local command seals the example after the placeholders have been filled in.

```powershell
$planFile = 'C:\path\to\approved-plan.json'
python -c "import json, sys; from pathlib import Path; from tools.model_bench.approval import content_sha256; p=Path(sys.argv[1]); d=json.loads(p.read_text(encoding='utf-8')); d['content_sha256']=content_sha256(d); p.write_text(json.dumps(d, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')" $planFile
```

Invoke `tools.model_bench.run` with `--provider`, `--model`, one `--case` per printed
ID, `--live --approved-plan <plan-file>` and the approved output reserve. Run only
the agreed single screening pass per model. The runner binds the plan ID to its
content hash in `.local/model_bench_runs/approvals/<plan_id>.json`. This append-only
JSON Lines ledger charges a reservation before dispatch and credits the unused
portion when attempts are known. Every run or resume shares the model's remaining
budget. Content edits require renewed owner approval and a new plan ID. The hash is a
content-integrity check. Keep control of the approved file and its ledger local.

For an interrupted run, reuse its directory with `--output-dir` and `--resume`. Keep
`budget.json` beside the checkpoint. If dispatch status is uncertain, reconcile the
checkpoint before resuming. An unsettled reservation stays charged in full. Clear
stale lock files only after confirming the corresponding process has stopped.

Record completion, deterministic scores, and efficiency for the screening pass. Use
`human_review.jsonl` to score the two rubric responses against their evidence and
criteria. Schedule separate stability repeats after reviewing the screening results.
