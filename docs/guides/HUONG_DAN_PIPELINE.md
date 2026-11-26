# Hướng dẫn dùng pipeline kịch bản

Tài liệu này dành cho chủ dự án: cách tạo kịch bản tiếng Việt từ một bộ truyện, cách chấm, và
cách chỉnh tên nhân vật. Chi tiết kỹ thuật nằm trong
`docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md`.

## 1. Chuẩn bị

- **Key Gemini:**
  - Xác nhận dự án và model miễn phí trước khi chạy theo [hướng dẫn cấu hình Gemini](FREE_LLM_PROVIDER_SETUP.md).
  - Chạy trên máy: chép `.env.example` thành `.env` rồi điền `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`… Không bao giờ commit file `.env`.
  - Chạy trên Claude cloud: key đặt trong cài đặt môi trường (nên dùng mục *Network secrets* thay cho biến môi trường thường).
- **Cài thư viện:**

  ```
  python -m pip install -r requirements-canonical-story.txt -r requirements-story-extraction-gemini.txt
  ```
- **Chọn chuỗi model:** thử lần lượt từ trái sang phải khi một model bị quá tải hoặc hết quota.

  ```
  gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.5-flash-lite
  ```

## 2. Đưa truyện vào

- **Truyện có dòng trống giữa các đoạn** (như mẫu tiếng Nhật trong repo): dùng manifest M3 sẵn có.
- **Truyện mỗi đoạn chỉ xuống dòng một lần** (thường gặp ở web novel Hàn, Trung): chuẩn bị trước bằng lệnh dưới. Lệnh này sinh ra `.local/sources/<tên>/manifest.yaml`, các lệnh sau dùng `--manifest` trỏ tới file đó.

  ```
  python -m tools.story_pipeline.prepare_source --input-dir <thư mục các chương .txt> \
      --out .local/sources/<tên truyện> --story-id <mã truyện> --language ko
  ```
- **Mã ngôn ngữ:** `ja` (Nhật), `ko` (Hàn), `zh` (Trung).

## 3. Tạo kịch bản

- **Một tập:**

  ```
  python -m tools.story_pipeline.run_pipeline --chapters 2-5 --recap --revision-rounds 3 --model <chuỗi model>
  ```
- **Cả bộ, chia tập tự động:**

  ```
  python -m tools.story_pipeline.run_story --chapters 1-30 --episode-size 3 --revision-rounds 3 --model <chuỗi model>
  ```
  - Chạy lại đúng lệnh này để chạy tiếp: tập đã xong được bỏ qua, tập đang dở chạy tiếp từ chỗ dừng.
  - Khi hết quota, mùa dừng gọn (trạng thái `PAUSED_QUOTA`). Hôm sau chạy lại cùng lệnh.
  - Mục lục cả mùa nằm ở `.local/story_seasons/<mã truyện>/season.md`.
- **Gài lại chi tiết cũ (callback):** khi chạy theo tập (`--recap`, hoặc `run_story`), pipeline tự tìm trong brief của các chương trước những sự kiện liên quan đến tập này, kể cả sự kiện nhỏ, rồi đưa cho người viết kèm passage nguồn. Danh sách nằm ở mục `callbacks` của `memory_recap.json`. Tắt bằng `--no-callbacks`.
- **Độ dài:** đặt bằng `--min-words` / `--max-words`. Mặc định theo profile là 900–1100 từ; tập 4 chương nên đặt khoảng 2400–3000.

Kịch bản đầu ra luôn bằng tiếng Việt. Cổng kiểm tra chặn chữ Hán, kana, Hangul lọt vào kịch bản.

## 4. Đọc kết quả của một lần chạy

Trong thư mục của lần chạy (`.local/story_pipeline_runs/<id>/` hoặc thư mục tập trong mùa):

