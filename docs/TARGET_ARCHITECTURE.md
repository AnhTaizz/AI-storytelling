# Target Architecture

**Status:** CANDIDATE TARGET ARCHITECTURE — NOT AN IMPLEMENTATION COMMITMENT

This document describes a long-term capability map and candidate interaction model. It does not freeze specific technologies, require every shown component for the current milestone, or override accepted roadmap and architectural principles.

## 1. Overall Architecture

The story intelligence pipeline targets the following capability flow (Note: this is a target capability flow, not a currently implemented pipeline):

```mermaid
flowchart TD
    Source[Sources] --> Adapters[Source Adapters / Ingestion]
    Adapters --> Rep[Canonical Story Representation]
    Rep --> Extract[Story Understanding / Extraction]
    Extract --> Mem[(Persistent Story Memory)]
    Mem --> Ret[Retrieval]
    Ret --> ECP[Evidence Context Package]
    ECP --> Brief[Story Brief]
    Brief --> Plan[Narrative Plan]
    Plan --> Writer[Script Writer]
    Writer --> Valid[Validation / Critic]
    ECP --> Valid
    Valid --> HR[Human Review / Output]
```

### 1.1 Document Authority
When this target document conflicts with:
- `PRODUCT_VISION.md`
- `MVP_SCOPE.md`
- `ARCHITECTURAL_PRINCIPLES.md`
- `ROADMAP.md`
- accepted `DECISIONS.md`

the accepted foundation takes precedence until an explicit decision changes it.

## 2. Sequence Diagram (Script Generation)

```mermaid
sequenceDiagram
    participant User
    participant Orchestrator
    participant Retrieval Interface
    participant Story Memory
    participant LLM Provider
    participant Validation Layer
    
    User->>Orchestrator: Request new script generation
    Orchestrator->>Retrieval Interface: Query relevant story context
    Retrieval Interface->>Story Memory: Fetch entities/events
    Story Memory-->>Retrieval Interface: Return context
    Retrieval Interface-->>Orchestrator: Evidence Context Package
    
    Orchestrator->>LLM Provider: Generate Story Brief
    LLM Provider-->>Orchestrator: Story Brief
    Orchestrator->>User: Present Story Brief for optional review
    User-->>Orchestrator: Approve / edit / continue
    
    Orchestrator->>LLM Provider: Generate Narrative Plan
    LLM Provider-->>Orchestrator: Narrative Plan
    Orchestrator->>User: Present Narrative Plan for optional review
    User-->>Orchestrator: Approve / edit / continue
    
    Orchestrator->>LLM Provider: Write Script
    LLM Provider-->>Orchestrator: Script
    
    Orchestrator->>Validation Layer: Validate Script against Story Brief / Evidence Context
    Validation Layer-->>Orchestrator: Validation Report
    
    Orchestrator-->>User: Present Script & Report for Human Review
```

## 3. Provider Boundary and Independence

The architecture abstracts external providers to ensure that RAG and execution are independent of any specific vendor.

**Key Interfaces:**
- `LLM Provider`: Handles text generation and reasoning.
- `Embedding Provider`: Handles vectorization of story context.
- `Storage Adapter`: Manages persistence of raw and processed data.
- `Retrieval Interface`: Abstracts the retrieval mechanism.

Models (e.g., Gemini, OpenAI, Anthropic), databases (e.g., Neo4j, PostgreSQL), and providers are represented as replaceable choices rather than frozen dependencies.

### 3.1 Domain Model vs. Storage
The domain model must not be defined by storage technology. The correct direction of dependence is:
`Canonical Story Model → Storage Adapter → Vector / relational / graph implementations`

## 4. Evidence Context Package (Example)

The architecture distinguishes between raw ingestion and semantic intelligence:
`Source Evidence ≠ Extracted Story Intelligence ≠ Request-Scoped Evidence Context Package`

The Evidence Context Package is a disposable, request-scoped retrieval result assembled for downstream generation. It is distinct from the Persistent Story Memory, which is the long-lived historical story intelligence.

Architectural Principle 4 requires traceability. The context package must demonstrate provenance and epistemic status to prevent flattening differing levels of truth into generic facts.

