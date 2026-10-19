"""Admit physical devices before constructing any experiment model client."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from uuid import uuid4
from pearl.production.connection import VerifiedOT2, open_camera
from pearl.production.optics import load_calibration, CameraReader
from pearl.production.backend import PhysicalBackend
from pearl.production.provider import Provider
from pearl.runtime.ablation_runtime import create_runtime
from pearl.evaluation.scientific_assessment import CONTRACT_ID

ROOT = Path(__file__).resolve().parents[3]


def source_identity():
    digest = hashlib.sha256()
    for p in sorted((ROOT/'src').rglob('*.py')):
        digest.update(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes()+b'\0')
    return digest.hexdigest()


def save(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def run_task(sid, setup, robot_ip, camera_id, calibration_path, log_dir, *, prompt=None,
             ablation='full', model=None, max_turns=120, camera_interval_s=1.,
             robot_factory=VerifiedOT2, camera_factory=open_camera, provider_factory=Provider):
    if sid == 'ADHOC' and ablation != 'full':
        raise ValueError('Ablations are benchmark-only')
    if type(max_turns) is not int or max_turns <= 0:
        raise ValueError('max_turns must be a positive integer')
    path = Path(log_dir)/(sid+'_'+uuid4().hex)
    path.mkdir(parents=True, exist_ok=False)
    for name in ('events.jsonl', 'model.exchanges.jsonl'):
        (path/name).touch()
    robot = camera = run = None
    result = None
    failure = None
    try:
        calibration = load_calibration(calibration_path)
        robot = robot_factory(robot_ip, setup.deck, receipt_path=path/'robot.receipts.jsonl')
        robot.connect()
        camera = camera_factory(camera_id, setup.camera, path/'frames')
        reader = CameraReader(camera, setup, calibration, camera_id, path/'frames')
        if prompt:
            setup = replace(setup, public_goal={**setup.public_goal, 'objective': prompt})
        world = PhysicalBackend(setup, robot, reader)
        def sink(event):
            with (path/'events.jsonl').open('a') as f:
                f.write(json.dumps(event, allow_nan=False)+'\n')
        save(path/'setup.json', {**world.briefing(), 'scenario_id': sid,
             'ablation_profile': ablation, 'assessment_contract_id': CONTRACT_ID,
             'source_manifest_sha256': source_identity()})
        provider = provider_factory(path/'model.exchanges.jsonl', model=model)
        run = create_runtime(world, ablation=ablation, chat=provider, event_sink=sink,
                             compact_messages=True, continuous_camera_interval_s=camera_interval_s)
        result = run.run(max_turns=max_turns)
    except BaseException as exc:
        failure = exc
        if robot is not None:
            robot.stop()
        result = {'termination': 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'operational_error',
                  'evaluation_status': 'not_evaluated', 'error_type': type(exc).__name__, 'error': str(exc)}
    finally:
        try:
            if run is not None and run.continuous_camera:
                run.continuous_camera.close()
        except BaseException as exc:
            failure = failure or exc
            result = {'termination': 'operational_error', 'evaluation_status': 'not_evaluated',
                      'error_type': type(exc).__name__, 'error': str(exc)}
        if camera is not None:
            camera.release()
        if robot is not None:
            robot.disconnect()
        result = {**(result or {}), 'scenario_id': sid, 'ablation_profile': ablation,
                  'assessment_contract_id': CONTRACT_ID, 'source_manifest_sha256': source_identity(),
                  'log_dir': str(path.resolve())}
        save(path/'result.json', result)
    if failure:
        raise failure
    return result
