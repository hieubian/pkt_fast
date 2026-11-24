"""Adapter behavior tests with an in-memory pktlib-shaped fake."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pkt_builder import TopologyError, build_pkt_bytes


class FakePort:
    def __init__(self, owner, name):
        self.owner = owner
        self.name = name
        self.address = None

    def connect(self, other):
        self.owner.network.links.append((self.owner.name, self.name, other.owner.name, other.name))


class FakeDevice:
    def __init__(self, network, name, kind):
        self.network = network
        self.name = name
        self.kind = kind
        self.config_text = []
        self.ports = {}

    def __getitem__(self, name):
        return self.ports.setdefault(name.lower(), FakePort(self, name.lower()))

    def config(self, text):
        self.config_text.append(text)


class FakeNetwork:
    def __init__(self):
        self.devices = []
        self.links = []

    def _device(self, name, kind):
        device = FakeDevice(self, name, kind)
        self.devices.append(device)
        return device

    def router(self, name, model, at):
        device = self._device(name, f"router-{model}")
        device.at = at
        return device

    def switch(self, name, at):
        device = self._device(name, "switch")
        device.at = at
        return device

    def pc(self, name, **kwargs):
        device = self._device(name, "pc")
        device.kwargs = kwargs
        return device

    def save(self, path):
        Path(path).write_bytes(b"FAKE-PKT")


class FakePktlib:
    def __init__(self):
        self.network = FakeNetwork()

    def new(self):
        return self.network


def topology():
    return {
        "name": "basic-lab",
        "devices": [
            {"id": "r1", "type": "router", "name": "R1", "model": "2911", "x": 500, "y": 160,
             "config": {}, "interfaces": [{"name": "g0/0", "ip": "192.168.10.1", "cidr": 24}]},
            {"id": "sw1", "type": "switch", "name": "SW1", "model": "2960-24TT", "x": 500, "y": 360,
             "config": {}, "vlans": [1, 10],
             "ports": {"c1": {"mode": "trunk"}, "c2": {"mode": "access", "vlan": 10}, "c3": {"mode": "access", "vlan": 1}}},
            {"id": "pc1", "type": "pc", "name": "PC1", "x": 300, "y": 560,
             "config": {"ip": "192.168.10.10", "cidr": 24, "gateway": "192.168.10.1"}},
            {"id": "pc2", "type": "laptop", "name": "PC2", "x": 700, "y": 560,
             "config": {"ip": "192.168.10.11", "cidr": 24, "gateway": "192.168.10.1"}},
        ],
        "connections": [
            {"id": "c1", "from": "r1", "to": "sw1", "fromPort": "g0/0", "toPort": "fa0/1"},
            {"id": "c2", "from": "sw1", "to": "pc1", "fromPort": "fa0/2", "toPort": "fa0"},
            {"id": "c3", "from": "sw1", "to": "pc2", "fromPort": "fa0/3", "toPort": "fa0"},
        ],
        "firewallRules": [],
    }


class PacketBuilderTests(unittest.TestCase):
    def test_builds_topology_and_configures_ports(self):
        fake = FakePktlib()
        output = build_pkt_bytes(topology(), fake)
        self.assertEqual(output, b"FAKE-PKT")
        self.assertEqual(len(fake.network.devices), 4)
        self.assertEqual(len(fake.network.links), 3)
        router = fake.network.devices[0]
        self.assertEqual(router["g0/0"].address, "192.168.10.1/24")
        switch_config = fake.network.devices[1].config_text[0]
        self.assertIn("vlan 10", switch_config)
        self.assertIn("switchport mode trunk", switch_config)
        self.assertIn("switchport access vlan 10", switch_config)

    def test_rejects_unsupported_device_type(self):
        payload = topology()
        payload["devices"].append(
            {"id": "srv", "type": "server", "name": "Server1", "x": 0, "y": 0, "config": {}}
        )
        with self.assertRaisesRegex(TopologyError, "chưa được hỗ trợ"):
            build_pkt_bytes(payload, FakePktlib())

    def test_rejects_reused_port(self):
        payload = topology()
        payload["connections"][2]["fromPort"] = "fa0/2"
        with self.assertRaisesRegex(TopologyError, "dùng trùng cổng"):
            build_pkt_bytes(payload, FakePktlib())


if __name__ == "__main__":
    unittest.main()

