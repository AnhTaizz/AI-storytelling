# M4 P4 Output Contract Redesign V1

Status: **offline design and readiness only** (M4-04B4A). No provider call, no prediction, no dataset access. Nothing here has been tested against a model.

Record: `benchmarks/m4_extraction/M4_04B4A_P4_OUTPUT_CONTRACT_REDESIGN.yaml`.

## 1. Why P3 failed

The blind DEV3 run of P3 ended with 0 of 10 structurally valid cases. No draft reached the compiler. The forensics (M4-04B3HR) found one dominant cause, with high confidence.

The P3 prompt said that the "appended exact Draft V1.1 schema" was authoritative. The file it appended was the canonical Draft V1.1 schema. That file is a **delta**. It defines the root object and `Mention`. For every other record it points, by `$ref`, at the Draft V1 schema. The Draft V1 schema was not in the prompt.

So the model was never shown the definitions of `Assertion`, `Evidence`, `EvidenceRole`, `Entity`, `Event`, `TemporalAnchor` or `Proposition`. Field names such as `proposition_handle` and `anchor_handle` appeared nowhere in what it received. Every one of the 1,028 schema errors fell in those missing definitions. None fell in the parts the prompt did contain.

Two secondary findings:

- JSON MIME mode alone still produced malformed JSON in 3 of 20 responses.
- The repair diagnostic carried only phase, code and path. It never said which rule was broken.

This means P3 measured prompt packaging. It did not measure extraction quality, which remains unknown.

## 2. Two contracts, kept apart

P4 separates two things that P3 treated as one.

| Contract | What it is | Changed in P4? |
|---|---|---|
| Canonical draft contract | `STORY_EXTRACTION_DRAFT_V1_1`: the two schema files and the validator the compiler uses | No |
| Model-facing output contract | What the model is shown and constrained by | Yes |

The canonical schemas are written for a validator. A validator resolves `$ref` across files. A model cannot. The model-facing contract is the same rules, laid out so that nothing has to be resolved.

## 3. Why P4 does not change story semantics

- The canonical Draft V1 and Draft V1.1 schema files are unchanged.
- The V1.1 compiler and the predicate registry are unchanged.
- The model-facing schema adds no rule and removes none. Section 4 shows how that is checked.
- The P4 preamble keeps every semantic instruction of P3. It differs in four passages, all about how the schema is described.

P4 is a better presentation of Draft V1.1. It is not Draft V1.2.

## 4. How the self-contained schema is built

Identity: `STORY_EXTRACTION_DRAFT_V1_1_MODEL_SCHEMA_V1`.

Tool: `tools/story_extraction/materialize_draft_v1_1_model_schema_v1.py`. Tracked output: `schemas/story_extraction/story_extraction_draft_v1_1_model_schema_v1.schema.json`.

The materializer does three things:

1. It takes the root object and `Mention` from the Draft V1.1 file.
2. It copies into one local `$defs` namespace every Draft V1 definition that those reach, directly or indirectly. There are 16. The one Draft V1 definition left out is V1's own `Mention`, which nothing else references and which V1.1 replaces.
3. It rewrites each external reference to a local one.

The result has 17 definitions and 30 references. None leaves the document.

**It cannot drift.** The tracked file is never edited. Loading it fails unless it equals the materializer's output byte for byte.

**It is equivalent, in two independent ways.**

- *By construction.* Each copied definition is compared to its Draft V1 original and must be identical. The root and `Mention` must equal the Draft V1.1 originals with only the reference targets relocated. Any relaxation, such as dropping a required field or widening an enum, fails this check.
- *By behaviour.* The canonical validator and the model schema are run on the same drafts and must return identical findings, including the findings inside every `oneOf` variant. The corpus is 27 valid drafts, every enum token in place, 27 targeted rule violations, and single-edit mutants of valid drafts. The full set of 13,518 mutants of four base drafts was run once with no mismatch. The test suite checks a deterministic sample of them; `M4_FULL_EQUIVALENCE_CORPUS=1` re-runs the full set.

`Mention` keeps the V1.1 definition, which has no `evidence_handle`.

## 5. The coverage gate

A gate now checks the prompt before any request can exist.

It lists every structural rule the validator enforces: 318 of them, covering required fields, allowed fields, enum tokens, types and collection shapes, handle patterns, constants, bounds, conditional rules and `oneOf` variants. For each rule it asks how the model receives it:

- `MODEL_SCHEMA`: the rule is in the schema object that is really inside the prompt.
- `EXPLICIT_PROMPT_TEXT`: the rule is spelled out in the preamble.
- `REQUIRED_BY_VALIDATOR_BUT_UNAVAILABLE_TO_MODEL`: neither. This result is forbidden.

