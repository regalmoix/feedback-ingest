import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from scripts.seed_lib import TENANTS, seed_tenant

SEED_FILE = Path(".seed.json")


def main() -> None:
    base_url = os.environ.get("FI_BASE_URL", "http://127.0.0.1:8000")
    token = os.environ.get("FI_BOOTSTRAP_TOKEN") or sys.exit("set FI_BOOTSTRAP_TOKEN")
    SEED_FILE.touch(mode=0o600)
    SEED_FILE.chmod(0o600)  # it holds api keys and webhook secrets
    seeded: dict[str, dict[str, Any]] = {}

    def save(tenant: dict[str, Any]) -> None:  # after every step: a failure keeps earlier keys
        seeded[tenant["name"]] = tenant
        SEED_FILE.write_text(json.dumps(seeded, indent=2))

    with httpx.Client(base_url=base_url, timeout=10) as client:
        for name in TENANTS:
            save(seed_tenant(client, token, name, save))
    print(f"wrote api keys and webhook secrets to {SEED_FILE} (mode 600)")  # noqa: T201


if __name__ == "__main__":
    main()
