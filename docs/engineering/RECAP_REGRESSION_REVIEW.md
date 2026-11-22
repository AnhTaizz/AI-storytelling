# Recap regression and model review

## Reproduce a pipeline regression

Run `python -m tools.ci.run_tests --suite story_pipeline` for the offline loop.
[The end-to-end tests](../../tests/story_pipeline/test_story_pipeline_v0.py) use
`ScriptedLLMClient` to run the real orchestrator with deterministic responses.
For a bug fix, make the relevant existing test or a new case fail for the
reported reason on the old code, then pass after the fix. Assert on the script,
report or calls that an editor or operator would observe. For example, if the
source checker fails, inspect the final verdict as well as the recorded error.

Use the [review forms](../../tools/story_pipeline/review_summary.py) for listening
trials. For a model comparison, hide the model names while rating each script,
then match the ratings to the run's usage. Keep reference plot events anchored
to source passages and independent of either model's brief.

## Changes to the recap pipeline

Use the relevant checks below when changing the corresponding behaviour. They
are acceptance criteria for those changes, not a description of existing features.

- **Plot coverage.** Check fidelity in both directions. For an omission fix,
  use a short source in which a decision has a stated cause and consequence.
  Remove the cause from the brief and script. The source-to-brief check should
  flag it even when every remaining brief event appears in the script. Keep
  uncertain motives uncertain and evidence within the episode's spoiler boundary.
- **Verification status.** Distinguish a finished run from a verified script.
  Exercise an overlong source, an unavailable checker and an unresolved claim
  when changing verdicts. Expose the affected scope and reason in the report
  the editor sees. A skipped required check cannot establish a pass.
- **Resume and memory.** When changing reuse, exercise both an unchanged run
  and a relevant input change (source, upstream output, prompt, profile or
  model route). Rebuild affected stages and reuse independent work. If a fix
  should persist across episodes, test the next episode with shared memory.
  Keep the original evidence and the approved correction traceable.
- **Model use and cost.** For a routing or context change, compare the same
  episode, length target and initial cache state. Count provider-reported input,
  output and total tokens across attempts, including repairs and fallbacks.
  Identify missing usage. Record plot omissions alongside cost. Label dry-run
  estimates separately from measured usage.
- **Channel settings and voice.** Keep point of view and compression in the
  narrative profile. For a 40–50% target, report the length basis, especially
  when source and narration use different languages. In narration trials, have
  the editor compare openings, causal clarity and spoken flow on the same scene.
  Record editing time when available. Automated checks alone measure neither
  listener preference nor editing effort.

In a pipeline PR, describe the viewer- or editor-visible effect and the check
that demonstrates it. For a quality or cost claim, identify the sample used
and what was measured. For a documentation-only change, verify the referenced
paths and run the existing repository gate.
