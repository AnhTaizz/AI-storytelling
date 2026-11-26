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

## Wave 1 availability review · 2026-11-25

The four pinned entries retain a planning budget of 40 base requests and a maximum of 160. The following provider publications supplement the generated registry estimates. Current account entitlement, remaining quota and serving capacity still need confirmation immediately before an approved run.

- Groq lists both GPT-OSS models under free plan limits of 30 requests/minute, 1,000 requests/day, 8,000 tokens/minute and 200,000 tokens/day per model. Confirm the organization is on the free plan. [Groq limits](https://console.groq.com/docs/rate-limits)
- **Cloudflare uses GLM-4.7-Flash.** The current model card lists the pinned ID, 131,072 context tokens and reasoning support. The price table lists 5,500 Neurons per million input tokens and 36,400 per million output tokens. Workers Free includes 10,000 Neurons/day per account and the published text-generation limit is 300 RPM. The repo allows the exact model and applies a local 9,000-Neuron ceiling. Confirm the account is on Workers Free, its usage and its available quota before dispatch. Catalog status was verified without inference. [Model card](https://developers.cloudflare.com/workers-ai/models/glm-4.7-flash/) · [Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/) · [Workers AI limits](https://developers.cloudflare.com/workers-ai/platform/limits/)
- OpenRouter lists the pinned Gemma free variant with zero input and output price. Accounts with fewer than 10 credits purchased have limits of 20 requests/minute and 50 free-model requests/day. Check the remaining daily count against the approved budget and recheck the named free variant at dispatch. [Gemma model card](https://openrouter.ai/google/gemma-4-31b-it:free) · [Free-model limits](https://openrouter.ai/docs/api_reference/limits.md)

<!-- BEGIN GENERATED SCREENING SAMPLE -->

Revision at generation: `1ac73e400c2e4d0b47055a03cfd0856176833fd5`

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
| cloudflare / @cf/zai-org/glm-4.7-flash | Quality-critical · GLM candidate with Neuron quota | 10 × 1 | 10 | 40 | 1710 + 5120 | 8960 + 20480 | account_neurons. rpm 300 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day 10000 [verified], free_requests_per_day unknown [unknown] | 1 / 1 |
| openrouter / google/gemma-4-31b-it:free | Utility · named Gemma free variant | 10 × 1 | 10 | 40 | 1600 + 5120 | 8520 + 20480 | account. rpm 20 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day 50 [estimated] | 2 / 1 |
| **Wave total** |  | 40 | 40 | 160 | 6510 + 20480 | 34520 + 81920 | Per-model caps and quota scopes apply |  |

- groq / openai/gpt-oss-20b plan SHA-256 `af8e3d3b277b71397016de3270102593919296adbc4fb1203b9a981add8c09b7`
- groq / openai/gpt-oss-20b unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], limits.rpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- groq / openai/gpt-oss-120b plan SHA-256 `d774ce7118bbdcca0db6f0589674c10ecbbdff66129c547e879fd6c155876613`
- groq / openai/gpt-oss-120b unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], limits.rpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- cloudflare / @cf/zai-org/glm-4.7-flash plan SHA-256 `8ad08999b0f525c8ed46c66a278815ee8088a44a9d738afbdd6eeed875cea616`
- cloudflare / @cf/zai-org/glm-4.7-flash unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [estimated], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- cloudflare / @cf/zai-org/glm-4.7-flash estimated Neurons at cap 800
- openrouter / google/gemma-4-31b-it:free plan SHA-256 `8286a7d9d4a6a0fb3721237cac2d5a0f7b59382a41f317958a390c6444aba998`
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

- gemini / gemini-3.5-flash-lite plan SHA-256 `99b19e471d5ccc86a6b44e118ab7171c009e52702a2aaa247f2053799755deee`
- gemini / gemini-3.5-flash-lite unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [unknown], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.
- gemini / gemini-3.6-flash plan SHA-256 `0935a19dc69a5d7afe5b9bd9abc91cdd9683b6bf485736d7eb82df38188461f1`
- gemini / gemini-3.6-flash unverified fields: context_tokens [unknown], max_output_tokens [unknown], structured_output [unknown], reasoning [unknown], limits.rpm [unknown], limits.tpm [unknown], limits.rpd [unknown], limits.tpd [unknown], limits.neurons_per_day [unknown], limits.free_requests_per_day [unknown]. Confirm current quota and usage.

<!-- END GENERATED SCREENING SAMPLE -->

Wave 1 uses the screening runner and one shared owner plan with four caps of 40.
Use the first scored case for each model as its smoke check. Its dispatch and all
its retries count in that model's cap and in the 160-request wave ceiling. A
separate provider smoke command would bypass the benchmark ledger and is outside
this plan. Public catalog lookups are metadata reads. The 40-request cap leaves
retry headroom above the ten base requests and fits the
repository's estimated OpenRouter daily quota of 50 if the account has enough free
capacity. With a 24-request reserve per case, more than seven retries before the last
case may cut screening short. The table estimates tokens against the coded Groq TPM
limit, OpenRouter's account request limits, and Cloudflare's request and Neuron limits.
Unknown limits require owner confirmation. The owner's 2026-11-24 catalog
snapshot recorded 262,144 context tokens, zero prompt and completion prices, and
support for `response_format` and `reasoning` for the named Gemma free variant.
The registry records native JSON mode and no structured-output support.
Re-check free variant availability before each live run.

### Proposed routing cleanup

Remove `@cf/qwen/qwen3-30b-a3b-fp8` and `@cf/meta/llama-3.1-8b-instruct-fp8`
from the active Workers Free allowlist and matching registry in a separate owner
decision. Both exact IDs were retired on November 20 and return HTTP 410 per the
provider notice. Replace the Qwen default fallback with GLM-4.7-Flash, update the
dashboard fallback display and routing guide, and test explicit legacy selections
with a clear configuration failure. Keep historical configuration records as
evidence. The May notice explicitly retained the Llama 3.3 70B FP8 Fast variant.
The pin change in this PR only affects the screening plan. [November notice](https://developers.cloudflare.com/changelog/post/2026-11-05-planned-model-deprecations/) · [May notice](https://developers.cloudflare.com/changelog/post/2026-05-08-planned-model-deprecations/)

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
