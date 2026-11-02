"""Pure validation for the weekly GPT discovery job; never treat generated citations as evidence."""
import re
from datetime import datetime, timedelta, timezone

TAIPEI = timezone(timedelta(hours=8))

def week_key(now: datetime) -> str:
    year, week, _ = now.astimezone(TAIPEI).isocalendar()
    return f"{year}-W{week:02d}"

def validate_proposals(items, claims, held, macro_ids, now):
    if not isinstance(items, list) or len(items) > 3:
        raise ValueError("At most three proposals per week")
    evidence = {}
    for claim in claims:
        date = claim.get("published_at") or claim.get("as_of")
        try:
            day = datetime.fromisoformat(date[:10]).date()
        except (ValueError, TypeError):
            continue
        if not 0 <= (now.astimezone(TAIPEI).date() - day).days <= 21:
            continue
        for code in claim.get("codes") or []:
            evidence.setdefault(str(code), set()).add(claim["report_id"])
    seen, result = set(), []
    for item in items:
        code = item.get("code", "")
        if not re.fullmatch(r"\d{4}", code) or code in held or code in seen:
            raise ValueError("Proposal must be a unique, unheld Taiwan stock")
        seen.add(code)
        reports = item.get("reportIds", [])
        if not 2 <= len(set(reports)) <= 10 or not set(reports) <= evidence.get(code, set()):
            raise ValueError("Two recent public reports must explicitly identify the stock")
        for field in ("reason", "risk", "macroReason"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"Missing {field}")
        sources = item.get("macroSourceIds", [])
        if not sources or not set(sources) <= macro_ids:
            raise ValueError("Macro reasoning must cite observed macro source IDs")
        reason = f"{item['reason'].strip()} | Macro: {item['macroReason'].strip()} [{','.join(sources)}] | Risk: {item['risk'].strip()}"
        if not 10 <= len(reason) <= 300:
            raise ValueError("Public evidence summary must fit 10–300 characters")
        result.append({"code": code, "reportIds": list(dict.fromkeys(reports)), "reason": reason, "conviction": "normal"})
    return result
