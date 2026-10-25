"""Per-instrument research maps: supply chain and technology (Mermaid) plus a cycle / technology / delivery view.

Stored in the versioned AI analysis table under productType "research" (code like the analysis records:
2330, 6857-JP, META-US). Records are never deleted, so research survives an instrument leaving the holdings.
Bundled seeds in maya_sawa/data/market_research/ are written at startup only where no one has edited the record.
"""
import json
import logging
import re
from pathlib import Path
from datetime import date
from maya_sawa.services.market_research_allocation import validate_allocations

logger = logging.getLogger(__name__)

PRODUCT_TYPE = "research"
SEED_EDITOR = "seed"
SEED_MODEL = "Codex · research review 2026-10-25 · seed"
SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "market_research"
VIEWS = {"順風", "中性", "逆風"}
LEANS = {"買", "中立", "賣"}
ASSESSMENT_KEYS = ("cycle", "technology", "delivery")
# Mermaid interaction directives can attach links or callbacks to nodes; research diagrams are static.
_UNSAFE_MERMAID = re.compile(r"^\s*(click|callback|href)\b|<\s*script|javascript:", re.IGNORECASE | re.MULTILINE)


def _text(value, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def _mermaid(value, field: str) -> str:
    source = _text(value, field)
    if not re.match(r"(flowchart|graph)\s+(LR|RL|TB|TD|BT)\b", source):
        raise ValueError(f"{field} must be a Mermaid flowchart")
    if _UNSAFE_MERMAID.search(source):
        raise ValueError(f"{field} must not contain links or scripts")
    return source


def validate_research_content(content: str) -> dict:
    """Parse and check a research record; raises ValueError with the first problem found."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("Research content must be JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Research content must be a JSON object")
    for field in ("name", "market", "asOf", "summary"):
        _text(data.get(field), field)
    if data.get('kind') == 'etf':
        try:
            if date.fromisoformat(data['asOf']).isoformat() != data['asOf']:
                raise ValueError('invalid ETF review date')
        except ValueError:
            raise ValueError('ETF asOf must be an ISO calendar date') from None
        validate_allocations(data.get('allocations'))
        theme = data.get('theme')
        theme_research = data.get('themeResearch')
        if theme or theme_research is not None:
            _text(theme, 'theme')
            if not isinstance(theme_research, dict):
                raise ValueError('thematic ETFs require themeResearch')
            validate_research_content(json.dumps({**theme_research, 'kind': 'company',
                **{key: data[key] for key in ('name', 'market', 'asOf')}}, ensure_ascii=False))
        for source in data.get('sources') or []:
            if not isinstance(source, dict) or not str(source.get('url', '')).startswith('https://'):
                raise ValueError('sources need an https url')
            _text(source.get('label'), 'sources.label')
        return data
    if data.get('kind') not in (None, 'company'):
        raise ValueError('research kind must be company or etf')
    _text(data.get('leanReason'), 'leanReason')
    _mermaid(data.get("supplyChain"), "supplyChain")
    _mermaid(data.get("technology"), "technology")
    assessment = data.get("assessment")
    if not isinstance(assessment, dict):
        raise ValueError("assessment must be an object")
    for key in ASSESSMENT_KEYS:
        item = assessment.get(key)
        if not isinstance(item, dict) or item.get("view") not in VIEWS:
            raise ValueError(f"assessment.{key}.view must be one of {sorted(VIEWS)}")
        _text(item.get("note"), f"assessment.{key}.note")
    if data.get("lean") not in LEANS:
        raise ValueError(f"lean must be one of {sorted(LEANS)}")
    for item in data.get("watch") or []:
        _text(item, "watch")
    for source in data.get("sources") or []:
        if not isinstance(source, dict) or not str(source.get("url", "")).startswith("https://"):
            raise ValueError("sources need an https url")
        _text(source.get("label"), "sources.label")
    return data


def load_seed_records(directory: Path = SEED_DIR) -> dict[str, dict]:
    """Bundled research seeds, one JSON file per record code (file name = code)."""
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))}


def seed_research(database, seeds: dict[str, dict]) -> dict:
    """Write seeds where the record is missing or still exactly as a previous seed left it."""
    counts = {"inserted": 0, "updated": 0, "kept": 0}
    for code, record in seeds.items():
        content = json.dumps(record, ensure_ascii=False, indent=1)
        validate_research_content(content)
        current = database.read(PRODUCT_TYPE, code)["analysis"]
        if current is None:
            database.save(PRODUCT_TYPE, code, SEED_MODEL, content, 0, SEED_EDITOR)
            counts["inserted"] += 1
        elif database.last_editor(PRODUCT_TYPE, code) == SEED_EDITOR and current["content"] != content:
            database.save(PRODUCT_TYPE, code, SEED_MODEL, content, current["revision"], SEED_EDITOR)
            counts["updated"] += 1
        else:
            counts["kept"] += 1
    return counts


def list_research(database) -> list[dict]:
    """Every stored research record (also ones no longer held), without the full content."""
    items = []
    for row in database.list(PRODUCT_TYPE):
        try:
            data = json.loads(row["content"])
        except ValueError:
            data = {}
        items.append({"code": row["code"], "name": data.get("name"), "market": data.get("market"), "lean": data.get("lean"),
                      "asOf": data.get("asOf"), "revision": row["revision"], "updatedAt": row["updatedAt"]})
    return items


def seed_bundled_research(database) -> None:
    try:
        logger.info("Research seeds: %s", seed_research(database, load_seed_records()))
    except Exception:
        logger.exception("Research seeding failed")


INDUSTRY_SEED = SEED_DIR.parent / "market_industries.json"


def load_industry_groups(path: Path = INDUSTRY_SEED) -> list[dict]:
    """Bundled industry groups (族群) and their member stocks."""
    return json.loads(path.read_text(encoding="utf-8"))["groups"]


def seed_industry_groups(database, groups: list[dict]) -> dict:
    """Create bundled groups that do not exist yet; groups edited through the API are never overwritten."""
    counts = {"inserted": 0, "kept": 0}
    for group in groups:
        if database.group(group["id"]) is None:
            database.save_group(group)
            counts["inserted"] += 1
        else:
            counts["kept"] += 1
    return counts


def seed_bundled_industries(database) -> None:
    try:
        logger.info("Industry group seeds: %s", seed_industry_groups(database, load_industry_groups()))
    except Exception:
        logger.exception("Industry group seeding failed")
