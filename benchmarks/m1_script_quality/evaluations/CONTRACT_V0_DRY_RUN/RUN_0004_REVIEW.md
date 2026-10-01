# Contract v0 Dry-Run Review — RUN_0004 (Script B)

FIRST-PASS RECORD. Locked before the historical cross-check. Not edited afterwards.

This is an operational dry-run by an AI reviewer. It tests whether the rubric can be applied. It is **not** the independent human review that `SCRIPT_QUALITY_CONTRACT/v0` section 16 requires, and it is not evidence about the Writer, the critic or the revision stage.

## 0. Review Header

- Script / run ID: `RUN_0004_H6_CRITIC` — `runs/RUN_0004_H6_CRITIC/revised_script.md`
- Reviewer role: AI agent, Script Quality Contract Operational Reviewer
- Date: 2026-10-01
- Contract: `SCRIPT_QUALITY_CONTRACT/v0` candidate at commit `cacdc2daf02d85c5f83e0daf9e48cf31dd272cd6`
- Requested scope: chapter 1 only
- Truth boundary used: `runs/RUN_0003_H2_STORY_BRIEF/story_brief.yaml` (the same boundary as Script A), cited by key
- Narrative Profile: manifest gives Vietnamese, 900–1100 words. The revision prompt the manifest references asks to keep the third-person YouTube storytelling style, safe humor and hooks of the original request. Spoiler mode: `NONE`.
- Automated checks consulted: word count and Unicode-script count run for this review. The critic report and critic review of this run were **not** read.
- Inputs used for this record: contract, review template, run manifest, the referenced revision prompt, truth boundary, script.

**Isolation disclosure.** Same as for Script A: earlier in this working session the reviewer read the H2/H6 comparison documents and the H6b residual analysis for another task. They were not reopened and no finding was copied from them, but the reviewer was not naive.

Line references (`L`) are line numbers in `revised_script.md`.

## 1. Part A — Integrity

### Findings

