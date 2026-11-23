# Bảng điều khiển AI Operations

Phase 6A hiển thị một ảnh chụp dữ liệu giả lập được tạo khi máy chủ khởi động.
Dòng **MOCK DATA — not connected** xuất hiện trên mọi trang. Dashboard chạy
ngoại tuyến, chỉ phục vụ trên máy đang chạy lệnh và chỉ cho phép đọc.

## Khởi động

Từ thư mục gốc của repository, chạy:

```powershell
python -m tools.ops_dashboard
```

Mở địa chỉ máy chủ in ra, mặc định là `http://127.0.0.1:8765/`. Có thể dùng
`--port 8766` để đổi cổng. Tham số `--host` chấp nhận `127.0.0.1`,
`localhost` hoặc `::1`. Nhấn **Ctrl+C** trong terminal để dừng máy chủ.

## Các trang

| Trang | Nội dung |
| --- | --- |
| Overview | Số bản ghi ứng viên từ đầu ngày UTC, tỷ lệ thành công của các lần đã gửi, token, chi phí giả lập 0 USD, số cooldown, tình trạng nhà cung cấp và sự cố gần đây. |
| Providers | Model, hạn mức miễn phí, lượng đã dùng và còn lại, thời điểm hết cooldown theo UTC và thời gian tương đối, mã lỗi gần nhất. Hạn mức Gemini tùy dự án và model. |
| Usage | Biểu đồ token và bản ghi ứng viên theo nhà cung cấp trong 24 giờ hoặc 7 ngày. Màu đặc biểu thị số liệu được báo cáo, vạch chéo biểu thị ước tính, màu xám trên biểu đồ yêu cầu biểu thị bản ghi thiếu số token. |
| Request History | Lọc theo nhà cung cấp, giai đoạn và kết quả. Bảng hiển thị thời gian, độ trễ, token và nguồn số liệu, mã lỗi. Nội dung prompt và phản hồi không xuất hiện. |
| Routing Policies | Đọc cấu hình giả lập theo giai đoạn và tier, thứ tự ứng viên, cờ chuyển sang nhà cung cấp khác và SHA-256 giả lập. |
| Pipeline Monitor | Tiến độ từ brief đến revise, trạng thái mỗi lượt chạy và gợi ý tiếp tục sau khi hết hạn mức hoặc khi cần duyệt. |

Số token ước tính có thể gồm phần dự trữ cho đầu ra. Nếu thiếu số liệu, bảng
hiển thị dấu gạch. Chi phí 0 USD là giả định của kịch bản miễn phí. Các chỉ số
hạn mức trên trang Providers là ảnh chụp mẫu riêng của từng phạm vi hạn mức.

## Kết nối trong Phase 6B

Phase 6B dự kiến thay nguồn giả lập bằng nguồn đọc SQLite telemetry, SQLite
trạng thái hạn mức và manifest của các lượt chạy. Hai cơ sở dữ liệu sẽ được mở
ở chế độ chỉ đọc. Dashboard chỉ lấy các trường metadata được phép, giữ nguyên
nguồn số liệu và không truy cập thông tin xác thực. Xem
[kế hoạch triển khai](../engineering/OPS_DASHBOARD_PLAN.md).
