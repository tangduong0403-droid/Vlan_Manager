# Campus VLAN Automation

Ứng dụng tự động hóa quản lý VLAN cho lab mạng Cisco IOS và MikroTik RouterOS. Chương trình cung cấp giao diện web bằng Flask và menu CLI, hỗ trợ kiểm tra cấu hình, xem trước lệnh, sao lưu, triển khai đồng thời, khôi phục, kiểm tra tuân thủ và xuất báo cáo.

> [!WARNING]
> Chương trình có thể thay đổi cấu hình thiết bị thật. Chỉ triển khai sau khi kiểm tra kỹ inventory, VLAN, cổng và kết nối SSH. Không đặt máy chủ Flask ra mạng công cộng khi chưa có cơ chế xác thực và bảo vệ phù hợp.

## Tính năng

- Quản lý thiết bị, VLAN và ánh xạ cổng Access/Trunk qua giao diện web.
- Kiểm tra cú pháp và tính nhất quán của các file YAML.
- Xem trước lệnh của Cisco IOS và MikroTik RouterOS.
- Sao lưu cấu hình trước khi triển khai.
- Tự động thử khôi phục snapshot trước triển khai nếu có lỗi.
- Kiểm tra trạng thái SSH, thu thập thông tin thiết bị và kiểm tra tuân thủ.
- Xuất báo cáo CSV về thiết bị và mức sử dụng cổng.
- Menu CLI cho diff, rollback và các thao tác chưa có trên giao diện web.

## Yêu cầu

- Windows 10/11 hoặc hệ điều hành tương thích chạy Python.
- Python 3.13.17 (có thể chạy bằng `python` hoặc trình launcher `py -3.13`).
- Quyền truy cập mạng SSH (thường là TCP 22) từ máy chạy ứng dụng đến tất cả thiết bị.
- Tài khoản SSH có quyền đọc cấu hình và thay đổi cấu hình.
- Với Cisco IOS, khai báo enable secret khi tài khoản cần chuyển sang chế độ privileged.
- Dự án được kiểm tra trong môi trường lab như EVE-NG.

Các thư viện Python bắt buộc được khai báo trong `requirements.txt`:

- Netmiko
- PyYAML
- Jinja2
- python-dotenv
- Flask

## Cài đặt

### 1. Mở terminal tại thư mục repository

Ví dụ:

```powershell
cd C:\Users\ACER\Downloads\Vlan_Manager
```

Nếu đã clone dự án ở vị trí khác, thay đường dẫn trên bằng thư mục gốc của repository.

### 2. Tạo và kích hoạt môi trường ảo

```powershell
cd .\Vlan
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Nếu máy không có trình launcher `py -3.13`, hãy chắc chắn lệnh `python` đang trỏ tới Python 3.13.17 rồi dùng:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Nếu PowerShell chặn kích hoạt môi trường ảo:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\.venv\Scripts\Activate.ps1
```

Lệnh sau sẽ cho biết môi trường ảo đang hoạt động:

```powershell
python -c "import sys; print(sys.executable)"
```

Đường dẫn trong kết quả phải chứa `.venv\Scripts\python.exe`.

## Cấu hình

Tất cả cấu hình chạy của chương trình nằm trong thư mục `Vlan\configs`.

| File | Chức năng |
|---|---|
| `configs/inventory.yaml` | Danh sách thiết bị, IP quản trị, nền tảng và tiền tố biến môi trường |
| `configs/vlans.yaml` | Danh sách VLAN, tên và gateway CIDR |
| `configs/ports.yaml` | Cổng Access/Trunk được gán cho từng thiết bị |
| `configs/compliance_rules.yaml` | Quy tắc kiểm tra tuân thủ trong CLI |

### 1. Cấu hình thiết bị trong inventory

Mỗi thiết bị phải có tên duy nhất, IP hợp lệ và `device_type` được hỗ trợ:

- `cisco_ios`
- `mikrotik_routeros`

Ví dụ `configs/inventory.yaml`:

```yaml
switches:
  - name: "SW1"
    ip: "192.168.239.11"
    device_type: "cisco_ios"
    env_prefix: "SW1"

  - name: "R1"
    ip: "192.168.239.14"
    device_type: "mikrotik_routeros"
    env_prefix: "R1"
```

`env_prefix` xác định tên biến đăng nhập trong `.env`. Ví dụ `SW1` yêu cầu `SW1_USERNAME`, `SW1_PASSWORD` và tùy chọn `SW1_SECRET`.

### 2. Khai báo tài khoản SSH

Tạo `.env` bằng cách sao chép file mẫu:

```powershell
Copy-Item .env.example .env
```

Sau đó chỉnh `.env`:

