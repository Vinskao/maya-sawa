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
    if key in {'maya', 'uiobbeci', 'duo'}
}
WEEKLY_PRESENTER_IDS = tuple(_SETTINGS['weeklyPresenterIds'])


def presenter_for_day(day: date):
    presenter = PRESENTERS[WEEKLY_PRESENTER_IDS[day.weekday()]]
    return {**presenter, 'voice': PRESENTERS[presenter['speaker']]['voice']} if presenter.get('speaker') else presenter


def presenter_greeting(presenter):
    """Opening line read before the script. Duo days are read by the speaker until Maya's part exists."""
    speaker = PRESENTERS[presenter['speaker']] if presenter.get('speaker') else presenter
    return f"早安，我是主播{speaker['name']}。"


def presenter_for_voice(voice: str | None):
    return next((presenter for presenter in PRESENTERS.values() if voice and presenter.get('voice') == voice), PRESENTERS['maya'])


def public_presenter_settings():
    return {
        'maya': {'id': PRESENTERS['maya']['id'], 'name': PRESENTERS['maya']['name'],
                 'videoFile': PRESENTERS['maya']['videoFile'], 'voice': PRESENTERS['maya']['voice']},
        'uiobbeci': {'id': PRESENTERS['uiobbeci']['id'], 'name': PRESENTERS['uiobbeci']['name'],
                     'videoFile': PRESENTERS['uiobbeci']['videoFile'], 'voice': PRESENTERS['uiobbeci']['voice']},
        'duo': {key: PRESENTERS['duo'][key] for key in ('id', 'name', 'videoFile', 'speaker', 'mayaStatus')},
        'weeklyPresenterIds': list(WEEKLY_PRESENTER_IDS),
    }