| File | Dùng để |
|---|---|
| `brief_check.md` | Kết quả đối chiếu từng mục brief với nguồn: mục đã tự sửa, và mục **CẦN XEM** để bạn quyết |
| `script_final.md` | Kịch bản cuối |
| `script_final.txt` | Chỉ lời dẫn, không tiêu đề hay ký hiệu: đưa thẳng vào công cụ đọc giọng (TTS). Cả mùa có thêm `season_script.md` ghép mọi tập |
| `review.html` | **Trang chấm**: mỗi đoạn kịch bản đặt cạnh brief và nguyên văn nguồn, chỗ bị báo lỗi được tô vàng |
| `report.md` | Báo cáo: các gate, lỗi còn lại, danh sách brief cần xem, số token |
| `review_form.md` | Phiếu chấm dạng chữ |

**Gate "CẦN XEM" không có nghĩa là kịch bản hỏng.** Nó nghĩa là còn lỗi mà vòng sửa chưa xử lý hết, và báo cáo ghi rõ câu nào.

**Mục "Brief bỏ sót"** liệt kê các câu mà critic báo là bịa (vì brief không có), nhưng bước đối chiếu nguồn
tìm thấy trong nguyên văn, có dẫn passage. Các câu này được giữ nguyên và không tính là lỗi. Nên liếc qua
passage được dẫn để chắc chắn.

Các bộ kiểm tra vẫn có thể bỏ sót, nên hãy đọc cả đoạn, không chỉ chỗ được tô.

## 5. Chấm kịch bản nhanh (góp ý cho pipeline)

1. Mở `review.html` bằng trình duyệt (trên điện thoại cũng được).
2. Đọc từng đoạn, so với cột nguồn bên phải.
3. Chấm 7 mục từ 1 đến 5, ghi lỗi cụ thể, chọn kết luận.
4. Bấm **"Chép phiếu dạng Markdown"** rồi dán vào `review_form.md` của lần chạy đó.
5. Xem tổng hợp mọi phiếu đã chấm:

   ```
   python -m tools.story_pipeline.review_summary
   ```

Chỉ phiếu của chủ dự án mới được tính. Phiếu agent chấm được tách riêng, chỉ để tham khảo. Phiếu này chỉ là góp ý nhanh. Script Quality Gate chính thức dùng phiếu ở mục 9.

### Để pipeline sửa theo góp ý của bạn

Trong mục "Lỗi cụ thể" của phiếu, mỗi lỗi một dòng: trích **nguyên văn** câu trong kịch bản trong ngoặc kép, rồi `→` và lý do.

```
- "Cậu dán miếng hạ nhiệt lên trán" → Mahiru dán lúc cậu đang ngủ
```

Sau đó chạy:

```
python -m tools.story_pipeline.run_pipeline --resume <thư mục lần chạy> --apply-review
```

- Pipeline sửa đúng các câu đó trong một vòng (chỉ sửa câu, không viết lại cả bài), rồi kiểm lại các đoạn vừa đổi.
- `report.md` có mục "Góp ý của người duyệt" ghi từng lỗi: đã sửa; đã sửa nhưng đoạn vẫn bị báo lỗi (câu mới vẫn có thể sai, hãy xem); câu vẫn còn; hoặc không tìm thấy câu (thường do trích không đúng nguyên văn).
- Ghi rõ **điều đúng trong nguồn** ở phần lý do (ví dụ "cậu quên đo, chỉ đo sau khi Mahiru gõ cửa nhắc"), không chỉ "sai". Lý do càng cụ thể, câu sửa càng đúng.
- `--resume` lấy lại tham số của lần chạy trước, nên các bước đã lưu được dùng lại. Nếu đổi truyện, phạm vi chương, phạm vi recap hoặc nội dung nguồn, hãy dùng thư mục đầu ra mới. Các lần chạy cũ chưa lưu phiên bản nguồn chỉ đối chiếu được truyện, chương và mã tài liệu đã ghi trong manifest.
- Phiếu bạn đã chấm được giữ lại thành `review_form_reviewed_1.md`, và một phiếu trống mới được tạo cho bản đã sửa.
- Với cả mùa: chạy lại lệnh `run_story` cùng các tham số cũ, thêm `--apply-review`. Chỉ những tập có lỗi chưa sửa mới được chạy lại.

### Duyệt Story Brief trước khi viết (M7)

