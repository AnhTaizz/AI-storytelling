# Contract v0 Dry-Run Review — RUN_0003 (Script A)

FIRST-PASS RECORD. Locked before the historical cross-check. Not edited afterwards.

This is an operational dry-run by an AI reviewer. It tests whether the rubric can be applied. It is **not** the independent human review that `SCRIPT_QUALITY_CONTRACT/v0` section 16 requires, and it is not evidence about the Writer.

## 0. Review Header

- Script / run ID: `RUN_0003_H2_STORY_BRIEF` — `runs/RUN_0003_H2_STORY_BRIEF/script.md`
- Reviewer role: AI agent, Script Quality Contract Operational Reviewer
- Date: 2026-10-01
- Contract: `SCRIPT_QUALITY_CONTRACT/v0` candidate at commit `cacdc2daf02d85c5f83e0daf9e48cf31dd272cd6`
- Requested scope: chapter 1 only (brief `source_scope.spoiler_boundary`)
- Truth boundary used: `runs/RUN_0003_H2_STORY_BRIEF/story_brief.yaml`. Brief fields are cited by key. The raw chapter was not consulted.
- Narrative Profile: the run manifest gives only output language (Vietnamese) and length (900–1100 words). Register, humor, perspective and hook style were taken from the script prompt the manifest references (`SCRIPT_FROM_BRIEF_PROMPT_V1.md`): spoken, youth-oriented Vietnamese for ages 15–25; light situational humor and narrator reactions; third-person storyteller; curiosity-first hook; compressed exposition; no call to action. Spoiler mode: `NONE`.
- Automated checks consulted: a word count and a Unicode-script count run for this review. No critic output.
- Inputs used for this record: contract, review template, run manifest, the referenced script prompt, truth boundary, script.

**Isolation disclosure.** Earlier in the same working session, for the contract-drafting task, this reviewer read the H1/H2/H6 comparison documents and the H6b residual analysis, which discuss this script. Those documents were not reopened for this review and no finding was copied from them, but the reviewer was not naive. `CRITIC_REVIEW.md`, `critic_report.yaml`, the H6b reference and H7 outputs had not been read.

Line references (`L`) are line numbers in `script.md`.

## 1. Part A — Integrity

### Findings

