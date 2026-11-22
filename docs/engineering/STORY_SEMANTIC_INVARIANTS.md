# Story Intelligence semantic invariants

Use the applicable rows when designing tests and reviewing a diff. The [decision register](../DECISIONS.md), frozen contracts and [architectural principles](../ARCHITECTURAL_PRINCIPLES.md) supply the requirements. The examples below describe the checks available on this branch. A fixture passing establishes behavior on that fixture.

### A. Source ingestion · DEC-018

Preserve the caller's story, stream and document identities, the version derived from exact bytes, manifest reading order and passage locators. A citation must recover the original source slice. Derived text belongs in a separate artifact with provenance. Reingesting identical input must reproduce its segments and fingerprint. [Light Novel ingestion contract](../research/m3/M3_LIGHT_NOVEL_INGESTION_CONTRACT_V0.md)

**Checked:** hash mismatch rejection, ordering, byte and code-point offsets, stable identity and repeatability on synthetic and sample inputs. **Review:** confirm the manifest identifies the intended edition and reading order, and that a consumer still cites the original evidence after preparing text. [Adapter tests](../../tests/story_ingestion/test_light_novel_adapter_v0.py)

### B. Canonical representation · DEC-005, DEC-008, DEC-010, DEC-011, DEC-016

Preserve entity and event IDs, typed relationships, supporting references, provenance, validity in story time and availability at a discourse position. Later identification or evidence can change a later view while preserving the earlier one. Keep source-specific locators inside the adapter boundary. The canonical assertion strengths are `EXPLICIT`, `ENTAILED` and `SUGGESTED`. The model expresses a report through perspective and an unresolved proposition through open polarity. Evidence that someone believes a claim supports the belief without establishing the claim itself. [Canonical schema](../../schemas/canonical_story/canonical_story_v0.schema.json) · [Predicate registry](../../schemas/canonical_story/predicate_registry_v0.yaml)

**Checked:** schema and conformance rules, evidence availability, flashbacks, state history and late identity resolution on fixtures. **Review:** whether two mentions denote the same entity, a cited passage supports the proposed relationship, and the assertion captures whose knowledge changes. [Schema tests](../../tests/canonical_story/test_canonical_schema_v0.py) · [As-of projection tests](../../tests/canonical_story/test_as_of_projection_v0.py)

### C. Story extraction · M4 research

For each asserted event, participant or relationship, trace support to the allowed source and preserve the strength of the inference. Leave unresolved motives, dates and identities unresolved unless the applicable contract supports resolving them. Apply the annotation conventions and protocol version bound to the experiment. Preserve sealed inputs, locks, predictions and recorded scores. [Annotation conventions V2](../research/m4/M4_ANNOTATION_CONVENTIONS_V2.md) · [Project State](../PROJECT_STATE.md)

**Checked:** draft structure, references, quote anchoring, mention evidence and compilation of synthetic graphs. **Review:** whether a structurally valid extraction invents an event, assigns an unsupported role or omits a material event. Score under the locked protocol. Report the dataset, split and limitations before making quality or generalization claims. [Compiler tests](../../tests/story_extraction/test_draft_compiler_v1_1.py)

### D. Story memory and retrieval · DEC-005, DEC-011, DEC-021

Bind facts to the intended story, brief snapshot and chapter scope. Retain historical relationship observations and the evidence available at the requested cutoff. Recap uses earlier chapters only. A matching name is insufficient evidence for a disputed identity. Reading order alone cannot establish the timing of a flashback. Check what the audience may know before delivering evidence to the writer.

**Checked:** story isolation, narrower windows and spoiler cutoffs, snapshot-bound refs, rejection of invalid chapter evidence, shared-alias reporting, and recap exclusion of episode and later chapters. **Review:** ambiguous identity merges, chronology, relevance and missing evidence. M6 entity evidence is explicitly partial. M5 brief memory remains a prototype. [Retrieval scope tests](../../tests/story_retrieval/test_retrieval_v0.py) · [Brief retrieval tests](../../tests/story_retrieval/test_brief_retrieval_v1.py) · [Memory tests](../../tests/story_memory/test_memory_v0.py)

### E. Story Brief and Narrative Plan · DEC-006, DEC-013, DEC-022, DEC-023

The episode brief establishes a reviewable factual boundary. Keep same-chapter evidence, verbatim quotes and the chapter brief's own epistemic labels. Apply verified corrections to the run's copy and preserve stored history. The plan controls presentation. Hook, callback, pacing, reordering or commentary must preserve supported facts, their causes and the audience's knowledge. [Chapter brief schema](../../schemas/story_pipeline/story_brief_v0.schema.json) · [Decisions](../DECISIONS.md)

**Checked:** brief citation scope and quotes, correction handling, allowed plan references and review edits. Some free-text and pacing checks are advisory. **Review:** compare the brief back to source for omissions, trace a callback's setup before its payoff, and read a reordered beat for an implied new fact. [Pipeline tests](../../tests/story_pipeline/test_story_pipeline_v0.py) · [Brief checks](../../tests/story_pipeline/test_brief_check.py) · [Plan review tests](../../tests/story_pipeline/test_plan_review.py)

### F. Script generation and validation · DEC-006, DEC-017

Trace material claims to the reviewed boundary and its evidence. Preserve episode coverage, spoiler cutoff, causal links, chronology and epistemic strength. Voice and compression can change phrasing. They cannot supply a character's private motive. Apply the requested language, output and narrative profile under the [script quality contract](../contracts/SCRIPT_QUALITY_CONTRACT_V0.md).

**Checked:** deterministic pipeline fixtures exercise citation checks and verify that incomplete source checking retains the draft and reports the need for review. **Human audit:** contract sections 15–16 require human assessment of grounding, epistemic status, temporal/state fidelity, spoilers and coverage for an official passing verdict. Evaluate spoken flow and usefulness on the requested script. Keep the pipeline status, model critic and official contract verdict distinct. [Pipeline tests](../../tests/story_pipeline/test_story_pipeline_v0.py)

### G. Future manga ingestion · M12

M12 is gated. For a future adapter review, ask whether page/panel references identify the source image and version, how reading order was established, and how each reconstructed scene traces back to panels. Distinguish visible action, attributed dialogue and inferred speaker, identity or intent. Preserve uncertainty when panels admit several readings. These are design questions for a future contract. This branch has no M12 conformance check or accepted panel schema. [Roadmap](../ROADMAP.md) · [Canonical locator boundary](../../schemas/canonical_story/canonical_story_v0.schema.json)
