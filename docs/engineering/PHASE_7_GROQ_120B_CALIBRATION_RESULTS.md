# Phase 7 · Groq GPT-OSS 120B calibration

Live run on 26 November 2026 (Asia/Bangkok), using Groq Free and synthetic DEV inputs. Four calibration dispatches recovered usable JSON on all three shared Wave 1 failures. The separate first-case Brief probe returned a complete JSON object and cleared the existing hard validators. The paired C0–C3 pilot awaits owner approval.

## Wave 1 calibration

The historical comparator is the `244ed20` Wave 1 run at 512 tokens. Its checkpoints and reports were preserved separately. Calibration ran at `4dc3b1a` with the same approved dataset, system message, user prompt, case order, temperature `0`, Groq endpoint and model. The three native JSON requests changed only `max_tokens` from 512 to 1,024. The follow-on for the remaining format failure changed only `response_format` from `json_object` to `json_schema` with `strict: true` at 1,024 tokens. The dàn ý schema required the original `answer` string and disallowed extra keys. It included no example answers or gold content. Each configuration/case pair had one dispatch and zero retries.

| Case and configuration | HTTP / finish reason | JSON | Factual accuracy | Input / completion / reasoning / total tokens | Latency |
| --- | --- | --- | --- | --- | --- |
| `narrative_plan-02`, baseline 512 | 400 `json_validate_failed` / unknown | Rejected | Unknown | Unknown | 2.725 s |
| `vietnamese_script-03`, baseline 512 | 400 `json_validate_failed` / unknown | Rejected | Unknown | Unknown | 2.653 s |
| `script_correction-07`, baseline 512 | 400 `json_validate_failed` / unknown | Rejected | Unknown | Unknown | 2.982 s |
| `narrative_plan-02`, native 1,024 | 400 `json_validate_failed` / unknown | Rejected | Unknown | Unknown | 2.726 s |
| `vietnamese_script-03`, native 1,024 | 200 / `stop` | Valid | 1/2 on factual fidelity, provisional | 255 / 901 / 737 / 1,156 | 2.600 s |
| `script_correction-07`, native 1,024 | 200 / `stop` | Valid | 1.0 exact match | 219 / 794 / 771 / 1,013 | 2.403 s |
| `narrative_plan-02`, strict 1,024 | 200 / `stop` | Valid | 2/2 on factual fidelity, provisional | 277 / 566 / 485 / 843 | 2.169 s |

All three successful completions exposed Groq's separate reasoning field and reasoning-token count. Reasoning tokens are included in the completion count. The failed 1,024-token case exposed a `failed_generation` field with no finish reason or usage. The results support a cap effect on two cases and a format effect on the narrative plan in this sample. The data cannot establish truncation as the cause of the HTTP 400s or estimate repeatability from one observation per configuration. Baseline latency is runner wall time. Calibration latency is measured around the HTTP request.

Groq documents `max_completion_tokens` as the current field and `max_tokens` as deprecated. The run retained the historical field to isolate the cap change. The API supports `low`, `medium` and `high` for GPT-OSS 120B and defaults to `medium`. `reasoning_effort` remained omitted in every request. Strict mode uses constrained decoding and requires all object properties to be required and `additionalProperties: false`. [Groq API reference](https://console.groq.com/docs/api-reference) · [Reasoning](https://console.groq.com/docs/reasoning) · [Structured Outputs](https://console.groq.com/docs/structured-outputs)

### Provisional rubric review

The assistant scored the text against the source, using each original criterion on its 0–2 scale. Owner grades and notes remain pending in the private review packet.

| Case | Criterion scores in rubric order | Evidence |
| --- | --- | --- |
| `narrative_plan-02` | **2 / 2 / 1 = 5/6** | The three beats preserve the wrong pocket, the ink clue and map recovery before departure. The transition links discovery to recovery. It uses the clue but gives it little suspense. |
| `vietnamese_script-03` | **1 / 1 / 1 = 3/6** | The opening uses the lit storefront, and the script has 109 whitespace-delimited words. It switches Phúc to a first-person narrator, adds details about tea, a smile and dialogue, and treats bà Sáu's later arrival as evidence against the idea she had gotten up early. The source establishes her later arrival and leaves her wake-up time unknown. The closing moral weakens the spoken pacing. |

The shared Wave 1 ledger moved from 23 to 27 of 160 total dispatches. GPT-OSS 120B moved from 10 to 14 of 40, leaving 26 for that model and 133 for Wave 1 overall. The calibration used 4 of its separate 6-dispatch maximum. Groq reported the Free-plan ceilings of 1,000 RPD and 8,000 TPM throughout, with no HTTP 429 or `Retry-After`. [Groq rate-limit counters](https://console.groq.com/docs/rate-limits)

## Brief Repair V2 first-case probe

The first ordered case, `lighthouse_clean`, starts with a valid frozen Brief, so C0 itself would make zero repair calls. The capacity probe used the existing full Brief generation prompt on that case's Japanese source at temperature `0`, native JSON mode and a 3,072-token cap. The frozen starting Brief stays the input for all four arms. This probe used **1/64** pilot dispatches and exercised full-object generation. C0 repair behavior awaits the paired pilot.

| HTTP / finish reason | JSON | Hard errors | Soft warnings | Input / completion / reasoning / total tokens | Latency |
| --- | --- | ---: | ---: | --- | --- |
| 200 / `stop` | Complete | 0 | 2 | 2,930 / 1,260 / 695 / 4,190 | 3.451 s |

The two warnings were untranslated Japanese in event location fields. The exact synthetic oracle recorded 0/2 event matches and 0/2 evidence matches because it first requires equality across event fields, including summary and location. Direct source inspection found both actions in order with the correct actor, certainty, exact quotes and passage IDs. The output also narrowed *nautical chart* to *lighthouse map* and treated the map as the second event's location. Owner review of these semantic differences is pending. [Exact fixture scorer](../../tools/story_benchmark/brief_repair_v2.py)

The private approval draft pins GPT-OSS 120B, the candidate commit, held-back dataset and per-case hashes, native JSON mode, temperature `0`, the existing validator sequence, a 4,500 estimated-input guard and a 3,072 completion cap. The remaining **63 dispatches** are shared across the paired arms, with up to two model repair opportunities per arm and case. The clean control retains its zero-call behavior. Run in a separate Groq quota window and record incomplete pairs if the dispatch ceiling or quota stops the run. [Brief Repair V2 protocol](BRIEF_REPAIR_V2_EXPERIMENT.md)

M9 r2 stayed paused. The five live calls all used the same Groq Free organization. Gemma remained on hold and Cloudflare needed no additional access for this run.
