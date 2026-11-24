"""Pure topology-to-Packet-Tracer adapter for SimuLAN Studio."""
from __future__ import annotations

import ipaddress
import json
import re
import tempfile
from pathlib import Path
from typing import Any

MAX_DEVICES = 100
MAX_CONNECTIONS = 300
HOST_TYPES = {"pc", "laptop"}
ROUTER_MODELS = {"2811", "2911"}
PORTS = {
    "router": {
        "2811": {"fa0/0", "fa0/1"},
        "2911": {"g0/0", "g0/1", "g0/2"},
    },
    "switch": {f"fa0/{index}" for index in range(1, 25)},
    "pc": {"fa0"},
    "laptop": {"fa0"},
}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


class TopologyError(ValueError):
    """Raised when the submitted topology cannot be represented safely."""


def _address(value: Any, cidr: Any = 24) -> str | None:
    if not value:
        return None
    try:
        prefix = int(cidr or 24)
        return str(ipaddress.IPv4Interface(f"{value}/{prefix}"))
    except (ValueError, TypeError) as exc:
        raise TopologyError(f"Địa chỉ hoặc CIDR không hợp lệ: {value}/{cidr}.") from exc


def _mask_and_wildcard(cidr_value: str) -> tuple[str, str]:
    if cidr_value.strip().lower() in {"any", "*"}:
        return "0.0.0.0", "255.255.255.255"
    interface = ipaddress.IPv4Interface(cidr_value)
    wildcard = str(ipaddress.IPv4Address(int(interface.network.hostmask)))
    return str(interface.ip), wildcard


