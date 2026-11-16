from pathlib import Path


def test_jenkins_syncs_gemini_secret_before_deploy():
    pipeline = (Path(__file__).resolve().parents[2] / "Jenkinsfile").read_text(encoding="utf-8")
    stage = pipeline.split("stage('Configure Gemini Visibility')", 1)[1].split("stage(", 1)[0]

    assert "credentialsId: 'GEMINI_API_KEY', variable: 'GEMINI_API_KEY'" in stage
    assert "kubectl create secret generic gemini-visibility" in stage
    assert "--from-env-file=/dev/stdin" in stage
    assert "--from-literal" not in stage
    assert pipeline.index("stage('Configure Gemini Visibility')") < pipeline.index("stage('Deploy")