```yaml
context_package:
  scope:
    story: "Source-Neutral Example"
    chapter_range: "1-3"
    spoiler_boundary: "Chapter 3 ending"

  focus_entities:
    - entity_id: "CHAR_01"
      name: "Protagonist"
      claims:
        - statement: "Is top of their class academically."
          epistemic_status: "EXPLICIT"
          evidence_refs: ["CH1_P4"]
        - statement: "Appears to be hiding a secret regarding the incident."
          epistemic_status: "SUPPORTED_INFERENCE"
          evidence_refs: ["CH2_P12"]

  relevant_events:
    - event_id: "EVT_05"
      statement: "An encounter in the rain."
      epistemic_status: "REPORTED"
      evidence_refs: ["CH3_P1-5"]

  unknowns:
    - "The exact motivation behind the antagonist's intervention in EVT_05 is currently unknown in this scope."

  constraints:
    - "Do not imply romantic feelings at this stage, as they are not supported by the current chapter scope."
```

## 5. Contracts Between Architectural Layers

1. **Source Adapter / Ingestion ↔ Canonical Story Representation**: The ingestion layer preserves source evidence/provenance and converts source-specific material into the shared source-independent representation required by downstream Story Intelligence.
2. **Canonical Story Representation ↔ Story Understanding / Extraction**: Extraction derives grounded entities, events, relationships, information, state changes, and other narrative facts while preserving references to source evidence.
3. **Story Understanding / Extraction ↔ Persistent Story Memory**: Only grounded story understanding that conforms to the Canonical Story Model and required provenance/validation contracts should be persisted as Story Memory.
4. **Persistent Story Memory ↔ Retrieval Interface**: Memory exposes retrievable story evidence and structured context through storage-independent interfaces.
5. **Retrieval Interface ↔ Story Brief**: Must supply a valid Evidence Context Package.
6. **Story Brief ↔ Narrative Plan**: The Story Brief serves as a declared, reviewable factual boundary for downstream narrative stages. It should preserve evidence, uncertainty, and spoiler scope, but remains subject to extraction error and validation. It defines what is currently supported, unknown, uncertain, and in scope. The Narrative Plan decides how supported material should be presented (ordering, pacing, emphasis, hook, callbacks). The Plan may NOT independently create canonical story truth.
7. **Narrative Plan ↔ Script Writer**: The Writer realizes the Narrative Plan while remaining bounded by the Story Brief and Evidence Context. It may use stylistic freedom where that freedom does not introduce unsupported story truth.
8. **Script Writer ↔ Validation / Critic**: Generated Script is evaluated against the declared Story Brief/evidence boundary and applicable Narrative Plan/output contracts. Validation attempts to detect violations but does not guarantee correctness.

### 5.1 Validation Input Contract
Validation inputs are task-dependent, but factual validation must have access to the declared factual boundary and/or corresponding evidence. The Validation / Critic layer cannot validate a Script in isolation. It receives at minimum:
- Generated Script
- declared factual boundary (Story Brief)

And, where needed:
- Evidence Context Package / provenance references
- Narrative Plan / output contract

### 5.2 Grounded YouTube script pilot

The vertical prototype exercises a narrower version of this flow. The M3 passage IDs
already carried by each chapter brief let the critic retrieve the original wording
independently of the writer's paraphrase. No new service is required. The narrator-facing
script stays clean. The editor receives the title, hook, opening narration, findings
and evidence separately. The evidence is bounded by the episode and any earlier CORE
recap events. The target M6 retrieval backend remains an open decision.

| Boundary | Observation motivating the design | Pilot change |
|---|---|---|
| Brief to critic | In chapter 1, run 9, the critic accepted several changes in meaning, including a narrator's metaphor attributed to classmates. | Compare each supported claim with a cited source passage. The deterministic check verifies the quote and its link. A person judges ambiguous readings. |
| Script to viewer | The writer generated a title, but the critic received only spoken paragraphs. A title could promise an event or relationship the episode never establishes. | Audit title premises alongside the narration. Ask the writer to introduce the same tension early and return to it in the episode. Keep title-only mentions out of event coverage. |
| Episode to episode | The original recap kept a CORE event summary while dropping its epistemic label and passage IDs. | Carry the earlier event's label and evidence into the next episode so hearsay can retain attribution. |
| Evaluation to release | Repeated runs on chapter 1 reveal concrete defects. Their results alone cannot estimate performance on new arcs or a channel's viewers. | Compare anonymized scripts on fresh episodes before changing the channel default. |

**Pilot evaluation.** Choose unused, authorized development material for three conditions:
an introductory chapter, a dialogue-heavy chapter containing a rumor, and a multi-chapter
episode with a recap. Keep the sealed M4 holdout separate. On each, run the previous and
proposed branches with identical sources, profile, model, temperature and revision budget
in separate directories. Record the actual provider model after any fallback. Randomize
the reading order and conceal branch names from the reviewer.

1. Read the title and first 30 seconds aloud. Write down the question a viewer would
   expect the video to answer. Identify the spoken beat that pays it off, or the point
   where the source deliberately leaves it open.
