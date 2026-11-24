# Phase 7B · First screening round

The six candidates span all four providers and both routing tiers. The tiers describe
the intended screening roles. The same ten DEV cases cover all ten task groups and
all three difficulties, with eight deterministic golds and two human rubrics. Each
candidate gets one run with a 512-token output reserve per case. The owner reviews
all ten golds or rubrics before authorizing the screening.

```powershell
python -m tools.model_bench.run --screening --dry-run --plan-md
```

The generated sample below is illustrative. Regenerate it at the revision being
approved, and use its per-model fingerprints in the owner plan.

<!-- BEGIN GENERATED SCREENING SAMPLE -->

## Owner approval table

Cases in execution order: `event_extraction-01`, `disambiguation-04`, `causal_relation-07`, `event_ordering-04`, `hallucination_detection-07`, `spoiler_detection-01`, `narrative_plan-02`, `vietnamese_script-03`, `script_correction-07`, `structured_output-01`

One run per model. Reserve 24 requests before every case. The run can stop early when the remaining cap cannot cover that reserve.
Token estimates use input plus reserved output. At the cap, use the largest case estimate for every request as a conservative planning figure. Quota windows are lower bounds from known limits only. Allow for shared quota, retry bursts and actual provider counters.
Schedule Gemini after M9 finishes. Stability repeats follow screening.

| Provider / model | Screening tier and reason | Cases × runs | Base requests | Request cap | Est. input + output (base) | Est. tokens at cap | Quota scope and limits | Min / days ≥ |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| gemini / gemini-3.5-flash-lite | Utility · Flash-Lite candidate | 10 × 1 | 10 | 40 | 1582 + 5120 | 29000 | project_model. rpm unknown [unknown], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | unknown / unknown |
| gemini / gemini-3.8-flash | Quality-critical · Flash candidate on the M9 provider | 10 × 1 | 10 | 40 | 1582 + 5120 | 29000 | project_model. rpm unknown [unknown], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | unknown / unknown |
| groq / openai/gpt-oss-20b | Utility · same model family across Groq and OpenRouter | 10 × 1 | 10 | 40 | 1582 + 5120 | 29000 | organization_model. rpm unknown [unknown], tpm 8000 [verified], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | 4 / unknown |
| groq / openai/gpt-oss-120b | Quality-critical · second GPT-OSS size on Groq | 10 × 1 | 10 | 40 | 1582 + 5120 | 29000 | organization_model. rpm unknown [unknown], tpm 8000 [verified], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day unknown [unknown] | 4 / unknown |
| openrouter / openai/gpt-oss-20b:free | Utility · pinned free variant, availability unverified | 10 × 1 | 10 | 40 | 1582 + 5120 | 29000 | account. rpm 20 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day unknown [unknown], free_requests_per_day 50 [estimated] | 2 / 1 |
| cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 | Quality-critical · different family and Neuron quota | 10 × 1 | 10 | 40 | 1692 + 5120 | 29440 | account_neurons. rpm 300 [estimated], tpm unknown [unknown], rpd unknown [unknown], tpd unknown [unknown], neurons_per_day 10000 [verified], free_requests_per_day unknown [unknown] | 1 / 1 |

- gemini / gemini-3.5-flash-lite plan SHA-256 `4b8a5f5933682424f2af33d96ceaf08270c4e96b460a79a1016307029a2cef7a`
- gemini / gemini-3.8-flash plan SHA-256 `254113764fd4447c150fe7cae20c4b97c70ffe43d7bec6ca709c45615266712d`
- groq / openai/gpt-oss-20b plan SHA-256 `51b3b99751316d673d50523cba56b22cf418955dc524c62807081c430e2ca792`
- groq / openai/gpt-oss-120b plan SHA-256 `aaa78f24e41de7a2ff80563a0b33b7c34ca212d481b089ae1a9ee6e39fb105b1`
- openrouter / openai/gpt-oss-20b:free plan SHA-256 `2427097e7866e3076f7b839d0331331d7a15c18772e482a57c24dcfc7ce9840b`
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 plan SHA-256 `b70b318debbfd33566f1dcee436a44c674a7b0f8ca47c5b89a1fbca9dfefdbb6`
- cloudflare / @cf/qwen/qwen3-30b-a3b-fp8 estimated Neurons at cap 680

<!-- END GENERATED SCREENING SAMPLE -->

The 40-request cap leaves retry headroom above the ten base requests and fits the
repository's estimated OpenRouter daily quota of 50 if the account has enough free
capacity. With a 24-request reserve per case, more than seven retries before the last
case may cut screening short. The table estimates tokens against the coded Groq TPM
limit, OpenRouter's account request limits, and Cloudflare's request and Neuron limits.
Unknown limits require owner confirmation. Confirm the availability of the named
OpenRouter free variant in the approved window.

Schedule Gemini only after M9 finishes. For live Gemini, point `--seasons-dir` at the
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
