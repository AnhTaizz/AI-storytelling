# M4 Fresh Validation V3 Protocol

## 1. Boundaries and blindness

FV3 was authored for a locked blind run of the development candidate. Source and canonical gold stay private to the independent author. Gold stays closed to the developer until predictions are locked and hashed. No predictions have been run. Seal status is `SEALED`.

## 2. Fresh source family and coverage

`ORIGINAL_JA_MINI_NARRATIVES_FV3` contains 16 independently authored Japanese units in contemporary settings. Fifteen have two passages and one has four. Freshness rests on independent authorship. Excluded corpora and packages were never opened for comparison.

The primary capabilities, in unit order, are

1. `honorifics_and_aliases`
2. `descriptive_reference`
3. `lending_return_and_bounded_custody`
4. `unheld_object_pickup`
5. `arrival_and_stationary_gesture`
6. `incidental_encounter`
7. `telling_and_conveyed_fact`
8. `belief_and_negated_speech_content`
9. `earlier_event_in_dialogue`
10. `narrated_benefactive_habit`
11. `retrospective_scene`
12. `deliberate_and_involuntary_perception`
13. `inanimate_change_and_signal`
14. `dated_events_and_explicit_order`
15. `simultaneous_events`
16. `prior_context_and_as_of_cutoff`

## 3. Source binding and inputs

Each unit has a separate `LIGHT_NOVEL_INGESTION/v0` manifest with source language `ja` and an exact source SHA-256. M3 ingested all 34 passages. The cases include 31 evidence-eligible passages, two context-only passages and one passage beyond the as-of cutoff. One case reuses prior canonical records. During blind prediction, only the prepared input for the corresponding case may reach the extractor.

## 4. Independent canonical annotation

The author declared canonical semantics against the M3 source before oracle projection. All 16 cases have a coverage note for every eligible passage under `STORY_UNDERSTANDING_CORE_V0`. The author designates them `COMPLETE_FOR_PROFILE` with `AGENT_DRAFT_GOLD` and `NOT_HUMAN_CONFIRMED` labels. Assertions are `UNREVIEWED`. The 165 required assertions exclude the prior batch. Seven eligible passages in seven units mix evidence roles.

The controlling conventions are `docs/research/m4/M4_ANNOTATION_CONVENTIONS_V4.md`, SHA-256 `32e315d553c683c804c50ab5dcb596064b16392b7a8f811cc52803ef4fda16f9`. The private builder records the annotation rules, including verbatim strings, date precision, holder-relative information and sentence-level date anchoring.

## 5. Checks and offline gate

The V1 and V3 checkers used exact source bytes and the applicable base document for all 16 case batches and the prior-context batch. Each checker reported zero mechanical findings. All 16 cases passed source-exact validation, Draft V1.1 projection and compilation, compiled-batch validation and canonical graph equivalence.

| Mechanical rule | V1 findings | V3 findings |
| --- | ---: | ---: |
| `R-EVR-01` | N/A | 0 |
| `R-EVT-02` | 0 | 0 |
| `R-LIT-01` | 0 | 0 |
| `R-LIT-02` | 0 | 0 |
| `R-LIT-04` | 0 | 0 |
| `R-LIT-05` | 0 | 0 |
| `R-MEN-01` | 0 | 0 |
| `R-MEN-02` | 0 | 0 |
| `R-ROLE-01` | 0 | 0 |
| `R-ROLE-02` | 0 | 0 |
| `R-TIME-02` | 0 | 0 |
| `R-TIME-03` | N/A | 0 |

## 6. Packages and reproducibility

The public case IDs in lock order are `fv3-01`, `fv3-02`, `fv3-03`, `fv3-04`, `fv3-05`, `fv3-06`, `fv3-07`, `fv3-08`, `fv3-09`, `fv3-10`, `fv3-11`, `fv3-12`, `fv3-13`, `fv3-14`, `fv3-15`, `fv3-16`. The gold archive binds the exact V4 convention bytes and the 17 V3 checker reports. Two independent builds in `.local/m4_fv3/sealed/` and `.local/m4_fv3/rebuild/` produced three byte-identical artifacts. The unchanged verifier passed on the final sealed directory with zero issues and 16/16 cases representable.

| Artifact | SHA-256 |
| --- | --- |
| input | `784f0276087795635aedd452a50cadbae761194bb3b9e55a176c758c457791be` |
| gold | `24cb19e083eb34cbeaa4278c7e20aa733e62c7089ab82bd3717950ab8d3dfb12` |
| blindness_manifest | `56586433c2d86a4b4e0b064f7af3be51412a1b045627c29d0d23215b049ab1f3` |

## 7. Limits and next boundary

The representational gate measures whether the notation can express the gold. Candidate accuracy requires a separately locked prediction run. The miniature units and agent-authored gold have no independent human adjudication. A future omission requires withdrawal of the affected completeness claim.
