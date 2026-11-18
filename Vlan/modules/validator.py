import ipaddress
import re
import yaml

CISCO_IFACE_PATTERN = re.compile(
    r"^(Ethernet|FastEthernet|GigabitEthernet|TenGigabitEthernet|Et|Fa|Gi|Te)\d+(/\d+)+$",
    re.IGNORECASE
)
MIKROTIK_IFACE_PATTERN = re.compile(
    r"^(ether|sfp|wlan|bridge)\d+$",
    re.IGNORECASE
)


def _is_missing(value):
    """Kiểm tra giá trị bị thiếu (None, chuỗi rỗng, hoặc danh sách rỗng)."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _is_valid_interface_name(iface, dev_type):
    if dev_type == "cisco_ios":
        return bool(CISCO_IFACE_PATTERN.match(iface))
    if dev_type == "mikrotik_routeros":
        return bool(MIKROTIK_IFACE_PATTERN.match(iface))
    return True


def validate_yaml_files(inventory_path="configs/inventory.yaml",
                        vlans_path="configs/vlans.yaml",
                        ports_path="configs/ports.yaml",
                        rules_path="configs/compliance_rules.yaml"):
    errors = []

    # 1. Kiểm tra file tồn tại, file rỗng hoàn toàn và lỗi cú pháp YAML
    loaded_files = {}
    for label, path in [
        ("inventory.yaml", inventory_path),
        ("vlans.yaml", vlans_path),
        ("ports.yaml", ports_path),
        ("compliance_rules.yaml", rules_path),
    ]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = yaml.safe_load(f)
            if not isinstance(content, dict) or not content:
                errors.append(f"[{label}] File đang bị trống hoàn toàn hoặc sai cấu trúc gốc.")
                loaded_files[label] = {}
            else:
                loaded_files[label] = content
        except FileNotFoundError:
            errors.append(f"[{label}] Thiếu file cấu hình tại đường dẫn '{path}'.")
            loaded_files[label] = {}
        except yaml.YAMLError as e:
            print("\n" + "=" * 65)
            print(f"[LỖI CÚ PHÁP YAML TRONG {label}] Không thể đọc file:")
            print(e)
            print("=" * 65)
            return False

    inv_data = loaded_files["inventory.yaml"]
    vlan_data = loaded_files["vlans.yaml"]
    port_data = loaded_files["ports.yaml"]
    rules_data = loaded_files["compliance_rules.yaml"]

    # 2. Kiểm tra điền thiếu trong inventory.yaml
    switches = inv_data.get("switches")
    ip_to_devtype = {}
    ip_to_name = {}

    if not isinstance(switches, list) or len(switches) == 0:
        errors.append("[inventory.yaml] Thiếu danh sách 'switches' hoặc danh sách đang trống.")
    else:
        for idx, sw in enumerate(switches, start=1):
            if not isinstance(sw, dict):
                errors.append(f"[inventory.yaml] Mục thiết bị #{idx} không đúng định dạng key-value.")
                continue

            # Kiểm tra thiếu từng trường bắt buộc của mỗi thiết bị
            for req_key in ("name", "ip", "device_type", "env_prefix"):
                if req_key not in sw or _is_missing(sw.get(req_key)):
                    errors.append(f"[inventory.yaml] Thiết bị #{idx} bị điền thiếu trường '{req_key}'.")

            name = str(sw.get("name") or f"Thiết bị #{idx}").strip()
            ip = str(sw.get("ip") or "").strip()
            dev_type = str(sw.get("device_type") or "").strip()

            if ip:
                try:
                    ipaddress.ip_address(ip)
                    if ip in ip_to_devtype:
                        errors.append(f"[inventory.yaml] Trùng lặp địa chỉ IP '{ip}' trên thiết bị '{name}'.")
                    ip_to_devtype[ip] = dev_type
                    ip_to_name[ip] = name
                except ValueError:
                    errors.append(f"[inventory.yaml] Địa chỉ IP '{ip}' của thiết bị '{name}' không hợp lệ.")

            if dev_type and dev_type not in ("cisco_ios", "mikrotik_routeros"):
                errors.append(f"[inventory.yaml] Thiết bị '{name}' ({ip}) khai báo device_type '{dev_type}' không được hỗ trợ.")

    # 3. Kiểm tra điền thiếu trong vlans.yaml
    vlans = vlan_data.get("vlans")
    valid_vlan_ids = set()

    if not isinstance(vlans, list) or len(vlans) == 0:
        errors.append("[vlans.yaml] Thiếu danh sách 'vlans' hoặc danh sách đang trống.")
    else:
        for idx, v in enumerate(vlans, start=1):
            if not isinstance(v, dict):
                errors.append(f"[vlans.yaml] Mục VLAN #{idx} không đúng định dạng key-value.")
                continue

            for req_key in ("vlan_id", "name", "gateway"):
                if req_key not in v or _is_missing(v.get(req_key)):
                    errors.append(f"[vlans.yaml] Mục VLAN #{idx} bị điền thiếu trường '{req_key}'.")

            vid = v.get("vlan_id")
            vname = str(v.get("name") or "").strip()
            gw = str(v.get("gateway") or "").strip()

            if not _is_missing(vid):
                if not isinstance(vid, int) or not (1 <= vid <= 4094):
                    errors.append(f"[vlans.yaml] VLAN ID '{vid}' (mục #{idx}) không hợp lệ (bắt buộc là số nguyên 1..4094).")
                elif vid in valid_vlan_ids:
                    errors.append(f"[vlans.yaml] Trùng lặp VLAN ID {vid}.")
                else:
                    valid_vlan_ids.add(vid)

            if vname and " " in vname:
                errors.append(f"[vlans.yaml] Tên VLAN {vid} ('{vname}') không được chứa khoảng trắng.")

            if gw:
                try:
                    ipaddress.ip_interface(gw)
                except ValueError:
                    errors.append(f"[vlans.yaml] Gateway '{gw}' của VLAN {vid} sai định dạng IP/Prefix (ví dụ: 192.168.10.1/24).")

    # 4. Kiểm tra điền thiếu và đối chiếu chéo trong ports.yaml
    ports_config = port_data.get("ports_config")
    configured_port_ips = set()

    if not isinstance(ports_config, list) or len(ports_config) == 0:
        errors.append("[ports.yaml] Thiếu danh sách 'ports_config' hoặc danh sách đang trống.")
    else:
        for idx, entry in enumerate(ports_config, start=1):
            if not isinstance(entry, dict):
                errors.append(f"[ports.yaml] Mục cấu hình cổng #{idx} không đúng định dạng.")
                continue

            if "switch_ip" not in entry or _is_missing(entry.get("switch_ip")):
                errors.append(f"[ports.yaml] Mục cấu hình cổng #{idx} bị điền thiếu trường 'switch_ip'.")
                continue

            sw_ip = str(entry.get("switch_ip")).strip()
            configured_port_ips.add(sw_ip)

            if sw_ip not in ip_to_devtype:
                errors.append(f"[ports.yaml] IP thiết bị '{sw_ip}' không tồn tại trong inventory.yaml.")
                continue

            dev_type = ip_to_devtype[sw_ip]

            if "access_ports" not in entry or entry.get("access_ports") is None:
                errors.append(f"[ports.yaml - {sw_ip}] Điền thiếu khóa 'access_ports' (nếu không có cổng access hãy ghi 'access_ports: []').")
            if "trunk_ports" not in entry or entry.get("trunk_ports") is None:
                errors.append(f"[ports.yaml - {sw_ip}] Điền thiếu khóa 'trunk_ports' (nếu không có cổng trunk hãy ghi 'trunk_ports: []').")

            access_ports = entry.get("access_ports") if isinstance(entry.get("access_ports"), list) else []
            trunk_ports = entry.get("trunk_ports") if isinstance(entry.get("trunk_ports"), list) else []

            if len(access_ports) == 0 and len(trunk_ports) == 0:
                errors.append(f"[ports.yaml - {sw_ip}] Thiết bị chưa được gán bất kỳ cổng nào (cả access_ports và trunk_ports đều trống).")

            seen_access = set()
            for a_idx, acc in enumerate(access_ports, start=1):
                if not isinstance(acc, dict):
                    errors.append(f"[ports.yaml - {sw_ip}] Mục access_ports #{a_idx} sai định dạng.")
                    continue

                if "interface" not in acc or _is_missing(acc.get("interface")):
                    errors.append(f"[ports.yaml - {sw_ip}] Mục access_ports #{a_idx} bị điền thiếu tên 'interface'.")
                if "vlan" not in acc or _is_missing(acc.get("vlan")):
                    errors.append(f"[ports.yaml - {sw_ip}] Cổng access '{acc.get('interface', f'#{a_idx}')}' bị điền thiếu số 'vlan'.")

                iface = str(acc.get("interface") or "").strip()
                vid = acc.get("vlan")

                if iface:
                    if not _is_valid_interface_name(iface, dev_type):
                        errors.append(
                            f"[ports.yaml - {sw_ip}] Tên cổng Access '{iface}' sai định dạng cho '{dev_type}' "
                            f"(ví dụ chuẩn: 'Ethernet0/1' hoặc 'ether1')."
                        )
                    if iface in seen_access:
                        errors.append(f"[ports.yaml - {sw_ip}] Cổng Access '{iface}' bị khai báo trùng lặp.")
                    seen_access.add(iface)

                if not _is_missing(vid) and vid not in valid_vlan_ids:
                    errors.append(
                        f"[ports.yaml - {sw_ip}] Cổng Access '{iface}' trỏ vào VLAN {vid} "
                        f"chưa được khai báo trong vlans.yaml (các VLAN hợp lệ: {sorted(valid_vlan_ids)})."
                    )

            seen_trunk = set()
            for t_idx, t_item in enumerate(trunk_ports, start=1):
                if _is_missing(t_item):
                    errors.append(f"[ports.yaml - {sw_ip}] Mục trunk_ports #{t_idx} bị để trống tên cổng.")
                    continue

                t_iface = str(t_item).strip()
                if not _is_valid_interface_name(t_iface, dev_type):
                    errors.append(
                        f"[ports.yaml - {sw_ip}] Tên cổng Trunk '{t_iface}' sai định dạng cho '{dev_type}' "
                        f"(ví dụ chuẩn: 'Ethernet0/0' hoặc 'ether1')."
                    )
                if t_iface in seen_trunk:
                    errors.append(f"[ports.yaml - {sw_ip}] Cổng Trunk '{t_iface}' bị khai báo trùng lặp.")
                seen_trunk.add(t_iface)

                if t_iface in seen_access:
                    errors.append(
                        f"[ports.yaml - {sw_ip}] Xung đột vai trò cổng '{t_iface}': "
                        f"vừa khai báo ở access_ports vừa khai báo ở trunk_ports."
                    )

    # Kiểm tra thiết bị đã có trong inventory.yaml nhưng lại bị thiếu trong ports.yaml
    for ip, name in ip_to_name.items():
        if ip not in configured_port_ips:
            errors.append(f"[ports.yaml] Thiết bị '{name}' ({ip}) đã khai báo trong inventory.yaml nhưng bị thiếu cấu hình cổng trong ports.yaml.")

    # 5. Kiểm tra điền thiếu trong compliance_rules.yaml
    if rules_data:
        rules = rules_data.get("rules")
        if not isinstance(rules, dict) or not rules:
            errors.append("[compliance_rules.yaml] Thiếu khối cấu hình 'rules' hoặc đang bị trống.")
        else:
            for req_rule in ("require_ssh", "forbid_telnet", "required_vlans", "approved_trunk_vlans", "forbidden_passwords"):
                if req_rule not in rules or _is_missing(rules.get(req_rule)):
                    errors.append(f"[compliance_rules.yaml] Thiếu quy tắc bắt buộc '{req_rule}'.")

    # 6. Tổng hợp và in toàn bộ danh sách lỗi lên màn hình
    if errors:
        print("\n" + "!" * 70)
        print(f"  PHÁT HIỆN {len(errors)} LỖI TRONG FILE DỮ LIỆU QUY HOẠCH ĐẦU VÀO:")
        print("!" * 70)
        for i, err in enumerate(errors, start=1):
            print(f"  {i}. {err}")
        print("!" * 70)
        print("  -> Hệ thống đã TỪ CHỐI thực thi. Vui lòng bổ sung/sửa các mục trên và thử lại.\n")
        return False

    print("[VALIDATOR] Kiểm tra dữ liệu quy hoạch YAML: HỢP LỆ (0 lỗi).")
    return True