2. Compare both versions with the source. Count unsupported or strengthened claims and
   missed CORE events, note the worst severity, and time the edits needed before recording.
   Record voice preference and one concrete line explaining it. Use the same text length
   and count convention when comparing error rates.
3. Compare calls, tokens and elapsed time from the run logs. Record unresolved claims
   and false alarms alongside errors caught. Prioritize a pilot version with no new
   major factual or spoiler errors and lower editing effort at comparable voice quality.
4. After publication, an editor can record intro retention at 30 seconds and inspect the
   first substantial dip against the actual recording. Compare videos of similar length
   and note topic and packaging differences. Treat these as observations about published
   videos. A blind script preference and an offline test measure different outcomes.
   [YouTube's audience retention guide](https://support.google.com/youtube/answer/9314415?hl=en)

Implementation, CLI and artifact details are in the
[prototype notes](research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md#source-backed-review-and-existing-runs).

### 5.3 Extending the channel to manga

The current output profile is a third-person light-novel recap. Viewpoint, pacing,
compression and commentary belong to a channel profile. A different output profile
can use the same underlying story facts. Choose Gemini model routes independently of
that profile to compare runs without changing the editorial instructions.

For a future manga adapter, identify panels by edition, chapter, page and reading order.
Extract dialogue, speaker (or unknown) and directly visible actions once. Cache each
extraction against the image content, crop/layout, extractor model and prompt version.
Use a visual model for ambiguous speakers, panel transitions and silent actions; send
adjacent panels only when they resolve ambiguity. Keep low-confidence observations and
their panel IDs. The writer can consume textual events; a critic or editor can request
the cited panel when necessary. This requires an image-capable adapter and visual
evidence checks before enabling manga. A manga episode should set its own duration or
word budget since page count has no direct mapping to full prose length.

## 6. Implementation Stages & MVP

### 6.1 Current Research / M1
Evidence gathering around script quality and narrative contracts. M1 research spikes may prototype later-stage capabilities (such as Story Brief or Critic) before their formal milestones. These experiments provide evidence for future architecture but do not count as implementation or milestone completion.

### 6.2 MVP Capability Path
Capabilities needed to reach verified script quality through M9.
- Controlled ingestion
- Canonical representation
- Grounded story understanding / extraction
- Persistent Story Memory
- Retrieval
- Story Brief
- Narrative Plan
- Script
- Validation

**Human Review**: Human inspection is a cross-cutting product principle, not a replacement for a specific milestone. The architecture supports optional review points for key intermediate artifacts.
**Validation / Critic**: Validation attempts to detect factual, temporal, contract, and presentation violations. It is a validation layer, not an infallible guarantee of correctness; unresolved uncertainty or failures may still require human review.

### 6.3 Script Quality Gate
M9 must establish verified script quality and factual reliability before advanced retrieval expansion, additional source formats, or downstream production automation are treated as progression-ready.

### 6.4 Post-Quality-Gate Expansion (M10–M14)
Advanced capabilities like GraphRAG, temporal retrieval, or production automation are future roadmap trajectories, not mandatory MVP infrastructure.

## 7. Roadmap Mapping

The following table maps the target capabilities directly to the accepted roadmap. Concepts such as the Evidence Context Package or LLM Providers are architectural concepts supporting these milestones, not replacements for them.

| Milestone | Accepted Capability                 | Architecture Relationship                           |
| --------- | ----------------------------------- | --------------------------------------------------- |
| M1        | Script Quality & Narrative Contract | Empirically define output/validation contracts      |
| M2        | Canonical Story Model               | Define source-independent story representation      |
| M3        | Light Novel Ingestion               | Initial source adapter                              |
| M4        | Story Extraction                    | Build grounded story understanding                  |
| M5        | Persistent Story Memory             | Persist story intelligence across progression       |
| M6        | Retrieval Baseline                  | Retrieve relevant evidence/context                  |
| M7        | Story Brief                         | Build reviewable factual boundary                   |
| M8        | Narrative Planning                  | Decide presentation strategy                        |
| M9        | Script Generation & Validation      | Produce and validate major output                   |
| M10       | Advanced Narrative Retrieval        | Improve complex contextual retrieval                |
| M11       | Temporal / Graph Story Memory       | Add structural/temporal reasoning based on evidence |
| M12       | Manga Ingestion                     | Add source adapter for manga                        |
| M13       | Visual Production                   | Convert scripts to visual production planning       |
| M14       | Voice & Video Automation            | Automate downstream production                      |

*(Status Legend: **M1** is experimentally explored. **M2-M9** are candidate capabilities not yet implemented. **M10-M14** are future/evidence-gated.)*
