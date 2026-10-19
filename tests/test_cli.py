import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_hardware import setup


def test_benchmark_full_default_and_subsets_are_parsed_without_devices(tmp_path):
    from pearl.production.cli import parse_args
    args = parse_args('benchmark', ['--robot-ip', '192.168.1.2', '--scenarios', 'S1-4,S6,S8'])
    assert args.ablation == 'full' and args.scenarios == ['S1', 'S2', 'S3', 'S4', 'S6', 'S8']
    args = parse_args('benchmark', ['--robot-ip', '192.168.1.2'])
    assert args.scenarios == [f'S{i}' for i in range(1, 9)]
    with pytest.raises(SystemExit): parse_args('chat', ['--robot-ip', '192.168.1.2', '--ablation', 'base_llm'])
    with pytest.raises(SystemExit): parse_args('chat', [])
    with pytest.raises(SystemExit): parse_args('chat', ['--robot-ip', '192.168.1.2', '--calibration', str(tmp_path/'missing.json')])


def test_all_scenario_assets_are_public_inputs_with_consistent_enzyme_materials():
    from pearl.production.cli import load_scenario
    rows = {f'S{i}': load_scenario(f'S{i}')[0] for i in range(1, 9)}
    for data in rows.values():
        assert set(data) == {'prompt', 'domain', 'deck', 'reagents', 'camera', 'plate_wells'}
    assert rows['S1']['prompt'] == 'Create a rainbow in the well-plate.'
    assert rows['S4']['prompt'] == 'Make bright orange'
    assert 'red and green' in rows['S2']['prompt']
    assert all(rows[s]['reagents'] == rows['S5']['reagents'] for s in ('S6', 'S7'))
    assert rows['S8']['reagents']['A2'] == rows['S5']['reagents']['A2']
    assert rows['S8']['reagents']['A3'] == rows['S5']['reagents']['A3']
    assert all(rows[s]['prompt'] == rows['S5']['prompt'] for s in ('S6', 'S7', 'S8'))
    assert rows['S5']['prompt'] == ('Autonomously characterize the HRP-TMB assay: '
        'identify its linear working range and estimate Km and kcat from time-resolved measurements.')


@pytest.mark.parametrize('profile', ['full', 'no_reasoner', 'no_predictor', 'no_knowledge',
                                    'no_watchdog', 'base_llm', 'pearl_minimal'])
def test_s8_prepared_stock_reaches_model_and_drives_dilution_accounting(profile):
    from pearl.production.cli import load_scenario
    from pearl.production.backend import PhysicalBackend
    from pearl.production.optics import Calibration
    from pearl.runtime.ablation_runtime import create_runtime
    from test_hardware import Robot
    from test_core import context
    data, settings = load_scenario('S8')
    world = PhysicalBackend(settings, Robot(), SimpleNamespace(calibration=Calibration()))
    seen = []
    def chat(role, messages, tools):
        c = context(messages)
        stock = c['setup']['reagents']['reservoir:A1']
        assert stock['concentration_value'] == .03
        assert stock['concentration_unit'] == 'uM'
        assert stock['label'] == 'Enzyme working stock (HRP), 0.03 uM'
        if role == 'watchdog':
            return {'name': 'submit_watchdog_review', 'arguments': {
                'verdict': 'clear', 'assessment': 'Offline input-routing fixture.', 'findings': []}}
        seen.append(role)
        return {'name': 'analyze_dilution_balance', 'arguments': {
            'stock_concentration': {'value': stock['concentration_value'], 'unit': stock['concentration_unit']},
            'target_concentration': {'value': 3., 'unit': 'nM'}, 'final_volume_ul': 100.,
            'current_stock_volume_ul': 0., 'current_diluent_volume_ul': 0., 'capacity_ul': 300.}}
    run = create_runtime(world, ablation=profile, chat=chat, compact_messages=True)
    run.run(max_turns=1)
    calculations = [e.result for e in run.board.event_log
                    if getattr(e, 'tool_name', '') == 'analyze_dilution_balance']
    assert seen == [run.planning_role]
    assert len(calculations) == 1
    assert calculations[0]['target_stock_volume_ul'] == pytest.approx(10.)
    assert calculations[0]['target_diluent_volume_ul'] == pytest.approx(90.)
    assert not world.command_log and not world.camera_active