| # | Script passage | Claim type | Parent / subtype | Sev. | Inv. | Gate | Boundary evidence | Reason | Suggested fix |
|---|---|---|---|---|---|---|---|---|---|
| A01 | L1 "để rồi sau đó nhận ra mình vừa bước vào một chuỗi sự kiện không lường trước được. Đó chính xác là những gì đã xảy ra" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | LOW | 05 | EPISTEMIC | `ending_state.unresolved_implication`: continued involvement is strongly suggested, not established | States as fact a later chain of events that the boundary only suggests. Vague, no specific future fact, so impact is small | Hedge: "…mà không ngờ chuyện có thể chưa dừng ở đó" |
| A02 | L3 "ngay bên phải phòng cậu" | UNSUPPORTED | `UNSUPPORTED_INVENTION` (no subtype fits) | LOW | 01 | FACTUAL | `characters[0]`: lives in the neighbouring room. Side absent | Spatial detail not in the boundary | "ngay bên cạnh" |
| A03 | L5 "luôn bóng mượt", "không tì vết", "sống mũi cao thanh tú", "hàng mi dài" | UNSUPPORTED | `UNSUPPORTED_INVENTION` (no subtype fits) | LOW | 01 | FACTUAL | `characters[1]`: flaxen straight hair, milk-white skin, large eyes. Rest absent | Added physical attributes. Does not change interpretation | Keep to the three supported attributes |
| A04 | L7 "top 1 toàn trường" | STRENGTHENED | `EPISTEMIC_ERROR` / `REPUTATION_OR_FREQUENCY_STRENGTHENING` | LOW | 05 | EPISTEMIC | `characters[1]`: always ranked first. Scope (whole school) absent | Widens scope | "luôn đứng nhất" |
| A05 | L11 "Cậu tự biết thân biết phận, khoảng cách giữa một người bình thường và một 'thiên thần' là quá lớn" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | MEDIUM | 04 | FACTUAL | `relationships`: no romantic feelings, avoided involvement. No reason given | Invents a sense of inferiority as his motive | Remove |
| A06 | L11 "cậu biết tỏng nếu dính líu đến Mahiru thì kiểu gì cũng chuốc lấy sự ghen tị" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | MEDIUM | 04 | FACTUAL | Absent | Invents a second motive (fear of jealousy) and states it as something he knows | Remove |
| A07 | L11 "Amane thừa nhận Mahiru rất hấp dẫn… Cậu chỉ coi Mahiru như một tác phẩm nghệ thuật để ngắm nhìn từ xa" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | Only "no romantic feelings" is supported | Invented attitude, same direction as the supported fact | Reduce to "không có tình cảm yêu đương" |
| A08 | L15 "Amane chợt khựng lại"; L17 "bộ đồng phục trường" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `events.E1`: he was about to pass the park. Uniform absent | Minor staging and costume detail | Optional removal |
| A09 | L21 "cũng chẳng có ý định tìm chỗ trú" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `HIDDEN_INTENTION_INFERENCE` | MEDIUM | 04 | FACTUAL | `events.E1`: her motivation is UNKNOWN. `unknowns` | States her intention as fact where the boundary marks it unknown | "cũng chẳng buồn tìm chỗ trú" → "vẫn ngồi yên dưới mưa" |
| A10 | L21 "ngước khuôn mặt tái nhợt vì lạnh lên, ánh mắt vô hồn" | STRENGTHENED / UNSUPPORTED | `UNSUPPORTED_INVENTION` / `PHYSICAL_OR_EMOTIONAL_STATE_INVENTION` | LOW | 01 | FACTUAL | `events.E1`: staring vaguely somewhere. Pallor, cold, raised face absent | "Soulless" intensifies "vaguely"; pallor invented | "nhìn vô định vào đâu đó" |
| A11 | L23 "Với cái kiểu này thì cảm lạnh chắc luôn," Amane thầm nghĩ | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | MEDIUM | 05 | EPISTEMIC | `events.E3` motivation: *if* she caught a cold he would feel bad. Conditional | Invented quoted thought that turns a possibility into certainty | "Kiểu này dễ cảm lạnh lắm" or remove |
| A12 | L25 "người ta muốn dầm mưa thì là chuyện của người ta" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | `events.E1`: he first did not intend to get involved. This reasoning absent | Invented reasoning; also presupposes she wants to be there before she says so | "Cậu vốn không định dính vào" |
| A13 | L27 "Cậu vò đầu bứt tai" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | Absent | Invented gesture | Remove |
| A14 | L27 "tối nay chắc chắn cậu sẽ mất ngủ vì cắn rứt" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | MEDIUM | 05 | EPISTEMIC | `events.E1` consequence: his conscience pricked. `events.E3`: an uneasy-conscience idiom, conditional on her catching cold | Asserts a certain, literal consequence (losing sleep tonight) | "lương tâm cậu thấy cắn rứt" |
| A15 | L29 "cố gắng giữ giọng điệu lạnh lùng nhất có thể để đối phương không hiểu lầm" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | `events.E2`: he speaks to her. Manner and purpose absent | Invented intention behind his tone | Remove |
| A16 | L33 "Mahiru giật mình quay lại. Mái tóc… dán chặt vào gò má" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | Absent | Invented reaction and visual detail | Optional removal |
| A17 | L35 "người hàng xóm hay chạm mặt vào buổi sáng" | STRENGTHENED | `EPISTEMIC_ERROR` / `REPUTATION_OR_FREQUENCY_STRENGTHENING` | LOW | 05 | EPISTEMIC | `relationships`: she has seen his face to some degree | Adds frequency and time of day | "người hàng xóm cô từng thấy mặt" |
| A18 | L39 "Amane hơi bất ngờ vì cô nhớ tên họ của mình" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | `relationships`: she knows his surname. His surprise absent | Invented reaction | Optional removal |
| A19 | L39 "một cô gái lúc nào cũng bị đám con trai làm phiền thì cảnh giác là chuyện đương nhiên" | UNSUPPORTED | `CAUSALITY_ERROR` / `CAUSALITY_INVENTION` | MEDIUM | 03 | FACTUAL | `events.E2` motivation: wary because she was suddenly spoken to. `characters[1]`: often approached | Gives a different cause for her wariness than the boundary does. "lúc nào cũng" also strengthens "often" | "Bị bắt chuyện đột ngột, cô cảnh giác cũng phải" |
| A20 | L41 "Không có việc gì cả," Amane nhún vai… "…thấy hơi chướng mắt thôi."; L43 "Cảm ơn vì sự quan tâm của bạn… Xin đừng bận tâm đến tôi." | UNSUPPORTED | `UNSUPPORTED_INVENTION` (no subtype fits invented speech) + `UNSUPPORTED_ACTION_OR_STAGING` for the shrug | MEDIUM | 01 | FACTUAL | `events.E2`: his one question, her "do you need something", her "I am here because I want to be". His reply, her thanks and "don't mind me" absent | Puts unrecorded lines in both characters' mouths as direct quotes | Keep the supported lines; narrate the rest indirectly |
| A21 | L45 "Giọng của Mahiru rất mềm mại, không hề gay gắt" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | Absent | Invented manner of speech | Optional removal |
| A22 | L47 "Cậu biết tỏng là cô nàng đang có tâm sự gì đó rất nặng nề" | UNSUPPORTED | `EPISTEMIC_ERROR` / `EPISTEMIC_KNOWLEDGE_OVERCLAIM` | **HIGH** | 06 | EPISTEMIC | `important_details`: reason not revealed; her expression only *seemed* near tears to him, truth unknown. `unknowns` | "Knows" is factive. The sentence makes it a story fact that she has a heavy trouble and that he knows it. That resolves the scope's central unknown | "Trông cô có vẻ không ổn, nhưng cậu không biết vì sao" |
| A23 | L49 "Amane vốn dĩ là người rất sợ rắc rối" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | Only "avoided involvement" | Generalizes behaviour into a trait | Remove |
| A24 | L49 "Lương tâm của cậu chỉ thúc giục đến mức ra hỏi thăm một câu là kịch kim… hoàn toàn có thể quay lưng bước đi mà không thấy tội lỗi nữa" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | MEDIUM | 04 | FACTUAL | `events.E3` motivation: he still felt uneasy and gave the umbrella | Invents a state of being free of guilt, which the next event contradicts | Remove |
| A25 | L51 "cô gái nhỏ bé… ngồi co ro" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `scene_state_constraints`: seated on the swing. Posture absent | Invented posture and build | "ngồi trên xích đu" |
| A26 | L55 "Trước khi cô nàng kịp mở miệng phản đối"; L57 "tiếng mưa ồn ã đã lấn át tất cả… cũng chẳng bận tâm xem cô nói gì" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `UNSUPPORTED_ACTION_OR_STAGING` | LOW | 01 | FACTUAL | `events.E3`: her small voice was heard behind him; he did not turn | Invented sequencing, an invented reason for not hearing, and an invented attitude | "Cậu nghe thấy giọng cô khe khẽ phía sau nhưng không quay lại" |
| A27 | L59 "Cậu đã làm hết sức rồi… dường như đã rửa sạch mọi sự cắn rứt" | UNSUPPORTED | `UNSUPPORTED_INVENTION` / `MOTIVE_OR_INTERNAL_STATE_INVENTION` | LOW | 04 | FACTUAL | Absent. Hedged by "dường như" | Invented self-assessment | Remove |
| A28 | L61 "nghĩa là cô ấy cũng chẳng muốn dính dáng gì đến cậu… Amane tin chắc rằng" | STRENGTHENED | `EPISTEMIC_ERROR` / `CERTAINTY_INFLATION` | LOW | 05 | EPISTEMIC | `ending_state.factual_state`: he *thinks* this is the end | "Thinks" becomes "is certain"; her wish is inferred inside his reasoning | "Amane nghĩ rằng" |
| A29 | Whole script: 1648 words recorded; 1565 by whitespace recount | — | `REQUEST_NONCOMPLIANCE` / `LENGTH_NONCOMPLIANCE` | MEDIUM (see §5) | 14 | REQUEST | Target 900–1100 | 42–50% above the upper bound, depending on the counting method | Cut roughly 470–550 words |

