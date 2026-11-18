# VLAN Manager

Ứng dụng CLI tự động hóa cấu hình VLAN qua SSH cho thiết bị Cisco IOS và MikroTik RouterOS. Dự án được thiết kế để chạy trong phòng lab; hãy kiểm tra cấu hình và xác nhận bạn có quyền quản trị thiết bị trước khi triển khai.

## Chức năng

- Triển khai cấu hình VLAN đồng thời trên các thiết bị trong inventory.
- Sao lưu cấu hình đang chạy; tự tạo bản sao lưu trước mỗi lần triển khai.
- Xem trước lệnh cấu hình bằng chế độ dry-run.
- So sánh hai bản sao lưu bằng unified diff.
- Khôi phục cấu hình từ một bản sao lưu.
- Kiểm tra một số tiêu chí compliance: SSH, Telnet, VLAN bắt buộc, trunk và mật khẩu mặc định.
- Kiểm tra khả năng kết nối SSH đến thiết bị.
- Xuất báo cáo trạng thái dưới dạng CSV.

> **Lưu ý:** Dry-run ban đầu chỉ in các lệnh dự kiến, nhưng sau đó ứng dụng hỏi có triển khai thật ngay hay không. Chỉ nhập `y` nếu bạn muốn áp dụng cấu hình.

## Yêu cầu

- Windows và **Python 3.13.17**.
- Python 3.13.17 phải được cài đặt trước khi tạo môi trường ảo. Có thể kiểm tra các phiên bản Python mà Python Launcher nhận diện bằng `py -0p`; bảo đảm phiên bản được dùng là `3.13.17`.
- Kết nối mạng từ máy chạy ứng dụng đến các thiết bị trong inventory.
- SSH đã được bật và tài khoản có đủ quyền cấu hình trên các thiết bị.

## Cài đặt và chạy trên Windows

Mở PowerShell tại thư mục dự án, sau đó chạy:

