import io
import os
import yaml
from contextlib import redirect_stdout
from flask import Flask, render_template_string, request, redirect, url_for, flash
from dotenv import load_dotenv

from modules.validator import validate_yaml_files
from main import DeploymentManager

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = "vlan_manager_secret_key"

INVENTORY_PATH = os.path.join(BASE_DIR, "configs", "inventory.yaml")
VLANS_PATH = os.path.join(BASE_DIR, "configs", "vlans.yaml")
PORTS_PATH = os.path.join(BASE_DIR, "configs", "ports.yaml")
BACKUPS_DIR = os.path.join(BASE_DIR, "backups")

# Giao diện dự phòng tự động kích hoạt nếu chưa tìm thấy file web.html bên ngoài
FALLBACK_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Campus VLAN Automation — NOC Dashboard</title>
  <style>
    :root {
      --bg-page: #f1f5f9; --bg-card: #ffffff; --navy-900: #091526; --navy-800: #0f253e;
      --blue-600: #2563eb; --blue-700: #1d4ed8; --blue-50: #eff6ff;
      --emerald-600: #059669; --emerald-50: #ecfdf5; --amber-600: #d97706; --amber-50: #fffbeb;
      --rose-600: #e11d48; --rose-50: #fff1f2; --slate-900: #0f172a; --slate-700: #334155;
      --slate-500: #64748b; --slate-200: #e2e8f0; --slate-100: #f8fafc;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg-page); color: var(--slate-900); line-height: 1.5; }
    .topbar { background: linear-gradient(125deg, var(--navy-900) 0%, var(--navy-800) 60%, #163a63 100%); color: #fff; padding: 26px 0 30px; }
    .container { max-width: 1240px; margin: 0 auto; padding: 0 24px; }
    .topbar-inner { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px; }
    .brand-title { display: flex; align-items: center; gap: 12px; }
    .brand-icon { width: 42px; height: 42px; border-radius: 10px; background: rgba(37,99,235,0.25); border: 1px solid rgba(96,165,250,0.4); display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: 18px; color: #60a5fa; }
    .brand-title h1 { font-size: 23px; font-weight: 700; }
    .brand-subtitle { font-size: 13.5px; color: #94a3b8; margin-top: 3px; }
    .status-pill { display: inline-flex; align-items: center; gap: 8px; background: rgba(15,23,42,0.55); border: 1px solid rgba(148,163,184,0.25); padding: 7px 14px; border-radius: 999px; font-size: 12.5px; color: #e2e8f0; }
    .dot-live { width: 8px; height: 8px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px #10b981; }
    .nav-wrapper { background: var(--bg-card); border-bottom: 1px solid var(--slate-200); position: sticky; top: 0; z-index: 40; }
    .nav-tabs { display: flex; gap: 8px; list-style: none; overflow-x: auto; }
    .nav-tab { padding: 14px 16px; font-size: 13.5px; font-weight: 600; color: var(--slate-500); cursor: pointer; border-bottom: 3px solid transparent; white-space: nowrap; }
    .nav-tab:hover { color: var(--blue-600); background: var(--slate-100); }
    .nav-tab.active { color: var(--blue-600); border-bottom-color: var(--blue-600); }
    .kpi-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 18px; margin: 24px 0; }
    .kpi-card { background: var(--bg-card); border: 1px solid var(--slate-200); border-radius: 12px; padding: 20px 22px; display: flex; justify-content: space-between; align-items: center; }
    .kpi-label { font-size: 13px; font-weight: 600; color: var(--slate-500); }
    .kpi-value { font-size: 28px; font-weight: 800; color: var(--slate-900); margin-top: 4px; }
    .kpi-badge { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 14px; }
    .kpi-blue { background: var(--blue-50); color: var(--blue-600); }
    .kpi-emerald { background: var(--emerald-50); color: var(--emerald-600); }
    .kpi-amber { background: var(--amber-50); color: var(--amber-600); }
    .kpi-rose { background: var(--rose-50); color: var(--rose-600); }
    .card { background: var(--bg-card); border: 1px solid var(--slate-200); border-radius: 12px; padding: 24px; margin-bottom: 24px; }
    .card-header { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; padding-bottom: 14px; border-bottom: 1px solid var(--slate-100); }
    .card-title { font-size: 17px; font-weight: 700; }
    .card-sub { font-size: 12.5px; color: var(--slate-500); margin-top: 2px; }
    .btn { padding: 8px 15px; border: none; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
    .btn-primary { background: var(--blue-600); color: #fff; }
    .btn-success { background: var(--emerald-600); color: #fff; }
    .btn-warning { background: var(--amber-600); color: #fff; }
    .btn-dark { background: var(--slate-900); color: #fff; }
    .btn-outline { background: #fff; color: var(--slate-700); border: 1px solid var(--slate-200); }
    .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 6px; }
    .btn-danger-soft { background: var(--rose-50); color: var(--rose-600); border: 1px solid #fecdd3; }
    .toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 14px; }
    .input-control { padding: 8px 12px; border: 1px solid var(--slate-200); border-radius: 8px; font-size: 13.5px; background: #fff; }
    .search-field { width: 310px; }
    table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
    thead th { text-align: left; padding: 12px 14px; background: var(--slate-100); color: var(--slate-700); font-weight: 700; font-size: 12.5px; text-transform: uppercase; border-bottom: 1px solid var(--slate-200); }
    tbody td { padding: 13px 14px; border-bottom: 1px solid var(--slate-100); }
    .tag { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; margin: 2px 4px 2px 0; }
    .tag-ios { background: #e0f2fe; color: #0369a1; }
    .tag-mikrotik { background: #f3e8ff; color: #7e22ce; }
    .tag-access { background: var(--blue-50); color: var(--blue-700); border: 1px solid #bfdbfe; }
    .tag-trunk { background: var(--emerald-50); color: var(--emerald-600); border: 1px solid #a7f3d0; }
    .tag-del { background: none; border: none; color: inherit; cursor: pointer; font-weight: 800; opacity: 0.7; }
    .alert { padding: 13px 18px; border-radius: 10px; margin-top: 18px; font-size: 13.5px; font-weight: 600; display: flex; justify-content: space-between; }
    .alert-success { background: var(--emerald-50); color: #065f46; border: 1px solid #a7f3d0; }
    .alert-danger { background: var(--rose-50); color: #9f1239; border: 1px solid #fecdd3; }
    .alert-warning { background: var(--amber-50); color: #92400e; border: 1px solid #fde68a; }
    .terminal-wrap { margin-top: 18px; border-radius: 10px; overflow: hidden; border: 1px solid #1e293b; }
    .terminal-bar { background: #1e293b; color: #94a3b8; padding: 8px 14px; font-size: 12px; font-family: Consolas, monospace; display: flex; justify-content: space-between; align-items: center; }
    .terminal-body { background: #0b1120; color: #34d399; font-family: Consolas, monospace; font-size: 13px; padding: 18px; white-space: pre-wrap; max-height: 480px; overflow-y: auto; line-height: 1.55; }
    .terminal-body.err { color: #fda4af; }
    .modal-overlay { display: none; position: fixed; inset: 0; background: rgba(15,23,42,0.6); align-items: center; justify-content: center; z-index: 100; }
    .modal-overlay.open { display: flex; }
    .modal-dialog { background: #fff; width: 450px; max-width: 94vw; border-radius: 14px; padding: 24px; }
    .form-row { margin-bottom: 13px; }
    .form-row label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 5px; }
    .form-row input, .form-row select { width: 100%; }
    .modal-footer { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
    .pane { display: none; }
    .pane.active { display: block; }
    .inline-form { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 18px; background: var(--slate-100); padding: 14px; border-radius: 10px; }
  </style>
</head>
<body>
  <header class="topbar">
    <div class="container topbar-inner">
      <div class="brand-title">
        <div class="brand-icon">VN</div>
        <div>
          <h1>Campus VLAN Automation</h1>
          <div class="brand-subtitle">Hệ thống tự động hóa quản lý VLAN, Trunk &amp; Inter-VLAN Routing (Cisco IOS &amp; MikroTik)</div>
        </div>
      </div>
      <div class="status-pill"><span class="dot-live"></span><span>EVE-NG Lab Controller &bull; Validator Active</span></div>
    </div>
  </header>

  <nav class="nav-wrapper">
    <div class="container">
      <ul class="nav-tabs">
        <li class="nav-tab {{ 'active' if active_tab in ['overview', 'devices'] }}" onclick="switchPane('overview', this)">Tổng quan &amp; Thiết bị</li>
        <li class="nav-tab {{ 'active' if active_tab == 'vlans' }}" onclick="switchPane('vlans', this)">Quy hoạch VLAN</li>
        <li class="nav-tab {{ 'active' if active_tab == 'ports' }}" onclick="switchPane('ports', this)">Cổng Access / Trunk</li>
        <li class="nav-tab {{ 'active' if active_tab in ['automation', 'result'] }}" onclick="switchPane('automation', this)">Tự động hóa &amp; Kiểm tra lỗi</li>
        <li class="nav-tab {{ 'active' if active_tab == 'backups' }}" onclick="switchPane('backups', this)">Bản sao lưu ({{ total_backups }})</li>
      </ul>
    </div>
  </nav>

  <main class="container">
    {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}{% for cat, msg in messages %}
        <div class="alert alert-{{ cat }}"><span>{{ msg }}</span><button class="tag-del" onclick="this.parentElement.remove()">✕</button></div>
      {% endfor %}{% endif %}
    {% endwith %}

    <section class="kpi-grid">
      <div class="kpi-card"><div><div class="kpi-label">Tổng thiết bị mạng</div><div class="kpi-value">{{ total_devices }}</div></div><div class="kpi-badge kpi-blue">DEV</div></div>
      <div class="kpi-card"><div><div class="kpi-label">VLAN nghiệp vụ</div><div class="kpi-value">{{ total_vlans }}</div></div><div class="kpi-badge kpi-emerald">VLAN</div></div>
      <div class="kpi-card"><div><div class="kpi-label">Cổng Access đã gán</div><div class="kpi-value">{{ total_access }}</div></div><div class="kpi-badge kpi-amber">PORT</div></div>
      <div class="kpi-card"><div><div class="kpi-label">Bản sao lưu cấu hình</div><div class="kpi-value">{{ total_backups }}</div></div><div class="kpi-badge kpi-rose">CFG</div></div>
    </section>

    <section id="pane-overview" class="pane {{ 'active' if active_tab in ['overview', 'devices'] }}">
      <div class="card">
        <div class="card-header">
          <div><div class="card-title">Quản lý thiết bị hạ tầng (configs/inventory.yaml)</div><div class="card-sub">Danh sách Switch Layer 2/3 và Router thực hiện định tuyến Inter-VLAN</div></div>
          <button class="btn btn-primary" onclick="openAddDevice()">+ Thêm thiết bị mới</button>
        </div>
        <div class="toolbar">
          <input type="text" id="searchDev" class="input-control search-field" placeholder="Lọc nhanh theo tên, IP, nền tảng..." onkeyup="filterDevices()">
          <span class="card-sub" id="devCountText">Hiển thị {{ total_devices }}/{{ total_devices }} thiết bị</span>
        </div>
        <table id="devTable">
          <thead><tr><th>Tên thiết bị</th><th>Địa chỉ IP</th><th>Hệ điều hành</th><th>Env Prefix</th><th>SSH</th><th style="text-align:right;">Thao tác</th></tr></thead>
          <tbody>
            {% for sw in switches %}
            <tr>
              <td><strong>{{ sw.name }}</strong></td>
              <td><code>{{ sw.ip }}</code></td>
              <td><span class="tag {{ 'tag-mikrotik' if sw.device_type == 'mikrotik_routeros' else 'tag-ios' }}">{{ sw.device_type }}</span></td>
              <td>{{ sw.env_prefix }}</td>
              <td>22</td>
              <td style="text-align:right;">
                <button class="btn btn-outline btn-sm" onclick="openEditDevice('{{ sw.name }}','{{ sw.ip }}','{{ sw.device_type }}','{{ sw.env_prefix }}')">Sửa</button>
                <form action="/device/delete/{{ sw.ip }}" method="POST" style="display:inline;" onsubmit="return confirm('Xóa thiết bị {{ sw.name }}?')">
                  <button type="submit" class="btn btn-danger-soft btn-sm">Xóa</button>
                </form>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>

    <section id="pane-vlans" class="pane {{ 'active' if active_tab == 'vlans' }}">
      <div class="card">
        <div class="card-header"><div><div class="card-title">Danh sách VLAN &amp; Sub-interface Gateway (configs/vlans.yaml)</div></div></div>
        <form action="/vlan/add" method="POST" class="inline-form">
          <input type="number" name="vlan_id" class="input-control" placeholder="VLAN ID (10-4094)" required>
          <input type="text" name="name" class="input-control" placeholder="Tên VLAN (vd: Phong_Nhan_Su)" required>
          <input type="text" name="gateway" class="input-control" placeholder="Gateway (vd: 192.168.50.1/24)" required>
          <button type="submit" class="btn btn-primary">+ Thêm VLAN</button>
        </form>
        <table>
          <thead><tr><th>VLAN ID</th><th>Tên phòng ban</th><th>Default Gateway</th><th style="text-align:right;">Thao tác</th></tr></thead>
          <tbody>
            {% for v in vlans %}
            <tr>
              <td><span class="tag tag-access">VLAN {{ v.vlan_id }}</span></td>
              <td><strong>{{ v.name }}</strong></td>
              <td><code>{{ v.gateway }}</code></td>
              <td style="text-align:right;">
                <form action="/vlan/delete/{{ v.vlan_id }}" method="POST" style="display:inline;">
                  <button type="submit" class="btn btn-danger-soft btn-sm">Xóa</button>
                </form>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>

    <section id="pane-ports" class="pane {{ 'active' if active_tab == 'ports' }}">
      <div class="card">
        <div class="card-header"><div><div class="card-title">Phân bổ cổng Access &amp; Trunk (configs/ports.yaml)</div></div></div>
        <form action="/port/add" method="POST" class="inline-form">
          <select name="switch_ip" class="input-control" required>
            {% for sw in switches %}<option value="{{ sw.ip }}">{{ sw.name }} ({{ sw.ip }})</option>{% endfor %}
          </select>
          <select name="port_type" id="portTypeSelect" class="input-control" onchange="document.getElementById('vlanSelect').style.display=(this.value==='access')?'inline-block':'none'">
            <option value="access">Access Port</option>
            <option value="trunk">Trunk Port</option>
          </select>
          <input type="text" name="interface" class="input-control" placeholder="Tên cổng (vd: Ethernet0/3)" required>
          <select name="vlan" id="vlanSelect" class="input-control">
            {% for v in vlans %}<option value="{{ v.vlan_id }}">VLAN {{ v.vlan_id }} ({{ v.name }})</option>{% endfor %}
          </select>
          <button type="submit" class="btn btn-primary">+ Gán cổng</button>
        </form>
        <table>
          <thead><tr><th>Thiết bị (IP)</th><th>Cổng Access</th><th>Cổng Trunk</th></tr></thead>
          <tbody>
            {% for p in ports_config %}
            <tr>
              <td><strong>{{ p.switch_ip }}</strong></td>
              <td>
                {% for a in p.access_ports or [] %}
                  <span class="tag tag-access">{{ a.interface }} &rarr; VLAN {{ a.vlan }}
                    <form action="/port/delete" method="POST" style="display:inline;">
                      <input type="hidden" name="switch_ip" value="{{ p.switch_ip }}">
                      <input type="hidden" name="port_type" value="access">
                      <input type="hidden" name="interface" value="{{ a.interface }}">
                      <button type="submit" class="tag-del">✕</button>
                    </form>
                  </span>
                {% endfor %}
              </td>
              <td>
                {% for t in p.trunk_ports or [] %}
                  <span class="tag tag-trunk">{{ t }}
                    <form action="/port/delete" method="POST" style="display:inline;">
                      <input type="hidden" name="switch_ip" value="{{ p.switch_ip }}">
                      <input type="hidden" name="port_type" value="trunk">
                      <input type="hidden" name="interface" value="{{ t }}">
                      <button type="submit" class="tag-del">✕</button>
                    </form>
                  </span>
                {% endfor %}
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </section>

    <section id="pane-automation" class="pane {{ 'active' if active_tab in ['automation', 'result'] }}">
      <div class="card">
        <div class="card-header"><div><div class="card-title">Bảng điều khiển Tự động hóa &amp; Kiểm tra lỗi YAML</div></div></div>
        <div style="display:flex; gap:10px; flex-wrap:wrap;">
          <form action="/action/validate" method="POST"><button class="btn btn-dark" title="Rà soát cú pháp, định dạng IP, tên cổng trên toàn bộ file YAML">1. Kiểm tra dữ liệu đầu vào</button></form>
          <form action="/action/dry_run" method="POST"><button class="btn btn-primary" title="Sinh câu lệnh CLI xem trước, không tác động thiết bị">2. Mô phỏng &amp; Xem trước lệnh</button></form>
          <form action="/action/backup" method="POST"><button class="btn btn-outline" title="Sao lưu cấu hình đang chạy về thư mục backups/">3. Sao lưu cấu hình hiện tại</button></form>
          <form action="/action/deploy" method="POST" onsubmit="return confirm('Xác nhận triển khai cấu hình tự động xuống toàn bộ thiết bị EVE-NG?')"><button class="btn btn-success" title="Đẩy cấu hình xuống thiết bị thật qua SSH">4. Triển khai cấu hình tự động</button></form>
          <form action="/action/status" method="POST"><button class="btn btn-warning" title="Thu thập và hiển thị trạng thái VLAN, cổng mạng thực tế trên thiết bị">5. Trạng Thái Thực Tế</button></form>
        </div>
        <div class="terminal-wrap">
          <div class="terminal-bar">
            <span>console@vlan-manager:~/automation</span>
            <button class="btn btn-outline btn-sm" style="padding:2px 8px; font-size:11px;" onclick="navigator.clipboard.writeText(document.getElementById('consoleOutput').innerText);alert('Đã copy log!');">Copy Log</button>
          </div>
          <div id="consoleOutput" class="terminal-body {{ 'err' if 'PHÁT HIỆN' in last_output or 'LỖI' in last_output }}">{{ last_output if last_output else 'Sẵn sàng thực thi. Chọn tác vụ phía trên để chạy Validator hoặc triển khai cấu hình...' }}</div>
        </div>
      </div>
    </section>

    <section id="pane-backups" class="pane {{ 'active' if active_tab == 'backups' }}">
      <div class="card">
        <div class="card-header"><div><div class="card-title">Bản sao lưu cấu hình (backups/)</div></div></div>
        <table>
          <thead><tr><th>Đường dẫn file</th></tr></thead>
          <tbody>{% for bf in backup_files %}<tr><td><code>{{ bf }}</code></td></tr>{% endfor %}</tbody>
        </table>
      </div>
    </section>
  </main>

  <div id="deviceModal" class="modal-overlay">
    <div class="modal-dialog">
      <h3 id="mTitle" style="margin-bottom:14px;">Thêm thiết bị mới</h3>
      <form id="devForm" action="/device/add" method="POST">
        <input type="hidden" name="old_ip" id="fOldIp">
        <div class="form-row"><label>Tên thiết bị</label><input type="text" name="name" id="fName" class="input-control" required></div>
        <div class="form-row"><label>Địa chỉ IP</label><input type="text" name="ip" id="fIp" class="input-control" required></div>
        <div class="form-row"><label>Nền tảng</label>
          <select name="device_type" id="fType" class="input-control">
            <option value="cisco_ios">cisco_ios</option>
            <option value="mikrotik_routeros">mikrotik_routeros</option>
          </select>
        </div>
        <div class="form-row"><label>Env Prefix</label><input type="text" name="env_prefix" id="fPrefix" class="input-control" required></div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline" onclick="document.getElementById('deviceModal').classList.remove('open')">Hủy</button>
          <button type="submit" class="btn btn-primary">Lưu cấu hình</button>
        </div>
      </form>
    </div>
  </div>

  <script>
    function switchPane(name, el) {
      document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
      el.classList.add('active');
      document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
      document.getElementById('pane-' + name).classList.add('active');
    }
    function filterDevices() {
      const q = document.getElementById('searchDev').value.toLowerCase();
      const rows = document.querySelectorAll('#devTable tbody tr');
      let c = 0;
      rows.forEach(r => { const ok = r.innerText.toLowerCase().includes(q); r.style.display = ok ? '' : 'none'; if (ok) c++; });
      document.getElementById('devCountText').innerText = `Hiển thị ${c}/${rows.length} thiết bị`;
    }
    function openAddDevice() {
      document.getElementById('mTitle').innerText = 'Thêm thiết bị mới';
      document.getElementById('devForm').action = '/device/add';
      document.getElementById('fOldIp').value = '';
      document.getElementById('fName').value = '';
      document.getElementById('fIp').value = '';
      document.getElementById('fPrefix').value = '';
      document.getElementById('deviceModal').classList.add('open');
    }
    function openEditDevice(name, ip, type, prefix) {
      document.getElementById('mTitle').innerText = 'Sửa thiết bị: ' + name;
      document.getElementById('devForm').action = '/device/edit';
      document.getElementById('fOldIp').value = ip;
      document.getElementById('fName').value = name;
      document.getElementById('fIp').value = ip;
      document.getElementById('fType').value = type;
      document.getElementById('fPrefix').value = prefix;
      document.getElementById('deviceModal').classList.add('open');
    }
  </script>
</body>
</html>"""


def get_html_source():
    """Tự động tìm web.html ở mọi thư mục khả dĩ, nếu không có thì dùng FALLBACK_HTML."""
    candidates = [
        os.path.join(BASE_DIR, "templates_web", "web.html"),
        os.path.join(BASE_DIR, "templates", "web.html"),
        os.path.join(BASE_DIR, "web_templates", "web.html"),
        os.path.join(BASE_DIR, "web.html"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
    return FALLBACK_HTML


def load_yaml(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(path, data):
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def count_backups():
    total = 0
    if os.path.exists(BACKUPS_DIR):
        for _, _, files in os.walk(BACKUPS_DIR):
            total += len([f for f in files if f.endswith(".cfg")])
    return total


def run_with_validation(action_func):
    buf = io.StringIO()
    with redirect_stdout(buf):
        is_valid = validate_yaml_files()
        if is_valid:
            action_func()
    return is_valid, buf.getvalue()


@app.route("/")
def index():
    inv = load_yaml(INVENTORY_PATH).get("switches", [])
    vlans = load_yaml(VLANS_PATH).get("vlans", [])
    ports_cfg = load_yaml(PORTS_PATH).get("ports_config", [])

    total_access_ports = sum(len(item.get("access_ports") or []) for item in ports_cfg)
    backup_files = []
    if os.path.exists(BACKUPS_DIR):
        for root, _, files in os.walk(BACKUPS_DIR):
            for fn in sorted(files, reverse=True):
                if fn.endswith(".cfg"):
                    backup_files.append(os.path.relpath(os.path.join(root, fn), BASE_DIR))

    return render_template_string(
        get_html_source(),
        switches=inv,
        vlans=vlans,
        ports_config=ports_cfg,
        total_devices=len(inv),
        total_vlans=len(vlans),
        total_access=total_access_ports,
        total_backups=count_backups(),
        backup_files=backup_files[:25],
        last_output=request.args.get("output", ""),
        active_tab=request.args.get("tab", "overview"),
    )


@app.route("/device/add", methods=["POST"])
def add_device():
    inv_data = load_yaml(INVENTORY_PATH)
    switches = inv_data.setdefault("switches", [])
    new_sw = {
        "name": request.form.get("name", "").strip(),
        "ip": request.form.get("ip", "").strip(),
        "device_type": request.form.get("device_type", "cisco_ios").strip(),
        "env_prefix": request.form.get("env_prefix", "").strip(),
    }
    switches.append(new_sw)
    save_yaml(INVENTORY_PATH, inv_data)

    ports_data = load_yaml(PORTS_PATH)
    ports_list = ports_data.setdefault("ports_config", [])
    if not any(p.get("switch_ip") == new_sw["ip"] for p in ports_list):
        ports_list.append({"switch_ip": new_sw["ip"], "access_ports": [], "trunk_ports": []})
        save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã thêm thiết bị {new_sw['name']} ({new_sw['ip']}).", "success")
    return redirect(url_for("index", tab="overview"))


@app.route("/device/edit", methods=["POST"])
def edit_device():
    old_ip = request.form.get("old_ip", "").strip()
    new_ip = request.form.get("ip", "").strip()
    inv_data = load_yaml(INVENTORY_PATH)
    for sw in inv_data.get("switches", []):
        if sw.get("ip") == old_ip:
            sw["name"] = request.form.get("name", "").strip()
            sw["ip"] = new_ip
            sw["device_type"] = request.form.get("device_type", "cisco_ios").strip()
            sw["env_prefix"] = request.form.get("env_prefix", "").strip()
            break
    save_yaml(INVENTORY_PATH, inv_data)

    if old_ip != new_ip:
        ports_data = load_yaml(PORTS_PATH)
        for p in ports_data.get("ports_config", []):
            if p.get("switch_ip") == old_ip:
                p["switch_ip"] = new_ip
        save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã cập nhật thiết bị ({new_ip}).", "success")
    return redirect(url_for("index", tab="overview"))


@app.route("/device/delete/<ip>", methods=["POST"])
def delete_device(ip):
    inv_data = load_yaml(INVENTORY_PATH)
    inv_data["switches"] = [s for s in inv_data.get("switches", []) if s.get("ip") != ip]
    save_yaml(INVENTORY_PATH, inv_data)

    ports_data = load_yaml(PORTS_PATH)
    ports_data["ports_config"] = [p for p in ports_data.get("ports_config", []) if p.get("switch_ip") != ip]
    save_yaml(PORTS_PATH, ports_data)

    flash(f"Đã xóa thiết bị {ip}.", "warning")
    return redirect(url_for("index", tab="overview"))


@app.route("/vlan/add", methods=["POST"])
def add_vlan():
    vlan_data = load_yaml(VLANS_PATH)
    vlans = vlan_data.setdefault("vlans", [])
    vid_raw = request.form.get("vlan_id", "").strip()
    vlans.append({
        "vlan_id": int(vid_raw) if vid_raw.isdigit() else vid_raw,
        "name": request.form.get("name", "").strip(),
        "gateway": request.form.get("gateway", "").strip(),
    })
    save_yaml(VLANS_PATH, vlan_data)
    flash("Đã thêm VLAN mới vào vlans.yaml.", "success")
    return redirect(url_for("index", tab="vlans"))


@app.route("/vlan/delete/<int:vlan_id>", methods=["POST"])
def delete_vlan(vlan_id):
    vlan_data = load_yaml(VLANS_PATH)
    vlan_data["vlans"] = [v for v in vlan_data.get("vlans", []) if v.get("vlan_id") != vlan_id]
    save_yaml(VLANS_PATH, vlan_data)
    flash(f"Đã xóa VLAN {vlan_id}.", "warning")
    return redirect(url_for("index", tab="vlans"))


@app.route("/port/add", methods=["POST"])
def add_port():
    sw_ip = request.form.get("switch_ip", "").strip()
    port_type = request.form.get("port_type", "access")
    iface = request.form.get("interface", "").strip()
    vlan_raw = request.form.get("vlan", "").strip()

    ports_data = load_yaml(PORTS_PATH)
    for entry in ports_data.get("ports_config", []):
        if entry.get("switch_ip") == sw_ip:
            if port_type == "access":
                entry.setdefault("access_ports", []).append({
                    "interface": iface,
                    "vlan": int(vlan_raw) if vlan_raw.isdigit() else vlan_raw
                })
            else:
                entry.setdefault("trunk_ports", []).append(iface)
            break
    save_yaml(PORTS_PATH, ports_data)
    flash(f"Đã gán cổng {iface} cho thiết bị {sw_ip}.", "success")
    return redirect(url_for("index", tab="ports"))


@app.route("/port/delete", methods=["POST"])
def delete_port():
    sw_ip = request.form.get("switch_ip", "").strip()
    port_type = request.form.get("port_type", "access")
    iface = request.form.get("interface", "").strip()

    ports_data = load_yaml(PORTS_PATH)
    for entry in ports_data.get("ports_config", []):
        if entry.get("switch_ip") == sw_ip:
            if port_type == "access":
                entry["access_ports"] = [a for a in (entry.get("access_ports") or []) if a.get("interface") != iface]
            else:
                entry["trunk_ports"] = [t for t in (entry.get("trunk_ports") or []) if t != iface]
            break
    save_yaml(PORTS_PATH, ports_data)
    flash(f"Đã gỡ cổng {iface} khỏi {sw_ip}.", "warning")
    return redirect(url_for("index", tab="ports"))


@app.route("/action/<cmd>", methods=["POST"])
def execute_action(cmd):
    manager = DeploymentManager()
    action_map = {
        "validate": ("1. Kiểm tra dữ liệu đầu vào", lambda: None),
        "dry_run": ("2. Mô phỏng & Xem trước lệnh", manager.execute_dry_run),
        "backup": ("3. Sao lưu cấu hình hiện tại", manager.execute_backup),
        "deploy": ("4. Triển khai cấu hình tự động", manager.execute_deploy),
        "status": ("5. Trạng Thái Thực Tế", manager.execute_status),
        "compliance": ("Kiểm toán & Đối soát chuẩn", manager.execute_compliance),
    }
    if cmd not in action_map:
        flash("Lệnh không hợp lệ.", "danger")
        return redirect(url_for("index", tab="automation"))

    label, action_fn = action_map[cmd]
    is_valid, output_log = run_with_validation(action_fn)
    if not is_valid:
        flash("Phát hiện lỗi trong file cấu hình YAML! Hệ thống đã chặn thực thi.", "danger")
    else:
        flash(f"Hoàn tất tác vụ: {label}", "success")

    return redirect(url_for("index", tab="automation", output=output_log))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)