Story Brief là "ranh giới sự thật" của tập: kịch bản chỉ được kể những gì có trong đó. Nếu brief sai, kịch bản sẽ sai theo, nên tốt nhất là duyệt brief trước khi pipeline lập plan.

1. Chạy đến hết bước brief:

   ```
   python -m tools.story_pipeline.run_pipeline --chapters 2-3 --recap --stop-after brief --model <chuỗi model>
   ```
2. Mở `story_brief.html`. Mỗi mục (sự kiện, sự thật về nhân vật, quan hệ) nằm cạnh nguyên văn nguồn nó trích. Mục có viền vàng là chưa chắc chắn (lời đồn, vẻ bề ngoài, phỏng đoán) và phải giữ đúng mức độ đó.
3. Trong `brief_review_form.md`, mỗi mục là một dòng:
   - Mục sai: đổi `[ ] sai` thành `[x] sai` và viết nội dung đúng sau `→` ở cuối dòng.
   - Mục thừa hoặc không nên kể: đổi `[ ] bỏ` thành `[x] bỏ`.
   - Mục đúng thì để nguyên.
   Tùy chọn thử nghiệm `--brief-normalization` mặc định tắt. Với Brief đầu tiên, tùy chọn chỉ lấy chuỗi từ đối tượng có duy nhất
   trường `text` trong `unknowns` và `forbidden_inferences`. Mọi kiểm tra Brief và sửa lỗi toàn phần vẫn chạy như
   cũ khi cần. Phản hồi gốc vẫn dùng để chẩn đoán. Nếu đã chuẩn hóa, Full Repair nhận Brief đã chuẩn
   hóa kèm lỗi còn lại từ validator. `--resume` khôi phục chế độ từ manifest. Để đổi chế độ, dùng một thư mục đầu ra mới. Lượt chạy đã
   khóa không dùng tùy chọn này.

4. Chạy tiếp, không cần tham số nào khác: `python -m tools.story_pipeline.run_pipeline --resume <thư mục lần chạy>`.
   - Plan, kịch bản và critic dùng brief đã sửa.
   - `run_manifest.json` (mục `brief_review`) ghi lại từng thay đổi. Dòng không áp dụng được (thiếu nội dung sau `→`, hoặc mã mục không tồn tại) cũng được ghi lại, không bị bỏ qua lặng lẽ.
   - Phiếu bạn đã điền được giữ lại thành `brief_review_form_reviewed_1.md`.
   - Bộ nhớ của truyện không bị sửa: các tập khác vẫn dùng brief gốc.

## 6. Tên nhân vật (bảng tên của truyện)

Sau lần chạy đầu tiên của một truyện, file `.local/story_memory/<mã truyện>/glossary.yaml` được tạo, mỗi nhân vật một mục:

```yaml
- display: Lin Wan'er          # tên sẽ đọc trong kịch bản
  also_allowed: [Wan'er]       # các cách gọi khác được chấp nhận
  source_names: [林婉儿, 婉儿]  # tên gốc trong truyện
  pronoun: cô                  # đại từ dùng cho nhân vật này ở mọi tập
  confirmed: false
```

**Đại từ (`pronoun`):** nếu để trống, tập đầu tiên sẽ tự ghi lại đại từ mà người viết đã dùng (có ghi chú
`pronoun_source`). Từ tập sau, kịch bản phải theo đúng đại từ đó: câu nào gọi nhân vật bằng đại từ khác
(ví dụ "anh" thay cho "cậu") sẽ bị báo để vòng sửa thay. Muốn đổi thì sửa `pronoun`; phần bạn sửa không
bao giờ bị ghi đè.

- **Đổi tên:** sửa `display` (ví dụ `Lâm Uyển Nhi` cho truyện Trung theo âm Hán-Việt), sửa `also_allowed` (ví dụ `[Uyển Nhi]`), rồi đặt `confirmed: true`.
- **Pipeline không ghi đè phần bạn sửa.** Nó chỉ thêm nhân vật mới.
- **Từ lần chạy sau:** người viết được dặn dùng đúng tên này, và kịch bản nào còn dùng cách viết khác (ví dụ "Lin Wan'er") sẽ bị báo lỗi để vòng sửa thay.

## 7. Khi có lỗi

