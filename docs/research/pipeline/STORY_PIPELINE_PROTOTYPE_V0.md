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

### Korean readiness (prepared without a Korean sample)

| Area | State |
|---|---|
| M3 ingestion | Accepts any language tag (`source_language: ko`). It makes one passage per run of non-blank lines. **Checked on 2026-11-14** with an original Korean text: with blank lines between paragraphs it gives 12 passages; with single line breaks, the common web-novel layout, the whole chapter becomes 1 passage. The adapter is frozen, so `tools/story_pipeline/prepare_source.py` rewrites such files before M3 (see below). |
| Lexicon `ko.yaml` | Substring matching, because particles and endings attach to words. Reported speech is caught through endings such as ‑다고 한다 and ‑라던데, appearance through ‑것 같다 and ‑듯했다, speculation through ‑지도 모른다 and 아마, and metaphor through 마치 and ‑처럼. Ambiguous stems are excluded, for example 늘 (it matches inside 늘어나다) and 것이다. |
| Event minimum | Now counts source characters divided by the lexicon's `chars_per_event` (ja 550, ko 700, vi 1500, en 1600; rough, tunable) instead of counting passages. Korean web novels often put every sentence on its own line: 200 one-line passages now need 9 events instead of 14. |
| Foreign script check | Driven by the target language's allowed writing systems. **Hangul was previously not detected**, so Korean left in a Vietnamese script passed. Languages written without spaces (ja, zh, th) count length in characters. |
| Dialogue | ‘…’ is added to the quote characters; Korean novels use it for inner speech. |
| Names | The profile's name policy is now script-neutral: standard romanization, no original script. |
| Embeddings | The pipeline uses none. The M1 retrieval models (multilingual-e5, bge-reranker-v2-m3) are multilingual but were only benchmarked on Japanese. Measure them on a Korean probe set before relying on retrieval. |

### Preparing a source: `prepare_source.py`

```
python -m tools.story_pipeline.prepare_source --input-dir <raw chapter files> \
    --out .local/sources/<story> --story-id <id> --language ko
```

- **What it writes:** the chapter files, an M3 manifest (`manifest.yaml`) and `SOURCE_PREPARATION.json`, which keeps the hash of each original file and the layout decision. The prepared files are the source of record.
- **Layout `auto`:** a file is split line by line only when its paragraphs average 4 or more lines **and** at least 70% of its lines end a sentence. Hard-wrapped prose fails the second test and is left alone, with a warning. `--layout lines` and `--layout keep` force either way.
- **Pipeline warning:** a chapter that reaches the pipeline with 4 or more lines per passage is reported on the console, in the run manifest (`source_warnings`) and in `report.md`.

Still unverified: a real Korean chapter. The check above used text written for the test.

**2026-11-15, runs 11 and 12 (the same original Korean text, prepared with `prepare_source`, 180–280 words).**

- **Run 11 FAILED at the brief, a false positive.** 「눈가가 조금 붉어진 것처럼 보였다」 ("her eyes looked slightly reddened") contains the simile marker 처럼 inside an appearance construction. The check then required a figure of speech, and rejected "có vẻ hơi đỏ" three times. Now a metaphor is required only when the source marks nothing else.
- **Run 12 COMPLETED** in 6 calls and 107 s, with every gate passed and no audit finding left:
  - names romanized (Seo Ji-woo, Han So-yeon), no Hangul in the script;
  - hearsay kept ("nghe nói ... đứng đầu toàn trường") and the appearance kept ("có vẻ hơi ửng đỏ").
- **Manual check of run 12:**
  - 「목소리가 들린 것 같았지만」 ("he seemed to hear a voice") became a plain "nghe thấy". The Korean lexicon listed only the dictionary forms (것 같다, 것 같았다), so the inflected 것 같았지만 matched nothing. It now lists stems (것 같, 듯하, 보였).
  - The closing line again states that Ji-woo's belief "was wrong", where the source only says what he thought at the time (그때의 지우는 생각했다). This is the same over-commitment as in run 9.
  - The brief's event E2 contains a Hangul word (붉어) inside Vietnamese text. Foreign script is checked only in the script, not in briefs.
  - The test text itself contradicts itself: 같은 반 ("same class") and then 반이 달라서 ("different class"). The pipeline avoided both and wrote "cùng trường" (same school).

### Chinese (`zh.yaml`, prepared without a Chinese sample)

