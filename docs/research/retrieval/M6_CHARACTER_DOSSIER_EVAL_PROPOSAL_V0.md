# M6 character dossier completeness evaluation v0

Status: **PROPOSAL — not agreed; no gold authored and no system evaluation performed.**

The owner needs "everything about character X up to cutoff N" for character-life videos. This proposes an
independent completeness evaluation over the tracked chapters 1–5. It tests evidence availability and identity
resolution before script writing. Passage relevance alone does not establish a complete life history. It depends on
the proposed entity request in `M6_PHASE2_BRIEF_RETRIEVAL_PROPOSAL_V0.md` and on M4 extraction persisted by M5;
the existing StoryMemory chapter-brief roster is an explicitly partial interim source.

## Gold units and scope

Pin the tracked source manifest, chapter byte hashes, segmentation version and inclusive cutoff. Each gold record
contains story, character key, chapter, exact passage/span evidence, class, required/optional status, and the identity
and epistemic interpretation available **at that cutoff**. IDs are annotation-local; match by source evidence and
meaning, not by producer IDs. Repeated occurrences in different spans remain distinct evidence units.

| Class | Gold unit | Required versus optional |
|---|---|---|
| Direct named mention | One occurrence of the character's explicit name with exact span | Every unambiguous occurrence is required, even if it repeats known information. |
| Alias / nickname / honorific | One occurrence of an established variant, tied to the same character | Required when resolvable using chapters <= N; a later identity reveal cannot justify an earlier merge. |
| Pronoun / descriptor | One pronoun or description referring to X, with antecedent/support | Required when the eligible context resolves X; genuinely ambiguous identity is marked unresolved, with alternative assignments optional. |
| Indirect information | One atomic proposition about X reported by another speaker/narrator, including an event involving X | Required even when X is absent or unnamed locally. Preserve speaker/holder and REPORTED, speculation or other epistemic status; reporting does not make the content true. |
| State change | One evidenced transition in X's condition, knowledge as stated, role or relationship, with observation time and support | Every source-supported transition is required. Keep prior and new observations; inferred persistence, motivation or causality is optional only when explicitly marked and adjudicated as admissible. |

The first three classes are mutually exclusive occurrence labels (a name with an honorific uses the alias class).
Information and state units form a second layer and can share evidence with mentions and with each other; never add
overlapping class denominators into a single undocumented total. Include direct assertions/events about X as atomic
information units too, tagging them `direct` versus `indirect`, so the inventory does not omit facts merely because
they accompany a named mention. Report indirect recall as its own class. A state unit can require several spans;
lock sufficient evidence alternatives before evaluation. No inferred off-page biography is required.

An ambiguous reference still requires an unresolved-reference entry; optional identity assignments do not excuse
silently dropping the occurrence. Unresolvable cases are reported separately from resolved-entity recall. Optional
units never reduce required recall and are scored separately. An unlisted prediction is pending adjudication, not
automatically false. Lock treatment of headings, dialogue vocatives and non-narrative author notes before authoring.

## Independent authoring and lock protocol

1. The owner appoints a gold author **other than the system implementer**, preferably a fluent source-language reader,
   plus a second reviewer. Record identities, prior exposure and conflicts; implementer-authored gold cannot be called
   independent. Select characters and the annotation rules before seeing system outputs or search results.
2. Read every chapter sequentially in full, from chapter 1 to 5, annotating all occurrences and information units.
   Do not discover gold by searching names, browsing top-k results, or using the roster as a candidate list. Record
   chapters with zero evidence explicitly. Freeze chapter/cutoff-specific identity notes before reading later chapters;
   later aliases/reveals must not retroactively resolve earlier-cutoff gold.
3. The reviewer independently reads the same sequence and reconciles spans, atomicity, evidence alternatives,
   identity, epistemic labels and requiredness. A third owner-appointed adjudicator resolves disagreements from the
   eligible text and the preregistered rules, without system outputs. Log the ruling and unresolved cases. If no
   defensible unique identity exists at N, retain ambiguity instead of forcing a merge.
4. Lock canonical gold bytes, character/cutoff inventory, source hashes, annotation rules, adjudications, matcher and
   metric definitions with SHA-256 **before any system run for this evaluation**. Keep system inputs separate from
   gold and record the lock timestamp. Existing retrieval experiments are disclosed as prior exposure; these chapters
   are development material, not a fresh unseen corpus. No retrieval tuning against this locked gold is allowed.
5. Lock system versions, configurations and outputs before opening gold for scoring. Any later gold correction needs
   independent adjudication, a new version/hash and an explicit correction log; retain old scores and rescore every
   route under the same corrected version. Do not patch only a losing system's gold.

This task proposes the protocol only. It creates no annotation, opens no sealed M4/other holdout gold and makes no
model/LLM call. Any later extraction or LLM-assisted search requires its own authorization and locked run protocol.

