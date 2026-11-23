# Cài đặt OpenRouter Free

1. Đăng ký tài khoản OpenRouter. Tắt **Auto Top-Up** và chỉ nạp tiền nếu bạn chấp nhận mua credits. Mua tổng cộng ít nhất 10 credits nâng hạn mức miễn phí từ 50 lên 1.000 yêu cầu mỗi ngày. [Credits](https://openrouter.ai/settings/credits) · [Hạn mức OpenRouter](https://openrouter.ai/docs/api/reference/limits)
2. Tạo API key trên trang [OpenRouter Keys](https://openrouter.ai/settings/keys). Nếu giao diện cho phép, đặt hạn mức chi tiêu của key về 0.
3. Trong tệp `.env` ở thư mục gốc của dự án, thêm dòng `OPENROUTER_API_KEY_1=` rồi điền key sau dấu `=`. Không dán key vào chat hoặc đưa key cho agent. Nếu key bị lộ, thu hồi ngay và tạo key mới.
4. Kiểm tra cài đặt quyền riêng tư của tài khoản. Mỗi nhà cung cấp model miễn phí có chính sách dữ liệu riêng. Khi bỏ trống `OPENROUTER_DATA_COLLECTION`, OpenRouter dùng cài đặt tài khoản. Đặt `OPENROUTER_DATA_COLLECTION=deny` nếu bạn muốn loại các nhà cung cấp thu thập dữ liệu. Tùy chọn này có thể làm giảm số model khả dụng. [Chính sách thu thập dữ liệu](https://openrouter.ai/docs/guides/privacy/data-collection)
5. Chạy `python -m tools.llm_infra.openrouter_smoke`. Lệnh mặc định kiểm tra cấu hình ngoại tuyến. `READY_FREE_ONLY` cho biết chuỗi model đáp ứng quy tắc miễn phí.
6. Khi chủ dự án quyết định kiểm tra kết nối, chạy `python -m tools.llm_infra.openrouter_smoke --live`. Lệnh đọc hạn mức của key và gửi đúng một yêu cầu JSON mẫu với tối đa 32 token đầu ra. Lệnh không thử lại và chỉ in các số liệu công khai của key cùng kết quả chat.

Mặc định ứng dụng dùng `openrouter/free`. Có thể đặt `OPENROUTER_MODEL` thành một ID có hậu tố `:free` để chọn model cụ thể. Hạn mức dùng chung cho các model miễn phí trên tài khoản và đặt lại vào 00:00 UTC mỗi ngày. Thêm key hoặc tài khoản không làm tăng hạn mức. Số dư âm có thể khiến cả model miễn phí trả lỗi `PAYMENT_REQUIRED`.

Việc tích hợp vào pipeline được lên kế hoạch cho Phase 5.
