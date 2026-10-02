from helpers import FIXTURES, SECRET

from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source


def fixture_names(source_type: SourceType) -> list[str]:
    return sorted(path.stem for path in (FIXTURES / source_type).glob("*.json"))


def source(source_type: SourceType, mode: SourceMode = SourceMode.PUSH) -> Source:
    return Source(
        id=f"src-{source_type}",
        tenant_id="tenant-test",
        type=source_type,
        name=f"test {source_type}",
        mode=mode,
        config={"base_url": "https://forum.example.test", "start_after": "2026-02-01"},
        webhook_secret=SECRET if mode is SourceMode.PUSH else None,
        cursor=None,
    )