The gate reads the schema out of the assembled prompt. It does not trust a claim that a schema is present.

| Prompt | Unavailable rules | External references |
|---|---|---|
| P4 | 0 of 318 | 0 |
| P3, same gate | 214 of 318 | 7 |

The gate would have stopped P3 before any API call.

Against the published P3 blocker inventory: 16 requirement families were involved. All 16 were unavailable to the model in P3. None is unavailable in P4. This is a statement about whether the rules are visible. It is not a prediction of what a model will output.

## 6. Structured-output decision

**Decision: `NATIVE_SCHEMA_CONSTRAINT_SUPPORTED_OFFLINE`.**

Found by inspecting the installed SDK (`google-genai` 2.27.0), with no client and no call:

- `GenerateContentConfig` has a `response_json_schema` field that takes a JSON Schema. Its wire name is `responseJsonSchema`.
- The accepted transport passes the generation settings through unchanged, so no runtime change is needed to carry it.

P4 binds **one** schema object to both places: the prompt text and the provider's native parameter. Both come from the tracked model schema. There is no second copy to edit.

**Native enforcement would be partial.** The SDK documents a supported keyword subset. The model schema uses these keywords that are not in it:

`const`, `pattern`, `minLength`, `maxLength`, `minProperties`, `uniqueItems`, `if`, `then`, `else`, `not` (and the `$schema` annotation).

So handle patterns, constant discriminators such as the argument `kind`, length bounds, uniqueness and the conditional rule on temporal anchors would not be enforced by the provider. The local validator stays authoritative. The schema has no cyclic reference and no `$ref` with sibling keywords, which are two further restrictions the SDK documents.

## 7. Repair diagnostic V2

Identity: `M4_P4_STRUCTURAL_REPAIR_DIAGNOSTIC_V2`. The limit stays at one repair per case.

Each finding gives the path and names the broken rule:

| Rule broken | What the finding adds |
|---|---|
| `required` | `missing_required_fields` |
| `additionalProperties` | `allowed_fields` and a count of unexpected fields |
| `enum` | `allowed_enum_tokens` |
| `type` | `expected_type` |
| `const` | `required_constant` |
| `pattern` | `required_pattern` |
| length or size bound | `limit` |
| conditional (`not`) | `forbidden_fields` |
| `oneOf` | each variant's required fields, allowed fields and fixed values, plus why that variant did not match |
| JSON syntax | an error class with line and column |

**It is structural only, by construction.** Every string in a finding comes from the schema side of a validator error: a field name, an enum token, a type, a pattern. The response's own values are used only for membership tests and counts. They are never copied.

Two deliberate choices follow from that:

- Unexpected field names are counted, not echoed. A key is model-written text.
- A path element that is not a schema field or a registry argument name is shown as `<UNRECOGNIZED_KEY>`.

A test feeds the sanitizer several hundred arbitrary outputs with marker text in every value and key. No marker ever appears in a diagnostic, and every string in every diagnostic belongs to the schema vocabulary.

JSON error classes: `EMPTY_RESPONSE`, `NON_JSON_PREFIX_SUFFIX`, `UNTERMINATED_JSON`, `INVALID_PROPERTY_NAME`, `INVALID_ESCAPE`, `EXTRA_DATA`, `TRAILING_COMMA`, `OTHER_JSON_SYNTAX`. They are decided from punctuation and position, so they do not depend on the Python version's wording.

## 8. Data status

`DEV3_STATUS_FOR_P4 = TUNING_DATA_AFTER_P3_FAILURE`. DEV3 is no longer fresh validation data for P4. DEV3 gold stays sealed and was not opened. Fresh validation of P4 needs a later DEV4.

The P4 schema comes from the canonical contract. Nothing in it or in the prompts is derived from an individual DEV3 output, and no prompt names a dataset or a case.

## 9. What remains untested

- **Any model behaviour.** Whether a model given the complete schema produces valid drafts is unknown.
- **The native schema parameter on the provider side.** Only the local SDK path was checked. Whether the service accepts this schema, how it treats the keywords outside its documented subset, and whether the chosen model supports the parameter are all unverified.
- **Whether repair diagnostic V2 helps.** It is more informative and provably structural. Its effect on a model's second attempt is unmeasured.
- **Extraction quality.** Still unknown. P3 never reached the compiler.
- **Runtime binding.** P4 has an identity, `P4_STORY_EXTRACTION_DRAFT_V1_1_SELF_CONTAINED_V1`, but no model, credential slot or runner is bound. That needs a later protocol lock.
