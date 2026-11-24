# Bảng điều khiển AI Operations

Phase 6A hiển thị một ảnh chụp dữ liệu giả lập được tạo khi máy chủ khởi động.
Dòng **DỮ LIỆU MẪU — chưa kết nối hệ thống thật** xuất hiện trên mọi trang.
Dashboard chạy ngoại tuyến, chỉ phục vụ trên máy đang chạy lệnh và chỉ cho phép đọc.

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
| Tổng quan | Tóm tắt tình trạng hệ thống, yêu cầu hôm nay, tỉ lệ thành công, token, chi phí mẫu 0 ₫ và số nhà cung cấp đang chờ quota. Biểu đồ cột chồng cho biết số yêu cầu theo nhà cung cấp trong 24 giờ qua. |
| Nhà cung cấp | Model, phạm vi áp dụng quota, hạn mức miễn phí, lượng đã dùng và còn lại, thời điểm có thể thử lại và lỗi gần nhất. Hạn mức Gemini tùy dự án và model. |
| Mức sử dụng | Biểu đồ token và yêu cầu theo nhà cung cấp trong 24 giờ hoặc 7 ngày. Mỗi nhóm biểu đồ dùng chung thang đo để dễ so sánh. |
| Lịch sử yêu cầu | Lọc theo nhà cung cấp, bước và kết quả. Bảng hiển thị thời gian, độ trễ, token, nguồn số liệu và diễn giải lỗi kèm mã. |
| Quy tắc chọn model | Cấu hình mẫu theo từng bước, thứ tự thử model, quy tắc thử nhà cung cấp khác và SHA-256 của cấu hình. |
| Tiến độ quy trình | Tiến độ từ tóm tắt đến chỉnh sửa, trạng thái từng lượt chạy và hướng dẫn khi phải đợi quota hoặc cần người duyệt. |

Dashboard mặc định dùng tiếng Việt và giao diện theo hệ điều hành. Dùng hai mục
**Ngôn ngữ** và **Giao diện** ở đầu trang để đổi lựa chọn. Trên màn hình nhỏ,
nút **Menu** mở danh sách trang.

Các mốc thời gian hiển thị theo múi giờ của trình duyệt. Trỏ vào thời gian để
xem mốc UTC chính xác. Chỉ số **Yêu cầu hôm nay** tính từ đầu ngày UTC và gồm
cả lượt bỏ qua. **Tỉ lệ thành công** chỉ tính trên các lượt đã gửi.

Trỏ, chạm hoặc dùng phím **Tab** trên biểu đồ để xem chi tiết từng khoảng thời
gian. Nút **Xem dạng bảng** mở bảng số liệu tương ứng. Màu đặc biểu thị số liệu
nhà cung cấp báo, vạch chéo biểu thị ước tính và màu xám trên biểu đồ yêu cầu
biểu thị lượt thiếu số token. Số token ước tính có thể gồm phần dự trữ cho đầu
ra. Nếu thiếu dữ liệu token, bảng dùng dấu gạch. Các nút **?** giải thích
nguồn số liệu, đơn vị quota và thời gian chờ.

## Kết nối trong Phase 6B

Phase 6B dự kiến thay nguồn giả lập bằng nguồn đọc SQLite telemetry, SQLite
trạng thái hạn mức và manifest của các lượt chạy. Hai cơ sở dữ liệu sẽ được mở
ở chế độ chỉ đọc. Dashboard chỉ lấy các trường metadata được phép, giữ nguyên
nguồn số liệu và không truy cập thông tin xác thực. Xem
[kế hoạch triển khai](../engineering/OPS_DASHBOARD_PLAN.md).
