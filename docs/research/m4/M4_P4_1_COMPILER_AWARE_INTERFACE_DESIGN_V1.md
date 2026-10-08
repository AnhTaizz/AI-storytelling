# M4 P4.1 Compiler-Aware Interface Design V1

Task: M4-04B4D. Status: `M4_04B4D_P4_1_OFFLINE_CONTRACT_READY`. Offline design only.

Candidate: `P4_1_STORY_EXTRACTION_DRAFT_V1_1_COMPILER_AWARE_V1`,
definition SHA-256 `f016306647b48bf9b9dd6c7531a49c5e5775d8d9c7c760a54406e1035db218a8`.
Repair diagnostic: `M4_P4_1_STRUCTURAL_REPAIR_DIAGNOSTIC_V3`.

No provider or model was called for this task. No DEV3 input, DEV3 gold, private model
response, private prediction artifact or holdout file was opened. Everything below rests
on the accepted public M4-04B4CR record, the public schemas, registry and compiler, and
synthetic fixtures.

## 1. What P4.1 is

P4.1 changes two things the model sees and nothing the host accepts.

| Part | P4 | P4.1 |
| --- | --- | --- |
| Canonical Draft V1 and V1.1 schemas | accepted | unchanged |
| Full model schema in the prompt (`5aa2ed6d…7f14`) | accepted | unchanged |
| Provider projection (`89506def…b9bd`) | accepted | unchanged |
| Compiler V1 and V1.1, canonical validator, registry | accepted | unchanged |
| System instructions | P4 preamble | P4 preamble plus three compiler-rule sections |
| Repair diagnostic | V2 | V3 |
| Repair instructions | written for schema findings | written for V3 findings |

The principle is that the model is told the frozen constraints and is helped to repair
against them. The compiler is not made to accept output it rejected before. A draft that
was invalid under P4 is invalid under P4.1.

New files only. No existing P4 file is modified:

- `tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_system.txt`
- `tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_user.txt`
- `tools/story_extraction/prompts/story_extraction_draft_p4_1_v1_repair_user.txt`
- `tools/story_extraction/m4_04b4d_p4_1_compiler_aware_contract_v1.py`
- `tools/story_extraction/m4_04b4d_structural_diagnostic_v3.py`

## 2. Established findings this design starts from

These are results of accepted tasks, not of this one.

- **P3 on DEV3: 0 of 10 structurally valid.** The P3 prompt did not carry the Draft V1
  definitions the V1.1 schema refers to.
- **P4 on DEV3: 5 of 10 structurally valid** (M4-04B4C, prediction set
  `ee67ff92…6538`, 18 provider operations). This is a tuning comparison, not a blind
  validation.
- **Why P4 improved on P3.** P4 put one self-contained schema in the prompt, with every
  record, field, vocabulary and handle pattern defined in it. All 16 P4 responses,
  primary and repair, parsed and satisfied the full schema. Under P3 none compiled. The
  improvement is not attributed to the schema alone: P4 also added the provider-native
  projection and diagnostic V2, and these were not isolated.
- **Why P4 still failed five cases** (M4-04B4CR). Every failure is in compiler
  acceptance, after schema validation:
  - `AMBIGUOUS_QUOTE`: 9 blockers in 6 attempts, all on mentions. In each, the quote
    occurs exactly twice in its passage and the record carries no `occurrence`.
  - `ARGUMENT_ENTITY_KIND_NOT_ALLOWED`: 2 attempts.
  - `RULE_CANNOT_CONCLUDE_PREDICATE`: 2 attempts.
  - `DUPLICATE_CONCRETE_PROPOSITION_CONTENT`: 1 attempt.
  - Repair: 4 of 6 repair responses were byte-identical to their primary. Diagnostic V2
    masked the record handle in all 6 findings, named neither the failed check nor the
    record for canonical failures, and in one case merged several blockers into one
    finding.
- **No compiler defect is supported.** The locked result reproduces through the
  unchanged compiler.

## 3. Why schema-valid is not compiler-valid

The schema describes the shape of one draft. Three kinds of rule are outside what it can
say:

1. **Rules about the passage text.** Whether a quote occurs once or several times
   depends on the passage, which the schema never sees. `occurrence` must stay optional
   in the schema because it is optional for a unique quote.
2. **Rules that join two records through the registry.** An argument of kind `ENTITY`
   takes an entity handle, and the schema checks that. Whether that entity's `kind` is
   one the registry allows for that argument of that predicate joins the proposition,
   the entity and the registry. The same holds for a derivation rule and the predicate
   of the assertion it supports.
3. **Rules about the whole set.** Two propositions with identical content are each
   valid alone.

