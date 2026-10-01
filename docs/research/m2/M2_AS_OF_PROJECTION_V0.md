# M2 — As-Of Projection v0 (Reference Semantics)

Status: RESEARCH — TASK M2-04. Pending Orchestrator review. Not recorded in `DECISIONS.md`.

## 1. Purpose

A small, deterministic **reference semantics layer** proving mechanically that Canonical Story Schema v0 supports leak-free `as_of = N` views and the derived concepts M2-02 defined.

It is not:
- persistence;
- a graph or relational store;
- retrieval, ingestion or extraction;
- Story Brief generation;
- a production API.

| Artifact | Role |
|---|---|
| `tools/canonical_story/view_v0.py` | `project_as_of(document, discourse_position)` |
| `tests/canonical_story/test_as_of_projection_v0.py` | 36 semantic tests |
| `tests/canonical_story/expected_snapshots_m2_02_s21.json` | Machine-readable M2-02 §21 expectations |
| `tests/canonical_story/fixtures/valid/snapshot_m2_02_s21.json` | Cases E, F and J combined in one synthetic document |

**Dependencies.**
- Install: `python -m pip install -r requirements-canonical-story.txt` (jsonschema ≥ 4.18 < 5, PyYAML ≥ 6 < 7).
- Missing packages make the tests fail loudly with that command; they never skip.

## 2. Inputs

- **Document.** A Canonical Story v0 document that passes the conformance validator. Non-conforming documents are refused (`ProjectionError`).
- **Authority policy.** Must be `DEFAULT_V0` (see §10).
- **Discourse position.** A key within the story's discourse stream, compared lexicographically; a shorter key sorts before its extensions.
  - `[5]` therefore means "before any segment of unit 5".
  - `[5, 999]` means "after every segment of unit 5" in the synthetic fixtures.
- **No mutation.** The input is deep-copied, so projection never mutates it.

The output is a **derived, disposable view** (`view_format: canonical_story_view/v0`, `derived: true`). It is not, and must never become, a Canonical Story schema record.

## 3. Visibility Rule

```text
visible(A, N)  ⇔  review.state(A) ≠ REJECTED  ∧  availability(A) ≤ N
```

- **Shared availability.** Availability comes from the shared normative calculator in `conformance_v0.py`, exposed as `availability_calculator`. The view contains no second availability implementation.
- **Visible support.** Each visible assertion lists only the support that is complete by N:
  - sufficient evidence sets;
  - derivations;
  - audit-only (CORROBORATING, PARTIAL) sets whose evidence is all at or before N.

  A later alternative path is therefore not exposed.
- **Visible referents.** An entity, event, anchor, mention or proposition appears only if a visible assertion references it, or, for mentions, if the mention's own evidence is at or before N. An early view therefore cannot reveal that a later person, event or anchor exists.

## 4. Bound Projection

For each visible stative assertion, each ANCHOR bound is shown only if its own availability is at or before N. Otherwise it is rendered `OPEN`.

