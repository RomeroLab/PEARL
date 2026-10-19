"""Detached public relevance views, with exact paginated canonical detail reads.

The caller passes an expanded canonical context, never a previously projected
view. Projection changes presentation only; adoption and safety use the archive.
Read arguments are exact objects: shared events use event_ids/offset/limit;
context details use section/offset/limit. Limits are 1..64, offsets 0..total.
Empty event_ids browses the archive; ID filtering preserves archive chronology.
The runtime wrapper snapshots context detail reads: snapshot_id=null at offset
zero starts a detached snapshot; later pages use its returned snapshot_id. This
pure helper remains stateless and receives only section/offset/limit against
that static snapshot. Full append-only event reads do not need a snapshot.
"""
from copy import deepcopy
import hashlib
import json
from pearl.runtime.blackboard import ROLES
from pearl.runtime.retrieval_memory import receipt_reference
from pearl.runtime.rejected_decision import validation_cause
from pearl.runtime.transport import compact_context, order_context
DETAIL_SECTIONS = ('measurement_history', 'shared_messages', 'commanded_preparations.wells', 'plate_transfer_accounting.event_ids', 'cohort_memory', 'cohort_memory.members', 'acquisition_schedule.rows', 'working_plan_acquisition_context.captures', 'working_plan_acquisition_context.preparations', 'analysis_memory.calculations', 'color_comparison_memory.comparisons', 'evidence_history_view.units')
RECENT_MEASUREMENTS = 12
RECENT_MESSAGES = 6
RECENT_CALCULATIONS = 12
RECENT_PREPARATIONS = 2
HISTORY_DETAIL_BYTES = 16384
WORKING_RESULT_BYTES = 16384
HISTORICAL_COLLECTION_BYTES = 16384

def _collection_reference(memory, path, value):
    arguments = {'context_path': path}
    identity = json.dumps({'arguments': arguments, 'value': value}, allow_nan=False, separators=(',', ':'))
    receipt_id = 'context-collection-' + hashlib.sha256(identity.encode()).hexdigest()
    memory.archive('delivered_context_collection', arguments, value, receipt_id)
    return {**receipt_reference(receipt_id), 'item_count': len(value)}

def reference_context_collections(view, role, memory):
    """Archive oversized repeated collections without changing canonical facts.

    Call only on the detached compact delivery. Submit-only review phases keep
    literal evidence because they cannot fetch references. Adopted report basis
    and explicitly returned tool results are outside this projection.
    """
    if role == 'predictor' and view.get('review_workflow', {}).get('phase') in ('decision', 'correction'):
        return
    candidates = []
    for i, row in enumerate(view.get('recorded_analysis_intervals', [])):
        if isinstance(row, dict) and isinstance(row.get('supporting_observations'), list):
            candidates.append((row, 'supporting_observations', f'/recorded_analysis_intervals/{i}/supporting_observations'))
    history = view.get('evidence_history_view', {})
    if isinstance(history.get('unit_index'), list):
        candidates.append((history, 'unit_index', '/evidence_history_view/unit_index'))
    used = references = 0
    for row, field, path in reversed(candidates):
        value = row[field]
        if not value:
            continue
        encoded = json.dumps(value, allow_nan=False, separators=(',', ':'))
        size = len(encoded.encode())
        if used + size <= HISTORICAL_COLLECTION_BYTES:
            used += size
            continue
        reference = _collection_reference(memory, path, value)
        if field == 'unit_index':
            row['unit_index_details_read'] = reference
            row[field] = [{**{key: deepcopy(item) for key, item in unit.items() if key not in ('landmarks', 'pinned_measurement_ids')}, 'archived_detail_counts': {key: len(unit[key]) for key in ('landmarks', 'pinned_measurement_ids') if key in unit}} for unit in value]
        else:
            row[field] = reference
        references += 1
    if references:
        view['context_view']['collection_delivery'] = {'literal_json_allocation_bytes': HISTORICAL_COLLECTION_BYTES, 'literal_json_bytes': used, 'reference_count': references, 'scope': 'The allocation covers nonempty whole historical collections; empty arrays, fixed identity headers and reference metadata are outside it. Older or larger collections are exact session-durable ordered receipt reads. An abbreviated unit_index retains all identity headers and archived_detail_counts; unit_index_details_read returns its exact original rows, including every landmark and pinned ID. Interval headers remain visible. References are not evidence exclusion, adoption, qualification or resolution. Current camera, adopted report intervals and explicitly returned tool results retain their existing delivery.'}