The provider projection is a relaxation of the same schema, so it cannot enforce these
either. They are enforced only by the frozen compiler and canonical validator.

## 4. Quote locators

### What the prompt now states

The P4 prompt already said that a repeated quote needs an occurrence. M4-04B4CR rated
that statement explicit and correct, and the model still omitted the occurrence. P4.1
therefore does not just repeat the rule. It gives a procedure and examples:

- matching is exact code-point substring matching in the selected passage, with nothing
  normalized;
- count the exact matches; matches may overlap and all count (this was absent from P4);
- count 0 is rejected, count 1 lets `occurrence` be omitted, count 2 or more requires it;
- `occurrence` is the 1-based index of the match the record refers to, not an offset,
  and must be the match actually meant;
- the rule applies to every mention and every evidence record, and short quotes are the
  ones most likely to repeat (in M4-04B4CR every ambiguous quote was 1 to 3 code points);
- seven synthetic examples: one match, two, three, overlapping, Unicode composition, a
  quote of one code point, a quote of several.

The examples are invented text. Their match counts are not typed into the prompt. They
are computed by the frozen compiler's own matcher when the prompt is assembled, and a
coverage gate fails if any required kind of example is missing.

### Why the host cannot choose the occurrence

A repeated quote with no occurrence does not say which match the record is about. Each
match is a different place in the text and may be a different referent. If the host
filled in `occurrence = 1`:

- the locator would compile and could point at the wrong place, so a structural failure
  would become a silent grounding error;
- the published output would contain a choice the model never made;
- the measured structural validity would rise without the model's output improving.

M4-04B4CR showed that every valid occurrence clears the blocker. That is exactly why the
choice carries information only the model has. So:

- no code in the candidate writes `occurrence`, `quote` or any other draft field (a
  test checks the source for such assignments);
- no prompt tells the model to take a default occurrence (a gate rejects such wording);
- diagnostic V3 reports the match count and the valid range and never suggests a value;
- a repeated quote without an occurrence fails closed under the unchanged compiler.

## 5. Canonical constraints in the prompt

The registry was already in the P4 prompt as data. M4-04B4CR rated the two constraints
below as implicit only, and the duplicate rule as absent.

- **Entity kinds.** The prompt separates the two constraints in words: the argument kind
  (`ENTITY`) and the kind of the referenced entity. It says a type-correct handle can
  still break the second one, and that the registry values must be used, not guessed.
- **Derivation conclusions.** A rule may support only an assertion whose predicate is in
  that rule's `conclusion_predicates`. A registered rule id and valid premise handles
  are not sufficient.
- **Proposition identity.** Identical content is defined as the validator defines it:
  same predicate and, per argument name, same kind and same reference, token or literal.
  Emit it once, let several assertions cite it, reuse an identical existing proposition.
  Propositions that differ in any argument are kept. There is no fuzzy or semantic
  deduplication and the host rewrites nothing.

Two lists in the prompt repeat the registry in a form that is easy to check against:
every argument with an `entity_kinds` restriction (14) and every derivation rule with
its `conclusion_predicates` (4 of 4). They are generated from the frozen registry when
the prompt is assembled. No copy is maintained by hand. The coverage gate requires every
restricted argument and every rule to appear, and it fails closed if the registry hash
differs from the reviewed one, so a registry change forces a review of the wording.

One sentence inherited from P4 is corrected. P4 said "all eight required top-level
arrays". The schema has seven arrays next to `draft_version`. P4.1 says so.

## 6. Structural diagnostic V3

### What it reports

One finding per blocker. Each finding has the phase, the code, a rule class, the source
of the finding, the record (collection, numeric index, handle), a path inside the
record, the canonical validator check and section where they apply, and a structural
detail made of counts, registry values and verified handles.

For an ambiguous quote the detail holds the passage handle, the exact match count,
whether an occurrence is present and required, and the valid range. For an entity-kind
violation it holds the predicate, the argument, the kinds the registry allows and the
kind the referenced entity has. For a rule conclusion it holds the rule, the predicates
it may conclude and the predicate of the assertion. For a duplicate it names the record
it is identical to.

It never states what the story content should be, and never proposes an occurrence, a
kind, a rule or a predicate.

### How records are identified safely

A handle is shown only if it matches the handle grammar of its collection, read from
the frozen model schema, and is present exactly once in the parsed draft. The numeric
index goes with it. Anything else is replaced by a mask, and the diagnostic is marked
`complete: false` with a limitation token. V3 never guesses a record.

Nothing the model wrote as free text is copied: no quote, passage text, argument value,
label, unexpected key, unverified handle, exception message or unrecognized compiler
code. Before a diagnostic is returned, an assertion walks it and fails closed unless
every string is owned by the tool, the schema or the registry, or is a verified handle.
The public summary is narrower again: codes and counts only, with no handle, index or
path.

