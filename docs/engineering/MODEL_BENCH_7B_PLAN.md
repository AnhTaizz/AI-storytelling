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

## Wave 1 availability review · 2026-11-24

The four pinned entries retain a planning budget of 40 base requests and a maximum of 160. The following provider publications supplement the generated registry estimates. Current account entitlement, remaining quota and serving capacity still need confirmation immediately before an approved run.

- Groq lists both GPT-OSS models under free plan limits of 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute and 200,000 tokens/day per model. Confirm the organization is on the free plan. [Groq limits](https://console.groq.com/docs/rate-limits)
- **Cloudflare leg on hold.** Cloudflare retired the pinned Qwen model on November 20 and documents HTTP 410 for requests to it. Keep its allocation reserved pending the owner's choice of a replacement. Workers Free provides 10,000 neurons/day at account scope. Workers Paid can incur overages. [Model deprecation notice](https://developers.cloudflare.com/changelog/post/2026-11-05-planned-model-deprecations/) · [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- OpenRouter lists the pinned Gemma free variant with zero input and output price. Accounts with fewer than 10 credits purchased have limits of 20 requests/minute and 50 free-model requests/day. Check the remaining daily count against the approved budget and recheck the named free variant at dispatch. [Gemma model card](https://openrouter.ai/google/gemma-4-31b-it:free) · [Free-model limits](https://openrouter.ai/docs/api_reference/limits.md)

<!-- BEGIN GENERATED SCREENING SAMPLE -->

Revision at generation: `c8f8f0269ee68ff10f2be023e7da443c7aea9e59`

**Pending on `main` after merge.** Regenerate the dry-run plan and per-model fingerprints.

## Wave 1

Cases in execution order: `event_extraction-01`, `disambiguation-04`, `causal_relation-07`, `event_ordering-04`, `hallucination_detection-07`, `spoiler_detection-01`, `narrative_plan-02`, `vietnamese_script-03`, `script_correction-07`, `structured_output-01`

One run per model. Reserve 24 requests before every case. The run can stop early when the remaining cap cannot cover that reserve.
Token estimates use input plus reserved output. At the cap, use the largest case estimate for every request as a conservative planning figure. Quota windows are lower bounds from known limits only. Allow for shared quota, retry bursts and actual provider counters.

**Shared-quota check.** No other pipeline may use the same provider during this wave. M9 uses Gemini only.

| Provider / model | Screening tier and reason | Cases × runs | Base requests | Request cap | Est. input + output (base) | Est. input + output (at cap) | Quota scope and limits | Min / days ≥ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| groq / openai/gpt-oss-20b | Utility · smaller GPT-OSS candidate | 10 × 1 | 10 | 40 | 1600 + 5120 | 8520 + 20480 | organization_model. rpm unknown [unknown], tpm 8000 [verified], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | 4 / unknown |
| groq / openai/gpt-oss-120b | Quality-critical · larger GPT-OSS candidate | 10 × 1 | 10 | 40 | 1600 + 5120 | 8520 + 20480 | organization_model. rpm unknown [unknown], tpm 8000 [verified], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | 4 / unknown |
| cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 | Quality-critical · Qwen candidate with Neuron quota | 10 × 1 | 10 | 40 | 1710 + 5120 | 8960 + 20480 | account_neurons. rpm 300 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day 10000 [verified], free_requests_per_day unknown [unknown] | 1 / 1 |
| openrouter / google/gemma-4-31b-it:free | Utility · named Gemma free variant | 10 × 1 | 10 | 40 | 1600 + 5120 | 8520 + 20480 | account. rpm 20 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day 50 [estimated] | 2 / 1 |
| **Wave total** |  | 40 | 40 | 160 | 6510 + 20480 | 34520 + 81920 | Per-model caps and quota scopes apply |  |

- groq / openai/gpt-oss-20b plan SHA-256 `3769e896378e62d66e9e261fa7bf740f8c947e323d9b577ab808b29cc525d345`
- groq / openai/gpt-oss-20b unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], limits.rpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- groq / openai/gpt-oss-120b plan SHA-256 `3acbef3a22441ca6d92df503ff6c9b7d032d25477f724348085c4cef867454e7`
- groq / openai/gpt-oss-120b unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], limits.rpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 plan SHA-256 `23ce02128209ce186d647c18a57c0ff0d44cc43bf8917611ffc40b0832b7caca`
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [estimated], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 estimated Neurons at cap 680
- openrouter / google/gemma-4-31b-it:free plan SHA-256 `fb46579f8ad53850226913cfa881baa49bc608ace71ad95fd7d1b41a4c249f61`
- openrouter / google/gemma-4-31b-it:free unverified fields: max_output_tokens [unknown], limits.rpm [estimated], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [estimated]. Confirm current quota and usage.
- openrouter / google/gemma-4-31b-it:free: catalog snapshot; free variants can disappear — re-check before each live run.

## Wave 2 — after M9 finishes and the owner confirms Gemini quota

Cases in execution order: `event_extraction-01`, `disambiguation-04`, `causal_relation-07`, `event_ordering-04`, `hallucination_detection-07`, `spoiler_detection-01`, `narrative_plan-02`, `vietnamese_script-03`, `script_correction-07`, `structured_output-01`

One run per model. Reserve 24 requests before every case. The run can stop early when the remaining cap cannot cover that reserve.
Token estimates use input plus reserved output. At the cap, use the largest case estimate for every request as a conservative planning figure. Quota windows are lower bounds from known limits only. Allow for shared quota, retry bursts and actual provider counters.

**Shared-quota check.** No other pipeline may use the same provider during this wave. M9 uses Gemini only.

| Provider / model | Screening tier and reason | Cases × runs | Base requests | Request cap | Est. input + output (base) | Est. input + output (at cap) | Quota scope and limits | Min / days ≥ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| gemini / gemini-3.5-flash-lite | Utility · Flash-Lite candidate | 10 × 1 | 10 | 40 | 1600 + 5120 | 8520 + 20480 | project_model. rpm unknown [unknown], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | unknown / unknown |
| gemini / gemini-3.6-flash | Quality-critical · Flash candidate on the M9 provider | 10 × 1 | 10 | 40 | 1600 + 5120 | 8520 + 20480 | project_model. rpm unknown [unknown], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | unknown / unknown |
| **Wave total** |  | 20 | 20 | 80 | 3200 + 10240 | 17040 + 40960 | Per-model caps and quota scopes apply |  |

- gemini / gemini-3.5-flash-lite plan SHA-256 `5679972d5796e261fde79aca27ffc4ba01d6025aecb4f7da87d246088a5b8eaf`
- gemini / gemini-3.5-flash-lite unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [unknown], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- gemini / gemini-3.6-flash plan SHA-256 `9f506c57de983d94b672a253a3ba4943517c887f71cafb242965b2fdcbe68fb5`
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
