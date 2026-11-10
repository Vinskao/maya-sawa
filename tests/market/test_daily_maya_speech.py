from pathlib import Path

import pytest

from maya_sawa.services.daily_maya_speech import prepare_spoken_transcript, validate_spoken_transcript


FIXTURE = Path(__file__).parents[1] / 'fixtures' / 'daily_maya_speech_case.txt'


def test_realistic_transcript_is_rejected_for_embedded_document_metadata():
    transcript = FIXTURE.read_text(encoding='utf-8').strip()
    with pytest.raises(ValueError, match='document metadata'):
        validate_spoken_transcript(transcript)


def test_plain_spoken_analysis_passes_and_percent_is_rendered_as_words():
    transcript = '營收年增5.19%，但成本增加，獲利率反而下降。股票代號2330仍要觀察後續訂單。'
    assert prepare_spoken_transcript(transcript) == '營收年增百分之5.19，但成本增加，獲利率反而下降。股票代號2330仍要觀察後續訂單。'


@pytest.mark.parametrize('transcript', [
    '根據報告，需求仍然穩健。',
    '資料更新時間是今天。',
    '引用來源顯示需求改善。',
    '獲利成長。\n---\n更多分析。',
])
def test_document_language_or_non_speech_markup_fails_closed(transcript):
    with pytest.raises(ValueError):
        validate_spoken_transcript(transcript)


def test_enumeration_comma_is_spoken_as_a_pause_not_a_failure():
    # 2026-11-10: the approved brief used 頓號 once and the whole day's audio failed closed.
    assert prepare_spoken_transcript('要看出貨節奏、毛利率與客戶驗證進度，再下判斷。') == '要看出貨節奏，毛利率與客戶驗證進度，再下判斷。'


def test_decimal_points_are_allowed_only_inside_numbers():
    assert prepare_spoken_transcript('EPS為5.19，年增2.4%。') == 'EPS為5.19，年增百分之2.4。'
    with pytest.raises(ValueError):
        validate_spoken_transcript('查看 example.com 的說明。')


def test_cleaner_only_removes_markdown_formatting_and_preserves_spoken_words():
    assert prepare_spoken_transcript('**需求改善**，EPS達5.19。') == '需求改善，EPS達5.19。'
    assert prepare_spoken_transcript('# 今日重點\n需求仍然穩健。') == '今日重點 需求仍然穩健。'


def test_cleaner_spells_out_dates_and_ranges_and_preserves_ticker_components():
    assert prepare_spoken_transcript('2026-11-03 07:36，BRK.B目標區間5.1–5.3%。') == (
        '2026年11月3日 7點36分，BRK B目標區間5.1到百分之5.3。'
    )


def test_cleaner_preserves_signed_numeric_meaning():
    assert prepare_spoken_transcript('EPS為-0.25，營收增加+5.2%。') == (
        'EPS為負0.25，營收增加正百分之5.2。'
    )
