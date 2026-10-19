"""Optional arithmetic on caller-chosen plans; no world access or action generation."""
from collections import defaultdict
from decimal import Decimal, localcontext

def preparation_balance(arguments):
    with localcontext() as context:
        context.prec = 700
        amounts = []
        for field in ('current', 'target'):
            totals = defaultdict(Decimal)
            for row in arguments[field]:
                totals[row['component']] += Decimal(str(row['volume_ul']))
            amounts.append(totals)
        current, target = amounts
        capacity = Decimal(str(arguments['capacity_ul']))
        if capacity <= 0:
            raise ValueError('capacity_ul must be positive')
        current_total = sum(current.values(), Decimal(0))
        target_total = sum(target.values(), Decimal(0))
        deltas = {key: target.get(key, Decimal(0)) - current.get(key, Decimal(0)) for key in sorted(current.keys() | target.keys())}
        return {'current_total_ul': float(current_total), 'target_total_ul': float(target_total), 'remaining_capacity_ul': float(capacity - current_total), 'component_deltas_ul': {key: float(value) for key, value in deltas.items()}, 'addition_only_possible': all((value >= 0 for value in deltas.values())) and current_total <= capacity and (target_total <= capacity)}

def measurement_schedule(arguments):
    available = arguments['available_locations']
    unavailable = arguments['unavailable_locations']
    courses = arguments['courses']
    policy = arguments['location_policy']
    if policy not in {'distinct_per_reading', 'reuse_within_course'}:
        raise ValueError('Choose distinct_per_reading or reuse_within_course explicitly')
    for values in (available, unavailable, [row['id'] for row in courses]):
        if len(set(values)) != len(values):
            raise ValueError('Location inventories and course identifiers must be distinct')
    outside_inventory = sorted(set(unavailable) - set(available))
    if outside_inventory:
        raise ValueError('unavailable_locations must be a subset of the full available_locations inventory; locations absent from available_locations: ' + ', '.join((repr(location) for location in outside_inventory)))
    issues = []
    summaries = []
    owners = {}
    timeline = defaultdict(list)
    count = 0
    for course in courses:
        times = []
        for index, reading in enumerate(course['readings']):
            count += 1
            location, time = (reading['location'], reading['time_s'])
            timeline[time].append({'course': course['id'], 'reading_index': index, 'location': location, 'elapsed_time_s': time - course['start_time_s']})

            def issue(kind):
                issues.append({'kind': kind, 'course': course['id'], 'reading_index': index, 'location': location})
            if location not in available:
                issue('location_not_available')
            if location in unavailable:
                issue('location_unavailable')
            if location in owners and (policy == 'distinct_per_reading' or owners[location] != course['id']):
                issue('location_reused')
            owners[location] = course['id']
            if time < arguments['current_time_s']:
                issue('reading_before_current_time')
            if time < course['start_time_s']:
                issue('reading_before_start')
            if times and time <= times[-1]:
                issue('nonincreasing_times')
            times.append(time)
        summaries.append({'id': course['id'], 'elapsed_times_s': [time - course['start_time_s'] for time in times], 'distinct_time_count': len(set(times)), 'time_span_s': max(times) - min(times)})
    previous = arguments['current_time_s']
    ordered = []
    for time in sorted(timeline):
        ordered.append({'time_s': time, 'wait_from_previous_s': time - previous if time >= previous else None, 'readings': timeline[time]})
        previous = max(previous, time)
    return {'constraints_satisfied_for_supplied_plan': not issues, 'reading_count': count, 'used_location_count': len(owners), 'unused_locations': [loc for loc in available if loc not in owners and loc not in unavailable], 'courses': summaries, 'issues': issues, 'timeline': ordered}

def dilution_balance(arguments):
    """Nominal conserved-solute arithmetic; values and targets belong to the caller."""
    factors = {'M': Decimal(1), 'mM': Decimal('1e-3'), 'uM': Decimal('1e-6'), 'nM': Decimal('1e-9'), 'pM': Decimal('1e-12')}
    with localcontext() as context:
        context.prec = 700
        concentrations = []
        for key in ('stock_concentration', 'target_concentration'):
            row = arguments[key]
            if row['unit'] not in factors:
                raise ValueError('Use an explicit supported molar concentration unit')
            concentrations.append(Decimal(str(row['value'])) * factors[row['unit']])
        stock, target = concentrations
        final = Decimal(str(arguments['final_volume_ul']))
        capacity = Decimal(str(arguments['capacity_ul']))
        if stock <= 0 or target <= 0 or target > stock or (final <= 0) or (capacity <= 0):
            raise ValueError('Positive concentrations/volumes required; dilution target cannot exceed stock')
        current_stock = Decimal(str(arguments['current_stock_volume_ul']))
        current_diluent = Decimal(str(arguments['current_diluent_volume_ul']))
        desired_stock = target * final / stock
        desired_diluent = final - desired_stock
        stock_delta = desired_stock - current_stock
        diluent_delta = desired_diluent - current_diluent
        return {'target_stock_volume_ul': float(desired_stock), 'target_diluent_volume_ul': float(desired_diluent), 'stock_delta_ul': float(stock_delta), 'diluent_delta_ul': float(diluent_delta), 'current_total_ul': float(current_stock + current_diluent), 'target_total_ul': float(final), 'addition_only_possible': stock_delta >= 0 and diluent_delta >= 0 and (current_stock + current_diluent <= capacity) and (final <= capacity), 'calculation_scope': 'nominal_conserved_solute_in_stock_and_solute_free_diluent'}
