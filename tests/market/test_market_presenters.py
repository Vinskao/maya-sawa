from datetime import date

from maya_sawa.services.market_presenters import PRESENTERS, presenter_for_day, presenter_for_voice, public_presenter_settings


def test_daily_presenter_schedule_and_media_are_centralized():
    assert [presenter_for_day(date(2026, 11, day))['id'] for day in range(2, 9)] == [
        'maya', 'uiobbeci', 'maya', 'uiobbeci', 'maya', 'uiobbeci', 'maya'
    ]
    assert PRESENTERS['maya']['video_file'] == 'reporterMaya.mp4'
    assert PRESENTERS['uiobbeci']['video_file'] == 'reporterUiobbeci.mp4'
    assert presenter_for_voice(PRESENTERS['uiobbeci']['voice'])['id'] == 'uiobbeci'
    assert presenter_for_voice(None)['id'] == 'maya'
    assert public_presenter_settings()['weeklyPresenterIds'][1] == 'uiobbeci'
