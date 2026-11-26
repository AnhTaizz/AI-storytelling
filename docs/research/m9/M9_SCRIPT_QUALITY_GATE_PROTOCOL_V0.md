# M9 Script Quality Gate Protocol v0

`M9_SCRIPT_QUALITY_GATE_PROTOCOL/v0` · decision: DEC-033 · contract: `SCRIPT_QUALITY_CONTRACT/v0` (DEC-017)

This protocol says how the Script Quality Gate of DEC-009 is evaluated: which scripts, made how,
reviewed by whom, and what result passes. The contract judges one script against one request.
The protocol turns those verdicts into one gate result.

## 1. What is evaluated

- **Pipeline:** `STORY_PIPELINE_PROTOTYPE/v0` in season mode (`tools/story_pipeline/run_story.py`).
  The commit and the prompt fingerprints are recorded in the lock (section 3).
- **Request:** Narrative Profile `VI_YOUTUBE_CASUAL_V0` (Vietnamese, 900–1,100 words an episode,
  no spoilers beyond the episode), with the recap of earlier chapters on.
- **Model:** the single model `gemini-3.8-flash`, with no fallback chain, so that every script
  comes from the same model. Each call's model is recorded in `calls.jsonl`.
- **Settings:** the guide's season settings, `--revision-rounds 3`, with every other option at its
  default.

## 2. Sample

- **Story:** the Japanese web novel used throughout the project (`story-sample-0001`), read from the
  local Syosetu corpus through `LIGHT_NOVEL_SOURCE_MANIFEST_LATEST_LOCAL.json`.
- **Episodes:** four, of three chapters each: chapters 6–8, 9–11, 12–14 and 15–17. Each episode's
  recap covers every earlier chapter.
- **Why these chapters:** pipeline development used chapters 1–5 and short Korean and Chinese
  texts. Chapters 6–17 have not been used to tune any prompt or check.

## 3. Freeze before generation

Before the first episode, `gate_lock.json` is written in the season directory. It records:

- the repository commit;
- the SHA-256 of the profile, of the manifest and of chapters 1–17;
- the model, the exact command and the date.

The prompt fingerprints are in each episode's `run_manifest.json`.

Between the first and the last episode nothing in `tools/story_pipeline/` or its prompts may
change.

- **Allowed:** an episode interrupted by quota or the network is resumed with `run_story` from its
  saved stages.
- **Not allowed:** regenerating an episode to get a better script. Each episode has one attempt.
- **A pipeline change during the sample** restarts the sample on chapters that have not been used
  yet, and the restart is recorded.

## 4. Review

- **The project owner reviews all four scripts** in `gate_review_form.md`, produced by
  `python -m tools.story_pipeline.gate_review form <season dir>`. The form follows contract
  sections 15–18:
  - the request record is filled in;
  - the critic's remaining findings are listed as candidates, each confirmed or rejected by the
    reviewer;
  - the reviewer audits the five semantic gates against the source in `review.html`;
  - the reviewer gives the eight soft ratings, with evidence, and the edit cost.
- **The owner reviews the script as generated.** `--apply-review` or any hand edit comes after the
  gate review, never before.
- **An AI or model-assisted review may be added for triage.** It yields only a trace verdict and
  does not count toward the gate (contract section 16).

## 5. Result

`python -m tools.story_pipeline.gate_review summary <season dir> --out <dir>` computes:

- the gate statuses, trace verdict and official verdict of each form;
- the gate result.

The gate result is:

| Result | Condition |
|---|---|
| `NOT_EVALUATED` | Fewer than four scripts, a form incomplete, or a form not filled by a human |
| `FAIL` | Any official `FAIL`, any confirmed `CRITICAL` finding, or fewer than three of the four scripts `PASS` or `PASS_WITH_MINOR_EDITS` |
| `PASS` | Otherwise: no script fails, no `CRITICAL` finding, and at least 75% (three of four) `PASS` or `PASS_WITH_MINOR_EDITS` |

A `REVIEW_REQUIRED` script does not fail the gate on its own. It does not count toward the 75%.

## 6. Record

The public record is a new file under `benchmarks/m9_script_quality_gate/` with counts only:

- the verdicts;
- the gate statuses;
- the findings by taxonomy ID and severity;
- the soft ratings per script;
- the edit costs;
- the lock hashes.

Script text, source text and quotes stay under `.local/`. The result is recorded in
`docs/PROJECT_STATE.md` and in a decision.

## 7. What a result means

- **PASS** shows that this pipeline configuration met the contract on one story, in Vietnamese,
  for one reviewer. Under DEC-009 that is the evidence needed before production automation
  becomes a priority. It does not show the pipeline meets the contract on other stories, languages
  or profiles.
- **FAIL** leads to a failure analysis by gate and taxonomy, and then to fixes. Once reviewed,
  chapters 6–17 are development data, so the next attempt uses chapters 18–29.

## 8. Limits

- **Scope.** One story, one language and one profile.
- **Sample size.** Four scripts.
- **Reviewer.** One reviewer, so inter-reviewer agreement is not measured.
- **Coverage.** The coverage gate depends on the reviewer's judgement, because the contract has no
  procedure for listing necessary items (contract section 20).

## 9. Amendments

- **2026-11-24, DEC-043 — model `gemini-3.8-flash` → `gemini-3.6-flash`.** The first lock
  (2026-11-23, commit `840b6a4`) never produced an episode: `gemini-3.8-flash` returned 503 or 429
  for more than a day and episode 1 stopped at its first stages. That attempt is discarded whole,
  including its stage cache and story memory, and kept under `.local/` as
  `m9_gate_v0_aborted_3_8flash`. The sample was re-locked before any new generation with the same
  commit, profile, manifest, chapters, settings and command, changing only the model. No script was
  generated, so chapters 6–17 had not been seen by any reviewer and stay the sample.

## 10. Operational status of r2 · 2026-11-26

M9 r2 is **PAUSED** and the gate is **NOT EVALUATED**. Episode 1 has a script.
Episode 2 stopped in the chapter 10 Brief. Episodes 3 and 4 have no scripts.
The locked revision, model, inputs, settings, outputs and official scoring rule
remain as recorded by the lock and DEC-043.

On 2026-11-24 at 19:29 Bangkok time, the chapter 10 Brief exhausted its repairs
on a hard epistemic validation error. The owner authorized continuing the Brief
stage. The deviation log records the content retry separately from quota and
transport interruptions. The permission to continue the stage did not decide
whether r2 remains eligible for the gate under the one-attempt rule in section 3.
That decision belongs to the owner. Keep r2 paused pending that decision and
confirmation that the exact locked model and revision can resume.

If r2 is ineligible or cannot resume under the lock, submit a new independent
sample plan for approval. Keep all r2 evidence in its original cohort.
[Phase 7 closeout](../../engineering/PHASE_7_CLOSEOUT_20261126.md).
