import importlib.util
import json
from pathlib import Path


def load_plugin():
    path = Path(__file__).resolve().parents[1] / '__init__.py'
    spec = importlib.util.spec_from_file_location('live_context_injector', path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def config(tmp_path, enabled=('cli',), allowed=None, max_chars=12000):
    current = tmp_path / 'current.md'
    state = tmp_path / 'injector-state.json'
    return {
        'current_path': str(current),
        'state_path': str(state),
        'enabled_platforms': list(enabled),
        'allowed_sender_ids': list(allowed or []),
        'session_state_ttl_hours': 168,
        'max_context_chars': max_chars,
    }


def current_text():
    return '# Hermes live context for Ryo\n\nbody\n\n## 詳細参照\n- weather.md\n'


def test_platform_disabled_returns_none(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path, enabled=('cli',))
    Path(cfg['current_path']).write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)
    assert hook(platform='slack', session_id='s1', sender_id='u1') is None


def test_sender_allowlist_blocks_mismatch(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path, enabled=('slack',), allowed=['Ryo'])
    Path(cfg['current_path']).write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)
    assert hook(platform='slack', session_id='s1', sender_id='Other') is None


def test_cli_injection_does_not_require_sender_id_even_with_slack_allowlist(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path, enabled=('cli', 'slack'), allowed=['U0APZSWQPHA'])
    Path(cfg['current_path']).write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)

    result = hook(platform='cli', session_id='s1', sender_id='')

    assert result and '<hermes_live_context>' in result['context']


def test_slack_sender_allowlist_accepts_mention_form_config(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path, enabled=('slack',), allowed=['<@U0APZSWQPHA>'])
    Path(cfg['current_path']).write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)

    result = hook(platform='slack', session_id='s1', sender_id='U0APZSWQPHA')

    assert result and '<hermes_live_context>' in result['context']


def test_first_call_injects_and_second_same_hash_skips(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path)
    Path(cfg['current_path']).write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)
    first = hook(platform='cli', session_id='s1', sender_id='')
    assert first and '<hermes_live_context>' in first['context']
    assert 'ユーザーの発話ではなく' in first['context']
    assert hook(platform='cli', session_id='s1', sender_id='') is None


def test_changed_current_hash_reinjects(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path)
    current = Path(cfg['current_path'])
    current.write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)
    assert hook(platform='cli', session_id='s1', sender_id='') is not None
    current.write_text(current_text() + '\nnew', encoding='utf-8')
    assert hook(platform='cli', session_id='s1', sender_id='') is not None


def test_truncates_but_preserves_references(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path, max_chars=120)
    Path(cfg['current_path']).write_text('# Hermes\n' + 'x' * 500 + '\n\n## 詳細参照\n- weather.md\n', encoding='utf-8')
    hook = plugin.make_hook(cfg)
    result = hook(platform='cli', session_id='s1', sender_id='')
    assert '## 詳細参照' in result['context']
    assert 'weather.md' in result['context']
    assert '省略' in result['context']


def test_prunes_old_sessions(tmp_path):
    plugin = load_plugin()
    cfg = config(tmp_path)
    state_path = Path(cfg['state_path'])
    state_path.write_text(json.dumps({'sessions': {'old': {'last_injected_at': '2000-01-01T00:00:00+00:00'}}}), encoding='utf-8')
    Path(cfg['current_path']).write_text(current_text(), encoding='utf-8')
    hook = plugin.make_hook(cfg)
    hook(platform='cli', session_id='new', sender_id='')
    state = json.loads(state_path.read_text(encoding='utf-8'))
    assert 'old' not in state['sessions']
    assert 'new' in state['sessions']
