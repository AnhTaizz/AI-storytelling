# M4 Gemini API Runtime V1

Status: **PREPARED / WAITING FOR USER CREDENTIALS**

Task: `M4-04A-GEMINI-API-TRANSPORT-AND-KEY-POOL-PREP`

## Scope and protocol change

The earlier local `qwen2.5:1.5b-instruct` / Ollama experiment was stopped because
laptop inference was too slow and thermally undesirable. It happened before extractor
lock, holdout input access, prediction generation, or gold access and is classified
`ABORTED_EXPLORATORY_PRESELECTION`. It is not an official baseline candidate.

M4 extraction will use Python orchestration and the hosted Google Gemini API. The local
machine remains responsible for request construction, hashing, parsing, schema and
canonical validation, evaluation, and artifact management. M4-04A makes no API call,
does not discover models, and does not select or lock an extractor.

## Architecture

The prepared path is:

```text
Python orchestration
  -> GEMINI_TRANSPORT_V1
  -> Google Gemini API structured JSON response mode
  -> raw response content
  -> local JSON parsing
  -> STORY_EXTRACTION_BATCH/v0 validation
  -> canonical_story/v0 structural and semantic validation
  -> frozen M4 evaluator snapshot
```

`gemini_transport_v1.py` isolates the official `google-genai` SDK. SDK import and client
construction are lazy, so importing the module or running `--check-config` cannot make a
provider request. The SDK's own retry count is set to one; `GEMINI_TRANSPORT_V1` owns the
explicit, testable retry policy. Provider JSON mode is a syntax aid only. Local M4
validators are authoritative.

The request interface is:

```python
generate(system_instruction, user_content, model, generation_config, request_id)
```

It returns request id, provider, requested and reported model identity when available,
slot id, project label, UTC start/end time, latency, allow-listed usage and provider
metadata, raw content, and sanitized attempt records. It never returns a credential.

## Secret handling and `.env` workflow

`.env` and `.env.*` are ignored; the blank `.env.example` is the only exception. The
owner creates or replaces `.env` locally after M4-04A with newly rotated credentials.
Credentials from chat, logs, shell history, attachments, or old documents are not
authorized and must not be recovered or reused.

The minimal loader reads only numbered `GEMINI_API_KEY_N`, matching
`GEMINI_PROJECT_LABEL_N`, and `GEMINI_MODEL`. Process environment values take precedence
over the local file. Secret values exist only in private in-memory fields. Their values,
hashes, prefixes, and suffixes are excluded from public metadata, results, exception
messages, and representations. Duplicate secret values fail with a generic sanitized
configuration error. Known credential values are redacted defensively from response
content and metadata before a result is returned.

## Credential slots and project groups

Each credential has a stable local slot id such as `gemini_slot_1`; only the slot id and
project label identify it publicly. `GEMINI_KEY_POOL_V1` groups slots with the same
non-empty project label because several keys may share one quota boundary.

An omitted label is exposed as `PROJECT_GROUP_UNKNOWN`. Each unlabeled slot is scheduled
as its own unknown group so the runtime does not invent a shared quota relationship;
this is not a claim that their quotas are independent. Supplying accurate labels is the
owner's responsibility.

Scheduling is deterministic round robin across available groups and, separately, across
available slots inside a group. It is never random.

## Failure behavior

- **429 / resource exhaustion:** provider `Retry-After` is used when exposed; otherwise
  bounded exponential delay is used. The whole project group enters cooldown, so the
  pool does not immediately hammer other keys from the same project. An available,
  independently labelled group may receive the same semantic request.
- **Authentication:** only the affected slot is disabled. Credential text is not placed
  in the error. If no slot remains, the transport fails closed.
- **5xx, timeout, or network failure:** the exact same semantic request may be retried
  with bounded exponential backoff. The preparatory default is at most two retries
  (three attempts); M4-04B must freeze the final value.
- **Other provider failures:** fail closed without retry.

There is no local-model, alternate-model, or silent provider fallback.

Transport retry is distinct from structural repair. A transport retry resends the same
semantic request after a delivery/provider failure. Invalid JSON or failed local batch
or canonical validation is returned unchanged by this adapter and causes no automatic
second model call. A future orchestration layer may perform the separately governed
maximum of one structural repair call.

## Prompt package

`tools/story_extraction/prompts/story_extraction_base_v1.txt` is a reusable contract
base, not a selected-model prompt. It binds `STORY_UNDERSTANDING_CORE_V0`, the batch and
canonical contracts, automated/unreviewed status, evidence roles, mention/entity and
name/identity distinctions, event occurrence, holder-relative truth, epistemic status,
state validity, causality discipline, context-only handling, and exact M3 provenance.
It contains no holdout content or model-specific few-shot examples.

## Safe configuration check

Run:

```powershell
python tools/story_extraction/gemini_transport_v1.py --check-config
```

The command reports only credential-slot count, project-group count, whether a model is
configured, and a status. It does not instantiate an SDK client, discover models, or
print keys. An absent `.env` reports `WAITING_FOR_USER_CREDENTIALS`.

## M4-04B gate and blindness

After the owner locally provisions newly rotated keys, M4-04B may safely inspect models
available to those credentials, select exact candidates, preregister the benchmark, and
lock the extractor before any holdout input access. M4-04B must not begin implicitly.

During M4-04A the sealed holdout input and gold archives remain unopened, no predictions
are produced, and the frozen evaluation snapshot is unchanged. Gold remains forbidden
until a prediction package is locked and hashed. No M5 work begins here.