@pytest.mark.parametrize('failure', ['open', 'frame'])
def test_camera_admission_failure_stops_before_model_construction(tmp_path, failure):
    from pearl.production.execution import run_task
    from test_hardware import Robot
    lifecycle = []
    class ConnectedRobot(Robot):
        def connect(self): lifecycle.append('connected'); return self
        def stop(self): lifecycle.append('stopped')
        def disconnect(self): lifecycle.append('disconnected')
    def camera_factory(*args):
        if failure == 'open':
            raise ConnectionError('Camera unavailable')
        return SimpleNamespace(capture_raw=lambda **kwargs: None,
                               release=lambda: lifecycle.append('camera_released'))
    def provider_factory(*args, **kwargs):
        pytest.fail('Model construction requires usable robot and camera')
    with pytest.raises((ConnectionError, ValueError)):
        run_task('S5', setup(tmp_path), '192.168.1.2', 0, None, tmp_path/'logs',
                 robot_factory=lambda *args, **kwargs: ConnectedRobot(),
                 camera_factory=camera_factory, provider_factory=provider_factory)
    assert lifecycle[0] == 'connected' and lifecycle[-1] == 'disconnected'
    assert 'stopped' in lifecycle
    if failure == 'frame': assert 'camera_released' in lifecycle
    outcome = json.loads(next((tmp_path/'logs').glob('*/result.json')).read_text())
    assert outcome['termination'] == 'operational_error'
    assert outcome['evaluation_status'] == 'not_evaluated'


def test_missing_robot_admission_never_constructs_provider_or_camera(tmp_path):
    from pearl.production.execution import run_task
    provider_calls = []
    def robot_factory(*a, **k):
        return SimpleNamespace(connect=lambda: (_ for _ in ()).throw(ConnectionError('not connected')),
                               stop=lambda: None, disconnect=lambda: None)
    def provider_factory(*a, **k): provider_calls.append(True); pytest.fail('provider before hardware')
    with pytest.raises(ConnectionError):
        run_task('S5', setup(tmp_path), '192.168.1.2', 0, None, tmp_path/'logs',
                 robot_factory=robot_factory, provider_factory=provider_factory)
    assert provider_calls == []


def test_connected_execution_records_operational_result_without_scientific_grade(tmp_path):
    from pearl.production.execution import run_task
    from test_hardware import Robot
    events = []
    class ConnectedRobot(Robot):
        def connect(self): events.append('robot'); return self
        def disconnect(self): events.append('disconnect')
    import numpy as np
    camera = SimpleNamespace(release=lambda: events.append('release'),
        capture_raw=lambda **k: np.full((800,1200,3),200,dtype=np.uint8))
    def camera_factory(*a): events.append('camera'); return camera
    def provider_factory(*a, **k):
        events.append('provider')
        def chat(role, messages, tools):
            if role == 'watchdog':
                return {'name': 'submit_watchdog_review', 'arguments': {'verdict': 'clear', 'assessment': 'No acquired discrepancy.', 'findings': []}}
            return {'name': 'read_measurements', 'arguments': {'location': 'plate:A1'}}
        return chat
    result = run_task('S5', setup(tmp_path), '192.168.1.2', 0, None, tmp_path/'logs', max_turns=1,
                      robot_factory=lambda *a, **k: ConnectedRobot(), camera_factory=camera_factory,
                      provider_factory=provider_factory)
    assert events[:3] == ['robot', 'camera', 'provider']
    assert events[-2:] == ['release', 'disconnect']
    path = Path(result['log_dir'])
    assert all((path/name).is_file() for name in ('setup.json', 'events.jsonl', 'model.exchanges.jsonl', 'result.json'))
    assert result['termination'] == 'turn_limit' and result['evaluation_status'] == 'not_evaluated'
    assert not set(result) & {'P', 'A', 'E', 'I', 'D'}


def test_provider_logs_real_usage_and_preserves_unknown_counts(tmp_path):
    from pearl.production.provider import Provider
    captured = []
    def create(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(id='response-1', model='requested-model', usage=SimpleNamespace(
            prompt_tokens=210, completion_tokens=35, prompt_tokens_details=None, completion_tokens_details=None),
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(id='t', function=SimpleNamespace(
                name='inspect', arguments='{"locations":["plate:A1"]}'))], content=None, refusal=None), finish_reason='tool_calls')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    path = tmp_path/'model.exchanges.jsonl'
    p = Provider(path, model='requested-model', client=client)
    value = p('knowledge', [{'role': 'system', 'content': 'A public question.'}], [])
    assert value == {'name': 'inspect', 'arguments': {'locations': ['plate:A1']}}
    rows = [json.loads(l) for l in path.read_text().splitlines()]
    assert rows[-1]['usage']['input_tokens'] == 210 and rows[-1]['usage']['output_tokens'] == 35
    assert rows[-1]['usage']['reasoning_tokens'] is None and rows[-1]['role'] == 'knowledge'
    assert rows[0]['exchange_id'] == rows[-1]['exchange_id'] and rows[0]['kind'] == 'request'
    assert captured[0]['parallel_tool_calls'] is False and captured[0]['tool_choice'] == 'required'


def test_provider_uses_selected_environment_after_dotenv_loading(tmp_path, monkeypatch):
    import dotenv
    import openai
    from pearl.production.provider import Provider
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda: monkeypatch.setenv('OPENAI_MODEL', 'operator-model'))
    monkeypatch.setattr(openai, 'OpenAI', lambda **kwargs: object())
    provider = Provider(tmp_path/'exchanges.jsonl')
    assert provider.model == 'operator-model'