```powershell
cd .\Vlan
py -3.13 --version
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

Hai lệnh kiểm tra phiên bản phải in `Python 3.13.17`. Nếu `py -3.13` chọn một bản vá khác hoặc không tìm thấy Python, hãy cài Python 3.13.17 và tạo môi trường ảo bằng đường dẫn đầy đủ đến đúng `python.exe`, ví dụ:

```powershell
& "C:\đường-dẫn\đến\Python313\python.exe" -m venv .venv
```

Nếu PowerShell chặn kích hoạt môi trường ảo, có thể cho phép script cục bộ cho tài khoản hiện tại rồi kích hoạt lại:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

Khi môi trường ảo đã bật, dấu nhắc PowerShell thường hiển thị `(.venv)`. Cần bật lại môi trường ảo mỗi lần mở terminal mới:

```powershell
cd .\Vlan
.\.venv\Scripts\Activate.ps1
```

Thoát môi trường ảo bằng `deactivate`.

## Thông tin đăng nhập thiết bị

Ứng dụng đọc các biến môi trường có tiền tố được khai báo trong `configs/inventory.yaml`. Tạo file `.env` trong thư mục `Vlan` với thông tin của bạn:

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

Thay các giá trị mẫu bằng thông tin thật; bỏ các dòng `*_SECRET` nếu không sử dụng. Không đưa `.env` chứa thông tin xác thực thật lên Git. Nếu không khai báo biến môi trường, mã nguồn hiện có dùng thông tin mặc định, vì vậy hãy cấu hình thông tin riêng trước khi kết nối thiết bị.

## Cấu hình dự án

Các file YAML trong `configs/` là nguồn cấu hình của ứng dụng:

| File | Nội dung |
|---|---|
| `configs/inventory.yaml` | Tên, địa chỉ IP, loại thiết bị và tiền tố biến môi trường |
| `configs/vlans.yaml` | VLAN ID, tên VLAN và địa chỉ gateway |
| `configs/ports.yaml` | Cổng trunk/access trên từng thiết bị |
| `configs/compliance_rules.yaml` | Các tiêu chí kiểm tra compliance |

Cấu hình mẫu khai báo:

| Thiết bị | IP | Loại | Phân công cổng |
|---|---|---|---|
| SW1 | `192.168.239.11` | Cisco IOS | Trunk `Ethernet0/0`, `Ethernet0/2`; access `Ethernet0/1` thuộc VLAN 10 |
| SW2 | `192.168.239.12` | Cisco IOS | Trunk `Ethernet0/0`, `Ethernet0/1`; access `Ethernet0/2` thuộc VLAN 20 |
| SW3 | `192.168.239.13` | Cisco IOS | Trunk `Ethernet0/0`; access `Ethernet0/1` thuộc VLAN 30 và `Ethernet0/2` thuộc VLAN 40 |
| R1 | `192.168.239.14` | MikroTik RouterOS | `ether1` |

Các VLAN mẫu:

| VLAN | Tên | Gateway |
|---:|---|---|
| 10 | `Phong_Dao_Tao` | `192.168.10.1/24` |
| 20 | `Phong_Ke_Toan` | `192.168.20.1/24` |
| 30 | `Phong_Quan_Tri` | `192.168.30.1/24` |
| 40 | `Phong_IT` | `192.168.40.1/24` |

Điều chỉnh IP, loại thiết bị, VLAN và tên interface trong các file YAML sao cho khớp với lab thực tế trước khi chạy. Topology lab được cung cấp riêng dưới dạng file `.unl`; mở topology đó trong phần mềm lab tương ứng và bảo đảm các node đang chạy, có thể truy cập SSH từ máy chạy ứng dụng.

## Sử dụng

Sau khi chạy `python main.py`, chọn một chức năng trong menu:

| Lựa chọn | Chức năng |
|---:|---|
| 1 | `Deploy Configuration (Concurrent)` |
| 2 | `Backup Configuration` |
| 3 | `Compare Configuration (Diff)` |
| 4 | `Rollback Configuration` |
| 5 | `Dry-run (Preview Commands)` |
| 6 | `Compliance Checking` |
| 7 | `Network Device Status` |
| 8 | `Export Summary Report (CSV/Excel)` |
| 0 | `Exit` |

Chức năng 6 chỉ kiểm tra và báo cáo kết quả, không tự sửa các vi phạm. Trước khi triển khai hoặc rollback, nên sao lưu và kiểm tra kỹ thiết bị đích.

## Dữ liệu được tạo

- `backups/<ten_thiet_bi>/`: cấu hình sao lưu, gồm cả bản trước triển khai (`*_pre_deploy.cfg`).
- `reports/`: báo cáo CSV có dấu thời gian, có thể mở bằng Excel.

## Cấu trúc mã nguồn

```text
Vlan/
├── main.py
├── requirements.txt
├── README.md
├── configs/
│   ├── inventory.yaml
│   ├── vlans.yaml
│   ├── ports.yaml
│   └── compliance_rules.yaml
├── core/
│   ├── connection_manager.py
│   ├── deployment_manager.py
│   └── network_device.py
├── devices/
│   ├── cisco_ios.py
│   └── mikrotik.py
├── modules/
│   ├── deployer.py
│   ├── backup.py
│   ├── diff.py
│   ├── rollback.py
│   ├── compliance.py
│   └── reporter.py
├── templates/
│   └── vlan.j2
├── backups/
│   ├── SW1/
│   ├── SW2/
│   ├── SW3/
│   └── R1/
└── reports/
```

### Vai trò từng thành phần

- `main.py`: khởi chạy ứng dụng, nạp biến môi trường và hiển thị menu tương tác.
- `requirements.txt`: danh sách thư viện Python cần cài để chạy ứng dụng.
- `configs/`: cấu hình đầu vào dạng YAML. `inventory.yaml` khai báo thiết bị; `vlans.yaml` khai báo VLAN và gateway; `ports.yaml` ánh xạ VLAN vào cổng trunk/access; `compliance_rules.yaml` chứa các tiêu chí kiểm tra.
- `core/`: phần dùng chung của ứng dụng. `connection_manager.py` tạo đối tượng thiết bị và quản lý kết nối SSH; `network_device.py` định nghĩa giao diện chung cho thiết bị mạng; `deployment_manager.py` nạp cấu hình và điều phối các chức năng.
- `devices/`: triển khai hành vi riêng theo nền tảng. `cisco_ios.py` xử lý lệnh và kiểm tra trên Cisco IOS; `mikrotik.py` xử lý lệnh và kiểm tra trên MikroTik RouterOS.
- `modules/`: các tác vụ được điều phối bởi `DeploymentManager`: `deployer.py` tạo và triển khai cấu hình; `backup.py` sao lưu; `diff.py` so sánh bản sao lưu; `rollback.py` khôi phục cấu hình; `compliance.py` kiểm tra quy tắc; `reporter.py` xuất báo cáo CSV.
- `templates/vlan.j2`: template Jinja2 sinh lệnh VLAN, trunk/access cho Cisco IOS và MikroTik RouterOS.
- `backups/<ten_thiet_bi>/`: nơi lưu các bản cấu hình được lấy từ thiết bị, bao gồm snapshot trước khi triển khai.
- `reports/`: nơi lưu các báo cáo CSV được xuất từ chương trình.