def _validate_payload(payload: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise TopologyError("Dữ liệu sơ đồ không hợp lệ.")
    devices = payload.get("devices", [])
    connections = payload.get("connections", [])
    if not isinstance(devices, list) or not isinstance(connections, list):
        raise TopologyError("Danh sách thiết bị hoặc kết nối không hợp lệ.")
    if not devices:
        raise TopologyError("Sơ đồ cần có ít nhất một thiết bị.")
    if len(devices) > MAX_DEVICES or len(connections) > MAX_CONNECTIONS:
        raise TopologyError("Sơ đồ vượt giới hạn 100 thiết bị hoặc 300 kết nối.")

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for device in devices:
        if not isinstance(device, dict):
            raise TopologyError("Một thiết bị trong sơ đồ không hợp lệ.")
        kind = device.get("type")
        if kind not in {"pc", "laptop", "router", "switch"}:
            raise TopologyError(
                f"Thiết bị “{device.get('name', kind)}” chưa được hỗ trợ xuất .pkt. "
                "Hiện hỗ trợ PC, Laptop, Router và Switch."
            )
        device_id = str(device.get("id", ""))
        name = str(device.get("name", "")).strip()
        if not device_id or device_id in seen_ids:
            raise TopologyError("Thiết bị có mã trống hoặc bị trùng.")
        if not NAME_RE.fullmatch(name):
            raise TopologyError(
                f"Tên “{name or 'chưa đặt'}” cần bắt đầu bằng chữ và chỉ dùng chữ, số, gạch ngang hoặc gạch dưới."
            )
        folded = name.casefold()
        if folded in seen_names:
            raise TopologyError(f"Tên thiết bị “{name}” bị trùng.")
        seen_ids.add(device_id)
        seen_names.add(folded)

        if kind == "router" and str(device.get("model") or "2911") not in ROUTER_MODELS:
            raise TopologyError(f"Model router của {name} chưa được hỗ trợ.")
        if kind == "router" and not isinstance(device.get("interfaces", []), list):
            raise TopologyError(f"Danh sách interface của {name} không hợp lệ.")
        if kind == "switch":
            vlans = device.get("vlans", [1])
            ports_config = device.get("ports", {})
            if not isinstance(vlans, list) or not isinstance(ports_config, dict):
                raise TopologyError(f"Cấu hình VLAN của {name} không hợp lệ.")
            try:
                if any(int(vlan) < 1 or int(vlan) > 4094 for vlan in vlans):
                    raise TopologyError(f"VLAN trên {name} phải nằm trong khoảng 1–4094.")
            except (ValueError, TypeError) as exc:
                raise TopologyError(f"VLAN trên {name} không hợp lệ.") from exc
        config = device.get("config") or {}
        if not isinstance(config, dict):
            raise TopologyError(f"Cấu hình của {name} không hợp lệ.")
        if kind in HOST_TYPES and config.get("ip"):
            _address(config["ip"], config.get("cidr", 24))
            gateway = config.get("gateway")
            if gateway:
                try:
                    ipaddress.IPv4Address(gateway)
                except ValueError as exc:
                    raise TopologyError(f"Gateway của {name} không hợp lệ.") from exc

    by_id = {str(device["id"]): device for device in devices}
    used_ports: set[tuple[str, str]] = set()
    seen_links: set[tuple[str, str]] = set()
    for connection in connections:
        if not isinstance(connection, dict):
            raise TopologyError("Một kết nối trong sơ đồ không hợp lệ.")
        from_id, to_id = str(connection.get("from", "")), str(connection.get("to", ""))
        if from_id not in by_id or to_id not in by_id or from_id == to_id:
            raise TopologyError("Kết nối trỏ tới thiết bị không tồn tại.")
        link_key = tuple(sorted((from_id, to_id)))
        if link_key in seen_links:
            raise TopologyError("Có kết nối trùng giữa hai thiết bị.")
        seen_links.add(link_key)
        from_port = str(connection.get("fromPort", "")).lower()
        to_port = str(connection.get("toPort", "")).lower()
        if not from_port or not to_port:
            raise TopologyError("Mỗi kết nối cần có cổng ở cả hai đầu.")
        for device_id, port in ((from_id, from_port), (to_id, to_port)):
            device = by_id[device_id]
            allowed = PORTS.get(device["type"], set())
            if device["type"] == "router":
                allowed = PORTS["router"][str(device.get("model") or "2911")]
            if port not in allowed:
                raise TopologyError(f"Cổng {port} không hợp lệ trên {device['name']}.")
            key = (device_id, port)
            if key in used_ports:
                raise TopologyError(f"{device['name']} đang dùng trùng cổng {port}.")
            used_ports.add(key)
        for device_id in (from_id, to_id):
            device = by_id[device_id]
            if device["type"] == "switch":
                config = (device.get("ports") or {}).get(str(connection.get("id")), {})
                if not isinstance(config, dict):
                    raise TopologyError(f"Cấu hình cổng của {device['name']} không hợp lệ.")
                if config.get("mode", "access") not in {"access", "trunk"}:
                    raise TopologyError(f"Mode cổng trên {device['name']} phải là access hoặc trunk.")
                try:
                    vlan = int(config.get("vlan", 1) or 1)
                except (ValueError, TypeError) as exc:
                    raise TopologyError(f"VLAN trên {device['name']} không hợp lệ.") from exc
                if vlan < 1 or vlan > 4094:
                    raise TopologyError(f"VLAN trên {device['name']} phải nằm trong khoảng 1–4094.")
    firewall_rules = payload.get("firewallRules") or []
    if not isinstance(firewall_rules, list):
        raise TopologyError("Danh sách ACL không hợp lệ.")
    if firewall_rules and not any(device["type"] == "router" for device in devices):
        raise TopologyError("ACL cần ít nhất một router để tạo cấu hình Packet Tracer.")
    for rule in firewall_rules:
        if not isinstance(rule, dict):
            raise TopologyError("Một ACL trong sơ đồ không hợp lệ.")
        for field in ("source", "dest"):
            value = str(rule.get(field, "any")).strip()
            if value.lower() in {"any", "*"}:
                continue
            try:
                ipaddress.IPv4Network(value, strict=False)
            except ValueError as exc:
                raise TopologyError(f"Subnet {field} trong ACL không hợp lệ: {value}.") from exc
    return devices, connections


def _switch_config(device: dict[str, Any], connections: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    vlans = sorted({int(vlan) for vlan in device.get("vlans", [1]) if 1 <= int(vlan) <= 4094})
    for vlan in vlans:
        if vlan != 1:
            lines.extend([f"vlan {vlan}", " exit"])
    for connection in connections:
        if connection["from"] == device["id"]:
            port = connection["fromPort"].lower()
        elif connection["to"] == device["id"]:
            port = connection["toPort"].lower()
        else:
            continue
        config = (device.get("ports") or {}).get(connection.get("id"), {})
        mode = config.get("mode", "access")
        vlan = int(config.get("vlan", 1) or 1)
        lines.extend([f"interface {port}"])
        if mode == "trunk":
            lines.extend([" switchport mode trunk", " switchport trunk allowed vlan all"])
        else:
            lines.extend([" switchport mode access", f" switchport access vlan {vlan}"])
        lines.append(" no shutdown")
        lines.append(" exit")
    return "\n".join(lines)


def _router_config(
    device: dict[str, Any],
    router: Any,
    connections: list[dict[str, Any]],
    firewall_rules: list[dict[str, Any]],
) -> None:
    interfaces = device.get("interfaces") or []
    covered_ports: set[str] = set()
    subinterface_lines: list[str] = []
    for iface in interfaces:
        if not isinstance(iface, dict) or not iface.get("ip"):
            continue
        name = str(iface.get("name") or "").lower()
        vlan = iface.get("vlan")
        if "." in name and not vlan:
            base, suffix = name.rsplit(".", 1)
            vlan = int(suffix) if suffix.isdigit() else None
        if vlan:
            base = name.split(".", 1)[0]
            address = _address(iface["ip"], iface.get("cidr", 24))
            parsed = ipaddress.IPv4Interface(address)
            subinterface_lines.extend([
                f"interface {base}.{int(vlan)}",
                f" encapsulation dot1Q {int(vlan)}",
                f" ip address {parsed.ip} {parsed.network.netmask}",
                " no shutdown",
                " exit",
            ])
            covered_ports.add(base)
        else:
            port = name.split(".", 1)[0]
            address = _address(iface["ip"], iface.get("cidr", 24))
            if port and port in PORTS["router"][str(device.get("model") or "2911")]:
                router[port].address = address
                covered_ports.add(port)

    config_lines = subinterface_lines[:]
    # The simplified router IP field remains useful for direct router labs.
    top_config = device.get("config") or {}
    if top_config.get("ip") and not covered_ports:
        linked_port = next(
            (c["fromPort"].lower() if c["from"] == device["id"] else c["toPort"].lower()
             for c in connections if c["from"] == device["id"] or c["to"] == device["id"]),
            None,
        )
        if linked_port:
            router[linked_port].address = _address(top_config["ip"], top_config.get("cidr", 24))
            covered_ports.add(linked_port)

    acl_lines: list[str] = []
    valid_rules = [rule for rule in firewall_rules if isinstance(rule, dict) and rule.get("action", "deny") == "deny"]
    if valid_rules:
        acl_lines.extend(["ip access-list extended SIMULAN-FILTER"])
        for rule in valid_rules:
            try:
                source_ip, source_wildcard = _mask_and_wildcard(str(rule.get("source", "any")))
                dest_ip, dest_wildcard = _mask_and_wildcard(str(rule.get("dest", "any")))
            except (ValueError, TypeError):
                continue
            acl_lines.append(f" deny ip {source_ip} {source_wildcard} {dest_ip} {dest_wildcard}")
        acl_lines.extend([" permit ip any any", " exit"])
        for connection in connections:
            if connection["from"] == device["id"]:
                port = connection["fromPort"].lower()
            elif connection["to"] == device["id"]:
                port = connection["toPort"].lower()
            else:
                continue
            acl_lines.extend([
                f"interface {port}",
                " ip access-group SIMULAN-FILTER in",
                " exit",
            ])
    all_lines = config_lines + acl_lines
    if all_lines:
        router.config("\n".join(all_lines))


def build_pkt_bytes(payload: Any, pktlib_module: Any = None) -> bytes:
    """Build a .pkt in memory through pktlib; the module may be injected in tests."""
    devices, connections = _validate_payload(payload)
    firewall_rules = payload.get("firewallRules") or []
    if not isinstance(firewall_rules, list):
        raise TopologyError("Danh sách ACL không hợp lệ.")

    if pktlib_module is None:
        try:
            import pktlib as pktlib_module  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError(
                "Chưa cài pktlib. Cài thư viện theo requirements.txt rồi thử lại."
            ) from exc

    net = pktlib_module.new()
    objects: dict[str, Any] = {}
    for device in devices:
        name = str(device["name"]).strip()
        x = max(0, min(int(device.get("x", 0)), 6000))
        y = max(0, min(int(device.get("y", 0)), 4000))
        kind = device["type"]
        if kind == "router":
            model = str(device.get("model") or "2911")
            obj = net.router(name, model, at=(x, y))
        elif kind == "switch":
            obj = net.switch(name, at=(x, y))
        else:
            config = device.get("config") or {}
            kwargs: dict[str, Any] = {"at": (x, y)}
            address = _address(config.get("ip"), config.get("cidr", 24))
            if address:
                kwargs["ip"] = address
            if config.get("gateway"):
                kwargs["gateway"] = str(config["gateway"])
            obj = net.pc(name, **kwargs)
        objects[str(device["id"])] = obj

    for connection in connections:
        left = objects[str(connection["from"])][str(connection["fromPort"]).lower()]
        right = objects[str(connection["to"])][str(connection["toPort"]).lower()]
        left.connect(right)

    for device in devices:
        kind = device["type"]
        if kind == "switch":
            config = _switch_config(device, connections)
            if config:
                objects[str(device["id"])].config(config)
        elif kind == "router":
            _router_config(device, objects[str(device["id"])], connections, firewall_rules)

    filename = str(payload.get("name") or "topology")
    filename = re.sub(r"[^A-Za-z0-9_-]+", "_", filename).strip("_")[:48] or "topology"
    with tempfile.TemporaryDirectory(prefix="simulan-pkt-") as tmp:
        target = Path(tmp) / f"{filename}.pkt"
        net.save(str(target))
        data = target.read_bytes()
    if not data:
        raise RuntimeError("pktlib không tạo được dữ liệu file.")
    return data


def decode_request(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopologyError("Yêu cầu phải là JSON UTF-8 hợp lệ.") from exc
    if not isinstance(payload, dict):
        raise TopologyError("Dữ liệu sơ đồ không hợp lệ.")
    return payload

