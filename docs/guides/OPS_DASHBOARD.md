# Bảng điều khiển AI Operations

Chế độ mặc định đọc dữ liệu cục bộ và hiển thị **DỮ LIỆU THẬT — chỉ đọc**
cùng mốc dữ liệu gần nhất. Dùng `--mock` để xem ảnh chụp dữ liệu giả lập của
Phase 6A với dòng **DỮ LIỆU MẪU — chưa kết nối hệ thống thật**.
Dashboard chạy ngoại tuyến, chỉ phục vụ trên máy đang chạy lệnh và chỉ cho phép đọc.

## Khởi động

Từ thư mục gốc của repository, chạy:

```powershell
python -m tools.ops_dashboard
python -m tools.ops_dashboard --mock
```

Mở địa chỉ máy chủ in ra, mặc định là `http://127.0.0.1:8765/`. Có thể dùng
`--port 8766` để đổi cổng. Tham số `--host` chấp nhận `127.0.0.1`,
`localhost` hoặc `::1`. Nhấn **Ctrl+C** trong terminal để dừng máy chủ.

## Các trang

| Trang | Nội dung |
| --- | --- |
| Tổng quan | Tình trạng hệ thống, yêu cầu hôm nay, tỉ lệ thành công, token, chi phí được báo, độ trễ và số lần chờ quota. Biểu đồ cột chồng cho biết số yêu cầu theo nhà cung cấp trong 24 giờ qua. |
| Nhà cung cấp | Model, số key đã cấu hình và đủ điều kiện, số phạm vi quota, hạn mức theo tài liệu, bộ đếm gần nhất mà nhà cung cấp báo và các mốc chờ quota. |
| Mức sử dụng | Biểu đồ token và yêu cầu theo nhà cung cấp trong 24 giờ hoặc 7 ngày. Mỗi nhóm biểu đồ dùng chung thang đo để dễ so sánh. |
| Lịch sử yêu cầu | Lọc theo nhà cung cấp, bước và kết quả. Dùng nút trang trước hoặc trang sau để duyệt các yêu cầu trong 7 ngày gần nhất. |
| Quy tắc chọn model | Nhóm cho từng bước, thứ tự thử model, quy tắc thử nhà cung cấp khác và SHA-256 của tệp cấu hình. |
| Tiến độ quy trình | Trạng thái lượt chạy và mùa, thời lượng các bước có log, tổng số lượt gọi, token và hướng dẫn khi phải chờ quota hoặc cần người duyệt. Mùa có `gate_lock.json` chỉ hiển thị nhãn khóa M9 và trạng thái. |

Dashboard mặc định dùng tiếng Việt và giao diện theo hệ điều hành. Dùng hai mục
**Ngôn ngữ** và **Giao diện** ở đầu trang để đổi lựa chọn. Trên màn hình nhỏ,
nút **Menu** mở danh sách trang.

Ở chế độ thật, các trang **Tổng quan**, **Nhà cung cấp** và **Tiến độ quy trình**
tự cập nhật sau mỗi 30 giây khi tab đang hiển thị. Nút **Làm mới** cập nhật ngay.
Mốc **Cập nhật lúc** là giờ dashboard lấy dữ liệu.

Các mốc thời gian hiển thị theo múi giờ của trình duyệt. Trỏ vào thời gian để
xem mốc UTC chính xác. Chỉ số **Yêu cầu hôm nay** tính từ đầu ngày UTC và gồm
cả lượt bỏ qua. **Tỉ lệ thành công** chỉ tính trên các lượt đã gửi.

Trỏ, chạm hoặc dùng phím **Tab** trên biểu đồ để xem chi tiết từng khoảng thời
gian. Nút **Xem dạng bảng** mở bảng số liệu tương ứng. Màu đặc biểu thị số liệu
nhà cung cấp báo, vạch chéo biểu thị ước tính và màu xám trên biểu đồ yêu cầu
biểu thị lượt thiếu số token. Số token ước tính có thể gồm phần dự trữ cho đầu
ra. Nếu thiếu dữ liệu token, bảng dùng dấu gạch. Các nút **?** giải thích
nguồn số liệu, đơn vị quota và thời gian chờ.

## Nguồn dữ liệu cục bộ

| Nguồn | Mặc định | Tùy chọn |
| --- | --- | --- |
| Cấu hình nhà cung cấp | `.env` ở thư mục gốc của repository | `--dotenv PATH` |
| Telemetry Phase 5 | `.local/llm_telemetry.sqlite3` hoặc `LLM_TELEMETRY_PATH` | `--telemetry PATH` |
| Cooldown và sổ Neuron Cloudflare | `.local/llm_quota_state.sqlite3` hoặc `LLM_QUOTA_STATE_PATH` | `--quota-state PATH` |
| Manifest và metadata các lần gọi | `.local/story_pipeline_runs` | `--runs-dir PATH` |
| Mùa và manifest của từng tập | `.local/story_seasons` | `--seasons-dir PATH` |
| Quy tắc định tuyến | `configs/llm_routing/policy_v1.yaml` | `--policy PATH` |

Biến môi trường của tiến trình ghi đè cấu hình trong `.env`. Nếu thiếu tệp,
dashboard chỉ dùng biến môi trường. Đường dẫn telemetry và quota lần lượt ưu
tiên tham số dòng lệnh, biến môi trường, giá trị trong `.env`, rồi đường dẫn
mặc định. Khi khởi động, terminal báo trạng thái tìm thấy nguồn dữ liệu và chỉ
hiển thị tên tệp hoặc thư mục cho các đường dẫn mặc định hoặc chọn qua dòng lệnh.
Danh sách model và hạn mức lấy từ mã nguồn của dự án, kèm tài liệu và ngày kiểm tra.
Dashboard chỉ hiển thị số đếm từ cấu hình nhà cung cấp. Nếu hôm nay chưa có lượt
gọi nào và không có lỗi hay chờ quota, trang **Tổng quan** hiển thị số nhà cung cấp
đã cấu hình.

SQLite mở ở chế độ chỉ đọc. Nếu tệp lưu theo WAL, chọn bản sao SQLite dùng
rollback journal. Nếu thiếu telemetry, chạy pipeline một lần rồi quay lại
(`python -m tools.story_pipeline.run_pipeline --chapters 1`). Nếu schema không
khớp, hãy chọn cơ sở dữ liệu do Phase 5 ghi. Với trang quy tắc hoặc tiến độ trống,
kiểm tra đường dẫn cấu hình hoặc thư mục lượt chạy.

Số liệu **Thực tế** đến từ bộ đếm nhà cung cấp hoặc metadata đã ghi. **Ước tính**
bao gồm dự trữ token và tổng Neuron trong ngày UTC trên các tài khoản. Hạn mức
**Theo tài liệu nhà cung cấp** đi kèm ngày kiểm tra. **Không rõ** xuất hiện khi
thiếu số liệu, kể cả quota còn lại khi nhà cung cấp chưa báo bộ đếm. Biểu đồ
dùng tối đa 10.000 yêu cầu gần nhất trong khoảng đã chọn. API lịch sử trả tối đa
500 dòng mỗi trang. Tiến độ hiển thị tối đa 50 mục mới nhất theo giờ sửa tệp.

API chỉ xuất metadata được phép. Key, token xác thực, mã tài khoản, header
Authorization, prompt, phản hồi, nội dung truyện hoặc chương, bản tóm tắt,
kịch bản và đường dẫn tuyệt đối đều bị loại khỏi API.
