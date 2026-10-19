"""Index public replication clauses without deciding scientific applicability."""
from copy import deepcopy

def replication_requirement_scope(setup):
    quality = setup.get('measurement_quality')
    if not isinstance(quality, dict):
        return None
    index = {}
    if 'minimum_replicates_per_level' in quality:
        index['general_minimum'] = {'value': deepcopy(quality['minimum_replicates_per_level']), 'source_path': 'setup.measurement_quality.minimum_replicates_per_level'}
    policy = quality.get('replicate_exclusion_policy')
    if isinstance(policy, dict):
        for name, field in (('enrollment_minimum', 'minimum_enrolled_per_level'), ('conditional_retention_minimum', 'minimum_retained_after_justified_exclusion'), ('exclusion_limit', 'maximum_excluded_wells')):
            if field not in policy:
                continue
            index[name] = {'value': deepcopy(policy[field]), 'source_path': 'setup.measurement_quality.replicate_exclusion_policy.' + field}
            if name == 'conditional_retention_minimum':
                index[name].update(condition='after_justified_exclusion', conditions_source_path='setup.measurement_quality.replicate_exclusion_policy')
    if not index:
        return None
    index['scope'] = 'Current public declaration index, not a measured fact or acceptance verdict. General replication, enrollment and conditional retention have distinct scopes. Read the complete source clauses to assess whether an exception applies; counts alone prove neither independent replication, justified selection nor scientific quality. Missing declarations remain unknown. This index does not rewrite calculation-time requirement snapshots or authorize exclusion or action.'
    return index
