# Cấu hình Gemini miễn phí cho pipeline

## Thiết lập lần đầu

1. Với từng dự án chứa khóa, kiểm tra một lần rằng AI Studio hiển thị **Free tier** và Cloud Billing cho biết dự án chưa liên kết tài khoản thanh toán. Tránh các nút **Upgrade**, **Set up billing** và **Link a billing account**. Nếu chưa xác nhận được, hãy để trống dòng khóa của dự án đó. [AI Studio](https://aistudio.google.com) · [Cloud Billing](https://console.cloud.google.com/billing)
2. Chép `.env.example` thành `.env`. Dán mỗi khóa vào một dòng `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`… Chỉ cần một khóa để bắt đầu. Tự nhập khóa trên máy của bạn. Không dán khóa vào chat, giao cho agent hoặc đưa vào Git.
3. Chạy `python -m tools.llm_infra.check_config`. Lệnh kiểm tra ngoại tuyến. `READY_FREE_ONLY` cho biết cấu hình đáp ứng chính sách ứng dụng. Xem `available_now` để biết số nhóm khóa dùng được cho model đầu tiên và `blocked` để biết giờ UTC hết hạn chờ.
4. Chạy thử một chương bằng `python -m tools.story_pipeline.run_pipeline --chapters 1 --stop-after brief`. Lệnh này gửi nội dung đến Google và sử dụng quota. Theo bảng giá, Google có thể dùng nội dung ở free tier để cải thiện sản phẩm (“Used to improve our products: Yes”). [Bảng giá Gemini](https://aistudio.google.com/docs/pricing)

## Model và quota

Pipeline mặc định thử `gemini-3.8-flash`, sau đó chuyển sang `gemini-3.6-flash` nếu cần. Danh sách cho phép còn có `gemini-3.5-flash-lite` và `gemini-4-hydrogen`. Nhóm bảo trì ghi nhận các model có giá đầu vào và đầu ra văn bản “Free of charge” ở thẻ Standard, cột Free Tier ngày 2026-11-23. Danh sách có thể cũ khi giá thay đổi. Mọi cập nhật cần được duyệt trong code. [Danh sách trong mã nguồn](../../tools/llm_infra/gemini_free_models_v1.py) · [Bảng giá](https://aistudio.google.com/docs/pricing)

Pipeline luân phiên các khóa theo thứ tự, bỏ khóa trùng. Với khóa không gắn nhãn, lỗi 429 chỉ đưa khóa vừa dùng vào thời gian chờ cho model đang gọi. Các khóa có thể cùng một dự án và dùng chung quota thực tế. Mặc định, sau ba phản hồi 429 cho một lần gọi trên một model, router dừng thử khóa và trả về giờ UTC sớm nhất có thể thử lại. Khóa chưa thử vẫn dùng được. Khi tất cả nhóm đang chờ, router có thể đợi một lần trong giới hạn 60 giây. Client có thể chuyển sang model dự phòng.

Khi hết quota trên cả chuỗi model, mùa chuyển sang `PAUSED_QUOTA`. Đến giờ UTC được báo, chạy lại lệnh mùa với cùng thư mục đầu ra. Với một tập, chạy `python -m tools.story_pipeline.run_pipeline --resume <thư mục run>`. Pipeline dùng lại kết quả các bước đã hoàn thành. Thời gian chờ được lưu trong SQLite qua các lần chạy.

## Tùy chọn nâng cao

- `GEMINI_MODEL` hoặc `--model` chọn chuỗi model theo thứ tự, phân cách bằng dấu phẩy. `GEMINI_FREE_MODELS` chỉ thu hẹp danh sách trong code. Mọi model trong chuỗi phải thuộc danh sách sau khi thu hẹp.
- `GEMINI_PROJECT_LABEL_<n>` cho các khóa cùng dự án dùng chung thời gian chờ. Các khai báo billing của cùng nhãn phải nhất quán.
- `GEMINI_PROJECT_BILLING_<n>` nhận `FREE_TIER_CONFIRMED`, `UNVERIFIED` hoặc `BILLING_ENABLED`. Hai giá trị sau loại khóa đó. Theo quyết định của chủ dự án, khóa chưa khai báo được dùng mặc định. Đặt `GEMINI_KEYS_FREE_TIER_CONFIRMED=false` để chặn mọi khóa chưa khai báo.
- `GEMINI_MAX_RATE_LIMIT_HOPS` đặt số phản hồi 429 tối đa mỗi lần gọi router (số nguyên từ 1, mặc định 3). `LLM_QUOTA_STATE_PATH` đổi vị trí lưu trạng thái, mặc định là `.local/llm_quota_state.sqlite3`.
- `LLM_FREE_ONLY=true`, `LLM_ALLOW_PAID=false` và `MAX_PAID_SPEND_USD=0` là giới hạn của ứng dụng. Ứng dụng không thể kiểm tra billing từ khóa API. Nếu sau này chủ dự án liên kết tài khoản thanh toán, Google có thể tính phí các lần gọi.

**Chuyển cấu hình cũ.** Có thể giữ nguyên các dòng tùy chọn trong `.env` cũ. Nếu đã đặt `GEMINI_MODEL`, hãy kiểm tra từng ID trong chuỗi thuộc danh sách free tier hiện hành.

## Khi lộ khóa

Thu hồi khóa đó ngay ở [trang API keys](https://aistudio.google.com/apikey) (hoặc Cloud Console → APIs & Services → Credentials), tạo khóa thay thế trong dự án đã kiểm tra, cập nhật `.env` và xem lại Usage cùng Cloud Billing. Không dán khóa vào chat, issue hay PR.

## Nhà cung cấp khác (Phase 2–4, chưa hỗ trợ trong code)

- Groq: https://console.groq.com
- OpenRouter: https://openrouter.ai (chỉ model có hậu tố `:free`; không nạp credit, không bật auto top-up)
- Cloudflare Workers AI: https://dash.cloudflare.com (gói Free; token chỉ cấp quyền Workers AI cho đúng account)

Có thể tạo tài khoản trước nếu muốn, nhưng chưa cần điền khóa của các nhà cung cấp này vào `.env`.
