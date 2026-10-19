"""Search already acquired records using explicit command-relative timing."""
from copy import deepcopy
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.comparison_timing import validate_timing, timing_context

def find_observations(args, evidence, events, setup, locations):
    if not isinstance(args, dict) or set(args) != {'locations', 'preparation_context_ids', 'comparison_timing'}:
        raise ValueError('Choose locations, optional preparation IDs and complete comparison timing')
    chosen = args['locations']
    if not isinstance(chosen, list) or not chosen or any((not isinstance(p, str) or p not in locations for p in chosen)) or (len(set(chosen)) != len(chosen)):
        raise ValueError('Choose distinct declared locations')
    contexts = args['preparation_context_ids']
    if not isinstance(contexts, list) or any((not isinstance(i, str) for i in contexts)) or len(set(contexts)) != len(contexts):
        raise ValueError('Choose distinct preparation IDs, or [] for all historical preparations')
    declaration = validate_timing(args['comparison_timing'])
    if declaration is None or any((declaration[k] is None for k in ('reference', 'target_age_s', 'tolerance_s'))):
        raise ValueError('An acquired-observation timing query requires a complete timing premise')
    rows = [m for m in evidence.values() if m['location'] in chosen]
    acquired = acquisition_context(rows, events, setup['reagents'])
    available = {p['context_id'] for p in acquired['preparations']}
    if any((i not in available for i in contexts)):
        raise ValueError('Unknown historical preparation ID for the chosen locations')
    audit = timing_context(declaration, acquired)
    ids = {r['measurement_id'] for r in audit['observations'] if r['within_declared_tolerance'] is True and (not contexts or r['command_context_id'] in contexts)}
    selected = [deepcopy(m) for m in rows if m['measurement_id'] in ids]
    filtered = acquisition_context(selected, events, setup['reagents'])
    return {'measurements': selected, 'acquisition_context': filtered, 'timing_audit': timing_context(declaration, filtered), 'searched_measurement_count': len(rows), 'scope': 'Already acquired timing matches only. Nominal preparation records do not prove composition, comparable chemistry, independent replication, evidence eligibility or final adoption. No frame is inferred or replaced.'}
