# Campus VLAN Automation

Ứng dụng web chạy cục bộ để quản lý cấu hình VLAN, cổng Access/Trunk và tự động hóa các thiết bị Cisco IOS, MikroTik RouterOS qua SSH. Giao diện được xây dựng bằng Flask, phù hợp cho môi trường lab như EVE-NG.

> **Cảnh báo:** Đây là công cụ lab, không phải dịch vụ triển khai production. Chỉ chạy trên máy đáng tin cậy, không mở máy chủ ra mạng công cộng. Kiểm tra kỹ cấu hình và thiết bị đích trước khi triển khai.

## Chức năng trên giao diện web

- **Tổng quan & Thiết bị:** xem, thêm, sửa, xóa thiết bị trong inventory.
- **Quy hoạch VLAN:** thêm/xóa VLAN và khai báo gateway CIDR.
- **Cổng Access / Trunk:** gán hoặc gỡ cổng trên từng thiết bị.
- **Tự động hóa & Kiểm tra lỗi:** kiểm tra các file YAML, xem trước lệnh (dry-run), sao lưu cấu hình, triển khai đồng thời và kiểm tra kết nối SSH.
- **Bản sao lưu:** xem tối đa 25 file cấu hình sao lưu.
- Tự động sao lưu cấu hình trước mỗi lần triển khai; nếu triển khai thất bại, chương trình thử khôi phục từ snapshot trước triển khai.

Giao diện web không cung cấp thao tác so sánh bản sao lưu, rollback thủ công, kiểm tra compliance hoặc xuất báo cáo. Các thao tác này vẫn có trong menu CLI (`python main.py`).

> **Lưu ý về dry-run:** thao tác này in các lệnh dự kiến rồi hỏi xác nhận trong terminal đang chạy Flask. Nhập `y` sẽ tiếp tục triển khai thật; nhập `n` để chỉ xem trước và hủy. Nếu không có người nhập xác nhận trong terminal, yêu cầu dry-run trên trình duyệt sẽ chờ.

## Yêu cầu

- Windows và Python 3.13.17.
- Kết nối mạng từ máy chạy ứng dụng đến các thiết bị trong inventory.
- SSH được bật trên thiết bị và tài khoản có đủ quyền cấu hình.
- Một môi trường lab đã khởi chạy, chẳng hạn EVE-NG.

## Cài đặt và khởi chạy

Mở PowerShell tại thư mục gốc repository:

```powershell
cd .\Vlan
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Mở trình duyệt tại [http://127.0.0.1:5000](http://127.0.0.1:5000). Dừng máy chủ bằng `Ctrl+C` trong terminal.

Nếu PowerShell chặn kích hoạt môi trường ảo, có thể cho phép script cục bộ cho tài khoản hiện tại rồi kích hoạt lại:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

Để chạy giao diện dòng lệnh thay vì web:

```powershell
python main.py
```

## Khai báo thông tin đăng nhập

Tạo file `.env` trong thư mục `Vlan` và đặt thông tin phù hợp với giá trị `env_prefix` của từng thiết bị trong `configs/inventory.yaml`:

```dotenv
SW1_USERNAME=<ten_dang_nhap>
SW1_PASSWORD=<mat_khau>
SW1_SECRET=<enable_secret_neu_co>

SW2_USERNAME=<ten_dang_nhap>
SW2_PASSWORD=<mat_khau>
SW2_SECRET=<enable_secret_neu_co>

SW3_USERNAME=<ten_dang_nhap>
SW3_PASSWORD=<mat_khau>
SW3_SECRET=<enable_secret_neu_co>