| # | Script passage | Claim type | Parent / subtype | Sev. | Inv. | Gate | Boundary evidence | Reason | Suggested fix |
|---|---|---|---|---|---|---|---|---|---|
| B01 | L1 "để rồi nhận ra mình vừa bước vào một chuỗi sự kiện không lường trước được. Đó là những gì đã xảy ra" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | LOW | 05 | EPISTEMIC | `ending_state.unresolved_implication`: suggested, not established | States a suggested continuation as fact. Vague | Hedge |
| B02 | L5 "luôn bóng mượt", "sống mũi cao" | UNSUPPORTED | `UNSUPPORTED_INVENTION` (no subtype fits) | LOW | 01 | FACTUAL | `characters[1]`: hair colour and type, skin, eyes | Added attributes | Remove |
| B03 | L5 "Cái tính cách ngoan ngoãn, khiêm tốn khiến vô số nam sinh trong trường theo đuổi" | UNSUPPORTED | `CAUSALITY_ERROR` / `CAUSALITY_INVENTION` | LOW | 03 | FACTUAL | `characters[1]`: modest character; often receives confessions. No causal link | "khiến" makes her character the cause. "vô số" widens "often" | "…và cô cũng hay được các nam sinh tỏ tình" |
| B04 | L7 "Cậu nhận thức được sự hấp dẫn của cô… chủ động tránh né những phiền phức không đáng có" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | `relationships`: no romantic feelings; avoided involvement | Adds an acknowledgement and a mild motive ("trouble") | "cậu không có tình cảm gì và cũng tránh dính líu" |
| B05 | L11 "sau giờ học" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | LOW | 05 | EPISTEMIC | `setting.time_context`: after school **or** evening | Picks one branch of an either/or statement, which SQ-INV-05 names as strengthening. Negligible impact | "chiều hôm đó" |
| B06 | L11 "khu công viên nhỏ"; "chợt khựng lại"; "bộ đồng phục" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `setting.locations`: a park between school and apartment. Size, his halt and the uniform absent | Minor detail and staging | Optional removal |
| B07 | L15 "cũng chẳng có ý định tìm chỗ trú" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `HIDDEN_INTENTION_INFERENCE` | MEDIUM | 04 | FACTUAL | `events.E1`: her motivation is UNKNOWN | States her intention as fact. The same paragraph ends by saying he cannot know her reason, so the script contradicts itself | "vẫn ngồi yên dưới mưa" |
| B08 | L15 "ngước khuôn mặt nhợt nhạt lên, ánh mắt vô hồn" | STRENGTHENED / UNSUPPORTED | `UNSUPPORTED_INVENTION` / `PHYSICAL_OR_EMOTIONAL_STATE_INVENTION` | LOW | 01 | FACTUAL | `events.E1`: staring vaguely somewhere | Intensified and invented state | "nhìn vô định" |
| B09 | L17 "Người ta muốn dầm mưa thì là chuyện của người ta" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | `events.E1`: he first did not intend to get involved | Invented reasoning | "Cậu vốn không định dính vào" |
| B10 | L19 "lương tâm sẽ vô cùng cắn rứt" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | LOW | 05 | EPISTEMIC | `events.E1` consequence: his conscience pricked | Intensifier and a prediction over a supported feeling | "lương tâm cậu thấy cắn rứt" |
| B11 | L25 "Mahiru giật mình quay lại. Mái tóc… dán chặt vào gò má"; "người hàng xóm hay chạm mặt" | UNSUPPORTED / STRENGTHENED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `relationships`: she has seen his face to some degree | Invented reaction; "hay" adds frequency | Optional removal |
| B12 | L29 "Không có việc gì cả," Amane nhún vai. "…thấy hơi chướng mắt thôi."; L31 "Cảm ơn vì sự quan tâm của bạn… Xin đừng bận tâm đến tôi." | UNSUPPORTED | `UNSUPPORTED_INVENTION` (no subtype fits invented speech) + `UNSUPPORTED_ACTION_OR_STAGING` for the shrug | MEDIUM | 01 | FACTUAL | `events.E2`: his question, her two supported lines | Unrecorded lines given as direct quotes | Keep supported lines; narrate the rest indirectly |
| B13 | L33 "Giọng của Mahiru mềm mại" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | Absent | Invented manner | Optional removal |
| B14 | L35 "Giờ thì đã hỏi thăm xong, cậu có thể quay lưng bước đi mà không thấy tội lỗi nữa" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | MEDIUM | 04 | FACTUAL | `events.E3` motivation: he still felt uneasy | Invents a guilt-free state that the next paragraph reverses | Remove |
| B15 | L37 "ngồi co ro" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `scene_state_constraints`: seated | Invented posture | "ngồi trên xích đu" |
| B16 | L37 "cô ấy chắc chắn sẽ bị cảm lạnh" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | MEDIUM | 05 | EPISTEMIC | `events.E3` motivation: *if* she caught a cold | Possibility stated as certainty | "cô ấy dễ bị cảm lạnh" |
| B17 | L41 "Trước khi cô nàng kịp phản đối"; L43 "tiếng mưa đã lấn át tất cả… cũng chẳng bận tâm xem cô nói gì" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `events.E3`: her small voice heard behind him; he did not turn | Invented sequencing, cause and attitude | Narrate only what is supported |
| B18 | L45 "Cậu đã làm hết sức rồi… Việc làm đó đã giải tỏa sự cắn rứt trong lòng cậu" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | `events.E3`: he gave the umbrella because he would otherwise feel uneasy | Close to an inference from the supported motive, but stated flatly | Hedge or remove |
| B19 | L47 "Amane tin chắc rằng" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | LOW | 05 | EPISTEMIC | `ending_state.factual_state`: he thinks this is the end | "Thinks" becomes "is certain" | "Amane nghĩ rằng" |

**Cumulative escalation.** Considered and not applied. Four invented internal states remain (B04, B09, B14, B18), three of them LOW and close to supported content. They do not change how the character is understood.

### Considered and not flagged (story-claim test, §4.2)

| Passage | Decision | Why |
|---|---|---|
| L1 opening question | `COMMENTARY_RHETORIC` | Narrator to audience |
| L3 "thiên thần" in quotation marks; L5 "búp bê sống tinh xảo" | `COMMENTARY_RHETORIC` | Figures recognisable as figures |
| L5 "học sinh xuất sắc… thể thao cũng thuộc hàng top" | `SUPPORTED_FACT` | Paraphrase of the supported abilities |
| L7 "Nước giếng không phạm nước sông" | `COMMENTARY_RHETORIC` | Idiom over supported non-contact |
| L9 "buổi chiều định mệnh" | `COMMENTARY_RHETORIC` | Framing |
| L15 "Dù lý do của cô là gì thì cậu cũng chẳng thể biết được" | `SUPPORTED_FACT` | Keeps the boundary's unknown as unknown |
| L17 "dường như méo xệch… như thể sắp khóc" | `SUPPORTED_FACT` | Keeps "seemed" |
| L25 "Cô dường như nhận ra cậu" | `SUPPORTED_INFERENCE` | Hedged; she knows his name and face |
| L37 "điều đó lại khiến cậu cảm thấy áy náy vô cùng" | `SUPPORTED_FACT` | The supported motive for giving the umbrella |
| L49 "có lẽ chúng ta đành phải chờ xem…" | `COMMENTARY_RHETORIC` | Narrator sign-off; asserts no future fact |

### Gate status

