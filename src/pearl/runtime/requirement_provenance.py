"""Public declaration references and authored prerequisites, without adjudication."""
from copy import deepcopy
from jsonschema import ValidationError, validate
CLAIM_GROUNDING = 'Require public/scientific grounds for verification of the claimed property/precision. Observations do not establish composition; unknown composition alone does not negate an observed property.'
OPERATIONAL_ASSUMPTIONS = ' The planning owner justifies interpretations at the requested qualitative or quantitative precision. Peers independently question premises and prerequisite necessity. Clarify material ambiguity or missing necessary inputs. Do not relax public requirements or redefine success to fit observations. Separate commands/observations from revisable planning premises. Missing independent measurement is not refutation. A chosen design is revisable; a task requirement binds. Do not invent contents/bounds; hard safety limits bind. Weigh shared causes. Scope observation fitness:intended use/stage; justify causal/logical propagation. Chosen verification is revisable; required quality binds. Repeatable input-response evidence can justify bounded changed-state tests before resolving cause. ' + CLAIM_GROUNDING

def constraint_schema():
    text = {'type': 'string', 'minLength': 1, 'pattern': '\\S'}
    declarations = {'source_path': {**text, 'pattern': '^/'}, 'application': text}
    prerequisites = {key: text for key in ('condition', 'assumption_basis', 'supported_claim', 'failure_consequence', 'reconsideration')}

    def rows(properties):
        return {'type': 'array', 'maxItems': 8, 'items': {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}}
    return {'type': 'object', 'properties': {'public_declarations': rows(declarations), 'method_prerequisites': rows(prerequisites)}, 'required': ['public_declarations', 'method_prerequisites'], 'additionalProperties': False, 'description': 'Public vs authored premises: explain why each is necessary for its claim/property and precision. Scope gaps/reconsideration to dependent claims; origin is not necessity.'}

def public_value(setup, path):
    if not isinstance(setup, dict) or not isinstance(path, str) or (not path.startswith('/')):
        raise ValueError('A source reference requires the current public setup and a non-root JSON Pointer')
    current = setup
    for token in path[1:].split('/'):
        if '~' in token.replace('~0', '').replace('~1', ''):
            raise ValueError('Invalid source JSON Pointer escape')
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(current, dict):
            if token not in current:
                raise ValueError('Source reference is absent from public setup')
            current = current[token]
        elif isinstance(current, (list, tuple)):
            if not token.isascii() or not token.isdigit() or str(int(token)) != token or (int(token) >= len(current)):
                raise ValueError('Invalid public source array reference')
            current = current[int(token)]
        else:
            raise ValueError('Source reference traverses a public scalar')
    return deepcopy(current)

def validate_constraints(value, setup):
    try:
        validate(value, constraint_schema())
    except ValidationError as exc:
        path = '/'.join((str(part) for part in exc.absolute_path))
        raise ValueError('Constraint provenance ' + path + ': ' + exc.message) from exc
    result = deepcopy(value)
    seen = set()
    for row in result['public_declarations']:
        path = row['source_path']
        if path in seen:
            raise ValueError('Public source references must be distinct')
        seen.add(path)
        row['source_value'] = public_value(setup, path)
    return result

def requirement_scope(setup, current_decision):
    objective = {'source_path': '/objective', 'present': 'objective' in setup}
    if objective['present']:
        objective['value'] = deepcopy(setup['objective'])
    experiment = (current_decision or {}).get('decision', {}).get('decision_basis', {}).get('experiment')
    return {'original_objective': objective, 'public_clause_roots': ['/' + key.replace('~', '~0').replace('/', '~1') for key in setup], 'authored_conditions': {'decision_id': current_decision['event_id'], 'experiment': deepcopy(experiment)} if experiment is not None else None, 'scope': 'Exact public declaration locations and current authored experiment, not applicability or a verdict. Chosen method conditions do not become operator requirements; physical limits still bind. No cause, action or outcome is inferred.'}
