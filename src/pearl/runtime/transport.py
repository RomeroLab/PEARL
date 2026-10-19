"""Lossless named records for repeated observations and model context fields."""
import json
from copy import deepcopy
TABLE_GUIDE = 'Camera observation lists may use format=measurement_records. Each record names its measurement_id, location and captured_at_s explicitly when acquired; those identity fields are never inherited from shared metadata. Only fields present with exactly the same JSON value and type in every record are emitted as shared metadata; varying acquired fields stay explicit in each record where present. Named record fields take precedence when decoding shared fields. An absent field differs from an explicit null. IDs, values, locations, timestamps and order are unchanged; this is only a compact encoding of acquired data.'
TABLE_GUIDE += ' Non-camera lists may use format=shared_records: each named record inherits shared fields and overrides them with its own fields. Every original record remains in order. Camera observations are never inherited as shared fields. A format=literal_transport_object wrapper preserves its value as an ordinary object without decoding it.'
TABLE_GUIDE += ' An object with format=context_reference and path is an exact copy of the structured value at that JSON Pointer in this same context: / separates keys or list indices, ~1 means / and ~0 means ~. Resolve the referenced value including any transport encoding; no observations, qualifications or fields are omitted. References do not imply scientific adoption or equivalence of different measurements. Current camera records retain explicit identities.'
TABLE_GUIDE += ' Non-camera record lists may use format=column_records with shared fields, distinct named columns and ordered rows of values. Each row inherits shared fields and supplies its columns; absent_columns_by_row names fields absent in that row, whose row placeholders are null. Explicit nulls without an absence marker remain null. All values, unknown fields and record order are unchanged. Camera observations keep named measurement_records.'
IDENTITY_FIELDS = frozenset({'measurement_id', 'location', 'captured_at_s'})

def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)

def _contains_measurement(node):
    if isinstance(node, dict):
        return 'measurement_id' in node or node.get('format') in ('measurement_records', 'measurement_table') or any((_contains_measurement(v) for v in node.values()))
    if isinstance(node, list):
        return any((_contains_measurement(v) for v in node))
    return False

def order_context(context):
    """Keep persistent evidence before volatile feedback without removing fields."""
    sections = ('setup', 'requirement_scope', 'replication_requirement_scope', 'scientific_review_memory', 'cohort_memory', 'decision_memory', 'operation_observation_index', 'recorded_analysis_intervals', 'analysis_memory', 'color_comparison_memory', 'rejected_decision_memory', 'retrieval_memory', 'working_plan', 'working_plan_observations', 'working_plan_acquisition_context', 'commanded_preparations', 'estimated_inventory_ul', 'plate_transfer_accounting', 'measurement_history', 'camera', 'shared_messages', 'pending_reviews', 'action_workflow', 'last_tool_result', 'time_s')
    ordered = {key: context[key] for key in sections if key in context}
    ordered.update({key: value for key, value in context.items() if key not in ordered})
    return deepcopy(ordered)

