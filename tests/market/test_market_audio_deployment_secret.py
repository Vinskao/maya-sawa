from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _deployment_env():
    manifest = next(yaml.safe_load_all((ROOT / 'k8s' / 'deployment.yaml').read_text(encoding='utf-8')))
    return {
        item['name']: item
        for item in manifest['spec']['template']['spec']['containers'][0]['env']
    }


def test_speech_key_comes_from_kubernetes_secret_and_worker_stays_disabled():
    env = _deployment_env()

    assert env['AZURE_SPEECH_KEY']['valueFrom']['secretKeyRef'] == {
        'name': 'azure-speech-credentials',
        'key': 'AZURE_SPEECH_KEY',
    }
    assert env['MARKET_AUDIO_SPEECH_REGION']['value'] == 'eastus'
    assert env['MARKET_AUDIO_AZURE_ENABLED']['value'].lower() == 'false'
    assert env['MARKET_AUDIO_AUTOGEN_ENABLED']['value'].lower() == 'false'
    assert env['MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT']['value'] == '0'


def test_jenkins_injects_speech_key_without_putting_it_in_command_arguments():
    pipeline = (ROOT / 'Jenkinsfile').read_text(encoding='utf-8')

    assert "credentialsId: 'AZURE_SPEECH_KEY'" in pipeline
    assert "variable: 'AZURE_SPEECH_KEY'" in pipeline
    assert 'azure-speech-credentials' in pipeline
    assert '--from-env-file=/dev/stdin' in pipeline
    assert '--from-literal=AZURE_SPEECH_KEY' not in pipeline
