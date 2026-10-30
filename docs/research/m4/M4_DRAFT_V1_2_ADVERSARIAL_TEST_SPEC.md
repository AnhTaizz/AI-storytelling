# M4 Draft V1.2 — Synthetic Adversarial Test Specification

Status: `PROPOSED`. Task: M4-04B4B-R1.

This is a specification only. Tests are implemented with V1.2 in a later, separately authorized task. All source text is invented Japanese written for the test; no corpus, DEV or holdout text is used.

## Outcomes

| Outcome | Meaning |
|---|---|
| **VALID** | Compiles, and every span equals the intended span. A test asserts the exact span, not merely that compilation succeeded. |
| **INVALID** | Fails closed with the named blocker. |
| **EXPLICITLY UNRESOLVED** | The model declared the locator unresolved, or the compiler returned `LOCATOR_AMBIGUOUS`. No canonical record exists for it, and the count is reported. |

**Global rule:** a wrong source position is never VALID, however consistent its offsets, hashes and provenance are.

## Cases

Column V1.1 gives today's behaviour, where verified by `test_m4_04b4b_r1_silent_grounding_v1.py` or the M4-04B4B tests.

| ID | Source (invented) | Draft input | Expected V1.2 outcome | V1.1 today |
|---|---|---|---|---|
| ADV-01 | 真白は笑った。真白は窓を開けた。 | mention 真白, context_before 。, context_after は窓 | VALID: span = second 真白 | VALID only with occurrence 2 |
| ADV-02 | same | mention 真白, no context | INVALID `LOCATOR_AMBIGUOUS` | INVALID `AMBIGUOUS_QUOTE` |
| ADV-03 | same | context of the first occurrence, but meant for a claim about the second | VALID at the *first* span; caught only by gold (semantic SC1 residue, documented) | VALID silently (wrong occurrence) |
| ADV-04 | 「はい」 nine times in a row | middle はい with any context of 16 characters or less | INVALID `LOCATOR_AMBIGUOUS`, never VALID | VALID if any in-range occurrence is given |
| ADV-05 | same | model declares `REPEATED_IDENTICAL_CONTEXT` | EXPLICITLY UNRESOLVED; dependants omitted | not representable |
| ADV-06 | 真白は「はい」と答えた。遥も「はい」と答えた。 | evidence 「はい」, context_before 遥も, for a claim about 遥 | VALID at the second line | VALID only with occurrence 2; occurrence 1 silently cites 真白 (SC4) |
| ADV-07 | same | evidence 「はい」 with a context that matches neither occurrence | INVALID `LOCATOR_CONTEXT_MISMATCH` | n/a |
| ADV-08 | あははは、と真白は笑った。 | quote はは, context_before あ | VALID at offset 1, the first overlapping match | occurrence semantics diverge from intuition (SC2) |
| ADV-09 | 真白は笑った。（彼は誰だ） | mention 彼 with RefersTo to 真白, while the text leaves it open | VALID *position*; the link is semantic. Gold expects a placeholder or OPEN, so it is scored as an unsupported RefersTo, not caught structurally | same |
| ADV-10 | ……と言って、部屋を出た。 (omitted subject) | an event with an invented participant and no mention | VALID structurally; gold scores `UNSUPPORTED_ASSERTION`. The test asserts no mention or evidence is fabricated for the absent subject | same |
| ADV-11 | 真白さんと真白ちゃん | two mentions 真白さん and 真白ちゃん, no context needed | VALID, two distinct spans; aliasing is semantic | VALID |
| ADV-12 | 真白さん、真白さん。 | mention 真白さん, no context | INVALID `LOCATOR_AMBIGUOUS` | INVALID `AMBIGUOUS_QUOTE` |
| ADV-13 | 真白と真昼が来た。 | two candidate referents; RefersTo from 彼女 in the next passage | position VALID; link semantic; if not determined, the expected gold is a placeholder | same |
| ADV-14 | 真白は笑った。 | surface_form 真昼 supplied by the model | INVALID schema failure: `surface_form` is not a model field in V1.2. The compiler sets 真白 (G4). | VALID silently (SC5) |
| ADV-15 | 真白は笑った。 | quote 真昼 | INVALID `QUOTE_NOT_FOUND` | INVALID `QUOTE_NOT_FOUND` |
| ADV-16 | ｜真白《ましろ》は笑った。 | quote 真白は笑った (ruby dropped) | INVALID `QUOTE_NOT_FOUND` | INVALID (verified) |
| ADV-17 | same | quote 真白《ましろ》 | VALID, exact span including ruby markup | VALID |
| ADV-18 | NFD source 真白が笑った。 | NFC quote が笑った | INVALID `QUOTE_NOT_FOUND`, with hint `NORMALIZATION_VARIANT_PRESENT` | INVALID (verified), no hint |
| ADV-19 | １２時に来た。 (full-width digits) | quote 12時 | INVALID `QUOTE_NOT_FOUND` | same |
| ADV-20 | 真白は窓を開けた。\n\n風が入った。 | a Causes claim supported by one SUFFICIENT set containing two evidence locators, one per passage | VALID; two spans; no cross-passage quote | same |
| ADV-21 | same | one quote spanning both passages | INVALID `QUOTE_NOT_FOUND` | same |
| ADV-22 | 真白は笑った。 | a mention with no RefersTo | VALID with advisory `MENTION_WITHOUT_REFERSTO` (blocking is a policy decision) | same (advisory) |
| ADV-23 | 真白は笑った。 | Possesses(真白, 鍵) citing 真白は笑った | VALID structurally; gold scores an unsupported relation. Asserts that no evidence span is altered | same |
| ADV-24 | 真白は笑った。 | Occurred(EVT) for an event not in the text | VALID structurally; gold `UNSUPPORTED_ASSERTION` | same |
| ADV-25 | 真白は笑った。\n\n真白は窓を開けた。 | mention in P2 while the claim concerns P1 | VALID at the P2 span; caught only by gold (SC3 residue) | same |
| ADV-26 | 真白は笑った。 | context_before that would cross the passage start | INVALID `LOCATOR_CONTEXT_MISMATCH` | n/a |
| ADV-27 | as ADV-01 | the same draft compiled twice and in shuffled order | identical canonical JSON | identical (verified) |
| ADV-28 | as ADV-01 | `occurrence` field present | INVALID schema failure | accepted |

## Notes

- **Unchanged by V1.2.** ADV-03, ADV-09, ADV-10, ADV-13, ADV-23, ADV-24 and ADV-25 are semantic. V1.2 does not change them. They stay in the suite so that no report treats structural validity as semantic correctness.
- **Exact assertions.** Every VALID test asserts the exact resolved character offsets and the exact span text.
