# Story Pipeline Prototype v0

Status: **PROTOTYPE — not frozen, not a milestone completion.** Built under the roadmap's
Execution Semantics (vertical prototypes may touch later milestones to get early
empirical feedback) while M4 Story Extraction remains open.

Identity: `STORY_PIPELINE_PROTOTYPE/v0` — code in `tools/story_pipeline/`, schemas in
`schemas/story_pipeline/`, tests in `tests/story_pipeline/`.

## Purpose

Produce a grounded Vietnamese storytelling script end to end from ingested source
chapters, so the downstream stages (M7 Story Brief, M8 Narrative Planning, M9 Script
Generation & Validation) can be exercised and evaluated now, and so the real bottleneck
for script quality can be observed instead of assumed.

## Flow

```
M3 ingestion (frozen adapter, chapters in scope only)
  └─ per chapter: Story Brief  ──(optional story_facts/v0 hints from M4)
       └─ Narrative Plan (beats, hook, callbacks, word budget)
            └─ Script v1 (one section per beat)
                 └─ Claim-level Critic (paragraph units, contract claim types)
                      └─ Revision (MEDIUM+ findings) → Critic again → final script + report
```

| Stage | Input | Output | Deterministic checks |
|---|---|---|---|
| Brief | one chapter's passages (`[1.12] ...`), names known from earlier briefs | `story_brief_v0` | evidence ids exist in **this** chapter; character/event ids unique and resolvable; ≥1 CORE event |
| Plan | all briefs (with global refs `c1.E3`), profile | `narrative_plan_v0` | refs exist; every CORE event in some beat; CORE never omitted; beat word budgets sum within profile range |
| Script / Revise | briefs, plan, profile (+ findings) | `script_v0` | sections follow plan beats in order; length (SQ-INV-14), no CJK characters (SQ-INV-15), no Markdown/placeholders/meta text (SQ-INV-16) |
| Critic | briefs, paragraph units P001… | `critic_v0` | exactly one entry per unit, in order; problem claims carry severity and category |

## Design decisions

- **Validate-and-repair loop.** Every call is parsed, checked against its JSON Schema and
  the stage's semantic rules; the exact errors are sent back for up to `--max-repairs`
  (default 2) corrections. Length/language/clean-output errors are *soft*: they trigger
  repairs, but if they remain after the last attempt the script is kept and reported.
- **Spoiler boundary by construction.** Only chapters inside `--chapters` are loaded, so
  no later text can reach any prompt. The critic additionally flags `PREMATURE_SPOILER`.
- **Contract vocabulary.** Critic claim types, failure categories, severities and gates
  are taken from `SCRIPT_QUALITY_CONTRACT/v0` (sections 4.1, 13, 14). The report is an
  automated pre-check, not an official contract verdict.
- **Coverage is plan-level.** CORE-event coverage is enforced in the plan; whether the
  script narrates each beat's events is not yet checked automatically.
- **Provider.** Uses the existing M4 Gemini transport and key pool (`.env`). The model is
  a run parameter, so stronger models can be compared directly.

## Integration seam for M4: `story_facts/v0`

`tools/story_pipeline/facts.py` defines a small format (facts with kind, epistemic status
and passage evidence per chapter). When an extractor is selected, a projection from its
compiled canonical output (for example via `tools/canonical_story/view_v0.py`) into this
format can be passed with `--facts`. The Brief stage treats the facts as hints and must
still cite source passages, so extraction errors cannot enter the truth boundary
unchecked.

## Running

```
cp .env.example .env    # fill GEMINI_API_KEY_1 and GEMINI_MODEL
python -m pip install -r requirements-canonical-story.txt -r requirements-story-extraction-gemini.txt
python -m tools.story_pipeline.run_pipeline --chapters 1
python -m tools.story_pipeline.run_pipeline --chapters 1-5 --min-words 1500 --max-words 2000 --model <model>
python -m tools.story_pipeline.run_pipeline --resume .local/story_pipeline_runs/<run id>
```

Useful flags: `--stop-after brief|plan|script|critic`, `--revision-rounds N`,
`--revise-severities CRITICAL,HIGH`, `--profile <yaml>`, `--temperature`.

Each run writes to `.local/story_pipeline_runs/<run id>/` (git-ignored): `briefs/`,
`plan.json`, `script_v*.json|md`, `critic_v*.json`, `script_final.md`, `report.md`,
`report.json`, `calls.jsonl` (every model call with raw output and validation errors) and
`run_manifest.json` (scope, profile, model, prompt/schema sha256, status).

## Known limits

- Brief quality is not measured against gold; the critic judges the script only against
  the briefs, so a brief error becomes an undetected `SOURCE_GROUNDING_FAILURE`.
- The critic is a model and is known (H6/H6b) to miss violations; its PASS is weak evidence.
- Word count is whitespace tokens (Vietnamese syllables), matching the M1 runs.
- No human-review workflow yet; `UNDETERMINED` claims are listed in the report for a person.
