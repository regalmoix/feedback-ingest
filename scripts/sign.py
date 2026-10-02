import sys
from pathlib import Path

from feedback_ingest.utils.signing import sign


def main() -> None:
    secret, body_file = sys.argv[1:]
    print(sign(secret, Path(body_file).read_bytes()))  # noqa: T201


if __name__ == "__main__":
    main()
