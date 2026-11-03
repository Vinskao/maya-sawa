import pytest

from maya_sawa.services.daily_maya_sources import validate_sources


class Analysis:
    def read(self, kind, code):
        return {'history': [{'revision': 2, 'model': 'Claude Sonnet'}] if (kind, code) == ('stock', '2330') else []}


def test_resolves_real_immutable_revision_and_public_link():
    validate_sources(['stock:2330:2', 'https://example.org/release'], Analysis())


def test_rejects_unknown_revision_and_nonpublic_urls():
    for source in ['stock:2330:3', 'https://localhost/private', 'http://example.org', 'https://127.0.0.1/a']:
        with pytest.raises(ValueError):
            validate_sources([source], Analysis())
