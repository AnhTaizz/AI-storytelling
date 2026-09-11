# RUN_0007 — H6b Real Deterministic Claim Audit

## EXECUTION INSTRUCTION

You are executing a controlled factual-critic experiment.

Use ONLY the information provided in this packet.

Do not use prior conversation context, external sources, web search,
or unstated story knowledge.

Return exactly one response.

Do not revise or retry based on perceived answer quality.

## CRITIC INSTRUCTIONS

# CLAIM-LEVEL FACTUAL CRITIC PROMPT V3

You are an expert fact-checker and narrative critic. Your task is to audit a story script against a declared Story Brief (the factual boundary).

## 1. Input Contract

You will receive:
1. **Story Brief**: The declared factual boundary.
2. **Review Units**: A deterministically segmented version of the script.

Input review units have already been deterministically segmented. Do NOT omit, merge, split, renumber, reorder, or invent review units.

## 2. Extraction and Classification

For every review unit provided, you must output an exact corresponding audit unit (preserving the `unit_id` and `source_unit_sha256`).
If a review unit contains no meaningful story claim, you must still output the unit with an empty claims list and a `no_claim_reason`.

For each paragraph, extract all meaningful atomic claims. Do not force one claim per unit. A unit may have 0, 1, or many claims.

### Allowed Claim Types
`CHARACTER_IDENTITY`, `CHARACTER_ATTRIBUTE`, `PHYSICAL_DESCRIPTION`, `RELATIONSHIP`, `LOCATION`, `TIME`, `EVENT`, `ACTION`, `PHYSICAL_STATE`, `EMOTIONAL_STATE`, `INTERNAL_THOUGHT`, `MOTIVE`, `INTENTION`, `CAUSALITY`, `KNOWLEDGE_STATE`, `CERTAINTY_LEVEL`, `QUANTITATIVE_DETAIL`, `FUTURE_EVENT`, `FORESHADOW_INTERPRETATION`, `SCENE_STATE`, `OUTCOME`, `REPUTATION_OR_HEARSAY`, `OTHER_FACTUAL`

### Classification Enum
Every claim must use exactly one:
`DIRECTLY_SUPPORTED`, `SUPPORTED_PARAPHRASE`, `SUPPORTED_INFERENCE`, `CREATIVE_BUT_SAFE`, `QUESTIONABLE`, `UNSUPPORTED`, `CONTRADICTS_BRIEF`, `STRONGER_THAN_BRIEF`

### Semantic Rules

**Knowledge vs Appearance**: You must distinguish between what *seems* or *appears* to be true versus what is *known* or *certain*. For example, a character observing that someone "looks upset" does not automatically support a claim that the character knows the exact emotional cause or knows they have a hidden problem. Maintain epistemological boundaries.

**Safe Creativity**: You may use `CREATIVE_BUT_SAFE` for stylistic phrasing that does not alter material story truth (e.g., metaphors, rhetorical questions, narrator jokes, light stylistic emphasis). Safe creativity must not invent motive, chronology, relationship, event, physical state, knowledge, certainty, or causal chain.

**Severity**: Problematic classes (`QUESTIONABLE`, `UNSUPPORTED`, `CONTRADICTS_BRIEF`, `STRONGER_THAN_BRIEF`) require a severity rating of `LOW`, `MEDIUM`, or `HIGH`.
For valid classes, set severity to `null`.

