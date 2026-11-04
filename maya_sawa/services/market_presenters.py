"""Shared presenter schedule loaded from the checked-in JSON configuration."""
from datetime import date
import json
from pathlib import Path


_SETTINGS_PATH = Path(__file__).resolve().parents[2] / 'config' / 'market-presenters.json'
with _SETTINGS_PATH.open(encoding='utf-8') as settings_file:
    _SETTINGS = json.load(settings_file)

PRESENTERS = {
    key: {**value, 'video_file': value['videoFile']}
    for key, value in _SETTINGS.items()
    if key in {'maya', 'uiobbeci'}
}
WEEKLY_PRESENTER_IDS = tuple(_SETTINGS['weeklyPresenterIds'])


def presenter_for_day(day: date):
    return PRESENTERS[WEEKLY_PRESENTER_IDS[day.weekday()]]


def presenter_for_voice(voice: str | None):
    return next((presenter for presenter in PRESENTERS.values() if presenter['voice'] == voice), PRESENTERS['maya'])


def public_presenter_settings():
    return {
        'maya': {'id': PRESENTERS['maya']['id'], 'name': PRESENTERS['maya']['name'],
                 'videoFile': PRESENTERS['maya']['videoFile'], 'voice': PRESENTERS['maya']['voice']},
        'uiobbeci': {'id': PRESENTERS['uiobbeci']['id'], 'name': PRESENTERS['uiobbeci']['name'],
                     'videoFile': PRESENTERS['uiobbeci']['videoFile'], 'voice': PRESENTERS['uiobbeci']['voice']},
        'weeklyPresenterIds': list(WEEKLY_PRESENTER_IDS),
    }
