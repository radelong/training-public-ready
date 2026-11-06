#!/usr/bin/env python3
"""Register the four verified lab templates on a fresh Academy only."""

import argparse
import json
import sys
from pathlib import Path

if Path("/app/academy").is_dir():
    sys.path.insert(0, "/app")

from sqlalchemy import select

from academy.config import Settings
from academy.db import Audit, Lab, LabSession, User, allocation_lock, database
from academy.proxmox import Proxmox


EXPECTED = {"netlab": (9008, None, 28), "linux": (9105, None, 23),
            "callback-troubleshooting": (9251, 9252, 10),
            "docker-troubleshooting": (9200, None, 18)}
FIELDS = {"title", "description", "kind", "template_id", "secondary_template_id",
          "cores", "memory", "enabled"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("catalogue", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    definitions = json.loads(args.catalogue.read_text(encoding="utf-8"))
    if (not isinstance(definitions, list) or len(definitions) != 4 or
            {entry["id"] for entry in definitions} != set(EXPECTED)):
            raise ValueError("Expected exactly the four approved lab definitions")
    for entry in definitions:
        template_id, secondary, count = EXPECTED[entry["id"]]
        if (entry.get("template_id"), entry.get("secondary_template_id"), len(entry["drills"])) != (
                template_id, secondary, count):
            raise ValueError(f"Template or exercise mismatch: {entry['id']}")
        if not entry.get("enabled"):
            raise ValueError("Fresh labs must be ready for learner acceptance")

    settings = Settings()
    engine, factory = database(settings.database_url)
    try:
        with factory() as db:
            allocation_lock(db)
            users = list(db.scalars(select(User)))
            labs = list(db.scalars(select(Lab)))
            if len(users) != 1 or users[0].role != "admin" or not users[0].enabled:
                raise ValueError("This importer requires one fresh administrator and no learners")
            if db.scalars(select(LabSession)).first():
                raise ValueError("Existing lab sessions prevent a fresh import")
            if {lab.id for lab in labs} != {"netlab", "linux"} or any(lab.enabled for lab in labs):
                raise ValueError("Fresh base lab catalog must contain two inactive entries")

            proxmox = Proxmox(settings)
            for entry in definitions:
                proxmox.template_ready(Lab(template_id=entry["template_id"],
                                           secondary_template_id=entry.get("secondary_template_id")))
            print("VALIDATED 4 labs: 9008 Netlab, 9105 Linux, 9251/9252 Callback, 9200 Docker")
            if not args.apply:
                print("DRY RUN ONLY; catalog unchanged")
                return
            for entry in definitions:
                lab = db.get(Lab, entry["id"])
                values = {field: entry[field] for field in FIELDS if field in entry}
                values["drills_json"] = json.dumps(entry["drills"])
                if lab is None:
                    db.add(Lab(id=entry["id"], **values))
                else:
                    for key, value in values.items():
                        setattr(lab, key, value)
                db.add(Audit(user_id=users[0].id, action="import_fresh_lab", target=entry["id"]))
            db.commit()
            print("PUBLISHED 4 labs; verify launch, isolation, grading and cleanup before handoff")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