**Cumulative escalation (contract §14).** A05, A06, A07, A12, A15, A18, A23, A24 and A27 are nine invented motives or internal states of the same character. Together they present him as insecure, calculating about jealousy, and self-absolving. The boundary gives only two things: he did not want involvement, and his conscience pricked. This reviewer judges that the set changes how the character is understood and escalates the set to **HIGH**. This is a judgement call; see the sensitivity note in section 4.

### Considered and not flagged (story-claim test, §4.2)

| Passage | Decision | Why |
|---|---|---|
| L1 "Các bạn đã bao giờ… lỡ… tốt bụng chưa?" | `COMMENTARY_RHETORIC` | Narrator addressing the audience; no story fact |
| L3, L5 "thiên thần… chỉ là một cách ví von"; "búp bê sống" | `COMMENTARY_RHETORIC` | Figures recognisable as figures. The first is flagged as a figure by the script itself |
| L7 "Theo lời đồn đại…" for her abilities | Acceptable | Weakens a supported fact to hearsay. Weakening is allowed |
| L7 "hỏi sao mà đám con trai… không thi nhau tỏ tình" | `COMMENTARY_RHETORIC` | Rhetorical question over a supported fact |
| L9 "né thính"; L11 "Nước giếng không phạm nước sông" | `COMMENTARY_RHETORIC` | Narrator's label and idiom for supported non-contact |
| L13 "buổi chiều định mệnh"; L15 "Cái kiểu mưa mà ai nấy đều…" | `COMMENTARY_RHETORIC` | Framing and colour over supported heavy rain |
| L25 "dường như méo xệch… như thể sắp khóc" | `SUPPORTED_FACT` | Keeps the boundary's "seemed" |
| L27 "lý trí… chính thức bay màu" | `COMMENTARY_RHETORIC` | Joke over a supported decision |
| L33 "đẹp một cách phi lý"; L45 "như một bức tường thép" | `COMMENTARY_RHETORIC` | Evaluation and simile |
| L39 "Chắc cô nàng đang nghĩ Amane… bắt chuyện tán tỉnh" | `COMMENTARY_RHETORIC` (borderline) | Hedged guess. Unclear whether it is the narrator's or the character's |
| L63 "đã ngây thơ nghĩ như vậy" | `SUPPORTED_INFERENCE` | The boundary itself says his guess is strongly implied to be wrong |

