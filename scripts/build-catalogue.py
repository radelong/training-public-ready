"""Extract original exercise briefs without executing untrusted shell scripts."""
import json
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
drills = []
for file in sorted((root / "vendor/netlab/drills").glob("*.sh"),
                   key=lambda f: ({"net":0,"fw":1,"k8s":2}.get(f.stem.split("-")[0],3),f.stem)):
    content = file.read_text(encoding="utf-8")
    def field(name):
        value = re.search(rf'{name}="(.*?)"', content, re.S)
        return value.group(1) if value else ""
    drills.append({"id": file.stem, "title": field("DRILL_TITLE"), "brief": field("DRILL_BRIEF"),
                   "goal": field("DRILL_GOAL"), "tools": field("DRILL_TOOLS"),
                   "time": field("DRILL_TIME"), "level": field("DRILL_LEVEL") or "1"})

catalogue = [
    {"id": "netlab", "title": "Kubernetes Networking Lab (Netlab)", "kind": "netlab", "enabled": False,
     "description": "Practice networking, firewall, and Kubernetes troubleshooting in an isolated Ubuntu VM with locally installed K3s and exercise images.",
     "cores": 2, "memory": 4096, "drills": drills},
    {"id": "linux", "title": "Linux Lab", "kind": "linux", "enabled": False,
     "description": "Reserved for the Linux training environment you will provide. Activate it after the offline template is installed and validated.",
     "cores": 2, "memory": 2048, "drills": []},
]
(root / "catalogue.json").write_text(json.dumps(catalogue, indent=2), encoding="utf-8")
print(f"Catalogue generated: {len(catalogue[0]['drills'])} Netlab drills and one Linux placeholder")