| Gate | Status | Findings | Explanation |
|---|---|---|---|
| `GATE_FACTUAL_GROUNDING` | `GATE_CONDITIONAL` | B02–B04, B06–B09, B11–B15, B17, B18 | Three MEDIUM (B07, B12, B14), none material, no escalation |
| `GATE_EPISTEMIC_INTEGRITY` | `GATE_CONDITIONAL` | B01, B05, B10, B16, B19 | One MEDIUM (B16) |
| `GATE_TEMPORAL_STATE_INTEGRITY` | `GATE_PASS` | — | Order recoverable; seated throughout; identity and relationship correct |
| `GATE_SPOILER_DISCIPLINE` | `GATE_PASS` | (B01 considered) | Nothing beyond chapter 1 stated. The sign-off asserts no future fact |
| `GATE_NECESSARY_COVERAGE` | `GATE_PASS` | — | E1–E3, refusal, umbrella, ending implication present. The unknown reason is stated as unknown |
| `GATE_OUTPUT_INTEGRITY` | `GATE_PASS` | — | Latin-script letters only; no meta text |
| `GATE_REQUEST_COMPLIANCE` | `GATE_PASS` | — | 1074 words recorded; 1021 by whitespace recount. Both inside 900–1100 |

## 2. Part B — Narrative

| Dimension | Rating | Evidence | Why |
|---|---|---|---|
| `HOOK_STRENGTH` | 4 | L1 | Same curiosity-first question as Script A, now three short sentences |
| `NARRATIVE_FLOW` | 4 | L1 → L3–L7 → L9 → L11–L43 → L45–L49 | Hook, short setup, scene, close. Transitions clean |
| `PACING` | 4 | 274 of 1021 words (27%) before the rain scene; the scene L11–L43 carries most of the script | Reaches the inciting situation quickly. L35–L37 still loops once over his conscience |
| `EMOTIONAL_IMPACT` | 4 | L17, L37–L41 | The near-tears moment and the umbrella land with less inflation |
| `HUMOR_COMMENTARY_QUALITY` | 3 | L7 idiom; L13 "cô nàng đang làm cái quái gì ở đây vậy?" | Present and acceptable. Much of the narrator's voice is gone; the profile asks for light humor and reactions |
| `CALLBACK_QUALITY` | 3 | L1 and L49 | The ending returns to the hook, but the last sentence ("chờ xem 'khi đó' sẽ như thế nào") is awkward |
| `NARRATION_NATURALNESS` | 3 | L19 "Lương tâm… bắt đầu lên tiếng. Cậu cảm thấy… lương tâm sẽ vô cùng cắn rứt"; L49 | Mostly natural. Some compressed lines read like summary, with repetition; the final sentence is unclear when read aloud |
| `OVERALL_USEFULNESS` | 4 | — | Usable after a pass on four sentences and the ending line |

## 3. Edit Cost

Edit cost: `MODERATE`

Concrete edits:

1. Soften or remove four MEDIUM findings: B07, B12, B14, B16.
2. Rewrite the final sentence (L49).
3. Optional word-level fixes for the LOW findings (B01, B05, B10, B19 are single words or phrases).

Reason: several sentences change; structure and length stay. More than word-level, so not `MINIMAL`.

## 4. Verdict

**Dry-run trace** (this reviewer's judgements standing in for the audit):

```text
No gate GATE_FAIL; edit cost is not REWRITE          → not FAIL
No gate GATE_NOT_DETERMINED; no soft dimension ≤ 2;
edit cost is not MAJOR                               → not REVIEW_REQUIRED
Two gates GATE_CONDITIONAL; edit cost MODERATE       → not PASS
→ PASS_WITH_MINOR_EDITS
```

**Strict contract result.** No human has audited this review. Under section 16 the five semantic gates are `GATE_NOT_DETERMINED` and the contract verdict is `REVIEW_REQUIRED`.

**Sensitivity.** If a reviewer rated B07 or B16 HIGH, the verdict would be `FAIL`. This reviewer sees no basis for that: neither changes the interpretation of the scene, and B07 is corrected by the script's own next sentence. If a reviewer rated `NARRATION_NATURALNESS` 2, the verdict would be `REVIEW_REQUIRED`.

Single biggest remaining problem: a few flat statements of what the characters intend or will certainly suffer, and a weak last line.

## 5. Comparison (A versus B)

- **Which to narrate:** B. It reaches the scene sooner and carries fewer invented thoughts. A has the livelier narrator voice.
- **Which needs less editing:** B (`MODERATE`) against A (`MAJOR`).
- **Worth keeping from A as style reference:** the narrator asides ("né thính", "bay màu", "kịch kim"). They are commentary and carry no story claim.
- The contract separates the two scripts on integrity (A fails a gate; B is conditional), on pacing (2 against 4) and on edit cost, without averaging anything.