### Why canonical validation stays authoritative, and what V3 cannot see

The frozen compiler reports a canonical failure as the names of the failed validator
checks and nothing else. The validator's list of issues is not available without
wrapping or changing frozen code, and V3 does neither. M4-04B4CR used a recorder around
the validator for forensics; that recorder is not part of this design.

Instead, V3 applies the three rule classes seen in M4-04B4CR to the parsed draft
itself, read-only, against the frozen registry, under the same preconditions the
validator uses. These findings are labelled `INDEPENDENT_REGISTRY_CHECK`. They also run
when the compiler stopped earlier, for example at an ambiguous quote, and are then
labelled `compiler_reached: false`. Under P4 such a violation surfaced only after the
single repair had been spent on the earlier blocker.

The limits are stated in every diagnostic, not hidden:

- The compiler decides validity. If the compiler accepts a draft, V3 reports no finding,
  even if one of its own checks disagreed. The disagreement is recorded as a limitation.
- Canonical issues outside the three rule classes are not enumerated. Such a failure is
  reported with the failed check name and rule class `UNRECOGNIZED_CANONICAL_RULE`, and
  the diagnostic is marked incomplete.
- The frozen compiler holds its blockers as a set, so two blockers with the same phase,
  code and path are one blocker by its own definition. V3 adds no merging of its own.

In tests only, V3 is compared with the frozen validator through the M4-04B4CR recorder:
161 targeted synthetic variants that reach canonical validation, and 230 generic
schema-valid mutants of which 36 reach it. V3 and the validator agree on all of them
for the three rule classes. Only one synthetic fixture carries a derivation, so the
rule-conclusion class rests on three variants.

## 7. Repair

At most one repair per case, as before. The repair receives the same prepared input,
the unchanged primary response and diagnostic V3. The repair prompt explains how to
read a finding, explains every code the model can act on, and says to correct every
finding, change only what a finding requires and preserve every other choice. It forbids
adding facts, improving coverage, using scores or gold, and reinterpreting the story to
satisfy a rule.

## 8. What is established and what is a hypothesis

**Established by this task, offline:**

- The P4.1 prompt contains the full model schema and the exact registry, unchanged.
- Every quote rule of the frozen matcher is stated, with the seven kinds of example.
- Every registry entity-kind restriction and every rule conclusion restriction is in
  the prompt, generated from the registry.
- V3 keeps one finding per compiler blocker, names records only when verified, and on
  the synthetic corpora agrees with the frozen validator for the three rule classes.
- No adversarial string placed in a draft, a raw response or a compiler message reached
  a diagnostic.
- The P3 and P4 prediction sets, protocol V2, diagnostic V2, the schemas, the
  projection, the compiler and the registry are unchanged.

**Design hypotheses, not tested:**

- That a counting procedure and examples make the model supply an occurrence when
  stating the rule did not.
- That naming the two registry constraints makes the model respect them.
- That a finding naming the record and the rule produces a different and correct
  repair, where V2 mostly produced an identical response.
- Two instructions in the repair prompt are untested choices: to return a response
  different from the primary, and, when a finding cannot be corrected without asserting
  something the passages do not support, to remove the offending record and its
  dependents. The second may trade coverage for validity. Whether it does can be seen
  only with gold on unseen cases.
- That a longer system prompt does not reduce conformance elsewhere.

## 9. Why no success rate can be claimed

No model has seen the P4.1 prompt. Nothing in this task measures how often a P4.1
response compiles, whether repairs succeed, or what the extraction contains. Structural
validity is a precondition for quality and says nothing about recall, precision,
grounding or epistemic correctness. No threshold is introduced.

## 10. DEV3 and DEV4

`DEV3_STATUS_FOR_P4 = TUNING_DATA_AFTER_P3_FAILURE`. P4.1 was designed from failures
observed on DEV3, so DEV3 is tuning data for P4.1 as well. A P4.1 result on DEV3 could
not be presented as validation: the candidate was shaped by those ten cases, even though
only aggregate rule classes were used and no DEV3 text is in any prompt or test.

A fresh DEV4, sealed before any P4.1 run, is still required to validate the candidate.
It has not been created. DEV3 gold and the holdout remain sealed and unopened.

## 11. Next

Recommended: M4-04B4E, P4.1 runtime/protocol preparation and synthetic smoke review. It
needs the Orchestrator's review and its own authorization. This task binds no model,
credential, runtime, live protocol or operation budget and creates no runner.

Record: `benchmarks/m4_extraction/M4_04B4D_P4_1_COMPILER_AWARE_REDESIGN.yaml`.