- **Lexicon:** simplified and traditional forms side by side (据说/據說, 似乎, 也许/也許, 宛如, 仿佛/彷彿). Phrases are matched as substrings, so every phrase has at least two characters: 像 alone would match 图像 and 想像. 可能 is left out because it is inside 不可能 ("impossible").
- **Contrast openers:** 但是, 可是, 然而, 不过/不過.
- **Event density:** `chars_per_event` 420.
- **Source preparation:** Chinese web novels usually end paragraphs with a single line break and indent them with full-width spaces. `prepare_source` handles that layout, and the indentation is kept inside the passage text.
- **Open product decision:** Vietnamese audiences know Chinese novels by their Sino-Vietnamese names (Hán-Việt, for example Lâm Uyển Nhi) rather than pinyin (Lin Wan'er). The profile's name policy says "standard romanization of the source language", which means pinyin. The owner should choose which convention to use.

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

Useful flags:
- `--stop-after brief|plan|script|critic`, `--profile <yaml>`, `--temperature`;
- `--revision-rounds N` and `--full-revision-rounds K`: the first K rounds may rewrite the script, later rounds only patch sentences;
- `--revise-severities CRITICAL,HIGH`;
- `--source-check-chunk N` (default 4 paragraphs per call; 0 sends the whole script) and `--source-check-samples N` (calls per group, default 1), or `--no-source-check`;
- `--resume <run dir> --apply-review [FORM]`: fix the quoted errors of the owner's filled review form in one patch round (see "Owner corrections" below);
- `--no-callbacks`: do not add earlier events found by brief retrieval to an episode's recap (see "Callbacks from brief retrieval");
- `--full-recheck`: send every paragraph to the critic and the source check in every version. By default, a paragraph whose text is byte-identical to one in the previous version keeps that version's critic claims, source-check findings and brief gaps, and only changed paragraphs are checked again (`rechecked_units` per version in the manifest);
- `--recap` (episode mode), `--no-memory`.

A whole story, episode by episode:

```
python -m tools.story_pipeline.run_story --chapters 1-5 --episodes 1,2-3,4-5 --revision-rounds 3 --model <chain>
python -m tools.story_pipeline.run_story --chapters 1-30 --episode-size 3 --model <chain>
```

- Running the same command again continues the season: completed episodes are skipped, an interrupted one resumes from its saved stage outputs, and a quota error pauses the season (`PAUSED_QUOTA`).
- `.local/story_seasons/<story id>/` holds `season.json`, `season.md` (an index with links to every episode's report and review page) and one directory per episode.
- `--keep-going` continues after a failure that is not a quota stop.

A source whose paragraphs end with a single line break (common in Korean and Chinese web novels) is prepared first with `python -m tools.story_pipeline.prepare_source` (see below), then run with `--manifest <prepared manifest>`.

Each run writes to `.local/story_pipeline_runs/<run id>/` (git-ignored):
- `briefs/`, `plan.json`, `script_v*.json|md`, `critic_v*.json`, `source_check_v*[_cK][_sN].json` (per group K and sample N), `strength_audit_v*.json`, `script_final.md`;
- `script_final.txt`: the narration alone, for a voice-over tool (a season also writes `season_script.md`, every episode in order);
- `report.md` and `report.json`;
- `review.html`: the owner's review page. Each paragraph sits next to its cited brief items and source passages, with findings marked. It ends with the review form, whose button copies a filled `review_form.md`;
- `review_form.md`;
- `calls.jsonl`: every model call, with raw output, validation errors and token usage;
- `run_manifest.json`: scope, background chapters, where each brief came from, profile, model, prompt and schema sha256, tokens per stage, the glossary state and the status. Episode runs also write `memory_recap.json`.

Story memory lives in `.local/story_memory/<story id>/`: `chapters/` (one brief per chapter) and `glossary.yaml`, the name glossary.
- The glossary is synced from the roster after the briefs; new characters get their brief romanization.
- Edit `display` (and `also_allowed`) to choose the spelling viewers hear, for example Sino-Vietnamese names for a Chinese novel, then set `confirmed: true`.
- The pipeline never overwrites these edits. It tells the writer the display names, and flags any other spelling of the same character as a MEDIUM finding.

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

**2026-11-13, run 7 (memory re-validation and the brief hedge check, live).**

The run COMPLETED in 7 calls and 397 s.

- **Memory:** the stored chapter-1 brief from run 5 failed the current checks, with two hearsay facts (「そうだ」, 「らしく」). It was regenerated (`model (memory stale)`).
- **First new brief:** rejected for three reasons:
  - the metaphor 「比喩」 was stated as a nickname;
  - the hearsay 「らしい」 was stated as fact;
  - it listed 4 events where 5 are required.
- **Second brief:** passed, with "được ví như Thiên sứ" (likened to an angel) and "nghe nói ... được tỏ tình" (said to receive confessions).
- **Strength audit:** 9 findings in v1, 0 in v2. All automated gates passed.

Manual check of the final script against the two defects that had persisted since run 2:
- "everyone's nickname Angel" became "được ví như Thiên sứ";
- confessions are now attributed with "Nghe nói".

The closing hook is rendered faithfully ("Nhưng đó chỉ là những gì cậu nghĩ vào lúc ấy mà thôi"), and Amane is addressed with one pronoun throughout. Remaining small issue: Mahiru's hair is rendered as chestnut, where 亜麻色 means flaxen.

**Review of run 7's final script, and hedge checks for the script.**

Manual reading found three medium defects:
- "not waiting for anyone" is presented as Mahiru's words, but in 1.22 it is the narrator's 「なさそう」 ("seems not to").
- Wariness towards "the opposite sex" is stated as fact, but in 1.39 it is Amane's guess 「かもしれない」.
- "a pained expression" is stated as fact, but 1.26 has 「ように見えて」 ("seemed").

There were two small ones as well: hair rendered as chestnut instead of 亜麻色 (flaxen), and "on a whim" applied to the umbrella rather than to speaking to her (1.45).

Tracing showed that none of the three medium defects is hedged in the brief. They entered at the brief stage, through passages the brief cited but did not quote.

Two additions:

- **Script hedge audit (feeds revision).** For each paragraph, the hedged *clauses* of the brief items its claims cite are compared with the paragraph's own sentences. Clauses are split at punctuation and at each language's conjunctions, listed in the lexicons as `clause_markers`. A sentence that retells such a clause (bigram similarity >= 0.5) without a hedge becomes a MEDIUM finding.
  - The first, item-level version flagged sentences that retold the *unhedged* half of a joined statement.
  - On the saved scripts of runs 2, 3, 4, 5 and 7 the final version has no false positives, and also no catches, because the writers kept every hedge the briefs had.
  - It needs the brief and the script in one language.
- **Source hedge review (advisory, in report.md).** It lists brief items with no hedge although a *cited* passage carries one outside dialogue. Over runs 2–7 roughly half of these were real: a metaphor turned into a nickname, 「そうだ」 hearsay, 「ように見え」 dropped. The rest were hedges about something else in the same passage; for run 7 it was 1 of 4. Because forcing hedges onto true facts would distort them, this list is shown to a person and never sent back to the model.

The remaining gap is brief items that summarise several passages. A deterministic check cannot tell which passage a clause came from across languages. The next step would be per-clause evidence and an explicit epistemic label in the brief schema.

**Epistemic labels and atomic facts in the brief.**

Every fact, relationship and event now carries `epistemic`: EXPLICIT, REPORTED, APPEARANCE, SPECULATION or FIGURATIVE. The model sets it from every cited passage, quoted or not, and the checks bind it in two directions:
- A quoted sentence with a hedge cannot be labelled EXPLICIT (hard).
- A non-EXPLICIT label requires a hedge of that kind in the item's text, with FIGURATIVE requiring a metaphor (hard). This direction needs only the brief language's lexicon.

The script hedge audit reads the labels too, so a labelled item that the script tells as plain fact is a MEDIUM finding. A soft check asks for one fact per item: at most 2 clauses (`MAX_FACT_CLAUSES`), so that each fact has its own quote and label.

**2026-11-14, run 8 (labels, live): FAILED at the brief, a false positive.**

The first repair produced a brief with only soft (atomicity) errors. The second split the joined facts as asked, and one of them, "Amane is in a different class", quoted the start of 1.8:

> 周はクラスが違うので詳しくは知らないが、噂通りなら完璧超人なんじゃないかと思うほどである。

The 噂 (rumour) belongs to the part after 「知らないが、」, but the check looked at the whole sentence, so it demanded REPORTED. Two fixes:
- **Hedges stop at a contrast.** Lexicons list `contrast_endings` (ja が after a predicate as in 知らないが, けど, のに; ko 지만, 는데) and `contrast_openers` (en but, although; vi nhưng; ja しかし). The brief check only looks at the parts of the sentence the quote overlaps. A sentence without a contrast keeps its whole-sentence reach, because Japanese hedges are usually sentence-final. A bare が after a noun (「真昼が、」) is the subject particle and does not split.
- **A regressed repair no longer loses a usable result.** When the last attempt has hard errors, `run_json_stage` returns the latest attempt that had only soft errors.

**2026-11-14, run 9 (same code plus the fixes, live).**

The run COMPLETED in 10 calls and 976 s. The brief passed on its third attempt; the earlier ones failed on an `unknowns` schema error and on having 4 events where 5 are required. It kept 3 soft atomicity errors. One script call fell back from the first model after 4 server failures. The strength audit found 15 findings in v1 and 1 in v2. All gates passed except GATE_EPISTEMIC_INTEGRITY (one MEDIUM, see the minor issues below).

The brief's labels:
- the angel image is FIGURATIVE ("được ví như");
- the three reputation facts (grades and sport, temperament, confessions) are REPORTED ("nghe nói");
- everything else is EXPLICIT.

Manual check of the final script against run 7's defects:
- "not waiting for anyone" as Mahiru's words (1.22 「なさそう」): gone.
- Wariness towards the opposite sex as fact (1.39 「かもしれない」): gone. The wariness the script mentions is 1.35's explicit 「警戒が滲んだ」, and the confessions remain "nghe nói".
- "a pained expression" (1.26 「ように見えて」): now "trông như sắp khóc" (looked about to cry).
- Hair: now "màu lanh" (flaxen) for 亜麻色.

New minor issues:
- "sự đề phòng lộ rõ" (clearly visible) for 「うっすらと」 (faintly).
- "mưa bão" (storm) for 雨.
- "bạn bè ví như" attributes the narrator's metaphor to classmates.
- "hết sức bình lặng" (an unsourced intensifier, flagged by the strength audit but not fixed in the single revision round).
- The closing line says Amane's belief "did not match what was about to happen". The source's 「その時は。」 only implies this; run 7's "đó chỉ là những gì cậu nghĩ vào lúc ấy" was more faithful.

The LLM critic again reported no problems with the final script.

**2026-11-14, run 10 (first episode run: chapters 2–5 with a recap of chapter 1, two revision rounds, 2,400–3,000 words).**

The run COMPLETED in 24 calls and 1,787 s. All gates passed.

- **Briefs:** chapter 1 came from memory; chapters 2–5 were generated, and each took all three attempts. The first attempts failed on too few events, on hedges (a guess, an appearance and a metaphor labelled EXPLICIT, hearsay stated as fact) and on a schema error.
- **The run-8 repair fallback mattered:** the chapter-4 brief's last attempt had hard errors, and the attempt before it, with soft errors only, was used. Without the fallback the run would have failed.
- **Audits:** 26 findings in v1, 1 in v2, 0 in v3. The second revision round removed the last finding, which one round had left in run 9.
- **Episode mechanics:** the recap was used only for the umbrella callback. The script ends on chapter 5's closing line.

Manual check of the final script against the source of chapters 2–5 found three medium defects that no automated check reported:

- **An invented detail that contradicts the source.** The script says the porridge arrived "nghi ngút khói" (steaming). 3.81 says it gave off no steam and had been cooled on purpose. The writer added this in v1. It is not in the brief, and the critic passed it three times.
- **A narrator's thought turned into speech.** The "lost child" look (4.18) is Amane's thought. The brief records it correctly as a FIGURATIVE fact about him. The script has Amane explain it to Mahiru.
- **A cause dropped and a manner inverted.** In the source Mahiru answers the boyfriend question with exasperation and turns cold only at Amane's "one or two" (4.24, 4.30); 4.32 and 4.37 describe flat words and a chilling look, explicitly not heat. The brief keeps the trigger. The script merges the two events, drops the trigger and calls the reaction "dữ dội" (fierce).

Eight small ones as well: strengthened wording ("đỏ bừng mặt" for a faint blush, "sốt nặng"), small invented details, the weekend compressed into "the next day", and a remark Amane says aloud told as a thought. The text also has a garbage token ("so me"), which v2 had removed and v3 brought back, four misspellings, and one "anh" for Amane, who is "cậu" everywhere else.

What this run shows:

- The hedge and strength checks hold on four new chapters: no hearsay or appearance was stated as fact.
- The remaining defects are of kinds the lexicon checks cannot see: invented descriptive details, who says or thinks something, and merged events. All three entered at the script stage, and the briefs were right. The critic compares the script with the briefs and still missed them.
- Revision can undo an earlier fix (the garbage token).

Candidate next steps:

- A second verification pass that checks script sentences against the cited source passages, not only against the briefs.
- A deterministic check that speech and thought verbs in the script match the brief item's kind.
- A check that each revision keeps the fixes of the one before it.

**Attribution audit and source check (added after run 10).**

- **Attribution audit (deterministic, feeds revision).** It looks at the content of reported speech in the script ("X giải thích **rằng** |…"). If that content retells a brief statement better than any other, and the statement involves no speech at all, the sentence is a MEDIUM finding. A statement involves speech if its text has a verb of saying, or its quote or any cited passage has dialogue. Verbs and complementizers are optional lexicon fields (`speech_verbs`, `speech_complementizers`; vi and en so far). On the saved scripts of runs 2–10 (15 versions) it flags only run 10's "lost child" sentence. The first, looser prototype had 9 false positives for 1 catch.
- **Source check (LLM, feeds revision).** A second verifier gets the episode's source text and every paragraph. It reports, quoting the script exactly:
  - CONTRADICTS_SOURCE, NOT_IN_SOURCE and WRONG_SPEAKER;
  - STRENGTHENED and WRONG_CAUSE.

  Answers are rejected if a quote is not in its paragraph, a passage is outside the episode, or a paragraph is missing. It adds one call per script version, and is skipped (and recorded) above 60,000 source characters.
- **Before integrating:** on run 10's final script, five trial calls in two designs returned 12 findings, all real:
  - "steaming" porridge (4 of 5 calls);
  - the lost-child speech (4/5);
  - Itsuki's boast (3/5);
  - "back at school the next day" (1/5);
  - a strong blush (1/5);
  - an "eat the whole bowl" instruction that the manual review had missed (1/5).

  Giving the whole source worked better than giving each paragraph only its cited passages: the porridge passage (3.81) belonged to the next brief event. No trial call caught "fierce".

**2026-11-15, run 13 (run 10's settings plus both checks).**

The run COMPLETED in 14 calls and 875 s. All five briefs came from memory and passed the current checks. Findings for revision went 29 → 8 → 4.

- **Source check:**
  - v1: three real findings: the steaming porridge, Itsuki's boast, and Mahiru "calling his name" (5.39 has no name).
  - v2: five real errors, all introduced by the first revision: Amane "falling flat on the floor" (2.71: he sways towards the wall), a scene moved to the shoe lockers, "two days ill in bed" (5.3: well the next day), and two smaller ones.
  - v3: the WRONG_CAUSE "fierce" finding that no earlier check or trial call had caught, with the trigger (4.24) named.
- **Attribution audit:** it flagged Amane "explaining" Mahiru's virtues (top of the year, good at sport). In the source those come from the narrator (4.26–4.27), and Amane only says she is popular (4.24). Partly true: the gist was spoken, but the list was not.
- **Final script, checked by hand:**
  - The steaming porridge and the lost-child speech are gone. The lost-child look is now Amane's recollection, as in the source.
  - "Fierce" is still there, but the report now names it. It is no longer a silent pass.
  - Remaining, unflagged: "đỏ bừng cả mặt" (3.47: faintly), "eat the whole bowl" (not in 3.76), and "nghe nói" for messages Amane himself received (5.8).
  - The strength audit flagged "đúng không mọi người?", where "mọi người" addresses the audience. That is a false positive.
- **Gates:** they now report GATE_FACTUAL_GROUNDING and GATE_EPISTEMIC_INTEGRITY as needing review, with four MEDIUM findings after the two revision rounds. Run 10 passed every gate with three real defects inside.

What this shows:

- Reading the script against the source catches the class of defect the brief-based critic cannot see, including errors that revision itself introduces.
- Recall is still partial and varies from call to call, so the source check narrows the manual review but does not replace it.

**Patch-mode revision and audience address (added after run 13).**

- **Patch mode:** rounds after `--full-revision-rounds` (default 1) no longer rewrite the script. The model returns sentence-level edits (`script_patch_v0`). Each edit must copy its span exactly once from the named paragraph and must not add foreign-script characters. Code applies the edits in place, and a whole beat cannot be deleted.
- **Audience address:** phrases that address the viewers (`audience_address` in the lexicon, for example "đúng không mọi người") are blanked out before the strength audit reads a sentence.

**2026-11-15, run 14 (run 13 resumed after v2, then a patch round).**

Run 14 reused run 13's briefs, plan and versions 1–2 unchanged, so its v3 can be compared directly with run 13's full-rewrite v3. It took 4 new calls and 219 s.

- **The patch fixed all 8 findings in one valid call.** It changed 7 of 30 paragraphs; the other 23 are byte-identical. Every edit is a minimal, correct replacement:
  - "ngã rạp xuống sàn" became "kéo cậu lại để giúp cậu lấy lại tư thế";
  - the invented shoe-locker scene and "two days ill in bed" were removed;
  - "ai cũng" and "lúc nào cũng" were dropped.
- **v3:** neither the critic nor the source check reported anything. Run 13's full-rewrite v3 had 4 MEDIUM findings, and its rewrite had earlier introduced 5 new errors.
- **Defects known from manual review that are still in run 14's v3, unflagged:**
  - "phản ứng dữ dội": run 13's v3 source check caught it, this run's single call did not;
  - "đỏ bừng", the "eat the whole bowl" instruction;
  - a new "Nghe nói" before the weekend messages. The brief labelled that fact REPORTED because 5.8 says Itsuki "seems to have been worried" (らしく), but the messages themselves are plain narration. The hedge audit then asked the patch to add the hedge.

What this shows:

- Patching is the right tool for the last findings: it fixes what is flagged and touches nothing else.
- The weak point is now recall. A single source-check call misses defects that another call catches. Five trial calls returned only real findings, so taking the union of two calls per version is the obvious next step (one more call per version).
- The 「らしく」 case is another hedge-scope error, in the brief this time: a hedge on the worry is applied to the messages in the same sentence.

**Pooled source check and one-statement labelled facts (added after run 14).**

- **Pooled source check:** two independent source-check calls per version by default. Their findings are pooled, and findings on one paragraph with overlapping quotes count once.
- **One-statement labelled facts:** a brief fact labelled anything but EXPLICIT may not join two statements (a soft check). Coordinated parts shorter than 5 words, such as nouns in a list, do not count as statements.

  Tracing run 14 showed that the cause was not a hedge-scope error. The brief joined "reportedly worried" (5.8 「心配していたらしく」) and "sent messages" in one REPORTED fact, so the hedge audit asked for a hedge on the messages too.

**2026-11-15, run 15 (chapters 2–5; chapters 2 and 5 re-briefed; 1 full revision and 2 patch rounds; pooled source check).**

The run COMPLETED in 27 calls and 1,485 s. Findings for revision went 31 → 9 → 2 → 2.

- **Briefs:**
  - Chapter 2 needed three attempts. The first two failed on hedge labels (らしく, だろう), on too few events and on a quote that was not verbatim.
  - Chapter 5's last attempt hit a hard hedge error, so the earlier soft-only attempt was used. That attempt still joins "reportedly worried" and "sent messages". The soft check asked for a split, but the fallback restored the joined fact.
- **Source check:** two calls per version. Real findings by version:
  - v1: the writer invented steaming porridge twice ("nóng hổi", "nghi ngút khói"), Mahiru "sitting" where 3.21 has her standing, an invented gel pack nearly dropped, and a cause for Itsuki noticing that the source does not give.
  - v2: an invented "ask the teachers to go home early", and a reversed rumour.
  - v4: "đỏ bừng" (3.47: faintly). This is the first time it was flagged, but the revision rounds were used up.
- **Final script, checked by hand:**
  - Fixed: the porridge, now in the source's own terms ("không hề bốc khói nghi ngút mà đã được cô cố tình làm nguội bớt"); the lost-child look, now a recollection; the "nghe nói" before the messages, now gone.
  - Mahiru's reaction is now "ánh mắt lạnh ngắt và phản ứng gay gắt", closer to 4.32, though "gay gắt" is still a little strong.
  - Remaining: "đỏ bừng" (flagged), a strong "dữ dội" for the headache (2.6 「ずきずき」), and an awkward "nghe nói chưa từng có đồn đại" (3.41).
  - The run started before `review.html` existed. Its review page was rendered afterwards from its saved outputs.

Across runs 10, 13, 14 and 15 on the same chapters:

| | Run 10 | Run 13 | Run 14 | Run 15 |
|---|---|---|---|---|
| Medium defects found by hand in the final script | 3 | 1 (flagged) | 3 (unflagged) | 1 (flagged) |
| Of which reported by the gates | 0 | 1 | 0 | 1 |

**2026-11-15, season S1 (first live run of `run_story`: chapters 1–5 as episodes 1, 2–3 and 4–5; 3 revision rounds, profile length 900–1,100 words).**

The season COMPLETED in 52 calls, 884,372 tokens and 1,854 s. Every brief came from memory. The critic is the most expensive stage in every episode. `season.md` links each episode's report and review page.

| Episode | Chapters | Calls | Tokens | Findings by version | Left (flagged) |
|---|---|---|---|---|---|
| 1 | 1 | 15 | 205,201 | 11 → 2 → 1 | "cuộc sống bình lặng" (not in the source) |
| 2 | 2–3 | 14 | 249,629 | 7 → 2 → 0 | — |
| 3 | 4–5 | 23 | 429,542 | 18 → 3 → 6 → 1 | a hedge from a joined brief fact |

Manual check of the three scripts:

- **Episode 1:** the closing line is faithful ("Nhưng đó chỉ là những gì Amane nghĩ vào lúc ấy mà thôi..."). "Nghe nói ... **thường xuyên** nhận được lời tỏ tình" keeps the hearsay but carries the brief's "thường xuyên". The new advisory list of briefs stronger than their source names that item.
- **Episode 2:** no invented steam or posture this time, and no "đỏ bừng". The only issue is a strong "đau nhức dữ dội" for 2.6's throbbing headache.
- **Episode 3:** the lost-child look is Amane's comparison, as in the source. Mahiru's reaction is "gay gắt", still a little strong.
- **Across episodes:** Amane is "cậu" in episodes 1 and 2 and "anh" in episode 3. Each episode chose its pronoun on its own. This is a defect only a season shows, and it led to the glossary's `pronoun` field.

The tokens give a first cost estimate: about 175,000 tokens per chapter at these settings, so about 5.3 million for 30 chapters.

**2026-11-15, run 16 (season episode 3 again, with the concrete no-invented-detail rule and glossary pronouns Amane "cậu" and Mahiru "cô").**

The run COMPLETED in 17 calls, 323,269 tokens and 636 s. Findings went 17 → 4 → 6 → 3.

- **Pronoun:** Amane is "anh" 2 times, against 13 in season S1's episode 3. One sentence at the very end still slips. The rule is prompt-only; no deterministic check follows it.
- **Invented details:** the writer still added some, such as Mahiru "about to step out of the door" and a "gentle smile". The source check caught them in v1 and the revision removed them.
- **Left (flagged):** Mahiru's "phản ứng rất gay gắt". It survived three rounds; each rewrite kept a strong word for 4.32's flat, cold refusal.

**2026-11-15, Korean seasons (original two-chapter text, prepared with `prepare_source`, 180–300 words an episode).**

- **First season:** completed in 21 calls, with no flagged findings left.
  - The story's memory and glossary live apart from the Japanese sample's, as intended.
  - Names follow the glossary (Seo Ji-woo, Han So-yeon, Park Do-hyeon).
  - 「…다고들 한다」 became "nghe nói".
  - But Ji-woo was "cậu" in episode 1 and "anh" in episode 2.
- **Pronoun adoption:** counting pronouns near names could not fix this; it picked "cậu" for Mahiru in the Japanese season, because in two-person scenes the pronoun is about the other character. Instead, the writer now declares its pronouns in the script (`pronouns`). After a run, the glossary records them for characters that have none; owner-set pronouns are never changed. Later episodes are told the pronoun, and the pronoun check flags drift.
- **Pronoun check:** a sentence that names glossary characters who all have pronouns, and uses a third-person pronoun the glossary assigns to nobody, is a MEDIUM finding. Nouns such as "anh chàng" are excluded. On nine saved scripts it flags 13 sentences, all real.
- **Second season (rerun from scratch):** episode 1 declared Ji-woo "cậu" and So-yeon "cô", and the glossary recorded them. Episode 2 used "cậu" 5 times and "anh" 0 times.
- **Over-hedging:** the same episode hedged plain actions ("dường như cúi đầu chào").
  - The brief had labelled "seemed to stop, then bowed" APPEARANCE as one event.
  - The one-statement rule for labelled facts now covers events. 5 of the 6 events it flags on saved briefs mix a plain action with a hedge.

**2026-11-15, season S2 (chapters 1–5, the same episodes as S1, fresh briefs, every check added today).**

The season COMPLETED in three invocations; the season runner resumed episode 3 twice. The first two invocations each stopped on a robustness defect that the live free-tier conditions exposed:

- **First stop:** `gemini-3.6-flash` and `gemini-3.5-flash` were rate-limited (429) by then, so the critic ran on `gemini-3-flash-preview`. That model spent about 63,000 tokens thinking and cut its JSON off on all three attempts. Fix: a MAX_TOKENS finish now moves to the next model, and finish reasons are logged.
- **Second stop:** the next fallback model wrote paragraph ids as `<P001>`, so every source-check answer was rejected. Fix: tag brackets are tolerated, and a source check that fails after its repairs is recorded (`source_check_failed`) instead of failing the episode.

| Episode | Calls | Tokens | Findings by version | Left |
|---|---|---|---|---|
| 1 (ch. 1) | 14 | 207,947 | 14 → 0 | — |
| 2 (ch. 2–3) | 31 | 653,295 | 11 → 7 → 3 → 4 | 4 LOW critic findings, all true to the source (2.34, 3.18, 3.65–3.69): the details were missing from the briefs, the critic's truth boundary |
| 3 (ch. 4–5) | 10 (this invocation) | 378,520 | 14 → 6 → 9 → 4 | 2 source-check findings (a smile, "fruit jelly"), 1 critic MEDIUM, 1 critic LOW |

- **Pronouns:** Amane is "cậu" 51 times and "anh" once across the season, against "anh" 13 times in S1's episode 3. Episode 2 also recorded Itsuki's pronoun ("cậu") from the writer's declaration.
- **Not seen in this season:** invented steam, "đỏ bừng", "dữ dội" or the lost-child speech.
- **Limit — critic false positives:** a LOW critic finding can be a faithful detail that the brief left out. The source check, which reads the source, did not flag these four.

**Source check adjudicates the critic's findings (added after season S2).**

- **Why:** the critic judges the script against the briefs, so a detail that the source says but the brief left out looks invented. All four findings left in S2's episode 2 were of this kind.
- **How:** the source check, which already reads the whole episode, also receives the critic's problem claims (F1, F2…). For each it answers `IN_SOURCE` (naming the passages) or `NOT_IN_SOURCE` in `critic_reviews`. There is no extra call. Answers are rejected when a flag is unanswered or answered twice, when IN_SOURCE names no passage, or when a passage is outside the episode.
- **Effect:** a critic finding is overturned only when every source-check sample that answered says IN_SOURCE; one dissent keeps it. Overturned findings leave revision and the gates. They are listed as brief gaps (`report.json` `brief_gaps`, "Brief bỏ sót" in `report.md` and `review.html`) with the cited passages, so a person can check them. Each version records `critic_overturned`.
- **Live trial (S2 episode 2, v4 script and critic, `gemini-3.6-flash`, 2 samples, about 15,000 tokens a call):**
  - All four false positives were overturned by both samples, citing 2.34, 3.8/3.18, 3.65–3.69 and 3.65/3.68. A manual check of those passages agrees.
  - Negative control: four wrong statements were added as critic claims. They were run 10's real "steaming porridge" defect (contradicted by 3.81), an invented piggyback home, an invented confession and a fever "so high he fainted" (strengthened). Both samples answered NOT_IN_SOURCE for all four, and three of the four answers cited the passage that contradicts the claim.
  - Result: 8 of 8 verdicts correct in both samples. This is one episode; the verifier can still be wrong, which is why a single dissent keeps a finding.

**2026-11-15, run 17 (chapters 2–3 again, briefs from S2's memory, incremental checks; `gemini-3.6-flash` throughout).**

The run COMPLETED in 17 calls, 234,402 tokens and 357 s. S2's episode 2 took 31 calls and 653,295 tokens.

- **Where the difference comes from:** mostly not from incremental checks. This run needed no fallback model and almost no repairs, while S2's episode 2 ran three source checks on `gemini-3-flash-preview` at 32–71k tokens each and repeated four critic calls. S2's briefs (83k) were also reused from memory here.
- **What incremental checks saved:** paragraphs checked by version were 14 → 7 → 1 → 1. A call's prompt is mostly the briefs (critic) or the source (source check), so one paragraph still costs about half a full call: the critic went 23.9k (v1) → 17.5k → 12.6k → 11.4k, and the source check about 15k → 9k. Against full rechecks of v2–v4, this saves about 55k tokens, or 19% of the run.
- **Findings by version:** 9 → 1 → 1 → 1.
  - v1: the source check caught "Mahiru chẳng hề phàn nàn", which contradicts 3.18 where she does complain. In S2 the critic had wrongly flagged the faithful version of the same detail.
  - Left: "Rất nhanh trí" (quick-witted) for 2.73, where she only pulls his arm. A small embellishment, flagged for the reader.
- **Recall depends on how much a call sees.** Paragraph P006 contained three defects from v1 on: "trượt chân" (2.71: he sways toward the wall), Amane refusing help (2.81: he has no strength to resist) and "rất nhanh trí". Both whole-script checks of v1 missed all three. P006 was then rechecked alone in each later version, and each recheck found one of them. Incremental checks keep that focus on changed paragraphs, but give unchanged paragraphs fewer looks. A chunked source check is being measured next.

**Chunked source check (added after run 17).** On run 17's v1 script, the same source check was run with fewer paragraphs per call:

| Paragraphs per call | Calls | Defects found | Tokens |
|---|---|---|---|
| all 14, 2 samples (old default) | 2 | 2 | about 30k |
| 4, 1 sample | 4 | 7 | about 42k |
| 4, 2 samples pooled | 8 | 8 | about 84k |
| 2, 1 sample | 7 | 5 | about 73k |

- Seven of the eight defects are real. They include "cháo mận" announced before Amane sees it, a reversed rumour (3.41: he never heard she failed, not "heard she never failed"), "buổi chiều" for 7 p.m. (3.23) and a measurement 3.69–3.70 says did not happen then. The eighth ("định đóng cửa") is borderline.
- The two whole-script samples found only the two P008 contradictions, which every grouped call also found. Smaller groups are not better without limit: two paragraphs per call found fewer than four.
- The default is now 4 paragraphs per call and 1 sample. Each group is cached as `source_check_v{n}_c{k}.json`. With one sample, a critic finding is overturned on a single IN_SOURCE verdict; the adjudication trial had 8 of 8 single-sample verdicts right.

**Owner corrections (`--apply-review`).** The owner writes errors in `review_form.md` as `- "câu trong kịch bản" → vì sao sai` (review.html's copy button produces the same).

- Rerunning with `--resume <run dir> --apply-review` places each quote in the final script's paragraph (whitespace-insensitive) and fixes them in one patch round, first in the list and at HIGH severity. Only the paragraphs that changed are checked again.
- `report.md` lists each error as fixed, still present, or not found; lines without a quote are notes no round can apply.
- The round is recorded in `owner_review.json`, so later resumes replay it from the saved scripts. The filled form is kept as `review_form_reviewed_N.md`, and `review_summary` still counts it.
- `run_story` with `--apply-review` reruns only completed episodes whose form has errors not yet applied.
- Before this, a resumed run rewrote `review_form.md` and would have erased a filled form.
- Status per error: fixed; fixed but the paragraph still has findings (a rewrite can be wrong too); quote still present; quote not found.

**Live trial of `--apply-review` (a copy of run 17).** Run 17's final script had passed with one flag. Five of the defects that the grouped source check found in v1 were still in it. They were written into the form as an agent's test review, without scores, so `review_summary` does not count it.
- The correction round took 4 calls, 53,822 tokens and 81 s. All five quoted sentences were replaced.
- Three replacements are right: no "nhanh trí", "cháo" without the plum, "buổi tối".
- The rumour sentence is now faithful to 3.41, but the hedge audit flags it. The brief labels "there is no rumour that she failed" as REPORTED, so the audit asks for "nghe nói". This is a brief error, not a script error.
- The thermometer sentence is still wrong: "khi cô bước ra ngoài, cậu mới kẹp nhiệt kế". The recheck caught it, and the report marks it "fixed but still flagged". The owner's note should say what happened, not only what is wrong.
- Settings: a resume reuses saved stage outputs only under the same source-check grouping. This copy of a run made before grouping was resumed with `--source-check-chunk 0 --source-check-samples 2`. Since then the run manifest records its `invocation`, and `--resume <dir>` restores every option not given again (older runs are read from their scope and settings).

**Callbacks from brief retrieval (M6 Phase 2).** An episode's recap carried only the CORE events of earlier chapters, so a plan could not call back to a SUPPORTING or MINOR setup (an umbrella lent in chapter 1, a rumour heard in chapter 2).

- In recap mode, every event summary of the episode is used as one query to `tools/story_retrieval/brief_retrieval_v1.py`. The corpus is the background chapters' briefs only, with a cutoff of the chapter before the episode.
- The two best earlier events per query that the recap does not already carry are pooled, up to 8. They are added to `memory_recap.json` as `callbacks`: ref, chapter, summary, importance, epistemic label, quote and evidence ids. The run manifest lists their refs (`callbacks`).
- The plan may cite them like recap CORE events. The audits read their own epistemic label, so a recalled rumour must stay a rumour.
- `--no-callbacks` turns this off. If the corpus cannot be built (for example a background brief cites a passage outside its chapter), the reason is recorded as `callbacks_skipped`, and the episode runs on without callbacks.

**Story Brief for review (M7).** `docs/TARGET_ARCHITECTURE.md` presents the Story Brief to the user before planning ("approve / edit / continue"). Every run now writes the episode's declared factual boundary, built deterministically by `tools/story_pipeline/episode_brief.py` once the briefs, the recap and the callbacks are final:

- `story_brief.json` (`EPISODE_STORY_BRIEF/v1`) holds:
  - the scope and spoiler cutoff;
  - per chapter: events with importance, characters (glossary display names) with facts, relationships, unknowns, forbidden inferences and the closing hook;
  - an `uncertain` list of every item not labelled EXPLICIT;
  - the earlier-chapter background (recap CORE events and callbacks);
  - counts.

  Every item keeps its ref (`c3.E2`, `c3.CH1.F2`, `c3.R1`, the brief-retrieval scheme) and evidence ids.
- `story_brief.md`, and `story_brief.html`, which puts each item beside the source passages it cites and highlights uncertain items.
- `brief_review_form.md` has one line per item: `- [ ] sai [ ] bỏ \`ref\` ...`.
  - `[x] bỏ` drops the item. `[x] sai` with `→ correct text` at the end of the line replaces its text.
  - A wrong mark without a correction, or an unknown ref, is reported and not applied.
- The intended loop is `--stop-after brief`, then review, then `--resume <run dir>`.
  - On resume, a filled form becomes a round in `brief_review.json` and is kept as `brief_review_form_reviewed_N.md`. Each round is applied in order to this run's episode briefs, before planning.
  - `manifest["brief_review"]` lists every change. A dropped CORE event is flagged. `after_plan` is true when a plan already existed, since a saved plan is reused on resume.
  - Story memory and `briefs/` stay unchanged, and later resumes replay the recorded rounds.

## Known limits

- Brief paraphrase quality is not measured against gold. Quotes pin the evidence, but a
  wrong paraphrase of a correctly quoted passage still reaches the writer; the critic
  judges the script only against the briefs (the source check reads the source and
  overrules critic findings the source supports, but it does not correct the briefs).
- The critic is a model and is known (H6/H6b) to miss violations; its PASS is weak evidence.
- Word count is whitespace tokens (Vietnamese syllables), matching the M1 runs.
- No human-review workflow yet; `UNDETERMINED` claims are listed in the report for a person.
