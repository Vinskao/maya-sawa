"""Trusted source registry。

MVP 只允許少數幾個廠商官方網域；registry 之外的 evidence 一律拒絕。
新增來源必須是 code change + review，不能由執行期資料決定。

來源對應 Research Zone 目前 `dc-pdu` 這個 rack part 的三家廠商
（見 ty-multiverse-frontend/src/storages/companyProductMapping.json）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRUST_LEVELS = ("primary", "secondary")

# base_url 還沒填上真實 domain 前的佔位值。只要還有 placeholder，
# 就代表 registry 尚未完成，任何非 fixture 的 evidence 一律 fail closed。
PLACEHOLDER_BASE_URL = "https://"


@dataclass(frozen=True)
class TrustedSource:
    source_id: str
    name: str
    base_url: str
    scope: str
    fetch_method: str
    trust_level: str
    allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    rate_limit_note: str = ""

    def allows_host(self, host: str) -> bool:
        return host.lower() in self.allowed_hosts


TRUSTED_SOURCES: tuple[TrustedSource, ...] = (
    TrustedSource(
        source_id="delta-official",
        name="Delta Electronics official site",
        base_url="https://www.deltaww.com",
        scope="Delta 電源產品（DC-DC module、power shelf）",
        fetch_method="http_get",
        trust_level="primary",
        allowed_hosts=("www.deltaww.com", "deltaww.com"),
        rate_limit_note="每來源最多 1 req/sec",
    ),
    TrustedSource(
        source_id="vicor-official",
        name="Vicor official site",
        base_url="https://www.vicorpower.com",
        scope="Vicor Factorized Power / 電源模組",
        fetch_method="http_get",
        trust_level="primary",
        allowed_hosts=("www.vicorpower.com", "vicorpower.com"),
        rate_limit_note="每來源最多 1 req/sec",
    ),
    TrustedSource(
        source_id="infineon-official",
        name="Infineon official site",
        base_url="https://www.infineon.com",
        scope="Infineon 高壓 power stage",
        fetch_method="http_get",
        trust_level="primary",
        allowed_hosts=("www.infineon.com", "infineon.com"),
        rate_limit_note="每來源最多 1 req/sec",
    ),
)

_BY_ID = {source.source_id: source for source in TRUSTED_SOURCES}


def get_source(source_id: str) -> TrustedSource | None:
    return _BY_ID.get(source_id)


def is_trusted(source_id: str) -> bool:
    return source_id in _BY_ID


def trusted_source_ids() -> tuple[str, ...]:
    return tuple(sorted(_BY_ID))


def unresolved_placeholder_sources() -> tuple[str, ...]:
    """回傳 base_url 仍是 placeholder 或沒有 host allowlist 的來源 id。"""
    return tuple(
        source.source_id
        for source in TRUSTED_SOURCES
        if source.base_url.strip().rstrip("/") == PLACEHOLDER_BASE_URL.rstrip("/")
        or not source.allowed_hosts
    )


def registry_is_resolved() -> bool:
    return not unresolved_placeholder_sources()
