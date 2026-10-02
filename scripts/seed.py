import json
import os
from pathlib import Path

import httpx

from scripts.seed_lib import seed

SEED_FILE = Path(".seed.json")


def main() -> None:
    base_url = os.environ.get("FI_BASE_URL", "http://127.0.0.1:8000")
    token = os.environ.get("FI_BOOTSTRAP_TOKEN", "change-me")
    with httpx.Client(base_url=base_url, timeout=10) as client:
        seeded = seed(client, token)
    SEED_FILE.write_text(json.dumps(seeded, indent=2))
    for tenant_name, tenant in seeded.items():
        print(f"tenant {tenant_name:<8} id={tenant['id']} api_key={tenant['api_key']}")  # noqa: T201
        for source_name, source in tenant["sources"].items():
            secret = source["webhook_secret"] or "-"
            print(f"  {source_name:<20} {source['mode']:<4} id={source['id']} secret={secret}")  # noqa: T201
    print(f"wrote {SEED_FILE}")  # noqa: T201


if __name__ == "__main__":
    main()
