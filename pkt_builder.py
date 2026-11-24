"""Pure topology-to-Packet-Tracer adapter for SimuLAN Studio."""
from __future__ import annotations

import ipaddress
import json
import re
import tempfile
from pathlib import Path
from typing import Any
import base64
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))  # dùng pktlib đi kèm dự án

MAX_DEVICES = 100
MAX_CONNECTIONS = 300
HOST_TYPES = {"pc", "laptop", "server"}
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
FAMILY = {"router": {"router"}, "switch": {"switch", "multilayer"}, "pc": {"pc"}, "laptop": {"laptop"}, "server": {"server"}}
DEFAULT_MODEL = {"router": "2911", "switch": "2960-24TT", "pc": "PC-PT", "laptop": "Laptop-PT", "server": "Server-PT"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")


def _spec() -> dict:
    """Danh mục thiết bị thật của pktlib (rỗng nếu pktlib không có, ví dụ khi chạy test với bản giả)."""
    try:
        from pktlib import _model
        return _model.SPEC
    except Exception:
        return {}


def _short(port: str) -> str:
    return port.replace("FastEthernet", "fa").replace("GigabitEthernet", "g").replace("Serial", "s").replace("Ethernet", "e").lower()


def _ports_for(device: dict[str, Any]) -> set[str]:
    spec = _spec().get(str(device.get("model") or DEFAULT_MODEL.get(device["type"], "")))
    if spec:
        return {_short(p) for p in spec["wired"]}
    if device["type"] == "router":
        return PORTS["router"].get(str(device.get("model") or "2911"), set())
    return PORTS.get(device["type"], set())


def catalog() -> list[dict[str, Any]]:
    """Mọi model pktlib xuất được, kèm cổng thật, để giao diện hiển thị khay thiết bị."""
    import pktlib
    spec = _spec()
    return [{"model": m, "family": spec[m]["family"], "ios": bool(spec[m]["ios"]), "ports": spec[m]["wired"]}
            for m in pktlib.models()]


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
        if kind not in {"pc", "laptop", "server", "router", "switch"}:
            raise TopologyError(
                f"Thiết bị “{device.get('name', kind)}” chưa được hỗ trợ xuất .pkt. "
                "Hiện hỗ trợ PC, Laptop, Server, Router và Switch."
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

        spec = _spec().get(str(device.get("model") or DEFAULT_MODEL[kind]))
        if (spec and spec["family"] not in FAMILY[kind]) or (not _spec() and kind == "router" and str(device.get("model") or "2911") not in ROUTER_MODELS) or (_spec() and not spec):
            raise TopologyError(f"Model {device.get('model')} của {name} chưa được hỗ trợ cho loại {kind}.")
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
            allowed = _ports_for(device)
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
    sub_bases: list[str] = []
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
            if base not in sub_bases:
                sub_bases.append(base)
        else:
            port = name.split(".", 1)[0]
            address = _address(iface["ip"], iface.get("cidr", 24))
            if port and port in _ports_for(device):
                router[port].address = address
                covered_ports.add(port)

    # Cổng vật lý của router-on-a-stick phải được bật, nếu không mọi subinterface đều down.
    config_lines = [line for base in sub_bases for line in (f"interface {base}", " no shutdown", " exit")] + subinterface_lines
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


def build_network(payload: Any, pktlib_module: Any = None) -> tuple[Any, Any]:
    """Dựng mạng trong bộ nhớ bằng pktlib; trả về (network, module). Module có thể được tiêm khi test."""
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
            model = str(device.get("model") or "2960-24TT")
            obj = net.switch(name, at=(x, y)) if model == "2960-24TT" else net.switch(name, model, at=(x, y))
        else:
            config = device.get("config") or {}
            kwargs: dict[str, Any] = {"at": (x, y)}
            address = _address(config.get("ip"), config.get("cidr", 24))
            if address:
                kwargs["ip"] = address
            if config.get("gateway"):
                kwargs["gateway"] = str(config["gateway"])
            obj = getattr(net, kind)(name, **kwargs)
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
        cli = str(device.get("cli") or "").strip()
        if cli and kind in {"switch", "router"}:
            try:
                objects[str(device["id"])].config(cli)
            except Exception as exc:
                raise TopologyError(f"Lệnh IOS trên {device['name']} không hợp lệ: {exc}") from exc

    return net, pktlib_module


def build_pkt_bytes(payload: Any, pktlib_module: Any = None) -> bytes:
    """Build a .pkt in memory through pktlib; the module may be injected in tests."""
    net, _ = build_network(payload, pktlib_module)
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



def load_pkt(raw: bytes) -> dict[str, Any]:
    """Đọc file .pkt bằng pktlib và trả về sơ đồ theo định dạng của giao diện (thiết bị, dây, IP, VLAN, interface)."""
    import ipaddress
    import pktlib
    net = pktlib.Network.from_bytes(raw)
    spec = _spec()
    kinds = {"router": "router", "switch": "switch", "multilayer": "switch", "pc": "pc", "laptop": "laptop", "server": "server"}
    items: dict[str, dict[str, Any]] = {}
    modes: dict[str, dict[str, dict[str, Any]]] = {}
    skipped = 0
    for index, dev in enumerate(net.devices):
        family = (spec.get(dev.model) or {}).get("family", "")
        kind = kinds.get(family)
        if not kind or dev.model == "Meraki-Server":
            skipped += 1
            continue
        item: dict[str, Any] = {"id": f"d{index + 1}", "type": kind, "name": dev.name, "model": dev.model,
                                "x": int(dev.xy[0]), "y": int(dev.xy[1]), "config": {}}
        items[dev.name] = item
        if kind in HOST_TYPES:
            try:
                nic = ipaddress.IPv4Interface(str(dev["fa0"].address))
                item["config"] = {"ip": str(nic.ip), "cidr": nic.network.prefixlen, "gateway": str(dev.gateway or "")}
            except Exception:
                pass
            continue
        cur, ifaces, ports = None, [], {}
        for line in dev.running_config:
            text = line.strip()
            if line.startswith("interface "):
                cur = _short(line.split(None, 1)[1])
                if kind == "router":
                    ifaces.append({"name": cur, "ip": "", "cidr": 24, "vlan": None})
            elif cur and kind == "router" and text.startswith("encapsulation dot1Q"):
                ifaces[-1]["vlan"] = int(text.split()[2])
            elif cur and kind == "router" and text.startswith("ip address ") and "no" not in line.split()[:1]:
                parts = text.split()
                if len(parts) >= 4:
                    ifaces[-1]["ip"], ifaces[-1]["cidr"] = parts[2], ipaddress.IPv4Network(f"0.0.0.0/{parts[3]}").prefixlen
            elif cur and kind == "switch" and text.startswith("switchport mode "):
                ports.setdefault(cur, {"mode": "access", "vlan": 1})["mode"] = text.split()[2]
            elif cur and kind == "switch" and text.startswith("switchport access vlan "):
                ports.setdefault(cur, {"mode": "access", "vlan": 1})["vlan"] = int(text.split()[3])
        if kind == "router":
            item["interfaces"] = [i for i in ifaces if i["ip"]]
        else:
            item["vlans"] = sorted({1, *(v for v in dev.vlans if v < 1002)})
            modes[dev.name] = ports
    connections = []
    for number, link in enumerate(net.links, 1):
        a, b = link.ends
        if a.device not in items or b.device not in items:
            continue
        cid = f"c{number}"
        connections.append({"id": cid, "from": items[a.device]["id"], "fromPort": _short(a.port),
                            "to": items[b.device]["id"], "toPort": _short(b.port)})
        for end in (a, b):
            if items[end.device]["type"] == "switch":
                items[end.device].setdefault("ports", {})[cid] = modes[end.device].get(_short(end.port), {"mode": "access", "vlan": 1})
    return {"name": "imported", "devices": list(items.values()), "connections": connections, "firewallRules": [], "skipped": skipped}


def _json(status: int, payload: Any) -> tuple[int, str, bytes, None]:
    return status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"), None


def handle(raw: bytes) -> tuple[int, str, bytes, str | None]:
    """Một cửa cho POST /api/export: export (mặc định) | check | script | import | catalog."""
    try:
        payload = decode_request(raw)
        action = payload.get("action", "export")
        if action == "catalog":
            return _json(200, catalog())
        if action == "import":
            return _json(200, load_pkt(base64.b64decode(str(payload.get("pkt", "")))))
        if action in {"check", "script"}:
            net, module = build_network(payload)
            if action == "check":
                return _json(200, {"problems": [str(item) for item in module.audit(net)]})
            return _json(200, {"script": module.to_python(net)})
        data = build_pkt_bytes(payload)
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", str(payload.get("name") or "topology")).strip("_")[:48] or "topology"
        return 200, "application/octet-stream", data, f"{safe}.pkt"
    except TopologyError as exc:
        return _json(400, {"error": str(exc)})
    except RuntimeError as exc:
        return _json(503, {"error": str(exc)})
    except Exception as exc:
        return _json(422, {"error": f"Không xử lý được yêu cầu: {exc}"})
