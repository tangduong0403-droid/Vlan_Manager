from collections import deque
import ipaddress
import re
import yaml

CISCO_IFACE_PATTERN = re.compile(
    r"^(Ethernet|FastEthernet|GigabitEthernet|TenGigabitEthernet|Et|Fa|Gi|Te)\d+(/\d+)+$",
    re.IGNORECASE,
)
MIKROTIK_IFACE_PATTERN = re.compile(
    r"^(ether|sfp|wlan|bridge)\d+$",
    re.IGNORECASE,
)


def _is_missing(value):
    """Kiểm tra giá trị bị thiếu (None hoặc chuỗi rỗng)."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _normalize_iface(iface, dev_type):
    """Chuẩn hóa tên cổng để so sánh chính xác trên mọi dòng thiết bị."""
    s = str(iface).strip().lower()
    if dev_type == "cisco_ios":
        replacements = [
            ("tengigabitethernet", "te"),
            ("gigabitethernet", "gi"),
            ("fastethernet", "fa"),
            ("ethernet", "et"),
        ]
        for full, short in replacements:
            if s.startswith(full):
                return short + s[len(full):]
    return s


def _is_valid_interface_name(iface, dev_type):
    if dev_type == "cisco_ios":
        return bool(CISCO_IFACE_PATTERN.match(iface))
    if dev_type == "mikrotik_routeros":
        return bool(MIKROTIK_IFACE_PATTERN.match(iface))
    return True


def validate_yaml_files(
    inventory_path="configs/inventory.yaml",
    vlans_path="configs/vlans.yaml",
    ports_path="configs/ports.yaml",
    rules_path="configs/compliance_rules.yaml",
    error_list=None,
    strict=False,
):
    errors = []

    # 1. Kiểm tra file tồn tại, file rỗng và cú pháp YAML
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
            err_msg = f"[{label}] Lỗi cú pháp YAML nghiêm trọng không thể đọc file: {e}"
            if error_list is not None:
                error_list.clear()
                error_list.append(err_msg)
            print("\n" + "=" * 65)
            print(f"[LỖI CÚ PHÁP YAML TRONG {label}] Không thể đọc file:")
            print(e)
            print("=" * 65)
            return False

    inv_data = loaded_files["inventory.yaml"]
    vlan_data = loaded_files["vlans.yaml"]
    port_data = loaded_files["ports.yaml"]
    rules_data = loaded_files["compliance_rules.yaml"]

    # 2. Kiểm tra động danh sách thiết bị trong inventory.yaml
    switches = inv_data.get("switches")
    ip_to_devtype = {}
    ip_to_name = {}
    ip_to_uplink = {}

    if not isinstance(switches, list) or len(switches) == 0:
        errors.append("[inventory.yaml] Thiếu danh sách 'switches' hoặc danh sách đang trống.")
    else:
        for idx, sw in enumerate(switches, start=1):
            if not isinstance(sw, dict):
                errors.append(f"[inventory.yaml] Mục thiết bị #{idx} không đúng định dạng key-value.")
                continue

            for req_key in ("name", "ip", "device_type", "env_prefix"):
                if req_key not in sw or _is_missing(sw.get(req_key)):
                    errors.append(f"[inventory.yaml] Thiết bị #{idx} bị điền thiếu trường '{req_key}'.")

            name = str(sw.get("name") or f"Thiết bị #{idx}").strip()
            ip = str(sw.get("ip") or "").strip()
            dev_type = str(sw.get("device_type") or "").strip()
            mgmt_uplink = str(sw.get("mgmt_uplink") or "").strip()

            if ip:
                try:
                    ipaddress.ip_address(ip)
                    if ip in ip_to_devtype:
                        errors.append(f"[inventory.yaml] Trùng lặp địa chỉ IP '{ip}' trên thiết bị '{name}'.")
                    ip_to_devtype[ip] = dev_type
                    ip_to_name[ip] = name
                    if mgmt_uplink:
                        ip_to_uplink[ip] = _normalize_iface(mgmt_uplink, dev_type)
                except ValueError:
                    errors.append(f"[inventory.yaml] Địa chỉ IP '{ip}' của thiết bị '{name}' không hợp lệ.")

            if dev_type and dev_type not in ("cisco_ios", "mikrotik_routeros"):
                errors.append(
                    f"[inventory.yaml] Thiết bị '{name}' ({ip}) khai báo device_type '{dev_type}' không được hỗ trợ."
                )

    # 3. Kiểm tra danh sách VLAN trong vlans.yaml
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
                    errors.append(f"[vlans.yaml] VLAN ID '{vid}' (mục #{idx}) không hợp lệ (1..4094).")
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
                    errors.append(f"[vlans.yaml] Gateway '{gw}' của VLAN {vid} sai định dạng IP/Prefix.")

    # 4. Kiểm tra tổng quát cổng Access / Trunk và đường truyền cho mọi Topology
    ports_config = port_data.get("ports_config")
    configured_port_ips = set()
    trunks_by_ip = {}
    total_nodes = len(ip_to_devtype)

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

            if sw_ip in configured_port_ips:
                errors.append(f"[ports.yaml] Trùng lặp khối cấu hình cổng cho thiết bị '{sw_ip}'.")
                continue
            configured_port_ips.add(sw_ip)

            if sw_ip not in ip_to_devtype:
                errors.append(f"[ports.yaml] IP thiết bị '{sw_ip}' không tồn tại trong inventory.yaml.")
                continue

            dev_type = ip_to_devtype[sw_ip]
            dev_name = ip_to_name.get(sw_ip, sw_ip)

            if "access_ports" not in entry or entry.get("access_ports") is None:
                errors.append(f"[ports.yaml - {sw_ip}] Thiếu khóa 'access_ports' (ghi 'access_ports: []' nếu không dùng).")
            if "trunk_ports" not in entry or entry.get("trunk_ports") is None:
                errors.append(f"[ports.yaml - {sw_ip}] Thiếu khóa 'trunk_ports' (ghi 'trunk_ports: []' nếu không dùng).")

            access_ports = entry.get("access_ports") if isinstance(entry.get("access_ports"), list) else []
            trunk_ports = entry.get("trunk_ports") if isinstance(entry.get("trunk_ports"), list) else []

            # Cho phép cả Cisco và MikroTik linh hoạt có cổng Trunk & Access trong mọi topo
            if total_nodes > 1 and len(trunk_ports) == 0:
                errors.append(
                    f"[ports.yaml - {sw_ip}] Thiết bị '{dev_name}' thiếu cổng Trunk 802.1Q ('trunk_ports' trống). "
                    f"Trong mạng có {total_nodes} thiết bị, mỗi thiết bị phải có ít nhất 1 cổng Trunk để liên thông."
                )

            if len(access_ports) == 0 and len(trunk_ports) == 0:
                errors.append(f"[ports.yaml - {sw_ip}] Thiết bị '{dev_name}' chưa được gán bất kỳ cổng nào.")

            reserved_uplink = ip_to_uplink.get(sw_ip)

            # Kiểm tra cổng Access
            seen_access_norm = set()
            for a_idx, acc in enumerate(access_ports, start=1):
                if not isinstance(acc, dict):
                    errors.append(f"[ports.yaml - {sw_ip}] Mục access_ports #{a_idx} sai định dạng.")
                    continue

                if "interface" not in acc or _is_missing(acc.get("interface")):
                    errors.append(f"[ports.yaml - {sw_ip}] Mục access_ports #{a_idx} bị thiếu 'interface'.")
                if "vlan" not in acc or _is_missing(acc.get("vlan")):
                    errors.append(f"[ports.yaml - {sw_ip}] Cổng access '{acc.get('interface', f'#{a_idx}')}' bị thiếu 'vlan'.")

                iface = str(acc.get("interface") or "").strip()
                vid = acc.get("vlan")

                if iface:
                    norm_iface = _normalize_iface(iface, dev_type)
                    if reserved_uplink and norm_iface == reserved_uplink:
                        errors.append(
                            f"[ports.yaml - {sw_ip}] Cổng '{iface}' đã khai báo là 'mgmt_uplink' quản trị, "
                            f"không được gán vào access_ports."
                        )
                    if not _is_valid_interface_name(iface, dev_type):
                        errors.append(f"[ports.yaml - {sw_ip}] Tên cổng Access '{iface}' sai định dạng cho '{dev_type}'.")
                    if norm_iface in seen_access_norm:
                        errors.append(f"[ports.yaml - {sw_ip}] Cổng Access '{iface}' bị khai báo trùng lặp.")
                    seen_access_norm.add(norm_iface)

                if not _is_missing(vid):
                    if vid == 1:
                        errors.append(f"[ports.yaml - {sw_ip}] Cổng Access '{iface}' không được gán vào VLAN 1 quản trị.")
                    elif vid not in valid_vlan_ids:
                        errors.append(
                            f"[ports.yaml - {sw_ip}] Cổng Access '{iface}' trỏ vào VLAN {vid} "
                            f"chưa có trong vlans.yaml (hợp lệ: {sorted(valid_vlan_ids)})."
                        )

            # Kiểm tra cổng Trunk
            seen_trunk_norm = set()
            for t_idx, t_item in enumerate(trunk_ports, start=1):
                if _is_missing(t_item):
                    errors.append(f"[ports.yaml - {sw_ip}] Mục trunk_ports #{t_idx} bị để trống.")
                    continue

                t_iface = str(t_item).strip()
                norm_t = _normalize_iface(t_iface, dev_type)

                if reserved_uplink and norm_t == reserved_uplink:
                    errors.append(
                        f"[ports.yaml - {sw_ip}] Cổng '{t_iface}' đã khai báo là 'mgmt_uplink' quản trị, "
                        f"không được đưa vào trunk_ports."
                    )
                if not _is_valid_interface_name(t_iface, dev_type):
                    errors.append(f"[ports.yaml - {sw_ip}] Tên cổng Trunk '{t_iface}' sai định dạng cho '{dev_type}'.")
                if norm_t in seen_trunk_norm:
                    errors.append(f"[ports.yaml - {sw_ip}] Cổng Trunk '{t_iface}' bị khai báo trùng lặp.")
                seen_trunk_norm.add(norm_t)

                if norm_t in seen_access_norm:
                    errors.append(
                        f"[ports.yaml - {sw_ip}] Xung đột vai trò cổng '{t_iface}': "
                        f"vừa khai báo ở access_ports vừa khai báo ở trunk_ports."
                    )

            trunks_by_ip[sw_ip] = seen_trunk_norm

        # 4b. Kiểm tra cân bằng & đồ thị đường truyền Trunk tổng quát cho mọi Topo
        total_trunk_endpoints = sum(len(t) for t in trunks_by_ip.values())
        if total_nodes > 1 and total_trunk_endpoints < 2 * (total_nodes - 1):
            errors.append(
                f"[LỖI ĐƯỜNG TRUYỀN] Mạng có {total_nodes} thiết bị nên cần tối thiểu {2 * (total_nodes - 1)} "
                f"đầu cổng Trunk để nối thông toàn bộ sơ đồ (hiện tại mới khai báo {total_trunk_endpoints} đầu cổng Trunk)."
            )

        links = port_data.get("links")
        if isinstance(links, list) and len(links) > 0:
            adj = {ip: set() for ip in ip_to_devtype}
            used_link_ports = set()

            for l_idx, link in enumerate(links, start=1):
                src = link.get("from") or {}
                dst = link.get("to") or {}
                ip_a, port_a = str(src.get("ip", "")).strip(), str(src.get("port", "")).strip()
                ip_b, port_b = str(dst.get("ip", "")).strip(), str(dst.get("port", "")).strip()

                if ip_a not in trunks_by_ip or ip_b not in trunks_by_ip:
                    errors.append(f"[ports.yaml - links #{l_idx}] IP thiết bị trong liên kết không khớp với inventory.")
                    continue

                norm_a = _normalize_iface(port_a, ip_to_devtype[ip_a])
                norm_b = _normalize_iface(port_b, ip_to_devtype[ip_b])

                if (ip_a, norm_a) in used_link_ports or (ip_b, norm_b) in used_link_ports:
                    errors.append(f"[ports.yaml - links #{l_idx}] Một cổng vật lý bị đấu nối trùng cho nhiều tuyến cáp.")
                used_link_ports.update({(ip_a, norm_a), (ip_b, norm_b)})

                has_a = norm_a in trunks_by_ip[ip_a]
                has_b = norm_b in trunks_by_ip[ip_b]

                if has_a and not has_b:
                    errors.append(
                        f"[LỖI ĐƯỜNG TRUYỀN - Link #{l_idx}] {ip_to_name[ip_a]} ({ip_a}) đã mở Trunk '{port_a}' "
                        f"nhưng đầu đối diện {ip_to_name[ip_b]} ({ip_b}) thiếu Trunk '{port_b}'."
                    )
                elif has_b and not has_a:
                    errors.append(
                        f"[LỖI ĐƯỜNG TRUYỀN - Link #{l_idx}] {ip_to_name[ip_b]} ({ip_b}) đã mở Trunk '{port_b}' "
                        f"nhưng đầu đối diện {ip_to_name[ip_a]} ({ip_a}) thiếu Trunk '{port_a}'."
                    )
                elif not has_a and not has_b:
                    errors.append(
                        f"[LỖI ĐƯỜNG TRUYỀN - Link #{l_idx}] Cả hai đầu {ip_to_name[ip_a]} ({port_a}) và "
                        f"{ip_to_name[ip_b]} ({port_b}) đều chưa cấu hình Trunk."
                    )
                else:
                    adj[ip_a].add(ip_b)
                    adj[ip_b].add(ip_a)

            all_ips = list(ip_to_devtype.keys())
            if all_ips:
                visited = {all_ips[0]}
                queue = deque([all_ips[0]])
                while queue:
                    curr = queue.popleft()
                    for nxt in adj[curr]:
                        if nxt not in visited:
                            visited.add(nxt)
                            queue.append(nxt)
                isolated = [f"{ip_to_name[ip]} ({ip})" for ip in all_ips if ip not in visited]
                if isolated:
                    errors.append(
                        f"[LỖI ĐƯỜNG TRUYỀN] Phát hiện thiết bị bị cô lập khỏi sơ đồ Trunk chung: {', '.join(isolated)}."
                    )

    for ip, name in ip_to_name.items():
        if ip not in configured_port_ips:
            errors.append(f"[ports.yaml] Thiết bị '{name}' ({ip}) có trong inventory.yaml nhưng thiếu trong ports.yaml.")

    # 5. Kiểm tra compliance_rules.yaml
    if rules_data:
        rules = rules_data.get("rules")
        if not isinstance(rules, dict) or not rules:
            errors.append("[compliance_rules.yaml] Thiếu khối cấu hình 'rules' hoặc đang bị trống.")
        else:
            for req_rule in ("require_ssh", "forbid_telnet", "required_vlans", "approved_trunk_vlans", "forbidden_passwords"):
                if req_rule not in rules or _is_missing(rules.get(req_rule)):
                    errors.append(f"[compliance_rules.yaml] Thiếu quy tắc bắt buộc '{req_rule}'.")

            approved_trunks = rules.get("approved_trunk_vlans")
            if isinstance(approved_trunks, list) and len(approved_trunks) > 0:
                if 1 not in approved_trunks:
                    errors.append("[compliance_rules.yaml] 'approved_trunk_vlans' thiếu VLAN 1 quản trị.")
                missing_on_trunk = valid_vlan_ids - set(approved_trunks)
                if missing_on_trunk:
                    errors.append(
                        f"[compliance_rules.yaml] Các VLAN {sorted(missing_on_trunk)} chưa được cho phép qua Trunk."
                    )

    # 6. Tổng hợp lỗi / cảnh báo
    if error_list is not None:
        error_list.clear()
        error_list.extend(errors)

    if errors:
        print("\n" + "!" * 70)
        print(f"  PHÁT HIỆN {len(errors)} LỖI/CẢNH BÁO TRONG FILE DỮ LIỆU QUY HOẠCH ĐẦU VÀO:")
        print("!" * 70)
        for i, err in enumerate(errors, start=1):
            print(f"  {i}. {err}")
        print("!" * 70)
        if strict:
            print("  -> Hệ thống đã TỪ CHỐI thực thi. Vui lòng bổ sung/sửa các mục trên và thử lại.\n")
            return False
        print("  -> Hệ thống ĐÃ GHI NHẬN lỗi và VẪN TIẾP TỤC thực hiện các bước cấu hình tự động.\n")
        return True

    print("[VALIDATOR] Kiểm tra dữ liệu quy hoạch YAML: HỢP LỆ (0 lỗi).")
    return True