- **`FAILED` ở bước brief:** xem `calls.jsonl` để biết lý do từng lần thử. Chạy lại với `--resume <thư mục lần chạy>` (không cần tham số khác) để không phải gọi lại các bước đã xong.
- **Lỗi 503 / quá tải:** chuỗi model tự chuyển sang model sau. Nếu tất cả đều lỗi, chờ một lúc rồi chạy lại.
- **Hết quota:** với `run_story`, chạy lại cùng lệnh hôm sau.

## 8. Duyệt plan trước khi viết kịch bản (M8)

1. Chạy đến bước plan:

   ```
   python -m tools.story_pipeline.run_pipeline --chapters <phạm vi> --recap --stop-after plan
   ```
2. Mở `plan_review.html`: mỗi beat (đoạn kể) nằm cạnh các sự kiện brief nó kể và mã passage bằng chứng; beat có cảnh báo (nhịp kể, tên lạ, con số lạ) được viền vàng. Bản chữ ở `plan.md`.
3. Sửa `plan_review_form.md`, mỗi dòng một beat:
   - `bỏ: [x]` để bỏ beat (beat có sự kiện CORE không bỏ được);
   - đổi `vị trí:` để chuyển beat lên/xuống (1 = đầu tiên);
   - đổi `số từ:` để kể dài hay ngắn hơn;
   - viết sau `ghi chú:` điều người viết cần lưu ý.
4. Chạy `--resume <thư mục lần chạy>`: plan đã sửa được dùng để viết kịch bản; `report` ghi lại mọi thay đổi và mục bị từ chối. Phiếu đã điền được giữ thành `plan_review_form_reviewed_1.md`.

## 9. Chấm Script Quality Gate (chính thức, M1/M9)

Gate được chấm trên 4 tập của chương 6–17, theo [protocol](../research/m9/M9_SCRIPT_QUALITY_GATE_PROTOCOL_V0.md) (DEC-033). Mỗi tập có một phiếu `gate_review_form.md` trong thư mục của tập.

1. **Tạo phiếu** (agent thường làm sẵn):

   ```
   python -m tools.story_pipeline.gate_review form .local/story_seasons/<mùa>
   ```

2. **Đọc** `script_final.md`, đối chiếu nguyên văn trong `review.html`.
3. **Phần A, lỗi:**
   - Với mỗi dòng `critic` hoặc `máy`, ghi `có` (lỗi đúng) hoặc `không` (lỗi sai). Sửa Mức độ nếu bạn thấy khác.
   - Lỗi bạn tự tìm thì ghi vào dòng `người chấm`, gồm trích câu, mức độ, lý do và Xác nhận `có`.
   - HIGH hoặc CRITICAL nghĩa là gate đó hỏng.
4. **Phần "Gate đã kiểm tra":** ghi `có` cho từng gate bạn đã đối chiếu với nguồn. Gate chưa ghi `có` thì chưa được đánh giá.
5. **Phần B, chất lượng kể:** chấm 8 tiêu chí từ 1 đến 5, mỗi điểm kèm một câu trích và lý do. Điểm không có bằng chứng thì không hợp lệ.
6. **Chi phí sửa:** chọn MINIMAL, MODERATE, MAJOR hoặc REWRITE, rồi trả lời lỗi còn lại có sửa tại chỗ được không.
7. **Tính kết quả:**

   ```
   python -m tools.story_pipeline.gate_review score .local/story_seasons/<mùa>
   python -m tools.story_pipeline.gate_review summary .local/story_seasons/<mùa> --out .local/story_seasons/<mùa>/gate
   ```

   `score` báo ô nào còn thiếu. Bạn không tự ghi gate hay verdict: lệnh tính theo contract.

**Lưu ý:**
- Chấm kịch bản đúng như pipeline tạo ra. Chỉ dùng `--apply-review` hoặc sửa tay sau khi đã chấm xong.
- Gate đạt khi cả 4 phiếu do bạn chấm, không phiếu nào FAIL, không có lỗi CRITICAL, và ít nhất 3/4 phiếu là PASS hoặc PASS_WITH_MINOR_EDITS.