## Metrics and acceptance

Primary: required **unit recall per class**, per character and cutoff, with numerator/denominator and macro/micro
aggregates. Credit a recovered unit only when its evidence and identity/epistemic interpretation match; retrieving a
passage that happens to contain a pronoun is not successful pronoun resolution. Also report candidate evidence recall
without interpretation to distinguish retrieval reach from extraction/resolution quality.

- **Passage recall:** distinct required evidence passages recovered / all required evidence passages; use locked
  sufficient alternatives for multi-span units. Do not count optional passages in the required denominator.
- **Per-chapter recall:** required units recovered / required units in each chapter, and a character-by-chapter matrix.
  A zero-denominator chapter is N/A with count zero, not automatic 100%.
- **Full_Evidence_Success:** fraction of character/cutoff dossiers recovering every required unit, plus every sufficient
  evidence set needed for those units. Report at actual writer handoff and compare to the full internal inventory.
- **Alias-resolution errors:** false merges, false splits and wrong/unresolved assignments, with counts and denominators
  over adjudicated resolvable occurrences. Report gold ambiguity separately; never reward a guessed later identity.
- **Spoiler violations:** count/rate of any post-cutoff passage, assertion, state observation, alias or identity clue in
  output or query construction. **Must be 0.** Check every intermediate and final route, including expanded evidence.
- **Precision (secondary):** supported correctly assigned recovered units / emitted units, and relevant passage
  precision. Report optional valid units separately, adjudicate unmatched items, and distinguish retrieval candidates
  awaiting verification from accepted facts. Precision must not hide missing evidence through aggressive filtering.

Report output passage/unit/token counts, retrieval depth and overflow/truncation at handoff. Exhaustive modes should
return all eligible records through complete pagination; a prompt budget cannot silently reduce their completeness.
Report required omissions individually for reviewer action. Proposed character-life acceptance is 100% required-unit
recall and dossier success with zero spoilers; the owner must decide how incomplete systems may be used and whether
specific omissions are release blockers. A measured 100% is conditional on this gold and scope, not proof of universal
completeness.

## Separate and combined system comparisons

Use the same locked characters/cutoffs and source versions for each route:

| Route | What it tests | What to report |
|---|---|---|
| M4 records persisted/reloaded by M5 | Exhaustive mention/identity, participant, information and state extraction | Unit/class recall, resolution errors, evidence support and missing chapter records before retrieval; distinguish extraction loss from persistence loss. |
| Interim StoryMemory roster | `as_of` + `build_roster` names/aliases/facts with evidence from validated chapter briefs | The same recall and errors, plus omitted classes. Selected brief facts cannot substantiate an exhaustive claim. |
| Retrieval alone as safety net | Locked name/alias queries and optional agreed facets at @10/20/30/50 | Candidate passage/evidence recall and precision; identity-unit recall only after the same independent verification protocol. No gold-derived query terms. |
| M4/M5 + retrieval; roster + retrieval | Union with preserved route provenance, then candidate verification | Added required units, overlap, remaining omissions, verification cost and false matches; report both candidate and accepted-union recall. Never silently promote similarity hits to facts. |

Entity query seeds use only eligible known aliases. Score each route before the union, preserving baseline failures;
do not let a combined score conceal missing extraction classes. Sort dossiers by chapter/source position. For absent
M4/M5 output record `not run/unavailable`, rather than simulate completeness with roster data. This evaluation does
not require implementing all routes before independently locking gold.

## Size, limits and owner decisions

Start with about **4–6 characters**, subject to actual presence in chapters 1–5: two central, one or two supporting,
one sparse/minor and, if available, one described indirectly or with alias ambiguity. Use every applicable cutoff
1/2/3/4/5, including empty early scopes, for up to 20–30 dossiers. If fewer roles exist, use all available characters
and report that gap; do not invent source examples to meet a quota. Include repeat mentions and at least one
multi-chapter state history where the tracked source supports it. Publish class/role denominators so sparse categories
cannot disappear into averages. Generic role descriptions suffice here; no private characters or text are included.

Five chapters cannot establish multi-volume completeness, long-gap identity continuity or a new-language guarantee.
Larger independently authored, versioned evaluations across volumes/stories would be needed later. The current
implementer-authored retrieval DEV probes (n=30) measure question answering, not this dossier contract.

Owner decisions: approve required/optional classes and ambiguity/author-note rules; select roles, cutoffs, independent
author/reviewer/adjudicator and budget; agree span/proposition matching and reporting; define mandatory omissions and
release thresholds for each video type; approve writer delivery/verification cost and overflow handling; schedule
M4/M5 route availability and any later multi-volume study. LLM expansion/translation is a separate optional decision,
never the basis of a completeness guarantee.