def shared_message_context(events):
    """Keep acquisition-start traffic outside the recent message count."""
    messages, acquisitions = ([], [])
    for event in events:
        target = acquisitions if event.get('event_type') == 'observation' and event.get('observation_type') == 'camera_acquisition_started' else messages
        target.append(event)
    result = {'shared_messages': deepcopy(messages[-24:]), 'omitted_earlier_messages': max(0, len(messages) - 24)}
    for event in result['shared_messages']:
        if event.get('observation_type') == 'scientific_peer_validation_error':
            payload = event['payload']
            cause = validation_cause(payload['message'])
            event['payload'] = {'status': payload['status'], 'message': cause['message'], 'message_truncated': cause['truncated'], 'effect': payload['effect'], 'rejected_submission_omitted': True, 'full_event_read': {'tool': 'read_shared_events', 'arguments': {'event_ids': [event['event_id']], 'offset': 0, 'limit': 1}}}
    if acquisitions:
        result['camera_acquisition_memory'] = {'latest_event': deepcopy(acquisitions[-1]), 'total_events': len(acquisitions), 'earlier_events_omitted': len(acquisitions) - 1, 'scope': 'Acquisition-start metadata is counted separately from recent shared messages. The latest complete event is shown; all original events remain available through read_shared_events by ID or chronological page. This does not replace camera measurements, establish successful acquisition or resolve any scientific concern.'}
    return result

def _args(args, keys):
    if not isinstance(args, dict) or set(args) != set(keys):
        raise ValueError('Provide exactly ' + ', '.join(keys))
    if type(args['offset']) is not int or args['offset'] < 0 or type(args['limit']) is not int or (not 1 <= args['limit'] <= 64):
        raise ValueError('Use integer offset >= 0 and limit from 1 to 64')

def _page(value, args):
    if not isinstance(value, (dict, list)):
        raise ValueError('The selected detail section is not pageable')
    total = len(value)
    start = args['offset']
    if start > total:
        raise ValueError('Offset exceeds the selected archive')
    end = min(total, start + args['limit'])
    items = {key: value[key] for key in list(value)[start:end]} if isinstance(value, dict) else value[start:end]
    return {'kind': 'mapping' if isinstance(value, dict) else 'list', 'items': deepcopy(items), 'total': total, 'offset': start, 'next_offset': end if end < total else None, 'complete': end == total}

def read_shared_events(events, args):
    """Read exact public typed events by ID or chronological page, without writes."""
    _args(args, ('event_ids', 'offset', 'limit'))
    ids = args['event_ids']
    if not isinstance(ids, list) or any((not isinstance(i, str) or not i for i in ids)) or len(set(ids)) != len(ids):
        raise ValueError('Use distinct event IDs, or [] to browse all events')
    rows = [deepcopy(e if isinstance(e, dict) else e.to_dict()) for e in events]
    available = {e['event_id'] for e in rows}
    unknown = [i for i in ids if i not in available]
    if unknown:
        raise ValueError('Unknown public event IDs: ' + json.dumps(unknown))
    if ids:
        selected = set(ids)
        rows = [e for e in rows if e['event_id'] in selected]
    return {'section': 'shared_events', **_page(rows, args)}

class ContextSectionUnavailable(ValueError):
    """Describe public archive availability without inventing an empty collection."""

    def __init__(self, context, section):
        super().__init__('The selected context section is absent')
        available = []
        for name in DETAIL_SECTIONS:
            value = context
            parts = ['cohort_memory'] if name == 'cohort_memory.members' else name.split('.')
            for key in parts:
                if not isinstance(value, dict) or key not in value:
                    break
                value = value[key]
            else:
                available.append(name)
        self.details = {'requested_section': section, 'available_sections': available, 'public_event_read': {'tool': 'read_shared_events', 'identity_field': 'event_id', 'scope': 'Existing public tool records remain readable; no missing collection or scientific disposition is inferred.'}}

