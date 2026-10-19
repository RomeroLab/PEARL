"""Question-led retrieval of sourced, non-executable scientific guidance."""
from copy import deepcopy
import hashlib
import json
import re
from collections.abc import Mapping
from pearl.knowledge.audit import RetrievalAudit, RetrievalAuditSelection, RetrievalAuditRejection
from pearl.knowledge.terms import _terms as _long_terms, _NON_NEUTRAL

def _terms(text):
    short = set(re.findall('[a-z0-9]+', str(text).lower())) & {'km', 'kcat', 'rgb', 'od', 'cv', 'ph', 'ryb', 'red', 'hrp', 'tmb'}
    units = {re.sub('\\s+', '', unit) for unit in re.findall('\\b(?:u\\s*/\\s*(?:ml|mg)|mg\\s*/\\s*ml)\\b', str(text).lower())}
    return {'replicate' if term in {'replicates', 'triplicate', 'triplicates', 'replication'} else term for term in _long_terms(text) | short | units}

def _topic_qualification(row, question):
    if 'retrieval_anchor_groups' not in row:
        return (None, [])
    groups = row['retrieval_anchor_groups']
    if not isinstance(groups, list) or not groups or any((not isinstance(group, list) or not group or any((not isinstance(term, str) or not re.fullmatch('[a-zA-Z0-9]+(?:[ -][a-zA-Z0-9]+)*', term) for term in group)) for group in groups)):
        return ('invalid_topic_anchors', [])
    singular = {'pigments': 'pigment', 'paints': 'paint', 'dyes': 'dye', 'colorants': 'colorant', 'lights': 'light', 'lamps': 'lamp', 'leds': 'led', 'displays': 'display', 'projectors': 'projector', 'beams': 'beam'}

    def tokens(text):
        return [singular.get(t, t) for t in re.findall('[a-z0-9]+|[^\\w\\s-]', text.lower())]
    asked = tokens(question)

    def present(phrase):
        anchor = tokens(phrase)
        return any((asked[i:i + len(anchor)] == anchor for i in range(len(asked) - len(anchor) + 1)))
    matched = [group for group in groups if all((present(term) for term in group))]
    return (None if matched else 'missing_topic_anchors', deepcopy(matched))
ALIASES = {'rgb': 'color', 'bgr': 'color', 'od_estimate': 'absorbance', 'absorbance': 'absorbance', 'captured_at_s': 'time', 'time_s': 'time'}

def observed_kinds(packet):
    found = set()

    def walk(node):
        if isinstance(node, Mapping):
            found.update((ALIASES[k] for k in node if k in ALIASES))
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
    walk(getattr(packet, 'observations', packet))
    return found

class ScientificKnowledgeProvider:

    def __init__(self, rows, top_k=3):
        self.rows = deepcopy(rows)
        self.top_k = top_k
        self._audit = None

    def retrieve(self, goal, observation=None):
        asked = _terms(goal)
        asked.update((alias for field, alias in ALIASES.items() if field in goal.lower()))
        observed = observed_kinds(observation)
        ranked = []
        for row in self.rows:
            topic_reason, _ = _topic_qualification(row, goal)
            topic = _terms(row['name'] + ' ' + row['anomaly_id'] + ' ' + row.get('keywords', ''))
            body = _terms(row['description'])
            matches = asked & topic
            score = 4 * len(matches) + len(asked & body)
            reason = None
            text = json.dumps(row)
            if _NON_NEUTRAL.search(text):
                reason = 'non_neutral_text'
            elif not row.get('provenance') or not row.get('source_kind') or (not row.get('limitations')):
                reason = 'missing_source_scope'
            elif topic_reason is not None:
                reason = topic_reason
            elif not matches or score < 4:
                reason = 'no_topic_match'
            ranked.append((score, len(observed & set(row.get('measurement_kinds', []))), row, reason))
        ranked.sort(key=lambda x: (-x[0], -x[1], x[2]['anomaly_id']))
        chosen = [x for x in ranked if x[3] is None][:self.top_k]
        ids = {x[2]['anomaly_id'] for x in chosen}
        self._audit = RetrievalAudit(catalog_identity='scientific-guidance', catalog_size=len(self.rows), corpus_hash=hashlib.sha256(json.dumps(self.rows, sort_keys=True).encode()).hexdigest(), query_features=tuple(sorted(asked | observed)) or ('no_topic_terms',), selected=tuple((RetrievalAuditSelection(protocol_id=r['anomaly_id'], version=1, review_status='active', approved=True, score=s, rank=i + 1) for i, (s, _, r, _) in enumerate(chosen))), rejected=tuple((RetrievalAuditRejection(protocol_id=r['anomaly_id'], version=1, review_status='rejected' if reason in ('non_neutral_text', 'missing_source_scope', 'invalid_topic_anchors') else 'active', approved=reason not in ('non_neutral_text', 'missing_source_scope', 'invalid_topic_anchors'), score=s, rank=None, reason=reason or 'outside_top_k') for s, _, r, reason in ranked if r['anomaly_id'] not in ids)))
        return [dict(knowledge_id=r['anomaly_id'], name=r['name'], description=r['description'], kind='scientific_guidance', evidence_kind='prior_knowledge', provenance=r['provenance'], source_kind=r['source_kind'], limitations=r['limitations'], applicability={'conditions': deepcopy(r['evidence_required']), 'measurement_kinds': r.get('measurement_kinds', []), 'observed_measurement_kinds': sorted(observed), 'basis': 'Check these conditions against public evidence; retrieval does not establish applicability.'}, relevance={'score': s, 'topic_qualification': {'matched_anchor_groups': _topic_qualification(r, goal)[1], 'basis': 'Explicit question-topic support where the entry declares anchors; neither measured applicability nor assurance that the question is fully answered.'}, 'matched_terms': sorted(asked & _terms(r['name'] + ' ' + r['description'] + ' ' + r.get('keywords', '')))}, meaning='Scientific prior guidance, not an observation, diagnosis, recipe or execution authorization.') for s, _, r, _ in chosen]

    def retrieval_audit(self):
        if self._audit is None:
            raise RuntimeError('No retrieval performed')
        return self._audit
