"""Parse an exported KiCad XML schematic netlist.

This module deliberately does not assume that shared nets imply a fault
or electrical damage.
"""

from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Circuit, Component, Connection


def load_netlist(path: str | Path) -> Circuit:
    """Read components and explicit pin-to-net membership from KiCad XML."""
    root = ET.parse(path).getroot()
    if root.tag != "export":
        raise ValueError("Expected KiCad XML netlist root <export>")

    components: dict[str, Component] = {}
    for item in root.findall("./components/comp"):
        ref = (item.get("ref") or "").strip()
        if not ref:
            raise ValueError("Component missing ref")
        if ref in components:
            raise ValueError(f"Duplicate component ref: {ref}")
        library = item.find("libsource")
        components[ref] = Component(
            ref=ref,
            value=(item.findtext("value") or "").strip(),
            library_id=(
                f"{library.get('lib', '')}:{library.get('part', '')}"
                if library is not None else ""
            ),
        )

    connections: list[Connection] = []
    for net in root.findall("./nets/net"):
        name = (net.get("name") or "").strip()
        if not name:
            name = f"__code_{net.get('code', 'unknown')}"
        for node in net.findall("node"):
            ref = (node.get("ref") or "").strip()
            pin = (node.get("pin") or "").strip()
            if not ref or not pin:
                raise ValueError(f"Malformed pin entry on net {name}")
            if ref not in components:
                raise ValueError(f"Net {name} refers to unknown component {ref}")
            connections.append(Connection(ref=ref, pin=pin, net=name))

    if not components:
        raise ValueError("No components found in netlist")
    if not connections:
        raise ValueError("No pin-to-net connections found in netlist")
    return Circuit(components=components, connections=connections)