A bound's availability is `max(assertion availability, earliest complete path of the bound's own support)`, or the assertion's availability if the bound has no support of its own.

Example (case E): B's UNAWARE state is available at 4, and its end bound at 15.
- `as_of 14` shows `end: OPEN`.
- `as_of 15` shows `end: t-evt-tell`.

Start bounds behave the same way (tested).

## 5. Identity, Mention and Content Resolution

All three use a view-local union-find over visible, canonically AFFIRMED links only. Canonical records are never mutated or merged.

| Resolution | Built from | Behaviour |
|---|---|---|
| Identity | `SameAs` | Chains close transitively (U≡X, X≡A ⇒ U≡A). A visible NEGATED `SameAs` between members of one class raises `IDENTITY_CONFLICT`. A CONTESTED `SameAs` is not merged and raises `IDENTITY_CONTESTED`. Class representatives are the lexicographically smallest ID; they are labels, not identity. |
| Mention | `RefersTo` | Mention → identity class(es): RESOLVED, UNRESOLVED, or AMBIGUOUS (diagnostic). A later `RefersTo` never appears earlier. |
| Content | `SameContent` | Placeholder propositions become RESOLVED to concrete content only once the link is visible. Commitments and verdicts then apply to the whole content class. |

## 6. Canonical Commitment Semantics

For each visible proposition, only assertions that commit **directly** to a member of its content class are considered. `Says(A, P)` and `Attitude(A, …, P)` commit to their own attitude or report propositions, never to P.

| Status | Condition |
|---|---|
| UNCOMMITTED | No visible committing assertion |
| OPEN | Only OPEN-polarity assertions (an explicit "undetermined") |
| AFFIRMED / NEGATED | Only that polarity, possibly alongside OPEN. A determination supersedes an explicit undetermined, and the OPEN assertion stays listed. |
| CONTESTED | Both AFFIRMED and NEGATED visible, and not provably in disjoint time scopes. No winner is chosen. |
| TIME_SCOPED | Both polarities, but every affirmed/negated pair is provably disjoint |

**Disjointness rule (conservative, view-level).** Two scopes are disjoint only when one's visible end anchor is the same anchor as the other's visible start anchor. Validity is read as half-open at a shared anchor: a state ending at event E and another starting at E are consecutive. Nothing else is inferred.

## 7. Knowledge Verdicts

Derived only from visible AFFIRMED `Attitude` assertions. Never stored.

| Attitude | Canonical status of content (in this view) | Verdict |
|---|---|---|
| HOLDS_TRUE, content polarity c | AFFIRMED or NEGATED, equal to c | KNOWS |
| HOLDS_TRUE, content polarity c | AFFIRMED or NEGATED, opposite to c | MISTAKEN |
| HOLDS_TRUE | UNCOMMITTED, OPEN, CONTESTED, TIME_SCOPED; or content polarity OPEN | UNRESOLVED_BELIEF |
| SUSPECTS, UNAWARE, KEPT_UNAWARE, PERCEIVES, SEEMS_TO_PERCEIVE | — | Same as the attitude |

- **Content polarity.** It is respected: "A holds NOT-P" is KNOWS when P is canonically NEGATED and MISTAKEN when P is AFFIRMED (tested).
- **Earlier views stay unresolved.** A belief that becomes MISTAKEN later is UNRESOLVED_BELIEF in every earlier view.
- **UNAWARE** appears only where an UNAWARE assertion is visible. It is never inferred from a missing attitude (open world).

## 8. Relationship Projection

Relationship is derived, not persisted. Visible assertions whose registry classification is RELATION and that have at least two ENTITY arguments (for example `Regard`, `AddressesAs`) are grouped by:
- predicate;
- subject identity class and object identity class (sorted for SYMMETRIC predicates);
- key tokens: the `functional_on` token arguments, such as `dimension`.

Each group lists **stages**:
- value: the non-key arguments, such as `level` or `form`;
- polarity;
- epistemic status;
- visible validity;
- availability.

Stages are ordered by availability. There is no scalar score and no genre-specific assumption. Case D yields NEGATIVE → NEUTRAL (SUGGESTED) → POSITIVE across views at 2, 6 and 11.

## 9. Secret Projection

A secret concerns **signed information** `(P-class, X)`, where X is the `content_polarity` of the `Conceals` assertion (AFFIRMED or NEGATED; M2-05). It is reported for each visible AFFIRMED `Conceals(h, P, X, from: B)` **only if** a visible AFFIRMED `Attitude(h-class, HOLDS_TRUE, P-class, X)` exists.

Every match below requires the same content class **and** the same polarity X. `SameContent` resolution changes the content class, never the polarity carried by the assertion.

- Without that evidence of holding, no secret is derived. The diagnostic `CONCEALMENT_WITHOUT_EVIDENCED_HOLDING` is raised instead.
- **Status:**
  - `ENDED` if B's class has a visible `HOLDS_TRUE` on `(P-class, X)`, or the `Conceals` end bound is visible;
  - otherwise `ACTIVE`.
  - A belief in the opposite polarity does not end the secret. It is listed separately as `target_opposite_belief_evidence`.
- **Evidence lists:**
  - `target_unaware_evidence` lists only visible UNAWARE or KEPT_UNAWARE assertions on `(P-class, X)`. An empty list means "not evidenced", never "unaware".
  - Secrecy is never inferred from B lacking a knowledge state.
- **UNAWARE interpretation (V0).** Every Attitude targets signed information, so UNAWARE is **polarity-specific**: `UNAWARE(P, AFFIRMED)` means the holder does not have "P is true". Unawareness of the whole question can be stated as both signed attitudes; a dedicated form is deferred.
  - **STATUS: PROVISIONAL / NOT REAL-SOURCE VALIDATED.** The M2-06 real-source panel never needed UNAWARE, so this interpretation is tested only on synthetic fixtures (M2-07 record).
- **Reader fields** (these replace the polarity-unaware `reader_has_canonical_content` of M2-04):
  - `canonical_content_status`;
  - `reader_knows_content_resolution`: canonical P is AFFIRMED or NEGATED;
  - `reader_knows_signed_content`: canonical polarity equals X;
  - `reader_signed_content_status`: MATCHES_CANONICAL, OPPOSES_CANONICAL, or UNRESOLVED.

  In case E the reader knows the signed content at 7 while B learns it at 15. If the concealed content is (P, AFFIRMED) and canonical P is NEGATED, the reader knows P is false, which is OPPOSES_CANONICAL, not knowledge of the secret.

## 10. Reader Reveal Assumption

The reader is not stored as a holder.

For every content class with a visible canonical determination (AFFIRMED, NEGATED, TIME_SCOPED or CONTESTED), the view reports `reader_reveal_position` as the earliest availability among its committing assertions.

**This is valid only under `DEFAULT_V0`'s current narration-authority assumption:** ordinary narration is treated as reliable and canonical-capable. It is deliberately not future-proofed for unreliable narrators. Projection refuses any other authority policy. The list includes all canonical content: the reader also learns, for example, *that A believes X*.

## 11. Event Occurrence

Every visible event referent reports:
- `event_exists: true` (a visible assertion references it);
- `occurrence_status` from visible canonical `Occurred(E)` commitments: OCCURRED, NOT_OCCURRED, OPEN, CONTESTED, or NOT_ESTABLISHED.

An event referenced only inside `Says` or `Attitude` content is flagged `referenced_in_holder_relative_content` and is never reported as OCCURRED (tested). An Event record by itself never implies occurrence.

## 12. Temporal View

The view lists visible `TemporalRelation` assertions (BEFORE, AFTER, SIMULTANEOUS, DURING, OVERLAPS) explicitly, with polarity and epistemic status.
- Story order is never inferred from discourse order. Case B: an event depicted at unit 20 is BEFORE the opening event, and nothing orders them until that relation is visible.
- Transitive closure is **not** computed in v0. Explicit relations suffice for the stress tests, and closure over mixed relation types needs care that M11 is better placed to give.

## 13. Contradiction Handling

- **Reports:** `reported_claims` lists every visible `Says` with its relation to canonical content: CONSISTENT, CONTRADICTED or UNRESOLVED. Opposing reports on one content class appear under `conflicts`.
- **Later resolution:** a later canonical assertion changes the status in later views only. Earlier views are recomputed identically (tested). Historical reports are never deleted.
- **Conflicting canonical assertions** are both retained and yield CONTESTED. The view never picks a winner.
- **Functional conflict diagnostic (conservative):**
  - Raised when two visible AFFIRMED assertions of a `functional_on` predicate share a key but differ in value.
  - Scopes both timeless or identical: `POTENTIAL_FUNCTIONAL_CONFLICT`.
  - Scopes neither identical nor provably disjoint: `FUNCTIONAL_OVERLAP_NOT_DETERMINED`.
  - Disjoint (meeting) scopes raise nothing.
  - Nothing is rejected or resolved. Cases A, C and D produce no false conflict (tested).
  - From registry v0.1 (M2-07), `AddressesAs` is no longer functional, so co-existing address forms raise no diagnostic and appear as separate stages. `Owns` is functional on `item`.

## 14. Open-World Semantics

- **Absence.** Absence of an assertion is never negation, unawareness, secrecy, non-occurrence or identity difference. Missing information surfaces as UNCOMMITTED, UNRESOLVED, NOT_ESTABLISHED, or an empty evidence list.
- **Explicit unknowns.** These are OPEN assertions. Case J's `IdentityKnown(U)` stays OPEN even after `SameAs(U, A)`. That is a record that the identity was explicitly marked unknown at 4, and the view does not silently rewrite it.

## 15. Known Limitations

1. **No story-time slicing.** Verdicts are not sliced by story time. KNOWS pairs a visible belief with the visible canonical status of its content, without checking that the belief's validity overlaps the content's validity. Time-sliced knowledge needs interval reasoning (M11).
2. **Disjointness** is recognized only for scopes that meet at a shared anchor. Other overlaps are reported as undetermined, never assumed.
3. **Class representatives** are lexicographic labels, not canonical identities.
4. **Single discourse stream** (inherited from Schema v0).
5. **Reader reveal** depends on the reliable-narration assumption of DEFAULT_V0.
6. **Transitive closure** of temporal relations is deferred.
7. **Relationship keys** come from `functional_on`. Predicates without it group by their entity arguments only.
8. **No contradictory-state repair.** The view reports CONTESTED, conflicts and diagnostics, but resolving them is an editorial or extraction concern.
9. **Performance** is not a goal. The reference implementation favours clarity over efficiency.

## 16. M2-05 Handoff

M2-05 may:
- Consolidate M2: review Schema v0 plus the projection semantics as a candidate `DECISIONS.md` entry (still requiring Orchestrator approval).
- Define the M3 adapter contract for producing DiscoursePositions and evidence references from Light Novel text.
- Specify how the Story Brief (M7) consumes a view. The view's `reported_claims`, `canonical_commitments`, `knowledge_verdicts`, `secrets` and `reader_reveals` already map to the Evidence Context Package's epistemic labels.

It should not start storage, retrieval or extraction without an explicit task.
