import ast
import fnmatch
from pathlib import Path


def test_ci_dotenv_files_are_not_baked_into_the_runtime_image():
    rules = [line.strip() for line in Path('.dockerignore').read_text().splitlines() if line.strip() and not line.startswith('#')]
    for path in ['.env', '.env.production', '.env.development', 'nested/.env']:
        assert any(fnmatch.fnmatch(path, rule) for rule in rules if not rule.startswith('!')), path


def test_runtime_config_preserves_deployment_flags_and_never_logs_key_fragments():
    source = Path('maya_sawa/main.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'load_dotenv']
    assert calls
    assert all(not keyword.value.value for node in calls for keyword in node.keywords if keyword.arg == 'override')
    assert 'api_key[:8]' not in source
    assert 'api_key[-4:]' not in source
