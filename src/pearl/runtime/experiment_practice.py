"""Acknowledged operation facts and general experimental decision practice."""
from pearl.runtime.notebook import action_history
EXPERIMENT_PRACTICE = 'Choose steps by decision value, uncertainty, consequences and physical feasibility.\nBefore choosing physical work, assess the original objective and binding constraints under stated,\napplicable scientific assumptions. Conditional inference needs no universal proof. Seek information\nthat could change the decision. Failure of one chosen method is not task infeasibility; consider a\nrecoverable execution or measurement problem. Review both the truth of its limited claims and whether it resolves the original request.\nA chosen stopping rule cannot replace that request. Reconcile abandoned informative alternatives.\nA record-validation rejection is not scientific counterevidence; repair the record.\nExisting evidence, new observations, calculations, changes, repetition and stopping are options,\nnot a prescribed order. State the question and outcomes that would change interpretation.\nIn the existing recovery rationale, cite what was checked, compare acquired evidence (including\njustified selection) with new work, and identify missing decision-relevant evidence requiring that\nscope. Explain skipped evidence checks or why smaller alternatives are inadequate. Predictor reviews this comparison\nin its existing assessment: no extra turn or fixed tool order. Logical correction and justified stopping\nneed no new measurements; shared problems may justify broad redesign or repetition.\nDiscrepancy magnitude alone establishes neither cause nor required response. Apply declared quality\nand selection conditions in scope; fit agreement alone justifies neither adoption nor exclusion.\nPreserve observations, candidate identities, prior decisions and contrary evidence across revisions.\nLocalize problems to affected observational units; discordance does not establish contamination\nor invalidate a group. Evidence of violated comparison/measurement assumptions may justify scoped\nexclusion despite unknown cause. Assess shared causes, selection bias and sensitivity; disagreement\nor better fit alone cannot justify removal. Check retained independent coverage and unchanged quality\ncriteria. Adequate data need no replacement; otherwise target missing evidence or limit conclusions.\nUnknown cause mandates neither retaining unusable data nor whole-series repetition. Exclusion is not success.\nFor material evidence use, record decision_basis.evidence_use: intent/assumptions, exact locations/IDs,\nsupporting/contrary evidence, provisional cause or null, use and sufficiency. Separate diagnostics\nfrom adoption; justify explicit selection under original criteria. Existing Predictor review applies.\nCause certainty, exclusion, new work and extra review are optional.\nAssess measured resolution and uncertainty separately from fit agreement. Identical digitized values\nneed not have zero readout uncertainty; shared corrections need not create independent errors.\nreadout_precision and endpoint_readout_precision describe conditional readout contributions, not total\nconfidence or new acceptance rules. Calculations bind recorded inputs/intervals; later observations\nare not retroactive inputs. Check actual acquisition/operation timing and outstanding commitments,\nincluding outside the current focus. Future windows differ from historical observations; model latency\nis not a measured reaction interval. Nominal preparation/mix records do not verify delivery, composition,\nactivity or homogeneity. Repetition is not automatically informative. Scientific guidance is optional\nprior knowledge requiring applicability checks. Safety remains binding; allow justified unresolved or\nconflicting conclusions. No recipe, exclusion, sample count, repetition or result is prescribed.\n'

def operation_state(events):
    """Return detached nominal stage/mix facts from successful Actor receipts.

    The last mix remains an historical fact after a transfer. Only the count and
    IDs since the most recent material change describe mixes of the current stage.
    Transfers change both source and target, including withdrawal from a source.
    Unknown command completion times and missing material anchors remain null.
    """
    wells = {}

    def location(name):
        return wells.setdefault(name, {'last_change_event_id': None, 'last_change_completed_at_s': None, 'mix_count_since_change': 0, 'mix_event_ids_since_change': [], 'last_mix_event_id': None, 'last_mix_completed_at_s': None})
    for row in action_history(events):
        params = row['params']
        if row['action'] == 'transfer':
            for name in (params['source'], params['target']):
                state = location(name)
                state['last_change_event_id'] = row['event_id']
                state['last_change_completed_at_s'] = row['completed_at_s']
                state['mix_count_since_change'] = 0
                state['mix_event_ids_since_change'] = []
        elif row['action'] == 'mix':
            state = location(params['location'])
            state['mix_count_since_change'] += 1
            state['mix_event_ids_since_change'].append(row['event_id'])
            state['last_mix_event_id'] = row['event_id']
            state['last_mix_completed_at_s'] = row['completed_at_s']
    return {'basis': 'Nominal material stages and mix history from acknowledged Actor commands; not measured delivery, chemical identity, completion of an intended preparation or homogeneity. Prior mix facts may predate the current stage; current-stage counts reset on addition or withdrawal. Unknown times remain null.', 'wells': wells}
