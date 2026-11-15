# Hướng dẫn dùng pipeline kịch bản

Tài liệu này dành cho chủ dự án: cách tạo kịch bản tiếng Việt từ một bộ truyện, cách chấm, và
cách chỉnh tên nhân vật. Chi tiết kỹ thuật nằm trong
`docs/research/pipeline/STORY_PIPELINE_PROTOTYPE_V0.md`.

## 1. Chuẩn bị

- **Key Gemini:**
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
- **Độ dài:** đặt bằng `--min-words` / `--max-words`. Mặc định theo profile là 900–1100 từ; tập 4 chương nên đặt khoảng 2400–3000.

Kịch bản đầu ra luôn bằng tiếng Việt. Cổng kiểm tra chặn chữ Hán, kana, Hangul lọt vào kịch bản.

## 4. Đọc kết quả của một lần chạy

Trong thư mục của lần chạy (`.local/story_pipeline_runs/<id>/` hoặc thư mục tập trong mùa):

| File | Dùng để |
|---|---|
| `script_final.md` | Kịch bản cuối |
| `review.html` | **Trang chấm**: mỗi đoạn kịch bản đặt cạnh brief và nguyên văn nguồn, chỗ bị báo lỗi được tô vàng |
| `report.md` | Báo cáo: các gate, lỗi còn lại, danh sách brief cần xem, số token |
| `review_form.md` | Phiếu chấm dạng chữ |

**Gate "CẦN XEM" không có nghĩa là kịch bản hỏng.** Nó nghĩa là còn lỗi mà vòng sửa chưa xử lý hết, và báo cáo ghi rõ câu nào.

Các bộ kiểm tra vẫn có thể bỏ sót, nên hãy đọc cả đoạn, không chỉ chỗ được tô.

## 5. Chấm kịch bản (cần cho cổng chất lượng M1)

1. Mở `review.html` bằng trình duyệt (trên điện thoại cũng được).
2. Đọc từng đoạn, so với cột nguồn bên phải.
3. Chấm 7 mục từ 1 đến 5, ghi lỗi cụ thể, chọn kết luận.
4. Bấm **"Chép phiếu dạng Markdown"** rồi dán vào `review_form.md` của lần chạy đó.
5. Xem tổng hợp mọi phiếu đã chấm:

   ```
   python -m tools.story_pipeline.review_summary
   ```

Chỉ phiếu của chủ dự án mới được tính. Phiếu agent chấm được tách riêng, chỉ để tham khảo.

## 6. Tên nhân vật (bảng tên của truyện)

Sau lần chạy đầu tiên của một truyện, file `.local/story_memory/<mã truyện>/glossary.yaml` được tạo, mỗi nhân vật một mục:

```yaml
- display: Lin Wan'er          # tên sẽ đọc trong kịch bản
  also_allowed: [Wan'er]       # các cách gọi khác được chấp nhận
  source_names: [林婉儿, 婉儿]  # tên gốc trong truyện
  confirmed: false
```

- **Đổi tên:** sửa `display` (ví dụ `Lâm Uyển Nhi` cho truyện Trung theo âm Hán-Việt), sửa `also_allowed` (ví dụ `[Uyển Nhi]`), rồi đặt `confirmed: true`.
- **Pipeline không ghi đè phần bạn sửa.** Nó chỉ thêm nhân vật mới.
- **Từ lần chạy sau:** người viết được dặn dùng đúng tên này, và kịch bản nào còn dùng cách viết khác (ví dụ "Lin Wan'er") sẽ bị báo lỗi để vòng sửa thay.

## 7. Khi có lỗi

- **`FAILED` ở bước brief:** xem `calls.jsonl` để biết lý do từng lần thử. Chạy lại với `--resume <thư mục lần chạy>` để không phải gọi lại các bước đã xong.
- **Lỗi 503 / quá tải:** chuỗi model tự chuyển sang model sau. Nếu tất cả đều lỗi, chờ một lúc rồi chạy lại.
- **Hết quota:** với `run_story`, chạy lại cùng lệnh hôm sau.
