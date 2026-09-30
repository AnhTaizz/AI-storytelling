# M2 — Real-Source Canonical Mapping Spike (M2-06)

Status: RESEARCH — TASK M2-06. Pending Orchestrator review. Sanitized: this document contains no source prose, no names, and no private identifiers.

Aggregate result: `benchmarks/m2_canonical_model/REAL_SOURCE_MAPPING_SPIKE_V1_RESULT.yaml`.

## 1. Why Real-Source Mapping Was Needed

M2-01 to M2-05 validated Canonical Story Model v0 on synthetic stress cases. Synthetic cases confirm what the designers anticipated; they cannot show whether real prose fits the model naturally.

This spike tried to *break* the model on the private 30-chapter research corpus (identity verified: chunks SHA-256 `10ef5681…40fb`, corpus fingerprint `7f9bb810…7ff8`). Awkward fits count as weaknesses, not as successes.

## 2. Selection Methodology

- **Panel:** ten cases chosen by reading the source directly for modelling pressure. Frozen Task Q gold was not used. Three cases reuse chunks that also appear in Task Q probes; they model different facts, and this overlap is disclosed.
- **Difficulty:** 3 simple, 4 medium, 3 difficult. Seven cases stress several invariants at once.
- **Mapping first, JSON second.** Every case was mapped by hand in a private inventory before any JSON was built. The JSON was then generated mechanically from those decisions.
- **No model changes.** Schema, registry, validator and projection were untouched during the spike.
- **Extension probe.** To tell vocabulary gaps from model defects, a second document adds hypothetical predicates to an in-memory copy of the registry. Nothing is written to the repository registry.

## 3. Feature Coverage

| Feature | Cases |
|---|---|
| Straightforward event | 2 |
| State transition | 2 |
| Possession or location state | 4 |
| Changing form of address | 1 |
| Directional relationship state | 2 |
| Belief or knowledge | 4 |
| Concealment, secret, reveal | 2 |
| Emotion or intention with graded evidence | 2 |
| Retrospective or callback evidence | 5 |
| Long-range, multi-location evidence | 5 |
| Unknown content resolved later | 1 |
| Chronology differing from discourse order | 1 |
| Reported, false or misleading claims | 3 |

## 4. Fit Rubric

| Rating | Meaning |
|---|---|
| NATURAL | Represented directly, with no loss |
| ACCEPTABLE | Faithful, with a minor, explicit omission |
| AWKWARD | Needs a workaround or loses a real distinction; recorded as a weakness |
| NOT_REPRESENTABLE | Cannot be represented without inventing vocabulary |

Every case was rated twice:
- against the v0 registry exactly as committed;
- with the additive vocabulary proven by the probe.

Atomicity, epistemic, temporal and provenance fit were rated separately. Each case was also checked with `project_as_of` at meaningful cutoffs.

## 5. Aggregate Results

| | NATURAL | ACCEPTABLE | AWKWARD | NOT_REPRESENTABLE |
|---|---|---|---|---|
| v0 registry as-is | 1 | 4 | 4 | 1 |
| With additive vocabulary | 3 | 6 | 1 | 0 |

- **Difficult cases rated NATURAL or ACCEPTABLE:** 1 of 3 under v0; 3 of 3 with the additive vocabulary.
- **Conformance:** both documents pass the unchanged structural and semantic contract. The v0 document has 77 assertions, 47 exact evidence spans, 13 multi-path assertions, 5 multi-reference sufficient sets and 5 derivations.
- **As-of checks:** 36/36 (v0) and 41/41 (probe) pass, including two checks that deliberately reproduce known gaps.
- **Mapping errors:** one error in the first build pass (duplicate-content propositions) was found by an as-of check and fixed. It exposed finding F-DUP-PROP.

## 6. Gap Taxonomy

| Category | Cases | Main findings |
|---|---|---|
| PREDICATE_VOCABULARY_GAP | 7 | Health/physical condition; emotion toward a target; ownership vs custody; intention; habitual activity; address setting. All proven additive by the probe. |
| SEMANTIC_GAP | 6 | Causation by omission; existential / de dicto content ("some person"); non-assertive speech acts (requests, permissions, agreements); concealment from an unspecified public |
| EPISTEMIC_LIMITATION | 3 | Focalized narration of world claims (narrator truth vs focal-character belief); the INTERNAL_STATE gate relies on annotation discipline (depicted dialogue; motives encoded as `Causes`) |
| TEMPORAL_LIMITATION | 1 | Conditional future end bounds |
| PROJECTION_GAP | 1 | Content resolution does not propagate into propositions that embed a placeholder |
| SCHEMA_GAP | 1 | Duplicate-content propositions are accepted (identity by content not enforced) |
| ANNOTATION_AMBIGUITY | 1 | Repeated utterances of one claim collapse into one `Says` proposition |

**Blocking classification:**
- No BLOCKING_MODEL_DEFECT was found. No gap produced a leak, an overclaim, or a wrong canonical truth.
- Every projection-side gap errs toward under-reporting (UNRESOLVED or UNCOMMITTED).
- The rest are 6 non-blocking vocabulary extensions and 4 known limitations.

## 7. Important Lessons

1. **Core separation held on real prose.** Proposition vs Assertion vs `Says` vs `Attitude` is natural on real text. Reported causes, self-reports, hedged perceptions and a character's lie never became canonical, and the lie was CONTRADICTED once ownership was expressible.
2. **Signed information (M2-05) works on real concealment.** Concealment and discovery reveals matched by content and polarity, and the reveal derivation preserved polarity.
3. **Retrospective evidence behaved as designed.** Later passages supported occurrence but were only PARTIAL for details they do not repeat. A friend's later remark about a result did not ground participation.
4. **Temporal discipline held.** State histories appended rather than overwrote. End bounds learned chapters later stayed OPEN in earlier views. The in-chapter flashback was ordered only by an explicit relation.
5. **The registry is the weak point, not the schema.** Real narrative constantly needs condition, emotion, intention, ownership and habitual predicates. The v0 registry is intentionally small, but it is too small to be the frozen vocabulary.
6. **Address forms are setting-dependent.** Declaring `AddressesAs` functional on (speaker, addressee) is wrong for real data.
7. **Identity by content must be enforced.** A single duplicate proposition silently turned a KNOWS verdict into UNRESOLVED.
8. **Polarity-specific UNAWARE was not needed in this panel.** The panel yields no evidence for or against it.

## 8. Remaining Limitations

- Ten cases from one story and one genre. This is a stress sample, not coverage.
- The mapping was done by a single annotator (the research agent) and has not been independently reviewed.
- Existential content, omission causation, focalization, speech acts and conditional bounds remain open semantic questions. They are safe (conservative) but unmodelled.
- The probe vocabulary is illustrative; its exact form belongs to a registry decision.

## 9. Freeze-Readiness Recommendation

**READY_FOR_M2_FREEZE_REVIEW**, with explicit conditions for the Orchestrator:

1. Freeze the schema core, invariants and projection semantics, which showed no blocking defect. Treat the predicate registry as extensible: include an additive extension (condition, emotion toward target, intention, ownership, habitual activity) in the freeze scope or a registry v0.1.
2. Correct `AddressesAs` (add a setting argument or drop `functional_on`) before freeze.
3. Add a conformance rule rejecting duplicate-content propositions.
4. Record existential content, resolution propagation, omission causation, focalization, speech acts and conditional bounds as known limitations.

Without the vocabulary extension, only 1 of 3 difficult cases fits acceptably. The recommendation therefore depends on condition 1. This is a recommendation, not a freeze; `DECISIONS.md` is unchanged.
