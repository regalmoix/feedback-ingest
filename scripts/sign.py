import os
import sys
from pathlib import Path

from feedback_ingest.utils.signing import sign


def main() -> None:  # the secret comes from the environment, so it stays out of ps and history
    secret = os.environ.get("FI_SIGN_SECRET") or sys.exit("set FI_SIGN_SECRET")
    (body_file,) = sys.argv[1:]
    print(sign(secret, Path(body_file).read_bytes()))  # noqa: T201


if __name__ == "__main__":
    main()
