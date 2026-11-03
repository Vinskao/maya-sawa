from maya_sawa.services.market_audio_text import split_speech_text


def test_split_preserves_every_character_and_limit_for_long_chinese_report():
    report = ('美國 CPI 3.74%，AI 供應鏈仍然強勁。\n' * 180) + '最後一段 5.19%。'
    chunks = split_speech_text(report, 150)
    assert ''.join(chunks) == report
    assert all(0 < len(chunk) <= 150 for chunk in chunks)
    assert len(chunks) > 1


def test_split_unbroken_text_and_empty():
    assert split_speech_text('', 3) == []
    assert split_speech_text('abcdefg', 3) == ['abc', 'def', 'g']


def test_split_requires_positive_limit():
    import pytest
    with pytest.raises(ValueError):
        split_speech_text('test', 0)


def test_split_does_not_cut_decimal_at_sentence_boundary():
    chunks = split_speech_text('ABCDE 5.19% 後續內容', 8)
    assert ''.join(chunks) == 'ABCDE 5.19% 後續內容'
    assert not chunks[0].endswith('5.')