### Gate status

| Gate | Status | Findings | Explanation |
|---|---|---|---|
| `GATE_FACTUAL_GROUNDING` | `GATE_FAIL` | A02, A03, A05–A10, A12, A13, A15, A16, A18–A21, A23–A27 | Six MEDIUM findings (A05, A06, A09, A19, A20, A24) alone would give `GATE_CONDITIONAL`. The cumulative escalation of the internal-state set to HIGH makes it fail |
| `GATE_EPISTEMIC_INTEGRITY` | `GATE_FAIL` | A01, A04, A11, A14, A17, A22, A28 | A22 is HIGH |
| `GATE_TEMPORAL_STATE_INTEGRITY` | `GATE_PASS` | — | Hook, then linear order; true order recoverable. She is seated throughout (L21, L51), as the boundary requires. Identity and relationship correct |
| `GATE_SPOILER_DISCIPLINE` | `GATE_PASS` | (A01 considered) | Nothing beyond chapter 1 is stated. The ending tease is inside the boundary. A01 was classified as strengthening, not as a leak |
| `GATE_NECESSARY_COVERAGE` | `GATE_PASS` | — | Events E1–E3, the refusal, the umbrella and the ending implication are present |
| `GATE_OUTPUT_INTEGRITY` | `GATE_PASS` | — | Latin-script letters only; no meta text, no call to action |
| `GATE_REQUEST_COMPLIANCE` | `GATE_CONDITIONAL` | A29 | Under the existing wording the finding is MEDIUM (section 5) |

## 2. Part B — Narrative

| Dimension | Rating | Evidence | Why |
|---|---|---|---|
| `HOOK_STRENGTH` | 3 | L1 | Curiosity-first and in voice, as the profile asks, but generic and three sentences long before the story starts |
| `NARRATIVE_FLOW` | 3 | L1 → L3–L11 → L13 → L15–L57 → L59–L63 | Clear and followable. After the hook it is setup, then scene, in source order; transitions work |
| `PACING` | 2 | L3–L11: 572 of 1565 words (37%) come before the rain scene; L47–L51 and L59–L61 restate his feelings | The profile asks for compressed exposition. The scene itself is slowed by repeated internal monologue |
| `EMOTIONAL_IMPACT` | 3 | L25, L51–L55 | The near-tears moment and the umbrella land. L21 and L45 inflate ("vô hồn", "bức tường thép") |
| `HUMOR_COMMENTARY_QUALITY` | 4 | L9 "né thính", L27 "bay màu", L49 "kịch kim" | Specific, in the requested youth register, frequent without taking over |
| `CALLBACK_QUALITY` | 4 | L1 and L63 | The ending line answers the hook's promise |
| `NARRATION_NATURALNESS` | 4 | L15, L19, L27; against L33 "Mái tóc dài nặng trĩu vì nước dán chặt vào gò má" | Mostly natural spoken Vietnamese; a few written-prose sentences |
| `OVERALL_USEFULNESS` | 2 | — | A creator would have to cut about a third and remove claims spread across most paragraphs |

## 3. Edit Cost

Edit cost: `MAJOR`

Concrete edits:

1. Cut roughly 470–550 words. Most must come from L3–L11 (setup) and from L39, L47–L51, L59–L61 (monologue).
2. Rewrite A22 (HIGH).
3. Remove or soften eight MEDIUM findings: A05, A06, A09, A11, A14, A19, A20, A24.
4. Remove the remaining invented internal states (A07, A12, A15, A18, A23, A27).
5. Optional LOW staging fixes.

