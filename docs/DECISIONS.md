# Decisions

Status: DRAFT — pending TASK 000F review.

## DEC-001

ID: DEC-001
STATUS: PROPOSED
DECISION: Story Understanding and Storytelling are separate layers.
RATIONALE: The platform must establish what happened before deciding how to present it.
CONSEQUENCE: Creative presentation cannot be treated as the source of factual story truth.

## DEC-002

ID: DEC-002
STATUS: PROPOSED
DECISION: Canonical Story Representation must remain source-format independent.
RATIONALE: The long-term product supports multiple narrative source formats.
CONSEQUENCE: Source-specific adaptation is kept separate from downstream Story Intelligence.

## DEC-003

ID: DEC-003
STATUS: PROPOSED
DECISION: Light Novel is the first supported source.
RATIONALE: The initial MVP is bounded around controlled Light Novel text.
CONSEQUENCE: Manga and other source formats are deferred.

## DEC-004

ID: DEC-004
STATUS: PROPOSED
DECISION: Script generation is the first major product outcome.
RATIONALE: The initial product demonstration culminates in a grounded YouTube script.
CONSEQUENCE: Early work prioritizes script quality and the Story Intelligence needed to support it.

## DEC-005

ID: DEC-005
STATUS: PROPOSED
DECISION: Persistent Story Memory is a first-class architectural capability.
RATIONALE: Useful understanding must persist across chapters and volumes.
CONSEQUENCE: The product must support historical context rather than only local processing.

## DEC-006

ID: DEC-006
STATUS: PROPOSED
DECISION: Narrative style must not change factual story truth.
RATIONALE: Different presentation styles are needed without compromising groundedness.
CONSEQUENCE: Style can change presentation choices but not established story facts.

## DEC-007

ID: DEC-007
STATUS: PROPOSED
DECISION: Graph and vector retrieval are complementary.
RATIONALE: Structural reasoning and semantic similarity address different retrieval needs.
CONSEQUENCE: Neither retrieval approach is assumed to solve every narrative query.

## DEC-008

ID: DEC-008
STATUS: PROPOSED
DECISION: Technology choices must not define the Canonical Story Model.
RATIONALE: The domain must remain conceptually independent of storage and other implementation choices.
CONSEQUENCE: Specific databases and infrastructure remain open until justified.

## DEC-009

ID: DEC-009
STATUS: PROPOSED
DECISION: Video automation is postponed until the Script Quality Gate is passed.
RATIONALE: Production automation depends on reliable storytelling outputs.
CONSEQUENCE: Video automation follows the script quality milestone rather than preceding it.

## Technology Status

No specific database, graph system, vector system, or LLM is accepted by these foundation documents. Such options remain provisional or subject to benchmarking until explicitly decided.