def read_context_details(context, args):
    """Page an explicit original context section; never infer absent details."""
    _args(args, ('section', 'offset', 'limit'))
    if args['section'] not in DETAIL_SECTIONS:
        raise ValueError('Unknown context detail section')
    if args['section'] == 'cohort_memory.members':
        if not isinstance(context, dict) or 'cohort_memory' not in context:
            raise ContextSectionUnavailable(context, args['section'])
        members = [{'cohort_id': cohort['cohort_id'], 'member': member} for cohort in context['cohort_memory'] for member in cohort.get('members', [])]
        return {'section': args['section'], **_page(members, args)}
    value = context
    for key in args['section'].split('.'):
        if not isinstance(value, dict) or key not in value:
            raise ContextSectionUnavailable(context, args['section'])
        value = value[key]
    return {'section': args['section'], **_page(value, args)}

def archive_receipt(page):
    """Record retrieval coordinates without embedding previously read receipts.

    The full detached page still goes to the requesting caller. Event IDs are
    durable archive references; snapshot coordinates retain normal expiry.
    This receipt never represents the reference list as the retrieved items.
    """
    items = page['items']
    references = []
    if page['kind'] == 'mapping':
        references = [{'mapping_key': key} for key in items]
    else:
        fields = ('event_id', 'measurement_id', 'calculation_id', 'context_id', 'preparation_id', 'member_id', 'cohort_id', 'location')
        for i, item in enumerate(items):
            ref = {'page_index': page['offset'] + i}
            if isinstance(item, str):
                ref['event_id'] = item
            elif isinstance(item, dict):
                ref.update({key: deepcopy(item[key]) for key in fields if key in item})
                if isinstance(item.get('member'), dict):
                    ref.update({key: deepcopy(item['member'][key]) for key in fields if key in item['member']})
            references.append(ref)
    return {**deepcopy({key: value for key, value in page.items() if key != 'items'}), 'representation': 'canonical_detail_references', 'returned_item_count': len(items), 'item_references': references, 'meaning': 'Reference receipt only; the exact full page is delivered to the requesting role. Canonical event IDs remain readable. Snapshot coordinates retain their normal expiry.'}

def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str):
                yield key
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)

def _disclosure(original, selected):
    return {'available': len(original), 'shown': len(selected), 'omitted': len(original) - len(selected)}