def compact_context(context):
    value = json.loads(json.dumps(context, allow_nan=False))

    def columns(records, shared, original):
        names = list(dict.fromkeys((k for record in records for k in record)))
        original_bytes = len(_json(original).encode())
        if len(records) * (len(names) + 1) + 1 >= original_bytes:
            return original
        candidate = {'format': 'column_records', 'shared': shared, 'columns': names, 'rows': [[record.get(k) for k in names] for record in records]}
        absent = {str(i): [k for k in names if k not in record] for i, record in enumerate(records)}
        absent = {i: keys for i, keys in absent.items() if keys}
        if absent:
            candidate['absent_columns_by_row'] = absent
        return candidate if len(_json(candidate).encode()) < original_bytes else original

    def camera_records(records):

        def contains(node):
            if isinstance(node, dict):
                return 'measurement_id' in node and ({'location', 'captured_at_s'} <= node.keys() or any((k in node for k in ('rgb', 'od_estimate', 'od_lower_bound', 'clipped', 'od', 'od_noise_sd_estimate')))) or any((contains(v) for v in node.values()))
            if isinstance(node, list):
                return any((contains(v) for v in node))
            return False
        return contains(records)

    def pack(node, protected=False):
        if isinstance(node, list):
            if node and all((isinstance(r, dict) and 'measurement_id' in r for r in node)):
                records = [pack(r, protected) for r in node]
                if any((r.get('format') == 'literal_transport_object' for r in records)):
                    return records
                keys = list(dict.fromkeys((k for r in node for k in r)))
                shared = {k: records[0][k] for k in keys if k not in IDENTITY_FIELDS and k in records[0] and all((k in r and _json(r[k]) == _json(records[0][k]) for r in records))}
                candidate = {'format': 'measurement_records', 'shared': shared, 'records': [{k: v for k, v in r.items() if k not in shared} for r in records]}
                if len(records) > 1 and (not protected) and (not camera_records(node)):
                    return columns(candidate['records'], shared, candidate)
                return candidate
            records = [pack(v, protected) for v in node]
            if len(records) > 1 and all((isinstance(r, dict) and r.get('format') != 'literal_transport_object' for r in records)):
                shared = {k: records[0][k] for k in records[0] if not _contains_measurement(records[0][k]) and all((k in r and _json(r[k]) == _json(records[0][k]) for r in records))}
                original = records
                if shared:
                    candidate = {'format': 'shared_records', 'shared': shared, 'records': [{k: v for k, v in r.items() if k not in shared} for r in records]}
                    if len(_json(candidate).encode()) < len(_json(records).encode()):
                        original = candidate
                if not protected and (not camera_records(node)):
                    remaining = [{k: v for k, v in r.items() if k not in shared} for r in records]
                    return columns(remaining, shared, original)
                return original
            return records
        if isinstance(node, dict):
            if node.get('format') in ('measurement_records', 'measurement_table', 'shared_records', 'column_records', 'literal_transport_object', 'context_reference'):
                return {'format': 'literal_transport_object', 'value': node}
            return {k: pack(v, protected or (node is value and k in ('camera', 'measurement_history'))) for k, v in node.items()}
        return node
    return _reference_duplicates(pack(value))

def _reference_duplicates(value):
    """Share exact repeated structures using earlier, fully named locations."""
    seen = {}

    def visit(node, path, protected=False):
        if not isinstance(node, (dict, list)):
            return node
        if isinstance(node, dict) and node.get('format') == 'literal_transport_object':
            return node
        encoded = _json(node)
        if path and (not protected) and (len(encoded) > 256) and (not (isinstance(node, dict) and 'measurement_id' in node)):
            if encoded in seen:
                reference = {'format': 'context_reference', 'path': seen[encoded]}
                if len(_json(reference)) < len(encoded):
                    return reference
            else:
                seen[encoded] = path
        if isinstance(node, dict):
            return {key: visit(child, path + '/' + key.replace('~', '~0').replace('/', '~1'), protected or (not path and key in ('camera', 'measurement_history'))) for key, child in node.items()}
        return [visit(child, path + '/' + str(i), protected) for i, child in enumerate(node)]
    return visit(value, '')

