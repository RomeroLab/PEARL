"""Public backend requirements; production owns device admission."""
from collections.abc import Mapping

def validate_backend(world):
    if getattr(world, 'domain', None) not in ('color', 'enzyme'):
        raise ValueError('A declared experiment domain is required')
    if not isinstance(getattr(world, 'inventory', None), Mapping):
        raise ValueError('Nominal inventory is required')
    if any(not callable(getattr(world, n, None)) for n in ('briefing', 'validate_action', 'execute', 'inspect')):
        raise ValueError('An explicit experiment backend is required')
