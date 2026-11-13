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
| Brief | one chapter's passages (`[1.12] ...`), names known from earlier briefs | `story_brief_v0` | evidence ids exist in **this** chapter; every fact/relationship/event carries a `quote` that must occur verbatim (whitespace-insensitive) in its cited passages; character/event ids unique and resolvable; ≥1 CORE event |
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
- **Coverage, two levels.** CORE-event coverage is enforced in the plan. In the report,
  `GATE_NECESSARY_COVERAGE` flags CORE events that no *supported* critic claim cites
  (`brief_refs`); an event narrated without being cited can be a false flag.
- **Verbatim quotes.** Brief items must quote their cited passage exactly, so evidence ids
  cannot be invented or attached to the wrong passage. The quote does not prove the
  paraphrase is faithful; it proves the cited passage is the right one.
- **Human review sheet.** Each completed run writes `review_form.md` (Vietnamese, 1–5
  scores per contract dimension) for the project owner.
- **Provider.** Uses the existing M4 Gemini transport and key pool (`.env`). The model is
  a run parameter, so stronger models can be compared directly.

## Story memory and episodes (M5 spike)

`tools/story_memory/memory_v0.py` is a minimal persistent story memory, built so a long
story can be told as a series of episodes. It is a prototype and does not complete M5.

- **Store.** One JSON record per chapter brief under `.local/story_memory/<story_id>/`
  (`--memory`, disable with `--no-memory`). A record is reused only while the chapter's
  exact source bytes (M3 document version) and the brief setup (brief prompts, schema,
  brief language) are unchanged, so later episodes do not pay for earlier chapters again.
- **Roster.** Chapter-local characters are merged across chapters when they share a name,
  romanization or alias; a character matching several entries is reported, not guessed.
- **Relationship timeline** per character pair, chapter by chapter.
- **Recap.** For an episode starting at chapter N, `recap_context` summarises chapters
  `< N` only: chapter summaries, ending states, CORE events with refs, roster and the
  latest relationship states. It is passed to Plan, Script, Revision and Critic as
  background that is part of the truth boundary.
- **Episode mode.** `--chapters 3-5 --recap` tells chapters 3–5 and may open with a short
  recap of 1–2 and call back to their CORE events. Only the episode's own CORE events must
  be covered; nothing after chapter 5 is loaded.

```
python -m tools.story_pipeline.run_pipeline --chapters 1-2
python -m tools.story_pipeline.run_pipeline --chapters 3-5 --recap   # reuses briefs 1-2 from memory
```

Limits: the roster merge is name-based (two people with the same name would merge; one
person with no shared name across chapters would split); memory stores briefs, not
canonical assertions, until M4 output can be projected in through `story_facts/v0`.

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
`report.json`, `review_form.md`, `calls.jsonl` (every model call with raw output and validation errors) and
`run_manifest.json` (scope, background chapters, where each brief came from — memory or model —, profile, model, prompt/schema sha256, status). Episode runs also write `memory_recap.json`.

## Live runs

**2026-11-13, chapter 1, `gemini-3.6-flash`, free-tier key.**

Model availability on that key, from a one-line JSON request per model:

| Model | Result |
|---|---|
| Pro models (`gemini-3.1-pro-preview`, `gemini-pro-latest`) | 429: free-tier quota is 0 |
| `gemini-3.7-flash`, `gemini-3.8-flash`, `gemini-flash-latest` | 503: overloaded |
| `gemini-3.6-flash`, `gemini-3.5-flash`, `gemini-3-flash-preview`, `gemini-3.5-flash-lite` | answered |

What the run did:

- **Brief:** the first attempt failed schema validation because `forbidden_inferences` items came back as objects instead of strings. The repair loop sent the exact errors back, and the second attempt was valid (about 31 s and 26 s). The brief was stored in story memory.
- **Plan:** the call failed after 4 transport attempts with `SERVER_FAILURE`, which was 503 overload, not quota. The run stopped as FAILED.

Follow-up: `--model` now accepts a fallback chain. The client moves to the next model only after a model has exhausted its retries on overload, quota or network failure; a rejected request is not retried on another model. Backoff between retries now starts at 5 s. Every call log entry records the model that served it and any models that failed first. For a free-tier key:

```
python -m tools.story_pipeline.run_pipeline --chapters 1 --model gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview
```

Because a 429 cools down the whole credential rather than one model, a fallback after a quota error first waits out that cooldown.

**2026-11-13, run 2 (chapter 1, two free-tier keys, chain `gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview`).**

The run COMPLETED in 4 calls and 740 s:
- The brief came from story memory.
- The plan was served by `gemini-3-flash-preview` after both other models returned 503.
- The script needed one length repair: the first draft was 1204 words and the repaired one 1029.
- The critic reported **0 problems** across 23 claims in 17 paragraphs, and every automated gate passed.

A manual check against the Japanese source found defects the critic missed:

| Script claim | Source |
|---|---|
| everyone at school calls her "Thiên sứ" (angel) | "angel" is the narrator's metaphor (1.4); no such nickname is established |
| she receives countless confessions, very often | 「受けているらしく」 (1.39) is hearsay |
| she looked utterly devastated | 「どこか泣きそうに歪んだように見えて」 (1.26): she seemed somehow close to tears |
| he ran home soaked head to toe and freezing, and felt much lighter | he walked off briskly (1.55–1.56); his guilt eased "a little" (1.58) |
| (omitted) | Mahiru's refusal 「私はここに居たいから居るので」 (1.41) |

Root causes:
1. **The brief was too coarse.** It reduced 61 passages to 2 events, and the refusal was folded into "they talked briefly". The plan and the script could not cover what the brief did not separate.
2. **The critic under-extracted.** It produced about one claim per paragraph, so the intensifiers and the invented physical and emotional states were never isolated and checked.

Changes:
- **Brief granularity (hard check):** a brief needs at least ⌈passages/15⌉ events, and never fewer than 2. The prompt now defines an event as one action or one dialogue turn, and asks for hearsay markers to be recorded as REPORTED.
- **Critic density (soft check):** each paragraph needs at least one claim per 30 words unless the critic gives a no-claim reason. The prompt now lists the claim kinds to check separately: intensifiers, physical and emotional states, nicknames and reputation, and reported facts.

**2026-11-13, run 3 (chapter 1, same chain, after the granularity and density fixes).**

The run COMPLETED in 6 calls and 498 s.

- **Brief:** 7 events instead of 2, including Mahiru's refusal (E5).
  - The first attempt failed two checks. A `quote` stitched together from two passages was caught by the verbatim check, and the new minimum-event rule also fired.
  - The repaired attempt passed both.
- **Plan and critic v2:** both fell back to `gemini-3.5-flash` after 503 errors.
- **Critic:** 37 claims instead of 23. The density soft check asked for more once.
- **Script:** includes the refusal and the dialogue turns, and drops the hearsay about confessions.

The critic again reported 0 problems. The manual check still found strengthening that the critic labelled SUPPORTED_FACT:

| Script claim | Brief item it cited |
|---|---|
| "everyone calls her by the nickname Angel" | "likened to an angel" |
| "the guilt eased a lot" | "eased" |
| "the whisper was completely drowned out" | 「ほぼかき消される」: almost |

The brief was right; the writer strengthened the wording and the critic let it through.

**Strength audit (deterministic).** For every claim the critic accepts, each Vietnamese strengthening marker in the claim must also appear in the brief items the claim cites. The markers cover degree, frequency, scope, certainty, whole-body states and nicknames. Claims that fail become MEDIUM `STRENGTHENED_STORY_CLAIM` findings, which feed revision and the epistemic gate; they are also saved as `strength_audit_v*.json`.

Replayed offline on the saved critic outputs:
- **Run 2:** 6 flags, matching the manual findings ("utterly devastated", "freezing all over", "very often").
- **Run 3:** 7 flags, covering all three items above. One flag is arguably strict: Mahiru "soaked all over" while sitting in the rain.

## Known limits

- Brief paraphrase quality is not measured against gold. Quotes pin the evidence, but a
  wrong paraphrase of a correctly quoted passage still reaches the writer; the critic
  judges the script only against the briefs.
- The critic is a model and is known (H6/H6b) to miss violations; its PASS is weak evidence.
- Word count is whitespace tokens (Vietnamese syllables), matching the M1 runs.
- No human-review workflow yet; `UNDETERMINED` claims are listed in the report for a person.