def _resolve_references(value):
    """Resolve against the encoded root before interpreting record encodings."""

    def target(path):
        if not isinstance(path, str) or not path.startswith('/'):
            raise ValueError('Context reference requires a non-root JSON Pointer')
        node = value
        for part in path[1:].split('/'):
            remainder = part.replace('~0', '').replace('~1', '')
            if '~' in remainder:
                raise ValueError('Invalid JSON Pointer escape')
            part = part.replace('~1', '/').replace('~0', '~')
            try:
                if isinstance(node, list):
                    if not part.isascii() or not part.isdigit() or str(int(part)) != part:
                        raise ValueError('Invalid JSON Pointer index')
                    node = node[int(part)]
                elif isinstance(node, dict):
                    node = node[part]
                else:
                    raise ValueError('Context reference traverses a scalar')
            except (KeyError, IndexError) as exc:
                raise ValueError('Unresolved context reference') from exc
        return node

    def visit(node, active):
        if isinstance(node, dict):
            if node.get('format') == 'literal_transport_object':
                return deepcopy(node)
            if node.get('format') == 'context_reference':
                if set(node) != {'format', 'path'}:
                    raise ValueError('Malformed context reference')
                path = node['path']
                if isinstance(path, str) and path in active:
                    raise ValueError('Cyclic context reference')
                referenced = target(path)
                if not isinstance(referenced, (dict, list)):
                    raise ValueError('Context reference requires a structured value')
                return visit(referenced, active | {path})
            return {key: visit(child, active) for key, child in node.items()}
        if isinstance(node, list):
            return [visit(child, active) for child in node]
        return node
    return visit(value, set())

def expand_context(context):
    """Decode recorded model inputs for audits; never infer missing measurements."""
    return _expand_records(_resolve_references(context))

def _expand_records(context):
    if isinstance(context, dict):
        if context.get('format') == 'literal_transport_object' and 'value' in context:
            return deepcopy(context['value'])
        if context.get('format') == 'column_records':
            required = {'format', 'shared', 'columns', 'rows'}
            if not required <= context.keys() or set(context) - required - {'absent_columns_by_row'}:
                raise ValueError('Malformed column records')
            shared, columns, rows = (context['shared'], context['columns'], context['rows'])
            if not isinstance(shared, dict) or not isinstance(columns, list) or any((not isinstance(k, str) for k in columns)) or (len(set(columns)) != len(columns)) or set(columns).intersection(shared) or (not isinstance(rows, list)) or any((not isinstance(row, list) or len(row) != len(columns) for row in rows)):
                raise ValueError('Malformed column record fields or rows')
            absent = context.get('absent_columns_by_row', {})
            if not isinstance(absent, dict):
                raise ValueError('Malformed column record absence map')
            for index, keys in absent.items():
                if not isinstance(index, str) or not index.isascii() or (not index.isdigit()) or (str(int(index)) != index) or (int(index) >= len(rows)) or (not isinstance(keys, list)) or any((not isinstance(k, str) for k in keys)) or (len(set(keys)) != len(keys)) or any((k not in columns for k in keys)) or any((rows[int(index)][columns.index(k)] is not None for k in keys)):
                    raise ValueError('Malformed column record absence coordinates')
            decoded_shared = _expand_records(shared)
            result = []
            for i, row in enumerate(rows):
                record = {**deepcopy(decoded_shared), **{key: _expand_records(v) for key, v in zip(columns, row)}}
                for key in absent.get(str(i), []):
                    record.pop(key)
                result.append(record)
            return result
        if context.get('format') == 'shared_records' and {'shared', 'records'} <= context.keys():
            shared = _expand_records(context['shared'])
            return [{**deepcopy(shared), **_expand_records(record)} for record in context['records']]
        if context.get('format') == 'measurement_records' and {'shared', 'records'} <= context.keys():
            shared = _expand_records(context['shared'])
            return [{**deepcopy(shared), **_expand_records(record)} for record in context['records']]
        if context.get('format') == 'measurement_table' and {'shared', 'columns', 'rows'} <= context.keys():
            out = []
            for i, values in enumerate(context['rows']):
                if len(values) != len(context['columns']):
                    raise ValueError('Incomplete observation row')
                row = {**context['shared'], **dict(zip(context['columns'], values))}
                for key in context.get('missing_by_row', {}).get(str(i), []):
                    row.pop(key, None)
                out.append(row)
            return out
        return {k: _expand_records(v) for k, v in context.items()}
    if isinstance(context, list):
        return [_expand_records(v) for v in context]
    return context
