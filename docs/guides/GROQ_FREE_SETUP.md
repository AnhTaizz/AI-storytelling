# Cài đặt Groq Free

1. Đăng ký tài khoản Groq và giữ gói **Free**. Không nâng cấp lên Developer hoặc thêm thẻ thanh toán.
2. Tạo một API key trên trang [Groq API Keys](https://console.groq.com/keys).
3. Trong tệp `.env` ở thư mục gốc của dự án, thêm dòng `GROQ_API_KEY_1=` rồi điền key sau dấu `=`. Không dán key vào chat hoặc đưa key cho agent. Nếu key bị lộ, thu hồi ngay trên trang API Keys và tạo key mới.
4. Chạy `python -m tools.llm_infra.groq_smoke`. Lệnh mặc định kiểm tra cấu hình ngoại tuyến. `READY_FREE_PLAN` cho biết cấu hình đã sẵn sàng theo khai báo của bạn. Kiểm tra **Usage** và **Limits** trên bảng điều khiển Groq để xem mức sử dụng và hạn mức thực tế.
5. Chỉ chạy `python -m tools.llm_infra.groq_smoke --live` khi chủ dự án quyết định kiểm tra kết nối. Lệnh gửi đúng một yêu cầu JSON mẫu, giới hạn đầu ra 32 token và không thử lại.

Groq tính hạn mức theo tổ chức. Mọi key của cùng một tổ chức dùng chung hạn mức, nên thêm key không tăng hạn mức. Gói Free giới hạn 8.000 token mỗi phút cho mỗi model trong danh sách hỗ trợ. Nếu một yêu cầu vượt khoảng 8.000 token, kể cả token suy luận, Groq từ chối và ứng dụng báo `REQUEST_TOO_LARGE`.

Groq Free phù hợp với tác vụ ngắn như phân loại hoặc trích xuất JSON từ đoạn văn ngắn. Việc tích hợp vào pipeline sẽ nằm ở một PR sau khi đợt chạy mẫu của cổng chất lượng M9 kết thúc.
