"""ETF allocation provenance; ratios remain as disclosed, without invented residuals."""
from datetime import date
import math
from urllib.parse import urlparse


def validate_allocations(groups):
    if not isinstance(groups, list) or not groups:
        raise ValueError('allocations must be a non-empty array')
    dimensions = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError('allocation must be an object')
        dimension = group.get('dimension')
        if dimension not in {'holdings', 'sectors', 'regions', 'assets', 'derivatives'} or dimension in dimensions:
            raise ValueError('allocation dimension must be valid and unique')
        dimensions.add(dimension)
        coverage = group.get('coverage')
        if coverage not in {'complete', 'partial', 'unavailable'}:
            raise ValueError('allocation coverage must be complete, partial or unavailable')
        for key in ('denominator', 'sourceLabel', 'sourceUrl'):
            if not isinstance(group.get(key), str) or not group[key].strip():
                raise ValueError(f'allocation {key} is required')
        source = urlparse(group['sourceUrl'])
        if source.scheme != 'https' or not source.netloc:
            raise ValueError('allocation sourceUrl must be https')
        items = group.get('items')
        if not isinstance(items, list) or (not items and coverage != 'unavailable') or (items and coverage == 'unavailable'):
            raise ValueError('allocation items must agree with coverage')
        period = group.get('asOf')
        if period is not None or coverage != 'unavailable':
            try:
                if not isinstance(period, str) or date.fromisoformat(period).isoformat() != period:
                    raise ValueError('invalid allocation date')
            except (ValueError, TypeError):
                raise ValueError('allocation asOf must be an ISO calendar date') from None
        names = set()
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name'].strip():
                raise ValueError('allocation item name is required')
            name = item['name'].strip()
            if name in names:
                raise ValueError('duplicate allocation item')
            names.add(name)
            weight = item.get('weightPercent')
            if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight):
                raise ValueError('allocation weightPercent must be a finite number')
    return groups
