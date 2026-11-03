"""Validate cited public URLs and immutable existing analysis references.

A public-looking URL is not proof that its contents support the draft; review must
open the source and verify its evidence, date, and causal claims.
"""
import ipaddress
import re
from urllib.parse import urlsplit

_REFERENCE = re.compile(r'^(stock|macro|macro-node):([A-Z0-9-]{1,24}):([1-9][0-9]*)$')


def validate_sources(sources, analyses):
    if not sources or len(sources) > 50 or len(set(sources)) != len(sources):
        raise ValueError('One to 50 distinct sources required')
    for source in sources:
        if not isinstance(source, str) or len(source) > 2048:
            raise ValueError('Invalid source')
        match = _REFERENCE.fullmatch(source)
        if match:
            kind, code, revision = match.groups()
            result = analyses.read(kind, code)
            if not any(row['revision'] == int(revision) for row in result['history']):
                raise ValueError('Unknown analysis revision')
            continue
        try:
            url = urlsplit(source)
            host = url.hostname or ''
            if url.scheme != 'https' or not host or url.username or url.password or url.port not in (None, 443):
                raise ValueError('Invalid public URL')
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if '.' not in host or host.endswith(('.local', '.internal', '.localhost')):
                    raise ValueError('Invalid public URL')
            else:
                if not address.is_global:
                    raise ValueError('Invalid public URL')
        except ValueError as exc:
            raise ValueError('Invalid source') from exc