Reason: integrity fixes are spread across the script and whole paragraphs must be re-narrated to reach the length. The hook, scene order and supported dialogue can stay, so it is not `REWRITE`.

## 4. Verdict

**Dry-run trace** (this reviewer's judgements standing in for the audit):

```text
GATE_EPISTEMIC_INTEGRITY = GATE_FAIL (A22 HIGH)
→ FAIL
```

**Strict contract result.** Section 16 says a semantic gate needs a human audit, and a model-raised finding counts only once a human confirms it. No human has audited this review. Strictly, the five semantic gates are `GATE_NOT_DETERMINED` and the contract verdict is `REVIEW_REQUIRED`.

**Sensitivity.**

- Without the cumulative escalation, `GATE_FACTUAL_GROUNDING` is `GATE_CONDITIONAL`. The dry-run verdict stays `FAIL` because of A22.
- If another reviewer rated A22 MEDIUM, no gate would fail. The verdict would then be `REVIEW_REQUIRED` (PACING = 2, OVERALL_USEFULNESS = 2, edit cost `MAJOR`).
- So `FAIL` versus `REVIEW_REQUIRED` rests on one severity judgement. `PASS` and `PASS_WITH_MINOR_EDITS` are not reachable under any reading.

Single biggest remaining problem: the script fills the brief's silences with the protagonist's invented thoughts, and in one place states the scope's central unknown as known.

## 5. Length Edge Case

1. **Severity under the existing wording: MEDIUM.** Section 14 lists "length outside tolerance" as a typical MEDIUM case.
2. **Why not higher.** HIGH is defined as a material change to the interpretation of a character, scene or causal chain. CRITICAL is a false plot-level belief or an unusable deliverable. A script that is 42–50% too long is neither. The contract gives no rule that scales length severity with the size of the overrun.
3. **Required repair: `MAJOR`.** About a third of the text must go, across most paragraphs. That is more than "several sentences" and requires re-narrating sections.
4. **Gate status: `GATE_CONDITIONAL`.**
5. **Verdict from length alone** (all other gates assumed passing): no gate fails → edit cost `MAJOR` → `REVIEW_REQUIRED`.

Assessment: **`CONTRACT_SEMANTIC_GAP`**.

- Section 15 says `GATE_REQUEST_COMPLIANCE` "fails on: requested length or scope not met". Under sections 14 and 15 together, a length finding can never be material, so the gate can never fail on length. The two statements conflict.
- An overrun of 1 word and an overrun of 500 words receive the same severity and the same gate status. The outcome differs only indirectly, through edit cost and pacing.
- The end result for this script (`REVIEW_REQUIRED` from length alone) is not absurd. But a hard gate that cannot fail on its own subject is not what section 15 describes.

Resolving this means deciding when length non-compliance is material. That changes hard-gate or severity semantics, so it was not repaired in this review.

## 6. Operational Notes From Applying the Rubric

1. **Length severity and gate wording conflict** (section 5 above).
2. **Severity definitions are written for story truth.** For output and request findings there is no described HIGH case, only MEDIUM ("contamination token", "length outside tolerance") and CRITICAL ("unusable").
3. **No subtype for invented speech or for invented descriptive attributes.** A02, A03 and A20 had to be recorded at parent level. Workable, but A20 is a common kind of finding.
4. **Reconstructed direct quotes.** The contract says what a character said is a story claim. It does not say how close a translated or reconstructed quote must be to the boundary. Supported lines were accepted at paraphrase level.
5. **Spoiler versus strengthening.** A01 turns a boundary-level suggestion about the future into a fact. Two parents apply (`PREMATURE_SPOILER`, `CERTAINTY_INFLATION`) and they belong to different gates. The contract has no tie-break.
6. **Character reasoning in free indirect style** (A12, A28). It is unclear whether the content of an invented thought is one finding (the thought) or two (the thought and its content).
7. **Whose guess?** The L39 hedged guess could be the narrator's or the character's. The test in §5.3 depends on that.
8. **Cumulative escalation decided a gate.** It worked as written but depends on judgement, with no guidance on how many findings or how to record the escalated set.
9. **The request was not in one place.** The profile had to be assembled from the manifest and the prompt it references.
10. **Two word counts.** The recorded count (1648) and a whitespace count (1565) differ by 5%. The method for the recorded count is not stated. Both are far outside the range, so the result is unaffected here.
11. **An AI reviewer cannot produce a contract verdict.** Under section 16 every AI-only review ends at `REVIEW_REQUIRED`. This is consistent, but the template does not say how to record the difference between a provisional trace and the contract verdict.
