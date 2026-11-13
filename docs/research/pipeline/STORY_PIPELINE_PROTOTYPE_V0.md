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

## Languages

The pipeline is meant to work for any source language (`source_language` in the M3 manifest), any brief language and any script language (both set in the Narrative Profile). Prompts are written in English and name the languages explicitly; the model does the translating.

The deterministic checks that depend on words read them from **concept-keyed lexicons** in `tools/story_pipeline/lexicons/<iso code>.yaml`. Each file maps the same concept ids, defined in `tools/story_pipeline/lexicon.py`, to the phrases of that language:

| Kind | Concepts | Used by |
|---|---|---|
| `strength` | `degree_extreme`, `completeness`, `quantity_large`, `universality`, `frequency_always`, `certainty`, `firmness`, `reputation`, `intensity_fill` | **Strength audit:** a concept in an accepted script claim or paragraph must also be expressed in the cited brief items |
| `hedge` | `reported`, `appearance`, `speculation`, `metaphor` | **Brief hedge check:** when the source sentence a brief item quotes carries one of these, outside dialogue, the item must carry a hedge in the brief language. For a metaphor the hedge must itself be a metaphor marker. |

Because the checks compare concepts, the script and the brief may be in different languages. For example, a Vietnamese "vô cùng" is supported by an English brief's "extremely".

Lexicons exist for **vi**, **ja** and **en**.
- **Missing lexicon:** when a run involves a language without one, the affected checks do not run. The run manifest (`language_checks`) and `report.md` say so explicitly; nothing is skipped silently.
- **Adding a language:** add one YAML file containing every concept. `tests/story_pipeline/test_lexicon.py` validates every file it finds: all concepts present, lowercase phrases, and no phrase listed under two concepts. Spaced languages set `word_boundaries: true`; languages written without spaces, such as ja, zh and th, set it to `false`.
- **Dialogue detection** uses quote characters (「」『』“”"" «»), not words, so it is language-independent.

Replay on the saved live briefs (ja → vi):
- Run 2's and run 5's hearsay facts are flagged: 「らしく」 for the confessions and 「…そうだ」 for the PE performance.
- Run 3's brief is clean. Its only candidate was a 「だろう」 inside Amane's own line, which the dialogue rule excludes.

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

A model that has already been retried (for example three 503s) now falls back whatever its final error is. In live run 4 the last attempt of an overloaded model ended in an unclassified provider failure, and the run stopped instead of moving on. A request refused on its first attempt is still not retried on another model.

**2026-11-13, run 4 (resume of run 3 with the strength audit driving revision).**

The 7 audit findings went to revision, which was served by `gemini-3.5-flash` after `gemini-3.6-flash` failed. The re-critic succeeded after two recorded attempt failures (429, then 503). The run COMPLETED.

| | v1 | v2 |
|---|---|---|
| Words | 1040 | 957 |
| Strength-audit findings | 7 | 1 |
| "everyone calls her by the nickname" | yes | no, now "likened to an angel" |
| "everyone at school knows her" | yes | no |
| "the guilt eased a lot" | yes | no |
| "completely drowned out" | yes | no, now "drowned out" |
| "vô cùng" ("extremely") | 4 | 2 |

One finding remains, "được mọi người ví như Thiên sứ" (likened to an angel *by everyone*). It is reported, and `GATE_EPISTEMIC_INTEGRITY` = FLAG. With the default of one revision round it was not revised again.

**Review of the run 4 final script (manual).**

The chapter was faithful overall. Remaining defects:
- An "everyone" that the audit flagged.
- "vô cùng áy náy" (extremely guilty) against 「何となく寝覚めが悪い」 (vaguely uneasy).
- An invented motive: he explains himself "to make clear he means no harm".
- Small invented details: "ordinary student", "freezing weather", "storm".
- A lost closing hook: the chapter ends on 「その時は」, "(so he thought) at that time".
- One switch of pronoun for Amane, from "cậu" to "anh".

The "vô cùng" slipped through because the critic paraphrased the sentence as "khó chịu và áy náy". The claim-level audit never saw the intensifier.

Changes:
- **Text-level strength audit.** Every marker in a paragraph's own wording must also occur in a brief item cited by that paragraph's claims. Paragraphs that cite nothing (pure commentary) are skipped, and markers already flagged at claim level are not reported twice. Replayed on run 4 it adds "vô cùng áy náy" to v2, and "chắc chắn ... rất áy náy" plus "cực kỳ lịch sự" to v1.
- **Closing hook.** Briefs record a `closing_hook` with a verbatim quote and its evidence; the quote is checked. When the last chapter has one, the plan must say in `closing_hook` how the final beat lands it (hard check), and the script ends on it.
- **Script prompt.** Keep each character's pronoun consistent, and vary repeated phrasing.

**2026-11-13, run 5 (fresh run with all fixes, 8 keys).**

The run COMPLETED in 10 calls and 519 s. Every 503 and 429 was recorded per attempt and absorbed.

- **Brief:** passed on its second attempt; the first was rejected by the granularity check.
- **Closing hook:** captured as 「改めて帰路に就いた周はそう思っていた。その時は。」 and landed by the final beat.
- **Strength audit:** 12 findings in v1, 0 in v2. Guilt that eased "a little" is now rendered correctly.

Manual check of v2 found two kinds of remaining defect:

- **Errors that were already in the brief:**
  - "called by the nickname Angel": 1.3–1.4 is the narrator's metaphor, not a nickname.
  - "frequently receives confessions" stated as fact: 1.39 「受けているらしく」 is hearsay.

  Run 3's brief had both right. The brief prompt asks for hearsay to be REPORTED, but the model did not comply this time. Because the audit measures the script against the brief, it cannot catch errors the brief already contains.
- **Strengthening with words not on the marker list:** "full of wariness" against 「うっすらと警戒が滲んだ」 (faintly wary), and "firmly refused" against a soft refusal.
- **Small invented details:** "a calm daily life", "tired face".

Brief fidelity now varies more from run to run than the script stage does. The next step is to check briefs against the source, for example by flagging facts whose quoted sentence carries a hedging marker (らしい, そうだ, ように見え, 噂) when the fact text has no Vietnamese hedge.

**2026-11-13, run 6.** The run COMPLETED in 9 calls and 366 s. The audit found 12 issues in v1 and 1 in v2.

The run did **not** exercise the new brief hedge check. Chapter 1's brief was served from story memory, because the brief prompt, schema and language had not changed, so it was run 5's brief with the hearsay still stated as fact. Validators added after a brief was stored never saw it.

Fix: a brief read from memory is re-validated with the current checks before it is reused. If it fails, it is regenerated; the manifest records `brief_sources` = `model (memory stale)` and the reasons under `stale_memory`.

## Known limits

- Brief paraphrase quality is not measured against gold. Quotes pin the evidence, but a
  wrong paraphrase of a correctly quoted passage still reaches the writer; the critic
  judges the script only against the briefs.
- The critic is a model and is known (H6/H6b) to miss violations; its PASS is weak evidence.
- Word count is whitespace tokens (Vietnamese syllables), matching the M1 runs.
- No human-review workflow yet; `UNDETERMINED` claims are listed in the report for a person.
