# Định tuyến LLM miễn phí cho pipeline truyện

Khi chạy pipeline hoặc tạo cả mùa truyện, dùng `--provider gemini|groq|openrouter|cloudflare|auto`. Mặc định là `gemini`. Có thể đặt biến môi trường `LLM_PROVIDER`; cờ dòng lệnh được ưu tiên. Với một nhà cung cấp cụ thể, `--model` chọn mô hình hoặc chuỗi mô hình theo danh sách miễn phí của nhà cung cấp. Dùng khoá của gói miễn phí theo hướng dẫn thiết lập. Mỗi nhóm khoá của cùng tài khoản hoặc tổ chức chia sẻ hạn mức.

- **Gemini** là lựa chọn mặc định cho các bước ảnh hưởng trực tiếp đến chất lượng kịch bản, từ brief đến sửa từng đoạn.
- **Groq** phù hợp với lời nhắc ngắn và tác vụ phụ. Gói Free có 8.000 token/phút cho các mô hình gpt-oss đã chọn. Tổng token đầu vào ước tính và ngân sách đầu ra phải nằm trong giới hạn này.
- **OpenRouter** phù hợp với tác vụ ngắn, ít lượt gọi. Hạn mức mặc định là 50 yêu cầu/ngày cho tài khoản miễn phí. Dùng `openrouter/free` hoặc một định danh có hậu tố `:free`.
- **Cloudflare Workers AI** phù hợp với tác vụ ngắn trong ngân sách 10.000 Neurons/ngày của Workers Free. Bộ đếm cục bộ mặc định dừng ở 9.000 Neurons để chừa dự phòng.

[Thiết lập Gemini](FREE_LLM_PROVIDER_SETUP.md) · [Groq](GROQ_FREE_SETUP.md) · [OpenRouter](OPENROUTER_FREE_SETUP.md) · [Cloudflare](CLOUDFLARE_FREE_SETUP.md)

```powershell
python -m tools.story_pipeline.run_pipeline --chapters 1 --provider groq
python -m tools.story_pipeline.run_pipeline --chapters 1 --provider auto --routing-policy configs/llm_routing/policy_v1.yaml
python -m tools.llm_infra.check_config
```

Ở chế độ **AUTO**, mỗi công đoạn sử dụng một nhóm quy tắc trong [policy_v1.yaml](../../configs/llm_routing/policy_v1.yaml). Chủ dự án có thể sửa thứ tự ứng viên, ngân sách token đầu ra và quyền chuyển nhà cung cấp. Thứ tự thể hiện ưu tiên cấu hình, không phải bảng xếp hạng chất lượng. `provider:*` lấy chuỗi mô hình đã cấu hình cho nhà cung cấp. Chính sách mặc định dùng Gemini cho `brief`, `brief_check`, `plan`, `script`, `critic`, `source_check`, `revise` và `patch`. Các tác vụ khác dùng nhóm `utility`. Định tuyến bỏ qua mô hình không đủ điều kiện, không đủ dung lượng hoặc đang chờ hạn mức. Dung lượng dự phòng cho mô hình chưa có số liệu ngữ cảnh là 16.384 token, đã gồm ngân sách đầu ra.

Khi tất cả ứng viên bị chặn do hạn mức, mùa truyện chuyển sang `PAUSED_QUOTA`. Chạy lại lệnh sau thời điểm có thể thử lại, hoặc dùng `run_pipeline --resume <thư-mục-lượt-chạy>` cho một tập. Pipeline dùng lại các công đoạn đã lưu. Giữ nguyên nhà cung cấp và nội dung chính sách để tiếp tục. `check_config` xem cấu hình, hạn mức đã lưu và các ứng viên của từng nhóm mà không gọi API. Khả năng xử lý một lời nhắc cụ thể còn phụ thuộc vào độ dài lời nhắc và ngân sách còn lại.

Mùa có `gate_lock.json` hoặc tiến trình đặt `LLM_ROUTING_LOCKED=1` chỉ dùng đường chạy Gemini cũ. Mẫu M9 đã khóa tiếp tục chạy đúng commit và mô hình ghi trong biên bản khóa.

Telemetry lưu tại `.local/llm_telemetry.sqlite3`. Có thể đổi đường dẫn bằng `LLM_TELEMETRY_PATH`. Cơ sở dữ liệu lưu mô hình, số token, độ trễ, trạng thái và số liệu hạn mức công khai. Cơ sở dữ liệu không lưu lời nhắc, nội dung phản hồi, khoá, token xác thực, ID tài khoản hay header Authorization. [Lược đồ telemetry](../engineering/LLM_TELEMETRY_SCHEMA.md)
