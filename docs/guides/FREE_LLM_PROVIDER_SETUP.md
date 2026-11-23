# Cấu hình Gemini miễn phí cho pipeline

## Xác nhận dự án trước khi tạo khóa

1. Mở [Google AI Studio](https://aistudio.google.com), chọn đúng dự án và kiểm tra AI Studio hiển thị **Free tier**. Trong [Cloud Billing](https://console.cloud.google.com/billing), kiểm tra dự án đó không liên kết với tài khoản thanh toán. Nếu thiếu một trong hai xác nhận, giữ trạng thái `UNVERIFIED`.
2. Tránh các nút **Set up billing**, **Upgrade**, **Link a billing account**, **Activate a full Cloud account** và đăng ký tín dụng dùng thử (**Free trial**). Các bước này có thể kích hoạt thanh toán. Ứng dụng không thể bảo đảm chi phí bằng 0 nếu dự án đã bật billing. [Hướng dẫn billing](https://ai.google.dev/gemini-api/docs/billing)
3. Đối chiếu từng model với cột Free tier trên [bảng giá chính thức](https://ai.google.dev/gemini-api/docs/pricing). Xem hạn mức thực tế của dự án tại mục Usage trong AI Studio và mục Quotas của Cloud Console, lọc theo **Generative Language API**. Kiểm tra giới hạn yêu cầu/phút, token/phút và yêu cầu/ngày. Giao diện có thể thay đổi; ưu tiên thông tin trên [trang hạn mức chính thức](https://ai.google.dev/gemini-api/docs/rate-limits).
4. Tại [trang API keys](https://aistudio.google.com/apikey), tự chọn **Create API key**, chọn đúng dự án vừa xác nhận, rồi sao chép khóa vào file `.env` riêng trên máy. Không đưa khóa vào Git, ảnh chụp hay tin nhắn.

## Điền cấu hình và kiểm tra ngoại tuyến

Chép `.env.example` thành `.env`, dán từng khóa vào `GEMINI_API_KEY_1`, `GEMINI_API_KEY_2`… và thêm một dòng xác nhận cho tất cả khóa:

```
GEMINI_API_KEY_1=<khóa-1>
GEMINI_API_KEY_2=<khóa-2>
GEMINI_MODEL=<model-chính>,<model-dự-phòng>
GEMINI_KEYS_FREE_TIER_CONFIRMED=true
```

Chỉ đặt `true` khi mọi project của các khóa này chưa bật billing. Không cần ghi project hay label: mỗi khóa được xem là một nguồn quota riêng. Khóa nào bị 429 thì riêng khóa đó chờ, các khóa khác vẫn chạy. Nếu hai khóa thật ra cùng project thì tốn thêm tối đa một lần gọi bị từ chối cho mỗi khóa, vẫn miễn phí. Khóa trùng nhau chỉ dùng một lần. Giữ `LLM_FREE_ONLY=true`, `LLM_ALLOW_PAID=false`, `MAX_PAID_SPEND_USD=0`.

Tùy chọn, không bắt buộc:
- `GEMINI_PROJECT_LABEL_<n>`: ghi cùng nhãn cho các khóa cùng project để chúng chờ chung, tránh lần gọi thừa.
- `GEMINI_PROJECT_BILLING_<n>=BILLING_ENABLED`: đánh dấu một khóa thuộc project đã bật billing; ứng dụng sẽ không dùng khóa đó.
- `GEMINI_FREE_MODELS`: giới hạn thêm các model được phép dùng.

Chạy `python -m tools.llm_infra.check_config`. Lệnh chỉ đọc cấu hình và xem các nhóm đang chờ quota, không gửi yêu cầu Gemini. Khi thấy `READY_FREE_ONLY`, cấu hình đáp ứng chính sách của ứng dụng. Nếu đang chờ quota, xem thời điểm UTC của đúng dự án và model.

Chỉ khi chủ dự án quyết định thử thật, chạy `python -m tools.story_pipeline.run_pipeline --chapters 1 --stop-after brief`. Mỗi lần gọi tiêu thụ quota yêu cầu và token đầu vào/đầu ra. Kiểm tra brief, sửa JSON, thử lại hoặc chuyển model có thể phát sinh thêm lần gọi. Nếu bị tạm dừng vì hết quota (lỗi có `QUOTA_EXHAUSTED` và giờ UTC có thể chạy lại), đợi tới giờ đó rồi chạy tiếp: với một tập, dùng `python -m tools.story_pipeline.run_pipeline --resume <thư mục run>`; với cả mùa (`run_story`, trạng thái `PAUSED_QUOTA`), chạy lại đúng lệnh cũ. Các bước đã xong không bị gọi lại. Trạng thái chờ quota được lưu ở `.local/llm_quota_state.sqlite3` (không chứa khóa); có thể xóa file này nếu muốn bỏ lịch sử chờ.

## Khi lộ khóa

Thu hồi khóa đó ngay ở [trang API keys](https://aistudio.google.com/apikey) (hoặc Cloud Console → APIs & Services → Credentials), tạo khóa thay thế trong dự án đã kiểm tra, cập nhật `.env` và xem lại Usage cùng Cloud Billing. Không dán khóa vào chat, issue hay PR.

## Nhà cung cấp khác (Phase 2–4, chưa hỗ trợ trong code)

- Groq: https://console.groq.com
- OpenRouter: https://openrouter.ai (chỉ model có hậu tố `:free`; không nạp credit, không bật auto top-up)
- Cloudflare Workers AI: https://dash.cloudflare.com (gói Free; token chỉ cấp quyền Workers AI cho đúng account)

Có thể tạo tài khoản trước nếu muốn, nhưng chưa cần điền khóa của các nhà cung cấp này vào `.env`.