R1_USERNAME=<ten_dang_nhap>
R1_PASSWORD=<mat_khau>
```

Thay các giá trị mẫu bằng thông tin thật; `*_SECRET` chỉ cần cho Cisco khi cần vào chế độ enable. Hãy tự khai báo thông tin xác thực trước khi kết nối: nếu thiếu biến môi trường, mã nguồn hiện dùng giá trị dự phòng được định nghĩa trong chương trình. Không chia sẻ hoặc đưa `.env` chứa thông tin thật lên Git.

## Cấu hình lab mẫu

Các file trong `configs/` là nguồn dữ liệu được giao diện đọc và cập nhật:

| File | Nội dung |
|---|---|
| `configs/inventory.yaml` | Tên, IP quản trị, loại thiết bị và tiền tố biến môi trường |
| `configs/vlans.yaml` | VLAN ID, tên VLAN và gateway |
| `configs/ports.yaml` | Ánh xạ cổng Access/Trunk theo IP thiết bị |
| `configs/compliance_rules.yaml` | Quy tắc dùng bởi chức năng compliance trong CLI |

Cấu hình mẫu hiện tại:

| Thiết bị | IP quản trị | Nền tảng | Cổng được cấu hình |
|---|---|---|---|
| SW1 | `192.168.239.11` | Cisco IOS | Trunk `Ethernet0/0`, `Ethernet0/2`; Access `Ethernet0/1` thuộc VLAN 10 |
| SW2 | `192.168.239.12` | Cisco IOS | Trunk `Ethernet0/0`, `Ethernet0/1`; Access `Ethernet0/2` thuộc VLAN 20 |
| SW3 | `192.168.239.13` | Cisco IOS | Trunk `Ethernet0/0`; Access `Ethernet0/1` thuộc VLAN 30 và `Ethernet0/2` thuộc VLAN 40 |
| R1 | `192.168.239.14` | MikroTik RouterOS | Trunk `ether1` |

| VLAN | Tên | Gateway |
|---:|---|---|
| 10 | `Phong_Dao_Tao` | `192.168.10.1/24` |
| 20 | `Phong_Ke_Toan` | `192.168.20.1/24` |
| 30 | `Phong_Quan_Tri` | `192.168.30.1/24` |
| 40 | `Phong_IT` | `192.168.40.1/24` |

Điều chỉnh IP, loại thiết bị, interface, VLAN và gateway để khớp topology thực tế. Dùng tab **Tổng quan & Thiết bị**, **Quy hoạch VLAN** và **Cổng Access / Trunk** trên giao diện để cập nhật cấu hình. Trước khi chạy tác vụ, chọn **Kiểm tra dữ liệu đầu vào**; bước này kiểm tra định dạng và tính nhất quán YAML, không xác nhận rằng thiết bị có thể truy cập qua mạng.

## Quy trình thao tác khuyến nghị

1. Khởi chạy lab và xác nhận các IP quản trị có thể truy cập từ máy chạy ứng dụng.
2. Cập nhật inventory, VLAN, gateway và ánh xạ cổng cho đúng topology; khai báo tài khoản SSH.
3. Chạy **Kiểm tra dữ liệu đầu vào** và xử lý mọi lỗi được báo.
4. Chạy **Mô phỏng & Xem trước lệnh**. Xem nội dung trong terminal; nhập `n` nếu chưa muốn triển khai.
5. Sao lưu cấu hình hiện tại, sau đó mới chạy **Triển khai cấu hình tự động**. Nút triển khai áp dụng thay đổi lên các thiết bị đã khai báo.
6. Kiểm tra kết quả tác vụ và trạng thái SSH; xác minh cấu hình trực tiếp trên thiết bị.

## Dữ liệu được tạo

- `backups/<ten_thiet_bi>/`: file `.cfg` sao lưu; bản chụp trước triển khai có hậu tố `_pre_deploy`.
- `reports/`: báo cáo CSV được tạo bởi chức năng xuất báo cáo trong CLI.

Tab **Bản sao lưu** trên web chỉ liệt kê file; khôi phục và so sánh cấu hình thực hiện qua CLI. Các lựa chọn CLI hiện có: deploy, backup, compare diff, rollback, dry-run, compliance, kiểm tra trạng thái và xuất báo cáo.

## Cấu trúc dự án

```text
Vlan/
├── app.py                 # Máy chủ Flask và các thao tác của giao diện web
├── main.py                # Menu CLI
├── Web/
│   └── Web.html           # Bản giao diện HTML tĩnh đi kèm
├── configs/               # Inventory, VLAN, port và compliance rules
├── core/                  # Điều phối triển khai và kết nối thiết bị
├── devices/               # Hành vi theo Cisco IOS / MikroTik RouterOS
├── modules/               # Deploy, backup, diff, rollback, compliance, report
├── templates/             # Template cấu hình VLAN
├── backups/               # Cấu hình sao lưu
└── reports/               # Báo cáo CSV
```
