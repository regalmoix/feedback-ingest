import ipaddress
import socket
from collections.abc import Mapping
from datetime import timedelta
from urllib.parse import urlsplit

from feedback_ingest.connectors.base import PullConnector, SourceConnector
from feedback_ingest.connectors.custom import CustomConnector
from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.connectors.intercom import IntercomConnector
from feedback_ingest.connectors.playstore import PlaystoreConnector
from feedback_ingest.connectors.twitter import TwitterConnector
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source
from feedback_ingest.utils.time import NAIVE_UTC

_DISCOURSE: PullConnector = DiscourseConnector()
CONNECTORS: dict[SourceType, SourceConnector] = {
    c.source_type: c
    for c in (
        _DISCOURSE,
        PlaystoreConnector(),
        TwitterConnector(),
        IntercomConnector(),
        CustomConnector(),
    )
}
PULLERS: dict[SourceType, PullConnector] = {SourceType.DISCOURSE: _DISCOURSE}
_MAX_WINDOW_DAYS = 31


def check_source(source: Source) -> None:
    required = CONNECTORS[source.type].required_config
    if source.mode is SourceMode.PULL:
        if source.type not in PULLERS:
            msg = f"{source.type} cannot pull"
            raise ValueError(msg)
        required += PULLERS[source.type].pull_config
    for key in required:
        if key not in source.config:
            msg = f"{source.type} {source.mode} source needs config[{key!r}]"
            raise ValueError(msg)
    _check_values(source.config)


def _check_values(config: Mapping[str, str]) -> None:
    if "base_url" in config:
        url = urlsplit(config["base_url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            msg = "config['base_url'] must be an http(s) URL without credentials"
            raise ValueError(msg)
        if _is_internal(url.hostname):
            msg = "config['base_url'] must not point at an internal host"
            raise ValueError(msg)
    try:
        window_ok = 0 < int(config.get("window_days", "1")) <= _MAX_WINDOW_DAYS
    except ValueError:
        window_ok = False
    if not window_ok:
        msg = f"config['window_days'] must be 1 to {_MAX_WINDOW_DAYS}: {config['window_days']!r}"
        raise ValueError(msg)
    if "start_after" in config:
        try:
            start = NAIVE_UTC.validate_python(config["start_after"])
            start + timedelta(days=_MAX_WINDOW_DAYS)  # the puller's window end must exist
        except (OverflowError, ValueError):
            msg = f"config['start_after'] is not a usable datetime: {config['start_after']!r}"
            raise ValueError(msg) from None


# ponytail: checks the literal host only, no DNS (redirects and env proxies are off in HttpxClient),
# so only a public name that resolves to a private address gets through: *.nip.io-style names and
# DNS rebinding. Resolve and pin the address at request time if tenants are untrusted.
def _is_internal(host: str) -> bool:
    host = host.rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:  # short, decimal and hex IPv4 forms: 127.1, 2130706433, 0x7f000001
            ip = ipaddress.ip_address(socket.inet_aton(host))
        except OSError:
            return False
    return not ip.is_global