**Action Enum**: For problematic claims, specify a recommended action using exactly one of: `KEEP`, `SOFTEN`, `REMOVE`, `REWRITE`. (A LOW severity staging detail may legitimately have `KEEP` if it's worth flagging but not necessarily worth changing).

## 3. Output Format

Return raw YAML only.
Do NOT use Markdown code fences.
Do NOT include prose before or after YAML.

### Output Schema

```yaml
critic_version: CLAIM_LEVEL_FC_V3

input_contract:
  segmentation_version: PARAGRAPH_V1
  expected_unit_count: <integer_from_input>

audit_units:
  - unit_id: <must_match_input_unit_id>
    source_unit_sha256: "<must_match_input_hash>"
    claims:
      - claim_id: C001
        claim_type: <Claim Type Enum>
        normalized_claim: "<atomic_claim_statement>"
        classification: <Classification Enum>
        brief_support:
          - "<reference_to_story_brief_if_any>"
        severity: <Severity Enum or null>
        explanation: "<why_this_classification>"
        recommended_action: <Action Enum or null>
    no_claim_reason: "<if_claims_empty_why>"

problematic_claims:
  - claim_id: C0XX
    unit_id: P0XX
    classification: UNSUPPORTED
    severity: MEDIUM
    recommended_action: REMOVE
```


## STORY BRIEF

story_brief_version: SB_V1

source_scope:
  story: "お隣の天使様にいつの間にか駄目人間にされていた件"
  chapter: "01"
  language: "ja"
  spoiler_boundary: "Chapter 1 only"

characters:
  - name: "藤宮周"
    aliases: ["周", "あまね", "Amane"]
    explicit_facts:
      - "高校一年生 (L14)"
      - "今年から一人暮らしを始めた (L14)"
      - "真昼と同じ高校、同学年だがクラスは違う (L26-34)"
      - "真昼の隣のマンションの部屋に住んでいる (L14)"
    current_state: "真昼との関わりを望んでいなかったが、雨の中傘を貸した (L204)"
  - name: "椎名真昼"
    aliases: ["真昼", "天使様", "Mahiru"]
    explicit_facts:
      - "美しい可憐な少女。亜麻色のストレートヘアー、乳白色の肌、大きな瞳 (L18-22)"
      - "文武両道、成績優秀（常に一位）、体育でもエース並み (L26-30)"
      - "謙虚で大人しい性格 (L36)"
      - "学校の男子から告白やアプローチをよく受けている (L148)"
    current_state: "雨の公園で一人、傘をささずにブランコに座り、ずぶ濡れになっていた (L74-94)"

relationships:
  - entities: ["藤宮周", "椎名真昼"]
    relationship_type: "隣人、同じ高校の同学年"
    source_supported_state: "これまで接触はなかった。真昼は周の名字を知っており、顔を見かけたことはある程度の認識。周は真昼に恋愛感情はなく、関わりを避けていた。 (L52-62, L132-142)"

setting:
  locations:
    - "学校とマンションの間にある公園 (L74)"
  time_context: "雨が降りしきる放課後または夕方 (L74)"

events:
  - id: E1
    order: 1
    factual_description: "周が雨の公園で真昼を見つける"
    participants: ["藤宮周", "椎名真昼"]
    location: "公園"
    observed_actions: "真昼は傘をささず、ブランコに腰かけてどこかをぼんやり見ていた。周は公園の横を通り抜けようとした。"
    explicit_or_supported_motivation: "真昼の動機はUNKNOWN。周は最初関わるつもりがなかった。"
    consequences: "周は真昼の顔が泣きそうに歪んだように見え、良心が咎めた。(L102-110)"
  
  - id: E2
    order: 2
    factual_description: "周が真昼に声をかける"
    participants: ["藤宮周", "椎名真昼"]
    location: "公園"
    observed_actions: "周が「なにやってるんだ」と声をかける。真昼は警戒した態度で「私に何かご用で？」と応じる。"
    explicit_or_supported_motivation: "周：放っておくのは良心が痛んだから (L110)。真昼：急に話しかけられたことに対する警戒 (L134)。"
    consequences: "真昼は「ここに居たいから居る」と拒絶の意を示す (L154)。"

  - id: E3
    order: 3
    factual_description: "周が傘を押し付けて去る"
    participants: ["藤宮周", "椎名真昼"]
    location: "公園"
    observed_actions: "周は自分の傘を真昼に押し付け、返さなくていいと言って足早に立ち去る。"
    explicit_or_supported_motivation: "周：風邪を引かれると寝覚めが悪い、居心地が悪いから (L190-200)。"
    consequences: "真昼の小さな声が背後から聞こえたが、周は振り返らず帰路に就く (L208-214)。"

important_details:
  - "真昼が雨の中で座っていた理由は明かされていない (UNKNOWN)。"
  - "真昼の表情は「泣きそうに歪んだように見えた」(L102) と周には映ったが、真相は不明。"

scene_state_constraints:
  - "真昼はずっと『ブランコに座っていた』。立っていない。(L74)"

unknowns:
  - "真昼が雨に濡れていた本当の理由。"
  - "真昼の家庭の事情や過去。"

ending_state:
  factual_state: "周は傘を貸して一人で帰路につき、これで関わりは終わりだと思っている。"
  unresolved_implication: "「その時は」(L226) という記述により、周の『これっきりだ』という推測が外れ、今後も関わりが続くことが強く示唆されている。"

forbidden_inferences:
  - "周の部屋が散らかっている、または彼の生活がだらしないといった描写はない。"
  - "真昼が泣いていたと断定してはならない（泣きそうに見えただけ）。"


## DETERMINISTIC REVIEW UNITS

segmentation_version: PARAGRAPH_V1
source:
  path: benchmarks/m1_script_quality/runs/RUN_0003_H2_STORY_BRIEF/script.md
  sha256: d7fa7a39ec836165210c8084dd241a65f363acdffb743dc42c2ec5926b6f0f61
normalization:
  line_endings: LF
  split_rule: one_or_more_blank_lines
  trim_outer_whitespace: true
  semantic_rewrite: false
unit_count: 32
units:
- unit_id: P001
  text: |-
    Các bạn đã bao giờ vô tình vướng vào một rắc rối chỉ vì lỡ... tốt bụng chưa? Kiểu như đang đi đường, thấy người ta gặp chuyện, lương tâm cắn rứt nên đành ra tay giúp đỡ, để rồi sau đó nhận ra mình vừa bước vào một chuỗi sự kiện không lường trước được. Đó chính xác là những gì đã xảy ra với thanh niên Fujimiya Amane của chúng ta trong câu chuyện hôm nay.
  sha256: a11b9966a860498b82ccedbad643875549a19ab83bf27c357762171d67f19cfd
- unit_id: P002
  text: |-
    Chuyện là, Amane năm nay mới lên cao trung năm nhất, và cậu chàng vừa mới bắt đầu cuộc sống tự lập, dọn ra ở riêng trong một căn hộ chung cư. Cuộc sống của Amane có lẽ sẽ cứ êm đềm trôi qua như bao nam sinh bình thường khác, nếu như cậu không phát hiện ra một sự thật động trời: ở căn hộ ngay bên phải phòng cậu, có một thiên thần đang sinh sống.
  sha256: 81e30506339832739a3a1adcac9afbdd81356ead766b7b5da86e59b632e4a942
- unit_id: P003
  text: |-
    Đúng vậy, các bạn không nghe nhầm đâu. Tất nhiên, "thiên thần" ở đây chỉ là một cách ví von, nhưng nó hoàn toàn không phải là một trò đùa. Cô bạn hàng xóm của Amane tên là Shiina Mahiru, và cô ấy đẹp đến mức có thể dùng từ "hoàn mỹ" để miêu tả. Tưởng tượng xem, một cô gái với mái tóc thẳng màu hạt lanh luôn bóng mượt, làn da trắng ngần như sữa không tì vết, sống mũi cao thanh tú cùng đôi mắt to tròn ẩn dưới hàng mi dài. Nhìn cô ấy chẳng khác nào một con búp bê sống được chế tác thủ công cực kỳ tinh xảo.
  sha256: 6b0ce7fa345975048af2dbb8d5c9f3c0f1da21d5f97e6b52ffa06b75f02c7da3
- unit_id: P004
  text: |-
    Đâu chỉ có nhan sắc, Mahiru còn học cùng trường, cùng khối với Amane, và danh tiếng của cô thì nổi rần rần. Theo lời đồn đại, Mahiru không chỉ xinh đẹp mà còn là một thiên tài văn võ song toàn. Thành tích học tập lúc nào cũng đứng top 1 toàn trường, còn trong giờ thể dục thì hoạt động năng nổ chẳng kém gì át chủ bài của các câu lạc bộ. Lại thêm cái tính cách ngoan ngoãn, khiêm tốn, không hề kiêu ngạo, hỏi sao mà đám con trai trong trường không thi nhau tỏ tình và tìm cách tiếp cận cơ chứ.
  sha256: e4239c3a3d06fc383a5e9ff76f80abd1fddc0e3c4209a8141f33fa4f52af5e60
- unit_id: P005
  text: |-
    Nói chung, được làm hàng xóm của một mỹ nữ cỡ đó chắc chắn là giấc mơ của vô số thanh niên. Thế nhưng, nam chính của chúng ta lại có một suy nghĩ hết sức thực tế, hay nói đúng hơn là hơi bị... né thính.
  sha256: 755081986377a2f65b3f924695ed715086b1786c772707a14b76573014d219f0
- unit_id: P006
  text: |-
    Amane thừa nhận Mahiru rất hấp dẫn, nhưng cậu chẳng có ý định tiến tới hay làm thân gì cả. Cậu tự biết thân biết phận, khoảng cách giữa một người bình thường và một "thiên thần" là quá lớn. Hơn nữa, cậu biết tỏng nếu dính líu đến Mahiru thì kiểu gì cũng chuốc lấy sự ghen tị từ đám con trai trong trường. Thêm vào đó, với Amane, thấy một cô gái đẹp không có nghĩa là phải nảy sinh tình cảm yêu đương. Cậu chỉ coi Mahiru như một tác phẩm nghệ thuật để ngắm nhìn từ xa là đủ. Thế nên, dù sống ngay sát vách, Amane và Mahiru hoàn toàn không có bất kỳ sự giao tiếp nào. Nước giếng không phạm nước sông.
  sha256: f5c37bf6c860456b7b7bcbf92b0c8e05b2eaf5a9c9b66c20d0b1c63af7ab1f77
- unit_id: P007
  text: Mọi chuyện có lẽ sẽ cứ tiếp diễn như thế, cho đến một buổi chiều định mệnh.
  sha256: bbd145bdb42f41d353bc8fd9fd8c47c70d3ca5e2181ed10b9223f8f66795c1cd
- unit_id: P008
  text: |-
    Hôm đó, trời đổ mưa tầm tã. Cái kiểu mưa mà ai nấy đều cắm đầu cắm cổ chạy thục mạng về nhà ấy. Trên đường về, khi đi ngang qua khu công viên nằm giữa trường học và khu chung cư, Amane chợt khựng lại.
  sha256: 23f821eae0438c695f5d54016fca67caaa8ceb709a781bb6b6770e36f75a09ee
- unit_id: P009
  text: |-
    Xuyên qua màn mưa dày đặc và không gian nhập nhoạng tối, cậu nhìn thấy một hình bóng quen thuộc. Mái tóc màu hạt lanh nổi bật cùng bộ đồng phục trường... không trật đi đâu được, đó chính là Mahiru.
  sha256: cd221ea94bec6c779a76b42b9f6de5023dfa6680f508ad0bd4d464d28a77d542
- unit_id: P010
  text: Nhưng vấn đề là, cô nàng đang làm cái quái gì ở đây vậy?
  sha256: 71b16a0cce73a193517fbd3343eecbd0799c534eafb2becf42c2837ac94c65fd
- unit_id: P011
  text: |-
    Giữa cơn mưa nặng hạt, Mahiru không hề che ô. Cô cứ thế ngồi yên trên chiếc xích đu, mặc cho nước mưa xối xả ướt sũng cả người. Cô không có vẻ gì là đang đợi ai, cũng chẳng có ý định tìm chỗ trú. Cô chỉ ngồi đó, ngước khuôn mặt tái nhợt vì lạnh lên, ánh mắt vô hồn nhìn vào một khoảng không vô định. Cảnh tượng ấy trông vừa kỳ lạ, vừa mong manh đến mức Amane đứng nhìn mà phải tự hỏi liệu cô nàng có bị làm sao không.
  sha256: 548e2576e676307da9f733329daeb481ace24cc560c1c8412aad9b2be17a4397
- unit_id: P012
  text: '"Với cái kiểu này thì cảm lạnh chắc luôn," Amane thầm nghĩ.'
  sha256: 543f8598bae3823a87bc3b6a4fc39c60d170ca66b690b919d366cc948f75d7e2
- unit_id: P013
  text: |-
    Ban đầu, Amane định lờ đi và đi thẳng về nhà. Dù sao thì cậu cũng chẳng muốn dính líu, mà người ta muốn dầm mưa thì là chuyện của người ta, người ngoài xen vào làm gì. Thế nhưng, ngay khoảnh khắc Amane định bước qua, cậu chợt thấy khuôn mặt của Mahiru dường như méo xệch đi. Trông cô lúc ấy... như thể sắp khóc đến nơi.
  sha256: d6b3e2692455a6a54bd7ea34123eb923c97e44c84206e2e05f9cd7e7c8a572de
- unit_id: P014
  text: |-
    Và thế là, sự tỉnh táo và lý trí của Amane chính thức bay màu trước tiếng gọi của lương tâm. Cậu vò đầu bứt tai, cảm thấy nếu cứ thế bỏ mặc cô gái này thì tối nay chắc chắn cậu sẽ mất ngủ vì cắn rứt.
  sha256: a28d6269b6af6b1a70687daea402bf20743940c78132f761a516c77ebd60dfb3
- unit_id: P015
  text: |-
    Amane tiến lại gần, cố gắng giữ giọng điệu lạnh lùng nhất có thể để đối phương không hiểu lầm:
  sha256: ded57c451a40ee2e2e07bc4e095f6f70f88e617463da913a37443ddbecf0e258
- unit_id: P016
  text: '"……Cậu đang làm cái quái gì vậy?"'
  sha256: 2f711857fb5f53d9e26f7544fd8c304d68982aaed7f6f7bba4eb2c881b458ae3
- unit_id: P017
  text: |-
    Mahiru giật mình quay lại. Mái tóc dài nặng trĩu vì nước dán chặt vào gò má. Dù đang ướt sũng và nhợt nhạt, cô ấy vẫn đẹp một cách phi lý.
  sha256: 58982b3396fc30b981e424a54f6b9e24fc7a7c71ce46b4703a1522fac3d04e71
- unit_id: P018
  text: |-
    Mahiru chớp đôi mắt to tròn nhìn Amane. Cô có vẻ nhận ra cậu là người hàng xóm hay chạm mặt vào buổi sáng. Tuy nhiên, việc một người chưa từng nói chuyện đột nhiên tiếp cận khiến đôi mắt cô lập tức ánh lên sự cảnh giác cao độ.
  sha256: 7b5a8bdf46d1e0229812a85923ad839e1c69f725212d66b640ad9cbe6d3de03b
- unit_id: P019
  text: '"Bạn Fujimiya. Bạn có việc gì cần tôi sao?" Mahiru cất giọng.'
  sha256: c78fa8ff305c0fc62444e2961cfa2d9e2fceae69c15a28334c7b879369cc801b
- unit_id: P020
  text: |-
    Amane hơi bất ngờ vì cô nhớ tên họ của mình, nhưng thái độ phòng thủ của Mahiru thì rõ rành rành. Cũng phải thôi, một cô gái lúc nào cũng bị đám con trai làm phiền thì cảnh giác là chuyện đương nhiên. Chắc cô nàng đang nghĩ Amane nhân cơ hội này để bắt chuyện tán tỉnh đây mà.
  sha256: 081a865bf4ad44e9eb0923c2e622ea9d9b01ff18f639ec162d96c50cd187f90c
- unit_id: P021
  text: |-
    "Không có việc gì cả," Amane nhún vai, đáp lại gọn lỏn. "Chỉ là thấy cậu ở chỗ này một mình giữa trời mưa thì thấy hơi chướng mắt thôi."
  sha256: c8381b7d994a0d9457d2ecffe7e61ede6b0749b678929235a109755b069a2442
- unit_id: P022
  text: |-
    "Vậy sao. Cảm ơn vì sự quan tâm của bạn, nhưng tôi ở đây vì tôi muốn thế. Xin đừng bận tâm đến tôi."
  sha256: fb6fe557903c593a75f7ea65730f4463d01dbc9c413e9028207a90afb71066da
- unit_id: P023
  text: |-
    Giọng của Mahiru rất mềm mại, không hề gay gắt, nhưng sự từ chối thì lạnh lùng và kiên quyết như một bức tường thép. Cô đã nói rõ là muốn được ở một mình, và đừng có ai xen vào.
  sha256: 1047b1eca13fe817ebbf6abf7e92ad882dd592ab1819470695595b89aed5d2ab
- unit_id: P024
  text: |-
    "À, ừ... vậy sao," Amane đáp lời. Cậu biết tỏng là cô nàng đang có tâm sự gì đó rất nặng nề, nhưng cậu cũng chẳng có ý định đào sâu hay hỏi han thêm. Người ta đã không muốn nói thì thôi. Ép nài thêm chỉ tổ rước lấy sự khó chịu.
  sha256: 0baa0db2fd62d22408c1a16417f2edf5c007bd5289777d8cf8d9f61fa3af528a
- unit_id: P025
  text: |-
    Hơn nữa, Amane vốn dĩ là người rất sợ rắc rối. Lương tâm của cậu chỉ thúc giục đến mức ra hỏi thăm một câu là kịch kim rồi. Giờ thì nhiệm vụ hoàn thành, cậu hoàn toàn có thể quay lưng bước đi mà không thấy tội lỗi nữa.
  sha256: 22de26de03c4a2f5564437cdbb03b0e53c1a9cf6fa1773a0f8bd0b20a8a60c12
- unit_id: P026
  text: |-
    Thế nhưng, khi chuẩn bị rời đi, nhìn cô gái nhỏ bé ướt sũng nước mưa ngồi co ro trên xích đu, Amane lại cảm thấy... không đành lòng.
  sha256: 179bfd800e4d77f5584767a403c4c94cbb870d737398e609fcf1ba792f2d54eb
- unit_id: P027
  text: '"Cứ thế này thì ốm mất. Cầm lấy đi, rồi mau về nhà. Không cần trả lại đâu."'
  sha256: 206cb06235bee0443f4c45c9e369f5a02aeec2b1fe8d7769211e09e7b1cc2d35
- unit_id: P028
  text: |-
    Nói xong, Amane lấy luôn chiếc ô đang che trên đầu mình, nhét thẳng vào tay Mahiru. Trước khi cô nàng kịp mở miệng phản đối hay nói thêm lời nào, Amane đã dứt khoát quay lưng chạy thẳng vào màn mưa.
  sha256: cc0272a15ec11095bf0ba3c3aa0790acc5c491aed2b51cdbda6aff8d3d341ac3
- unit_id: P029
  text: |-
    Khi Amane vội vã rời đi, cậu loáng thoáng nghe thấy giọng nói nhỏ xíu của Mahiru vang lên phía sau, nhưng tiếng mưa ồn ã đã lấn át tất cả. Cậu không quay lại, cũng chẳng bận tâm xem cô nói gì.
  sha256: 7b45afd1c25f56197b1b088d12923e7ee2e45785f4d1e85cbbac666af60c4d8e
- unit_id: P030
  text: |-
    Vừa chạy trong mưa, Amane vừa thầm nhủ. Cậu đã làm hết sức rồi, cho cả ô rồi, hy vọng cô nàng sẽ không bị cảm lạnh. Việc làm đó dường như đã rửa sạch mọi sự cắn rứt trong lòng cậu.
  sha256: 43dfc6fa7244829923f004ccf5f32a06ec187958389b7680b5b989c64332bd89
- unit_id: P031
  text: |-
    Dù sao thì cô nàng cũng đã từ chối giao tiếp, nghĩa là cô ấy cũng chẳng muốn dính dáng gì đến cậu. Cuộc sống của hai người vốn là hai đường thẳng song song, và khoảnh khắc giao nhau ngắn ngủi này rồi cũng sẽ chìm vào dĩ vãng. Amane tin chắc rằng, sau sự việc ngày hôm nay, mối quan hệ giữa hai người sẽ quay trở về vạch xuất phát: những người hàng xóm không quen biết. Sẽ chẳng có chuyện gì xảy ra tiếp theo đâu. Một lần và mãi mãi.
  sha256: 1c792959f987dffe48c76578ccf57c89868b7c0df46b573ff3ea884a569e3deb
- unit_id: P032
  text: Ít nhất là, vào lúc đó, thanh niên Amane của chúng ta đã ngây thơ nghĩ như
    vậy.
  sha256: ca1b116200561a7240dacb98ec96cc9516c03cb99e6ee37b2562d2fa9bb7453b

