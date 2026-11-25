# Source Check context experiment on independent DEV data

Proposed Phase 7C-2 experiment. The 95.5% historical character-window overlap motivates measuring repeated source delivery. Provider token usage, billed cached input, quality and latency require separate observations.

## Current behaviour

The checker sends the complete in-scope source with each group of fresh paragraphs. It already carries unchanged paragraphs across revisions. With the default group size of four, critic flags follow their paragraphs. The implementation records an earlier example where a whole-script check found two defects and four-paragraph checks found seven. Larger groups therefore need a paired quality comparison. See [orchestration](../../tools/story_pipeline/run_pipeline.py), [validators](../../tools/story_pipeline/stages.py) and [prompt](../../tools/story_pipeline/prompts/source_check_user.md).

## Offline packing example

Use this synthetic episode with LF separators and no trailing newline.

```text
[1.1] Mai saw an amber lamp.
[1.2] Minh heard it might be broken.
[1.3] At noon Lan replaced its bulb.
```

Use nine separate script paragraphs, in the order below. A critic flag targets U4, U5 and U9 individually. Gold is written before model comparison.

| Paragraph | Script claim | Expected source trace |
|---|---|---|
| U1 | Mai saw the lamp. | 1.1 |
| U2 | The lamp was amber. | 1.1 |
| U3 | Minh heard a report about the lamp. | 1.2 |
| U4 | Minh proved the lamp was broken. | Strengthened claim, 1.2 preserves uncertainty |
| U5 | Mai replaced its bulb. | Wrong actor, 1.3 |
| U6 | The bulb was replaced at noon. | 1.3 |
| U7 | Lan replaced the bulb. | 1.3 |
| U8 | Mai saw the lamp, and Lan replaced its bulb. | Both 1.1 and 1.3 |
| U9 | Lan bought a spare lamp. | Unsupported across the full in-scope source |

| Variant | Group sizes | Calls before retries | Source characters in request bodies | Source IDs available per group |
|---|---|---:|---:|---|
| S0 default | 4, 4, 1 | 3 | 306 | All three |
| S1 stable cacheable prefix | 4, 4, 1 | 3 | 306 | All three |
| S2 larger chunks | 8, 1 | 2 | 204 | All three |

These counts follow directly from the 102-character rendered source and group boundaries. They exclude instructions, outputs and repair. S2 removes one dispatch and one source copy in this example. This is a packing result. Model defect recall, citation accuracy, token savings and cache hits have not been measured. S1 leaves the full source in each body and places stable system/schema/scope/source content before variable units and flags. Reuse an explicit provider prefix only when supported on the approved free route. Keep unit/flag text outside the reusable part.

## First live measurement to propose

Run S0 and S1 in order using the same three groups, citations, schema, decoding settings and account. The current prompt already puts the source before the changing paragraphs. Treat S1 as a warm repetition of those unchanged payloads and record cache counters on both passes. A baseline request can already hit. Use a fresh DEV source for an independent cold pass and require a reported zero before labeling it cold. Hash the serialized stable prefix for each request. Log actual dispatch time and keep the warm pass within the documented cache lifetime.

Groq documents automatic prefix caching for both named GPT-OSS candidates and reports the served count in `usage.prompt_tokens_details.cached_tokens`. Select a route after Wave 1 and confirm that it exposes the original usage payload and serves the prefix length. If the counter is missing, record unknown. If all measured counters are zero, report zero hits for this fixture and retain the default grouping. Compute hit frequency over requests with a reported count, and cached-input share as the sum of cached tokens divided by the sum of input tokens on those same requests. Attach the per-request counters to the exact unit/flag and passage mapping. The other Wave 1 routes need evidence of cache support and counters for their exact free model before use in this test. [Groq prompt caching](https://console.groq.com/docs/prompt-caching)

The proposed S0/S1 smoke comparison uses six dispatches with automatic retry disabled. Charge cold requests used to prime the cache. Set an estimated input ceiling of 2,048 per dispatch and reserve 2,048 output tokens, giving planning totals of 12,288 input and 12,288 reserved output. Verify the rendered payload and model limits before approval. Keep this budget separate from Wave 1 and Brief Repair. S2 requires a completed baseline and a separately reviewed budget.

## Paired comparison and rejection conditions

- Fix source bytes, cutoff, model pin, prompt/schema, temperature, output reserve and samples. Log run, revision, ordered unit IDs, per-unit content hash, flag-to-unit mapping, source ID-to-text hashes, chunk ID and passage citations. Cache identity also includes provider/model, prompt/schema and ordering. An altered cutoff, source, paraphrased unit or changed dependencies must invalidate affected reuse.
- Score all nine paragraphs and all three flags against the frozen synthetic gold. Check each unit and flag appears exactly once per sample, every cited ID is in scope, every quote belongs to its unit, and every required evidence group is present. U8 needs both passages. For U9, record unsupported with search scope and adjudication; do not invent a supporting citation. Validate before merging results across chunks. Partial, duplicate or missing chunks leave the sample incomplete.
- Compare defect recall on U4/U5/U9, false positives on the six supported units, and per-finding passage correctness. A structurally valid passage ID can cite unrelated text. Have a blinded reviewer adjudicate semantic matches. Include boundary permutations of the same nine units and paired cold/warm runs to separate group position and caching effects. Additional cases must be synthetic DEV with predeclared gold, independent of chapters 6-17.
- Report logical checks, actual HTTP attempts, usage by input/output/reasoning, reported cache-read/write tokens, cost eligibility, wall latency including retries and per-attempt latency when observable. Mark unavailable fields unknown. A warm request alone does not establish a cache hit.
- Reject adoption if any additional critical defect is missed, required evidence coverage or traceability drops, or a failure is silently treated as a clean check. Record paired outcomes and uncertainty across DEV cases before proposing a default. Prefer S1 first since group membership and complete evidence can be held fixed. An unchanged semantic result on the toy case alone does not justify S2.
- Require the S1 pass to preserve baseline detections and the exact required evidence groups. A larger S2 group must satisfy the same checks on boundary permutations. A single omitted gold defect or evidence group rejects the candidate for this fixture, regardless of cache or latency gains.

This preparation uses no provider calls. Any live experiment needs a separate owner-approved case list, route, free quota and budget. No M9 gate decision follows from these DEV comparisons.
