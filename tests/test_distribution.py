import ast
import importlib
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_import_graph_contains_only_physical_backend_and_portable_helpers():
    forbidden = ('pearl.simulation', 'pearl.harness', 'mock', 'pearl.brain.staged_runtime',
                 'pearl.brain.tools', 'pearl.production.worlds')
    for p in (ROOT/'src').rglob('*.py'):
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            names = ([node.module] if isinstance(node, ast.ImportFrom) else
                     [a.name for a in node.names] if isinstance(node, ast.Import) else [])
            assert not any((n or '').startswith(forbidden) for n in names), p
        name = '.'.join(p.relative_to(ROOT/'src').with_suffix('').parts)
        if name.endswith('.__init__'): name = name.removesuffix('.__init__')
        importlib.import_module(name)
    assert not any(name.startswith(('pearl.simulation', 'mock.')) for name in sys.modules)


def test_public_entrypoint_help_exits_without_device_or_provider_access():
    for name in ('quick_start.py', 'test_benchmark_scenario.py', 'calibrate_camera.py', 'assess_logs.py'):
        result = subprocess.run([sys.executable, str(ROOT/name), '--help'], cwd=ROOT,
            capture_output=True, text=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        assert result.returncode == 0, result.stderr
        assert 'usage:' in result.stdout


def test_product_has_no_historical_artifacts_or_non_english_text():
    assert not any((ROOT/p).exists() for p in ('mock','protocols','results','supplementary_data'))
    for folder in ('src', 'scenarios', 'config', 'docs'):
        for p in (ROOT/folder).rglob('*'):
            if p.is_file() and p.suffix in ('.py','.yaml','.json','.md'):
                assert not re.search('[\uac00-\ud7a3]', p.read_text()), p
