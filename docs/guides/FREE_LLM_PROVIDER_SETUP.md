# Cấu hình Gemini miễn phí cho pipeline

## Xác nhận dự án trước khi tạo khóa

1. Mở [Google AI Studio](https://aistudio.google.com), chọn đúng dự án và kiểm tra AI Studio hiển thị **Free tier**. Trong [Cloud Billing](https://console.cloud.google.com/billing), mở **My projects**, tìm đúng dự án và kiểm tra dự án đó không liên kết với tài khoản thanh toán. Nếu thiếu một trong hai xác nhận, giữ trạng thái `UNVERIFIED`.
2. Tránh các nút **Set up billing**, **Upgrade**, **Link a billing account**, **Activate a full Cloud account** và đăng ký tín dụng dùng thử (**Free trial**). Các bước này có thể kích hoạt thanh toán. Ứng dụng không thể bảo đảm chi phí bằng 0 nếu dự án đã bật billing. [Hướng dẫn billing](https://ai.google.dev/gemini-api/docs/billing)
3. Đối chiếu từng model với cột Free tier trên [bảng giá chính thức](https://ai.google.dev/gemini-api/docs/pricing). Xem hạn mức thực tế của dự án tại mục Usage trong AI Studio và mục Quotas của Cloud Console, lọc theo **Generative Language API**. Kiểm tra giới hạn yêu cầu/phút, token/phút và yêu cầu/ngày. Giao diện có thể thay đổi; ưu tiên thông tin trên [trang hạn mức chính thức](https://ai.google.dev/gemini-api/docs/rate-limits).
4. Tại [trang API keys](https://aistudio.google.com/apikey), tự chọn **Create API key**, chọn đúng dự án vừa xác nhận, rồi sao chép khóa vào file `.env` riêng trên máy. Không đưa khóa vào Git, ảnh chụp hay tin nhắn.

## Điền cấu hình và kiểm tra ngoại tuyến

Trên [trang API keys của AI Studio](https://aistudio.google.com/apikey), xem dự án ở dòng của từng khóa. Có thể đối chiếu trong Cloud Console bằng cách chọn đúng dự án rồi mở **APIs & Services → Credentials**. Chép `.env.example` thành `.env` trên máy riêng. Chọn một trong ba ví dụ trong file và thay các giá trị giữ chỗ.

- Với một khóa duy nhất, có thể để trống nhãn. Khóa trùng chỉ được tính một lần, giữ slot có số nhỏ nhất.
- Với nhiều khóa khác nhau, điền `GEMINI_PROJECT_LABEL_<n>` cho từng slot. Dùng cùng nhãn cho các khóa cùng dự án và nhãn khác nhau cho các dự án khác nhau. Các khóa cùng dự án chia sẻ thời gian chờ quota của từng model.
- Sau khi kiểm tra billing, đặt `GEMINI_PROJECT_BILLING_<n>=FREE_TIER_CONFIRMED` ở một slot của mỗi dự án đã xác nhận. Slot để trống kế thừa trạng thái cùng nhãn. Nếu dự án đã bật billing, dùng `BILLING_ENABLED`. Nếu chưa kiểm tra, giữ `UNVERIFIED`. Cả hai trạng thái này đều loại dự án khỏi danh sách được gọi.
- Chỉ khi cấu hình có đúng một dự án mới được dùng `GEMINI_KEYS_FREE_TIER_CONFIRMED=true`. Khai báo trạng thái cụ thể của dự án luôn được ưu tiên.
- Điền chuỗi model chính và dự phòng vào `GEMINI_MODEL`. Liệt kê từng model được phép trong `GEMINI_FREE_MODELS` sau khi đối chiếu bảng giá và hạn mức ở trên. Danh sách này là lời xác nhận của chủ dự án. Công cụ không kiểm chứng model có miễn phí trên tài khoản Google hay không.
- Giữ `LLM_FREE_ONLY=true`, `LLM_ALLOW_PAID=false` và `MAX_PAID_SPEND_USD=0`. Đây là giới hạn của ứng dụng.

Chạy `python -m tools.llm_infra.check_config` để xem từng dự án, các slot, nguồn xác nhận và thời điểm UTC hết chờ quota. Lệnh chạy ngoại tuyến. Chỉ `READY_FREE_ONLY` trả về mã 0. Khi đó chính sách ứng dụng đạt yêu cầu theo thông tin chủ dự án khai báo. Công cụ không truy cập tài khoản để xác minh billing và không bảo đảm Google sẽ không tính phí.

| Trạng thái | Cách xử lý |
| --- | --- |
| `WAITING_FOR_USER_CREDENTIALS` | Điền khóa ở một slot trong file riêng trên máy. |
| `BLOCKED_PROJECT_LABEL_REQUIRED` | Tra dự án của từng khóa rồi điền nhãn cho tất cả slot được nêu trong lỗi. |
| `BLOCKED_PER_PROJECT_CONFIRMATION_REQUIRED` | Bỏ dòng xác nhận chung, kiểm tra từng dự án và khai báo billing theo nhãn. |
| `BLOCKED_NO_CONFIRMED_FREE_PROJECT` | Kiểm tra AI Studio và Cloud Billing. Chỉ xác nhận dự án đủ điều kiện. |
| `BLOCKED_MODEL_NOT_CONFIRMED_FREE` | Chọn model, kiểm tra cả chuỗi dự phòng rồi điền danh sách miễn phí. Bỏ model không đủ điều kiện khỏi chuỗi gọi. |
| `CONFIG_ERROR` | Xem trường `error`. Sửa giá trị sai, khai báo mâu thuẫn trong cùng nhãn hoặc đường dẫn SQLite theo thông báo. |

**Chuyển từ PR #24.** Cấu hình cũ có nhiều khóa chưa gắn nhãn và dòng xác nhận chung sẽ dừng với `PROJECT_LABEL_REQUIRED`. Khi các nhãn và xác nhận đã hợp lệ, thiếu `GEMINI_FREE_MODELS` sẽ dừng với `MODEL_ALLOWLIST_EMPTY`. Gắn nhãn theo dự án, xác nhận từng dự án và liệt kê các model đã kiểm tra, rồi chạy lại lệnh kiểm tra.

Chỉ khi chủ dự án quyết định thử thật, chạy `python -m tools.story_pipeline.run_pipeline --chapters 1 --stop-after brief`. Mỗi lần gọi tiêu thụ quota yêu cầu và token đầu vào/đầu ra. Kiểm tra brief, sửa JSON, thử lại hoặc chuyển model có thể phát sinh thêm lần gọi. Nếu bị tạm dừng vì hết quota (lỗi có `QUOTA_EXHAUSTED` và giờ UTC có thể chạy lại), đợi tới giờ đó rồi chạy tiếp: với một tập, dùng `python -m tools.story_pipeline.run_pipeline --resume <thư mục run>`; với cả mùa (`run_story`, trạng thái `PAUSED_QUOTA`), chạy lại đúng lệnh cũ. Các bước đã xong không bị gọi lại. Trạng thái chờ quota được lưu ở `.local/llm_quota_state.sqlite3` (không chứa khóa); có thể xóa file này nếu muốn bỏ lịch sử chờ.

## Khi lộ khóa

Thu hồi khóa đó ngay ở [trang API keys](https://aistudio.google.com/apikey) (hoặc Cloud Console → APIs & Services → Credentials), tạo khóa thay thế trong dự án đã kiểm tra, cập nhật `.env` và xem lại Usage cùng Cloud Billing. Không dán khóa vào chat, issue hay PR và không giao khóa cho coding agent.

## Nhà cung cấp khác (Phase 2–4, chưa hỗ trợ trong code)

- Groq: https://console.groq.com
- OpenRouter: https://openrouter.ai (chỉ model có hậu tố `:free`; không nạp credit, không bật auto top-up)
- Cloudflare Workers AI: https://dash.cloudflare.com (gói Free; token chỉ cấp quyền Workers AI cho đúng account)

Có thể tạo tài khoản trước nếu muốn, nhưng chưa cần điền khóa của các nhà cung cấp này vào `.env`.
