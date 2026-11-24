# Benchmark mô hình miễn phí · Phase 7A

Phase 7A bổ sung danh mục mô hình, bộ câu hỏi DEV có bằng chứng và công cụ chạy thử ngoại tuyến. Bộ DEV gồm 78 tình huống hư cấu. Đáp án và rubric mặc định ở trạng thái `draft_needs_owner_review`. Kết quả DEV dùng để kiểm tra cách đo và chuẩn bị Phase 7B. Cổng chất lượng M1/M9 có quy trình đánh giá riêng.

## Xem dự toán ngoại tuyến

```powershell
python -m tools.model_bench.run --provider groq --model openai/gpt-oss-20b --group event_extraction --limit 3
python -m tools.model_bench.run --provider groq --model openai/gpt-oss-20b --group event_extraction --limit 3 --dry-run --plan-md
```

Chế độ mặc định in số lượt gọi, token đầu vào ước tính, token đầu ra dự phòng và các giới hạn từ danh mục. Có thể lặp `--group` hoặc `--case`. Khi dùng cả hai, chương trình lấy phần giao rồi áp dụng `--limit` theo thứ tự bộ DEV. Cột `unknown` cho biết dữ liệu nguồn chưa có giá trị. Ngưỡng 16.384 token dùng để chặn yêu cầu khi context chưa rõ và được ghi riêng là `adapter_context_guard`.

## Kiểm tra quy trình bằng dữ liệu giả lập

```powershell
python -m tools.model_bench.run --provider groq --model openai/gpt-oss-20b --offline-fake --output-dir .local/model_bench_runs/dev-demo
python -m tools.model_bench.run --provider groq --model openai/gpt-oss-20b --offline-fake --output-dir .local/model_bench_runs/dev-demo --resume
```

Chế độ giả lập dùng sẵn đáp án và câu mẫu, vì vậy điểm chỉ kiểm tra đường chạy. Mỗi lượt ghi cấu hình vào `run.json`, ghi từng ca vào `results.jsonl`, và tạo `summary.csv`, `report.md` cùng `human_review.jsonl`. Người duyệt dùng mã ca để đối chiếu câu hỏi và bằng chứng rồi chấm từng tiêu chí của rubric.

`set_f1` tính độ chính xác và độ bao phủ trên tập các mục duy nhất. Mỗi mục lặp được ghi vào `duplicate_predictions` kèm số lần xuất hiện. `order_kendall` tính tỷ lệ cặp đúng thứ tự khi dự đoán là hoán vị đầy đủ của đáp án. Một mục lặp, thiếu hoặc thừa làm điểm thứ tự bằng 0.

Báo cáo ghi số yêu cầu kể cả thử lại, số lượt sửa, độ trễ, mã lỗi và token với nguồn `reported`, `estimated` hoặc `unknown`. Tỷ lệ token trên mỗi ca thành công dùng tổng đầu vào và đầu ra. Token suy luận có cột riêng vì một số nhà cung cấp đã gộp chúng vào đầu ra. Số liệu thiếu hiển thị `unknown`.

## Duyệt đáp án và rubric ngoại tuyến

```powershell
python -m tools.model_bench.review_sheet
```

Mở `.local/model_bench_review/review_v1.html` trực tiếp trong trình duyệt. Dùng tìm kiếm, bộ lọc nhóm và độ khó để xem đoạn trích, bằng chứng tô nền, yêu cầu, đáp án và rubric. Điền tên, chọn quyết định cho từng ca rồi bấm **Xuất quyết định (JSON)** trước khi đóng trang. Dùng `--output` để đổi đường dẫn HTML.

Lưu tệp xuất tại `data/model_bench_dev/v1/GOLD_REVIEW.json`, hoặc chỉ định tệp riêng bằng `--gold-review`. Tệp chứa `dataset_sha256` và đối tượng `cases` theo mã ca. Mỗi quyết định ghi `status`, `reviewer`, `date` (UTC), `case_sha256` và ghi chú tùy chọn. Hash bộ dữ liệu và hash nội dung ca phải khớp để quyết định có hiệu lực. Khi hash thay đổi, các ca tương ứng trở về `draft_needs_owner_review`. Mặc định lượt chạy trực tiếp chỉ lấy ca có quyết định `approved`. Phê duyệt riêng cấu hình có `--include-drafts` để thêm ca ở trạng thái `draft_needs_owner_review`. Kết quả của các ca đó có nhãn `draft`.

## Duyệt lượt chạy Phase 7B

Project Owner duyệt ca, mô hình, bảng dự toán, lịch, hạn mức và ngày hết hạn theo [kế hoạch Phase 7B](../engineering/MODEL_BENCH_7B_PLAN.md). Vòng sàng lọc chạy một lượt cho mỗi cặp nhà cung cấp và mô hình. Với OpenRouter, chọn biến thể có tên kết thúc bằng `:free`. Dành các lượt lặp độc lập cho vòng đo độ ổn định sau sàng lọc.

Ngân sách dùng chung giữa các lượt chạy của cùng mã kế hoạch và mô hình. Chương trình giữ trước số yêu cầu tối đa cho một ca, tính số lượt thực tế từ bộ chuyển tiếp và dừng với `BUDGET_EXHAUSTED` khi ngân sách còn lại không đủ cho ca tiếp theo hoặc đã chạm trần. Khi số lượt thực tế chưa xác định, khoản giữ trước vẫn tính vào ngân sách. `budget.json` đi cùng checkpoint và `--resume` đối chiếu với sổ phê duyệt.

Chạy Gemini sau khi M9 kết thúc. Chương trình kiểm tra thư mục mùa `.local/story_seasons` hoặc thư mục đặt bằng `--seasons-dir`. Chủ dự án có thể xác nhận đã giải phóng quota bằng `--m9-clear-attested-by-owner`. Lượt chạy ghi lại xác nhận này trong `run.json`.