```dotenv
SW1_USERNAME=lab_admin
SW1_PASSWORD=mat_khau_thuc_te
SW1_SECRET=enable_secret_thuc_te

SW2_USERNAME=lab_admin
SW2_PASSWORD=mat_khau_thuc_te
SW2_SECRET=enable_secret_thuc_te

SW3_USERNAME=lab_admin
SW3_PASSWORD=mat_khau_thuc_te
SW3_SECRET=enable_secret_thuc_te

R1_USERNAME=lab_admin
R1_PASSWORD=mat_khau_thuc_te

FLASK_SECRET_KEY=doi_thanh_chuoi_ngau_nhien_va_bao_mat
```

Các quy tắc quan trọng:

- Không commit `.env` chứa thông tin thật.
- Không đặt thông tin đăng nhập trong các file YAML.
- `*_SECRET` chỉ cần khai báo cho thiết bị Cisco yêu cầu enable mode.
- `FLASK_SECRET_KEY` dùng để bảo vệ phiên Flask; nếu bỏ trống, ứng dụng tạo khóa ngẫu nhiên cho mỗi lần khởi động.
- Khi thêm thiết bị mới, thêm cả tài khoản tương ứng với `env_prefix` và xác nhận biến không bị thiếu.

### 3. Cấu hình VLAN

Ví dụ `configs/vlans.yaml`:

```yaml
vlans:
  - vlan_id: 10
    name: "Phong_Dao_Tao"
    gateway: "192.168.10.1/24"
```

Các yêu cầu:

- `vlan_id` là số nguyên trong khoảng `1..4094`.
- Không trùng VLAN ID.
- Tên VLAN không chứa khoảng trắng.
- Gateway phải có định dạng CIDR như `192.168.10.1/24`.

### 4. Cấu hình cổng

Ví dụ `configs/ports.yaml`:

```yaml
ports_config:
  - switch_ip: "192.168.239.11"
    access_ports:
      - interface: "Ethernet0/1"
        vlan: 10
    trunk_ports:
      - "Ethernet0/0"
      - "Ethernet0/2"
```

Tên cổng phải đúng nền tảng:

- Cisco: `Ethernet0/1`, `FastEthernet0/1`, `GigabitEthernet0/1`,...
- MikroTik: `ether1`, `ether2`, `sfp1`,...

VLAN dùng trong `access_ports` phải tồn tại trong `configs/vlans.yaml`. Mỗi thiết bị cần khai báo cả `access_ports` và `trunk_ports`; dùng danh sách rỗng `[]` khi không có cổng thuộc loại đó.

## Chạy chương trình

Luôn chạy lệnh từ thư mục `Vlan`, nơi chứa `app.py`, `main.py` và thư mục `configs`.

### Chạy giao diện web

```powershell
cd C:\Users\ACER\Downloads\Vlan_Manager\Vlan
.\.venv\Scripts\Activate.ps1
python app.py
```

Mở trình duyệt tại:

