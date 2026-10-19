"""Detached strict wire schemas; authoritative validation remains local."""
from copy import deepcopy
_WIRE_KEYWORDS = {'type', 'description', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'anyOf', 'pattern', 'format', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'minItems', 'maxItems'}
_LOCAL_KEYWORDS = {'minLength', 'maxLength', 'uniqueItems'}

def _strict_parameters(node):
    if not isinstance(node, dict):
        raise ValueError('Strict argument schemas require schema objects')
    unknown = set(node) - _WIRE_KEYWORDS - _LOCAL_KEYWORDS
    if unknown:
        raise ValueError('Unsupported strict schema keywords: ' + ', '.join(sorted(unknown)))
    result = {k: deepcopy(v) for k, v in node.items() if k not in _LOCAL_KEYWORDS}
    kinds = result.get('type', [])
    if isinstance(kinds, str):
        kinds = [kinds]
    if 'object' in kinds:
        properties = result.get('properties')
        required = result.get('required')
        if not isinstance(properties, dict) or not isinstance(required, list) or any((not isinstance(k, str) for k in required)) or (len(required) != len(set(required))) or (set(required) != set(properties)) or (result.get('additionalProperties') is not False):
            raise ValueError('Strict objects require all properties and additionalProperties=false')
    if 'properties' in result:
        result['properties'] = {k: _strict_parameters(v) for k, v in result['properties'].items()}
    if 'items' in result:
        result['items'] = _strict_parameters(result['items'])
    if 'anyOf' in result:
        result['anyOf'] = [_strict_parameters(v) for v in result['anyOf']]
    return result

def strict_function_tool(tool):
    """Opt an already closed function contract into constrained generation.

    Unsupported length/uniqueness annotations are omitted only from this wire
    copy. Callers retain their original schemas and all scientific validators.
    Optional fields are never promoted to required or replaced with nulls.
    """
    result = deepcopy(tool)
    function = result.get('function')
    if result.get('type') != 'function' or not isinstance(function, dict):
        raise ValueError('A function tool is required for strict arguments')
    parameters = function.get('parameters')
    if not isinstance(parameters, dict) or parameters.get('type') != 'object':
        raise ValueError('Strict function parameters require a root object')
    function['parameters'] = _strict_parameters(parameters)
    function['strict'] = True
    return result
