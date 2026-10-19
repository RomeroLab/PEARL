"""Terminal chat and selected public scenario execution on connected devices."""
import argparse
import json
from pathlib import Path
import yaml
from pearl.production.settings import robot_ip, select_scenarios, load_setup, validate_setup
from pearl.production.optics import load_calibration
from pearl.production.connection import probe_robot, select_camera, list_cameras
from pearl.production.execution import run_task, ROOT
from pearl.runtime.ablation_runtime import ABLATION_PROFILES


def parse_args(mode, argv=None):
    p = argparse.ArgumentParser(description='PEARL terminal chat' if mode == 'chat' else 'PEARL physical scenario execution')
    p.add_argument('--robot-ip', required=True, help='Actual OT-2 IP, HTTP port 31950')
    p.add_argument('--camera', type=int, help='Attached computer camera index; choose interactively if omitted')
    p.add_argument('--list-cameras', action='store_true')
    p.add_argument('--setup', type=Path, help='Slot/reagent/camera YAML or JSON')
    p.add_argument('--calibration', type=Path, help='Explicit blank calibration JSON; omitted means defaults')
    p.add_argument('--log-dir', type=Path, default=ROOT/'logs')
    p.add_argument('--model', help='Model identifier; otherwise OPENAI_MODEL is used')
    p.add_argument('--max-turns', type=int, default=120)
    p.add_argument('--camera-interval', type=float, default=1.)
    if mode == 'benchmark':
        p.add_argument('--scenarios', default='all', help='all, S2, S1-4, S1-S4, S1,S3,S8')
        p.add_argument('--ablation', choices=ABLATION_PROFILES, default='full')
    a = p.parse_args(argv)
    try:
        a.robot_ip = robot_ip(a.robot_ip)
        if a.camera is not None and a.camera < 0: raise ValueError('Camera index must be nonnegative')
        if a.max_turns <= 0: raise ValueError('max-turns must be positive')
        from pearl.production.settings import positive
        positive(a.camera_interval, 'camera-interval')
        load_calibration(a.calibration)
        if mode == 'benchmark': a.scenarios = select_scenarios(a.scenarios)
    except ValueError as exc:
        p.error(str(exc))
    return a


def load_scenario(sid):
    if sid not in [f'S{i}' for i in range(1, 9)]:
        raise ValueError('Choose S1..S8')
    path = ROOT/'scenarios'/(sid+'.yaml')
    data = yaml.safe_load(path.read_text())
    return data, validate_setup(data, base_dir=path.parent)


def interactive_setup(input_fn=input):
    def ask(text, default): return input_fn(f'{text} [{default}]: ').strip() or str(default)
    domain = ask('Domain: color/enzyme', 'color')
    deck = {'plate_slot': int(ask('Plate slot', 2)), 'reservoir_slot': int(ask('Reservoir slot', 3)),
            'tiprack_slot': int(ask('Primary tiprack slot', 1)),
            'secondary_tiprack_slot': None, 'secondary_tiprack_type': None,
            'secondary_pipette_type': None, 'secondary_pipette_mount': None}
    crop = Path(input_fn('Camera crop JSON path: ').strip()).expanduser().resolve()
    reagents = {}
    while True:
        well = input_fn('Reservoir well (A1-A12; blank to finish): ').strip().upper()
        if not well: break
        if well in reagents: raise ValueError('Duplicate reservoir well')
        row = {'label': input_fn('Reagent label: ').strip(),
               'volume_ul': float(input_fn('Starting volume (uL): '))}
        concentration = input_fn('Nominal stock concentration (blank if inapplicable): ').strip()
        if concentration:
            row.update(concentration_value=float(concentration), concentration_unit=input_fn('Concentration unit: ').strip())
        reagents[well] = row
    return validate_setup({'domain': domain, 'deck': deck, 'camera': {'crop_config': str(crop)},
                           'reagents': reagents, 'plate_wells': 'A1-H12'})


def prepare(setup, input_fn=input, print_fn=print):
    print_fn(f'Plate slot {setup.deck.plate_slot}; reservoir slot {setup.deck.reservoir_slot}; tiprack slot {setup.deck.tiprack_slot}')
    for well, r in setup.reagents.items():
        print_fn(f"  {well}: {r['label']} — {r['volume_ul']} uL")
    print_fn('Prepare the declared stocks, empty plate, fresh tips and labware calibration. Clear the camera view.')
    if input_fn('Enter READY to confirm this physical setup: ').strip() != 'READY':
        raise RuntimeError('Physical setup was not confirmed')


def run_benchmark(a, *, input_fn=input, print_fn=print):
    probe_robot(a.robot_ip)
    camera = select_camera(a.camera, input_fn=input_fn, print_fn=print_fn)
    tasks = []
    for sid in a.scenarios:
        data, default = load_scenario(sid)
        tasks.append((sid, data['prompt'], load_setup(a.setup, sid) if a.setup else default))
    for sid, prompt, setup in tasks:
        prepare(setup, input_fn, print_fn)
        r = run_task(sid, setup, a.robot_ip, camera, a.calibration, a.log_dir, prompt=prompt,
                     ablation=a.ablation, model=a.model, max_turns=a.max_turns, camera_interval_s=a.camera_interval)
        print_fn(f"{sid}: {r['termination']}; logs: {r['log_dir']}")
        if r['termination'] != 'completed':
            return 1
    return 0


def chat_loop(a, *, input_fn=input, print_fn=print):
    probe_robot(a.robot_ip)
    camera = select_camera(a.camera, input_fn=input_fn, print_fn=print_fn)
    setup = load_setup(a.setup) if a.setup else interactive_setup(input_fn)
    print_fn('PEARL — Enter an experiment request. /status, /setup PATH, /help, /quit')
    while True:
        prompt = input_fn('You> ').strip()
        if not prompt: continue
        if prompt in ('/quit', '/exit'): return 0
        if prompt == '/help':
            print_fn('Enter a scientific request and confirm the prepared equipment. /status shows setup; /setup PATH selects new setup; /quit exits.'); continue
        if prompt == '/status':
            print_fn(json.dumps({'robot': probe_robot(a.robot_ip), 'setup': setup.source}, indent=2)); continue
        if prompt.startswith('/setup '):
            setup = load_setup(Path(prompt[7:].strip()).expanduser()); continue
        if prompt.startswith('/'):
            print_fn('Unknown command. Use /help.'); continue
        prepare(setup, input_fn, print_fn)
        r = run_task('ADHOC', setup, a.robot_ip, camera, a.calibration, a.log_dir, prompt=prompt,
                     model=a.model, max_turns=a.max_turns, camera_interval_s=a.camera_interval)
        print_fn(f"PEARL> {r.get('conclusion', r['termination'])}\nLogs: {r['log_dir']}")
        if r['termination'] != 'completed': return 1


def main(mode, argv=None):
    a = parse_args(mode, argv)
    try:
        if a.list_cameras:
            print(json.dumps(list_cameras())); return 0
        return run_benchmark(a) if mode == 'benchmark' else chat_loop(a)
    except (EOFError, KeyboardInterrupt):
        print('\nExecution stopped.'); return 130
    except Exception as exc:
        print(f'Execution stopped: {exc}'); return 1
