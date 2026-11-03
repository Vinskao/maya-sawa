from sqlalchemy import create_engine
from maya_sawa.databases.market_audio_db import MarketAudioDatabase


def test_audio_persisted_and_idempotent_per_analysis_revision():
    db = MarketAudioDatabase(create_engine('sqlite:///:memory:'))
    db.save('macro', 'US', 10, '完整報告 5.19%', b'ID3audio', 'audio/mpeg', 'voice-a')
    db.save('macro', 'US', 10, '完整報告 5.19%', b'ID3audio', 'audio/mpeg', 'voice-a')
    rows = db.list_ready()
    assert len(rows) == 1
    assert rows[0]['revision'] == 10
    assert db.audio('macro', 'US', 10) == (b'ID3audio', 'audio/mpeg')


def test_missing_and_empty_audio_are_not_published():
    import pytest
    db = MarketAudioDatabase(create_engine('sqlite:///:memory:'))
    with pytest.raises(ValueError):
        db.save('macro', 'US', 1, 'text', b'', 'audio/mpeg', 'voice-a')
    assert db.audio('macro', 'US', 1) is None
    assert db.list_ready() == []