def _same_public_value(left, right):
    """Compare public payloads without merging bool/int or native key types."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return len(left) == len(right) and all((key in right and any((type(key) is type(other) and key == other for other in right)) and _same_public_value(value, right[key]) for key, value in left.items()))
    if isinstance(left, (list, tuple)):
        return len(left) == len(right) and all((_same_public_value(a, b) for a, b in zip(left, right)))
    return left == right

def _current_utility_references(view):
    """Reference exact unexecuted receipt results; return the number changed."""
    if 'last_tool_result' not in view:
        return 0
    references = 0
    for event in view.get('shared_messages', []):
        if event.get('event_type') == 'tool_call' and event.get('executed') is False and isinstance(event.get('event_id'), str) and event['event_id'] and ('result' in event) and _same_public_value(event['result'], view['last_tool_result']):
            event['result'] = {'representation': 'last_tool_result_reference', 'canonical_event_id': event['event_id'], 'result_path': 'last_tool_result'}
            references += 1
    return references

def _endpoint_preparation_references(view):
    """Keep the first full snapshot in place; reference exact later copies."""
    originals, coordinates, used = ({}, {}, set())
    references = 0

    def project(acquired, calculation_id, register):
        nonlocal references
        if not isinstance(acquired, dict):
            return
        rows = acquired.get('preparations')
        if not isinstance(rows, list):
            return
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            cid = row.get('context_id')
            if not isinstance(cid, str) or not cid:
                continue
            if cid not in originals:
                if register:
                    originals[cid] = deepcopy(row)
                    coordinates[cid] = {'calculation_id': calculation_id, 'preparation_index': i}
                continue
            if 'representation' in row or 'nominal_preparation_ref' in row or (not _same_public_value(row, originals[cid])):
                continue
            rows[i] = {key: value for key, value in row.items() if key not in ('nominal_preparation', 'location', 'last_addition_event_id', 'last_mix_event_id', 'last_change_event_id')}
            rows[i].update(representation='endpoint_preparation_reference', nominal_preparation_ref=cid)
            used.add(cid)
            references += 1
    for calculation in view.get('analysis_memory', {}).get('calculations', []):
        if calculation.get('tool') == 'analyze_measured_endpoint_series' and isinstance(calculation.get('calculation_id'), str):
            project(calculation.get('acquisition_context'), calculation['calculation_id'], True)
    for event in view.get('shared_messages', []):
        if event.get('event_type') == 'tool_call' and event.get('executed') is False and (event.get('tool_name') == 'analyze_measured_endpoint_series'):
            project(event.get('result', {}).get('acquisition_context'), None, False)
    if used:
        view['context_view']['endpoint_preparation_index'] = {cid: coordinates[cid] for cid in coordinates if cid in used}
        view['context_view']['endpoint_preparation_references'] = {'reference_count': references, 'indexed_full_records': len(used), 'meaning': 'Each reference names an unchanged full preparation in analysis_memory.calculations at the indexed calculation_id/preparation_index. First records remain full; conflicting snapshots remain inline. Exact original calculations remain readable through read_context_details or their canonical tool events through read_shared_events. References are presentation only; no preparation is omitted from canonical history.'}

def _historical_utility_references(view):
    """Display known archival collections by stable event references only.

    New utility data is delivered unchanged in last_tool_result. These shared
    receipts prove the read and locate the exact canonical result; they do not
    pretend that the displayed references are full acquired optical records.
    """
    measurement_fields = {'rgb', 'rgb_noise_sd_counts', 'rgb_quantization_step_counts', 'basis', 'clipped', 'od_estimate', 'od_lower_bound', 'od_noise_sd_estimate'}
    preparation_fields = {'volume_ul', 'source_equivalents_ul', 'last_addition_completed_at_s', 'last_mix_completed_at_s', 'last_change_completed_at_s'}
    action_fields = {'tool_call_id', 'trace_sequence', 'params'}
    parameter_fields = {'source', 'target', 'location', 'locations', 'volume_ul', 'seconds'}
    for event in view.get('shared_messages', []):
        if event.get('event_type') != 'tool_call' or event.get('executed') is not False or event.get('tool_name') not in ('read_measurements', 'find_acquired_observations', 'read_action_history') or (not isinstance(event.get('event_id'), str)):
            continue
        result = event.get('result')
        if not isinstance(result, dict) or any((key in result for key in ('archived_collections', 'canonical_event_id', 'archive_representation', 'archive_lookup'))):
            continue
        archived = {}

        def collection(container, key, name, columns, omitted, nested=None):
            rows = container.get(key)
            if not isinstance(rows, list) or not all((isinstance(row, dict) for row in rows)):
                return
            identities, extensions, absent = ([], [], {})
            for i, row in enumerate(rows):
                identities.append([deepcopy(row.get(k)) for k in columns])
                missing = [k for k in columns if k not in row]
                if missing:
                    absent[str(i)] = missing
                ref = {k: deepcopy(v) for k, v in row.items() if k not in omitted and k not in columns}
                if nested:
                    source_key, known = nested
                    value = row.get(source_key)
                    if isinstance(value, dict):
                        nested_extensions = {k: deepcopy(v) for k, v in value.items() if k not in known}
                        if nested_extensions:
                            ref[source_key] = nested_extensions
                    elif source_key in row:
                        ref[source_key] = deepcopy(value)
                if ref:
                    extensions.append({'row_index': i, 'fields': ref})
            archived[name] = {'representation': 'ordered_archive_identity_rows', 'count': len(rows), 'columns': list(columns), 'rows': identities}
            if absent:
                archived[name]['absent_columns_by_row'] = absent
            if extensions:
                archived[name]['extensions_by_row'] = extensions
            container.pop(key)
        collection(result, 'measurements', 'measurements', ('measurement_id', 'location', 'captured_at_s'), measurement_fields)
        collection(result, 'actions', 'actions', ('event_id', 'action', 'completed_at_s'), action_fields, ('params', parameter_fields))
        acquired = result.get('acquisition_context')
        if isinstance(acquired, dict):
            collection(acquired, 'preparations', 'acquisition_context.preparations', ('context_id', 'preparation_id', 'location'), {'nominal_preparation', 'last_addition_event_id', 'last_mix_event_id', 'last_change_event_id'}, ('nominal_preparation', preparation_fields))
            collection(acquired, 'captures', 'acquisition_context.captures', ('measurement_id', 'command_context_id', 'preparation_id', 'elapsed_since_addition_s', 'elapsed_since_mix_s', 'elapsed_since_change_s'), set())
        audit = result.get('timing_audit')
        if isinstance(audit, dict):
            collection(audit, 'observations', 'timing_audit.observations', ('measurement_id', 'command_context_id', 'preparation_id', 'elapsed_s', 'deviation_s', 'within_declared_tolerance'), set())
        if archived:
            result.update(archived_collections=archived, canonical_event_id=event['event_id'], archive_representation='canonical_utility_references')
            view['context_view']['utility_archive_scope'] = "Historical utility collections are ordered identity/timestamp references, not replacement optical or command records. Columns name each row's explicit values; absent_columns_by_row distinguishes absence from null. Unknown fields remain in extensions_by_row. read_shared_events with event_ids=[the receipt's canonical_event_id], offset=0, limit=1 returns its exact full immutable event/result. last_tool_result preserves new full delivery."

def project_context(context, role, *, history_unit_limit=64):
    """Select only by public references, action footprint and archive chronology.

    The latest camera packet and scientific obligations are untouched. Unknown
    extension fields are retained. Automatic history is a recent context slice,
    not the full acquired archive: read_measurements/read_shared_events reach
    earlier records. All ordinary omissions are explicitly disclosed.
    """
    if role not in ROLES or not isinstance(context, dict):
        raise ValueError('Use a declared role and canonical context object')
    if type(history_unit_limit) is not int or not 0 <= history_unit_limit <= 64:
        raise ValueError('Use a history unit limit from zero to64')
    view = deepcopy(context)
    focus_fields = ('proposed_action', 'proposed_report', 'proposed_decision', 'action_preparations', 'working_plan_observations', 'working_plan_acquisition_context', 'pending_reviews', 'scientific_review_memory', 'analysis_memory', 'recorded_analysis_intervals', 'last_tool_result')
    references = set(_strings({k: context[k] for k in focus_fields if k in context}))
    for cohort in context.get('cohort_memory', []):
        for member in cohort.get('members', []):
            references.update(member.get('evidence_ids', []))
            if member.get('preparation_id') is not None:
                references.add(member['preparation_id'])
    locations = {s for s in references if s.startswith(('plate:', 'reservoir:')) and '@' not in s}
    sections = {}
    memory = view.get('retrieval_memory')
    if isinstance(memory, dict) and isinstance(memory.get('entries'), list):
        closed_review = role == 'predictor' and context.get('review_workflow', {}).get('phase') in ('decision', 'correction')
        used = 0
        for entry in reversed(memory['entries']):
            if isinstance(entry, dict) and 'result' in entry and isinstance(entry.get('receipt_event_id'), str):
                size = len(json.dumps(entry['result'], separators=(',', ':')).encode())
                if closed_review or used + size <= WORKING_RESULT_BYTES:
                    used += size
                else:
                    entry['result'] = receipt_reference(entry['receipt_event_id'])
        memory.pop('archived_entries', None)
        memory['scope'] = 'Newest whole working results fit a 16KiB literal JSON result budget; larger/older results use exact receipt references. Submit-only Predictor review retains the entire admitted bounded cache. Storage bounds are not whole-request bounds. Receipt IDs remain readable after release/replacement/eviction; null ID pages the session archive. last_tool_result stays full. Retention is not adoption or resolution.'
    if 'evidence_history_view' in context:
        rows = context['evidence_history_view']['units']
        history = view['evidence_history_view']
        shown, used = (0, 2)
        for row in rows[:history_unit_limit]:
            size = len(json.dumps(compact_context(row), separators=(',', ':')).encode()) + int(shown > 0)
            if used + size > HISTORY_DETAIL_BYTES:
                break
            used += size
            shown += 1
        history['units'] = deepcopy(rows[:shown])
        history.update(units_available=len(rows), units_shown=shown, units_omitted=len(rows) - shown)
        if len(rows) > shown:
            history['unit_index'] = [{'offset': i, **{k: deepcopy(row[k]) for k in ('location', 'preparation_id', 'binding_status', 'acquired_count', 'pinned_measurement_ids') if k in row}, 'landmarks': [{k: deepcopy(m[k]) for k in ('measurement_id', 'location', 'captured_at_s') if k in m} for m in row.get('observations', [])], 'boundary_event_ids': [b['command']['event_id'] for b in row.get('boundaries', [])], 'memberships': [{'cohort_id': m['cohort_id'], 'member_id': m['member']['member_id']} for m in row.get('declared_members', [])]} for i, row in enumerate(rows)]
            history['remaining_units_read'] = {'tool': 'read_context_details', 'arguments': {'section': 'evidence_history_view.units', 'offset': 0, 'limit': 64, 'snapshot_id': None}, 'next_omitted_offset': shown, 'paging': 'Runtime binds this read to an exact delivery snapshot, including transient decision scope, before sending it to a model. The pure static view cannot allocate a runtime snapshot.'}
        sections['evidence_history_view.units'] = {'available': len(rows), 'shown': shown, 'selection': 'First units in declaration/reference order; no value-based rank. All canonical units are pageable.'}
    if isinstance(context.get('analysis_memory'), dict) and isinstance(context['analysis_memory'].get('calculations'), list):
        rows = context['analysis_memory']['calculations']
        closed_review = role == 'predictor' and context.get('review_workflow', {}).get('phase') in ('decision', 'correction')
        selected = rows if closed_review else rows[-RECENT_CALCULATIONS:]
        if len(selected) < len(rows):
            view['analysis_memory'].update(calculations=deepcopy(selected), total_calculations=len(rows), omitted_calculations=len(rows) - len(selected), archive_section='analysis_memory.calculations')
        sections['analysis_memory.calculations'] = {**_disclosure(rows, selected), 'selection': 'Recent calculations, not preferred results. Submit-only reviews retain all supplied calculations. Full chronological originals remain pageable; omitted records are not exclusions or superseded results.'}
    if 'color_comparison_memory' in context:
        rows = context['color_comparison_memory']['comparisons']
        view['color_comparison_memory']['comparisons'] = deepcopy(rows[-12:])
        view['color_comparison_memory']['total_comparisons'] = len(rows)
        view['color_comparison_memory']['omitted_comparisons'] = max(0, len(rows) - 12)
        view['color_comparison_memory']['archive_section'] = 'color_comparison_memory.comparisons'
        sections['color_comparison_memory.comparisons'] = {'available': len(rows), 'shown': min(12, len(rows)), 'selection': 'Most recent calculations only, not best results; full chronological comparisons are pageable.'}
    if 'measurement_history' in context:
        rows = context['measurement_history']
        latest_by_location = {}
        for i, row in enumerate(rows):
            if row['location'] in locations:
                latest_by_location.setdefault(row['location'], []).append(i)
        focused = {i for indices in latest_by_location.values() for i in indices[-2:]}
        selected = [row for i, row in enumerate(rows) if i >= len(rows) - RECENT_MEASUREMENTS or i in focused or row['measurement_id'] in references]
        view['measurement_history'] = deepcopy(selected)
        sections['measurement_history'] = _disclosure(rows, selected)
    if 'shared_messages' in context:
        rows = context['shared_messages']
        latest_peer = next((row.get('event_id') for row in reversed(rows) if row.get('observation_type') == 'scientific_review'), None)
        latest_knowledge = next((row.get('event_id') for row in reversed(rows) if row.get('event_type') == 'knowledge_response'), None)
        latest_utility = {}
        for row in rows:
            if row.get('event_type') == 'tool_call' and row.get('executed') is False:
                latest_utility[row.get('source_agent'), row.get('tool_name')] = row.get('event_id')
        utility_ids = set(latest_utility.values())
        selected = []
        for i, row in enumerate(rows):
            peer = row.get('observation_type') == 'scientific_review'
            referenced = row.get('event_id') in references or (peer and row.get('payload', {}).get('event_id') in references)
            ordinary_workflow = row.get('event_type') in ('plan', 'prediction', 'tool_call') or row.get('observation_type') == 'camera_acquisition_started' or peer
            utility = row.get('event_type') == 'tool_call' and row.get('executed') is False
            if referenced or row.get('event_id') in (latest_peer, latest_knowledge) or row.get('event_id') in utility_ids or (utility and i >= len(rows) - RECENT_MESSAGES) or (i >= len(rows) - RECENT_MESSAGES and (not ordinary_workflow)):
                selected.append(row)
        embedded = {row.get('payload', {}).get('event_id') for row in selected if row.get('observation_type') == 'scientific_review'}
        selected = [row for row in selected if not (row.get('event_type') == 'prediction' and row.get('event_id') in embedded)]
        view['shared_messages'] = deepcopy(selected)
        sections['shared_messages'] = _disclosure(rows, selected)
    if 'commanded_preparations' in context:
        wells = context['commanded_preparations'].get('wells', {})
        sections['commanded_preparations.wells'] = _disclosure(wells, wells)
    if 'plate_transfer_accounting' in context:
        rows = context['plate_transfer_accounting'].get('event_ids', [])
        selected = [i for n, i in enumerate(rows) if n >= len(rows) - RECENT_MESSAGES or i in references]
        if 'event_ids' in context['plate_transfer_accounting']:
            view['plate_transfer_accounting']['event_ids'] = deepcopy(selected)
            sections['plate_transfer_accounting.event_ids'] = _disclosure(rows, selected)
    if 'cohort_memory' in context:
        omitted_rationales = 0
        for cohort in view['cohort_memory']:
            for member in cohort.get('members', []):
                if member.get('location') not in locations and 'proposed_report' not in context and (member.get('disposition') != 'nonadopt') and ('rationale' in member):
                    member.pop('rationale')
                    omitted_rationales += 1
        sections['cohort_memory'] = {'members_omitted': 0, 'member_rationales_omitted': omitted_rationales}
    if 'acquisition_schedule' in context:
        available = shown = 0
        for row in view['acquisition_schedule'].get('rows', []):
            history = row.get('historical_preparations', [])
            selected = [p for i, p in enumerate(history) if i >= len(history) - RECENT_PREPARATIONS or p.get('preparation_id') in references or p.get('command_context_id') in references or any((mid in references for mid in p.get('matching_measurement_ids', [])))]
            row['historical_preparations'] = selected
            row['historical_preparations_available'] = len(history)
            row['historical_preparations_omitted'] = len(history) - len(selected)
            available += len(history)
            shown += len(selected)
        sections['acquisition_schedule.rows'] = {'historical_preparations_available': available, 'historical_preparations_shown': shown, 'historical_preparations_omitted': available - shown}
    view['context_view'] = {'scope': 'Public references, declared locations and chronological recency only; presentation omissions are not evidence exclusion, scientific resolution or changed cohort enrollment.', 'sections': sections, 'shared_event_index': [{key: deepcopy(row[key]) for key in ('event_id', 'trace_sequence', 'event_type', 'observation_type', 'tool_name') if key in row} for row in context.get('shared_messages', [])], 'earlier_measurements_outside_context': context.get('omitted_earlier_measurements', 0), 'earlier_messages_outside_context': context.get('omitted_earlier_messages', 0), 'archive_tools': ['read_measurements', 'read_shared_events', 'read_context_details'], 'detail_sections': list(DETAIL_SECTIONS), 'detail_scope': 'Runtime read_context_details: snapshot_id=null with offset=0 starts a detached context snapshot; use its returned snapshot_id for subsequent pages of that section. Unknown or expired snapshots reject. Earlier complete acquired history uses read_measurements; full append-only typed events use read_shared_events. Offsets are zero-based; limit is 1..64. The pure static helper accepts section/offset/limit only.'}
    if _current_utility_references(view):
        view['context_view']['current_utility_reference_scope'] = 'An exact unexecuted utility result may reference the full last_tool_result in this same context. Its canonical_event_id retrieves the original complete receipt through read_shared_events; event headers remain visible.'
    _endpoint_preparation_references(view)
    _historical_utility_references(view)
    history = view.get('evidence_history_view')
    if history and history['units']:
        encoded = compact_context(order_context(view))['evidence_history_view']['units']
        if len(json.dumps(encoded, separators=(',', ':')).encode()) > HISTORY_DETAIL_BYTES:
            return project_context(context, role, history_unit_limit=len(history['units']) - 1)
    return view