[http://127.0.0.1:5000](http://127.0.0.1:5000)

Chỉ tiếp nhận kết nối từ máy đang chạy ứng dụng do Flask được cấu hình với `host="127.0.0.1"`. Dừng ứng dụng bằng `Ctrl+C`.

### Chạy menu CLI

Mở terminal mới trong thư mục `Vlan`, kích hoạt `.venv` rồi chạy:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Menu CLI gồm:

1. Triển khai cấu hình đồng thời
2. Sao lưu cấu hình
3. So sánh cấu hình
4. Khôi phục cấu hình
5. Dry-run xem trước lệnh
6. Kiểm tra tuân thủ
7. Thu thập trạng thái và thông tin thiết bị
8. Xuất báo cáo tổng hợp CSV
9. Xuất báo cáo sử dụng cổng CSV
0. Thoát

Mọi lựa chọn chạy thao tác thiết bị đều chạy kiểm tra YAML trước. Nếu file cấu hình lỗi, chương trình không thực hiện thao tác thiết bị.

## Quy trình sử dụng khuyến nghị

1. Khởi động lab và xác nhận máy chạy ứng dụng có thể SSH đến mọi IP trong inventory.
2. Cập nhật inventory, VLAN, gateway và ánh xạ cổng cho đúng topology.
3. Tạo `.env` và khai báo đầy đủ thông tin đăng nhập.
4. Mở giao diện web và chạy **Kiểm tra dữ liệu đầu vào**.
5. Chạy **Mô phỏng lệnh** để xem các lệnh dự kiến trước.
6. Chạy **Sao lưu cấu hình hiện tại** để tạo snapshot thủ công.
7. Chạy **Triển khai cấu hình tự động**.
8. Kiểm tra kết quả từng thiết bị trong trang tổng quan, sau đó xác minh trực tiếp trên thiết bị.

### Lưu ý về dry-run trên web

Nút **Mô phỏng lệnh** chạy chế độ không tương tác và chỉ hiển thị lệnh dự kiến trong phần nhật ký. Nó không thay đổi thiết bị.

Chức năng dry-run của CLI có thể hỏi xác nhận trong terminal:

```text
Bạn có muốn triển khai thật các lệnh này ngay bây giờ không? (y/n):
```

- Nhập `y` để triển khai lệnh ngay sau dry-run.
- Nhập `n` để chỉ xem trước và hủy.

## Cấu hình lab mẫu

Ví dụ cấu hình hiện tại của dự án:

| Thiết bị | IP quản trị | Nền tảng |
|---|---|---|
| SW1 | `192.168.239.11` | Cisco IOS |
| SW2 | `192.168.239.12` | Cisco IOS |
| SW3 | `192.168.239.13` | Cisco IOS |
| R1 | `192.168.239.14` | MikroTik RouterOS |

| VLAN | Tên | Gateway |
|---:|---|---|
| 10 | `Phong_Dao_Tao` | `192.168.10.1/24` |
| 20 | `Phong_Ke_Toan` | `192.168.20.1/24` |
| 30 | `Phong_Quan_Tri` | `192.168.30.1/24` |
| 40 | `Phong_IT` | `192.168.40.1/24` |

Điều chỉnh các giá trị này để khớp thiết bị và topology thực tế. Sau khi đổi file, có thể chạy lại giao diện; các endpoint lưu cấu hình cũng tự tải lại dữ liệu.

## Dữ liệu được tạo

- `backups/<tên_thiết_bị>/`: file cấu hình sao lưu.
- File trước triển khai có hậu tố `_pre_deploy`.
- `reports/`: báo cáo CSV do chức năng thu thập dữ liệu, báo cáo tổng hợp và báo cáo cổng tạo ra.

Giao diện web chỉ hiển thị tối đa 25 file sao lưu gần đây. Để so sánh hoặc khôi phục cấu hình, dùng menu CLI.

## Cấu trúc thư mục

```text
Vlan/
├── app.py                 # Máy chủ Flask và các route giao diện web
├── main.py                # Menu dòng lệnh
├── README.md              # Hướng dẫn cài đặt và sử dụng
├── requirements.txt       # Thư viện Python
├── .env.example           # Mẫu biến môi trường
├── Web/
│   └── Web.html           # Giao diện HTML
├── configs/
│   ├── inventory.yaml
│   ├── vlans.yaml
│   ├── ports.yaml
│   └── compliance_rules.yaml
├── core/                  # Kết nối, thiết bị và điều phối triển khai
├── devices/               # Xử lý Cisco IOS và MikroTik RouterOS
├── modules/               # Deploy, backup, diff, rollback, compliance, báo cáo
├── templates/
│   └── vlan.j2            # Template sinh lệnh cấu hình
├── backups/
└── reports/
```

## Xử lý lỗi thường gặp

### ModuleNotFoundError hoặc ImportError

Kích hoạt môi trường ảo và cài lại dependencies:

```powershell
cd C:\Users\ACER\Downloads\Vlan_Manager\Vlan
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### Thiếu biến môi trường xác thực

Kiểm tra tên thiết bị và `env_prefix` trong `configs/inventory.yaml`, sau đó đảm bảo `.env` có đúng cặp biến:

```dotenv
<ENV_PREFIX>_USERNAME=...
<ENV_PREFIX>_PASSWORD=...
<ENV_PREFIX>_SECRET=...
```

Khởi động lại ứng dụng sau khi sửa `.env`.

### SSH connection failed

- Kiểm tra IP thiết bị và TCP 22.
- Kiểm tra tài khoản, mật khẩu và enable secret.
- Đảm bảo firewall hoặc ACL của lab cho phép kết nối.
- Cisco SSH cần cấu hình SSH và credentials hợp lệ.
- Một số thiết bị MikroTik có thể cần bật SSH service.

### Port Already in Use

Nếu cổng `5000` đang được ứng dụng khác dùng:

```powershell
netstat -ano | findstr :5000
```

Sau đó dừng tiến trình đang chiếm cổng, hoặc đổi `port=5000` trong `app.py` rồi chạy lại.

### YAML hoặc validator báo lỗi

Kiểm tra:

- Cú pháp YAML, dấu hai chấm và thụt lề.
- Trùng IP hoặc VLAN ID.
- Gateway có CIDR hợp lệ.
- Tên cổng phù hợp nền tảng.
- Cổng Access trỏ đến VLAN đã khai báo.
