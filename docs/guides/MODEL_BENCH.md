# Benchmark mô hình miễn phí · Phase 7A

Phase 7A bổ sung danh mục mô hình, bộ câu hỏi DEV có bằng chứng và công cụ chạy thử ngoại tuyến. Bộ DEV gồm các tình huống hư cấu. Tất cả đáp án và rubric đang ở trạng thái `draft_needs_owner_review`. Kết quả DEV dùng để kiểm tra cách đo và chuẩn bị Phase 7B. Cổng chất lượng M1/M9 có quy trình đánh giá riêng.

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

Chế độ giả lập dùng sẵn đáp án và câu mẫu, vì vậy điểm chỉ kiểm tra đường chạy. Mỗi lượt ghi cấu hình vào `run.json`, ghi từng ca vào `results.jsonl`, và tạo `summary.csv`, `report.md` cùng `human_review.jsonl`. Người duyệt dùng mã ca để đối chiếu câu hỏi và bằng chứng rồi chấm từng tiêu chí của rubric. Độ tự nhiên, sức hút và nhịp kể do người duyệt đánh giá. Trường hiệu năng thiếu được ghi `unknown` trong bảng báo cáo. Không có lượt sửa JSON tự động trong phép đo này.

## Duyệt lượt chạy Phase 7B

Project Owner duyệt bộ DEV, mô hình, bảng dự toán, lịch và hạn mức trước khi cấp tệp duyệt theo [kế hoạch Phase 7B](../engineering/MODEL_BENCH_7B_PLAN.md). Mỗi lượt dùng một cặp nhà cung cấp và mô hình. Thực hiện ít nhất ba lượt độc lập và chỉ dùng hạn mức không trùng với M9 đang chạy. Với OpenRouter, chọn biến thể có tên kết thúc bằng `:free`. Danh mục Phase 7A chỉ liệt kê tuyến miễn phí hữu hạn trong mã nguồn và áp dụng quy tắc của nhà cung cấp khi chọn biến thể có tên.
