"""KnowledgeAgent -- the Knowledge role as a blackboard peer.

The runtime never calls a knowledge provider's methods under the typed-event
transport.  It posts a :class:`~pearl.state.events.KnowledgeRequestEvent`; this
peer, subscribed on the blackboard, runs the audited protocol retrieval and
answers with a :class:`~pearl.state.events.KnowledgeResponseEvent` carrying the
knowledge rows and the complete retrieval audit as a plain mapping.  The
runtime rebuilds the typed audit from that mapping and applies the same
provenance checks it applied to a direct call, so the transport changes and
the content does not.

A provider failure is answered too (an ``error`` field in the audit, no rows)
so the runtime fails closed on the record rather than on a missing reply.
"""
from __future__ import annotations
import logging
from collections.abc import Mapping
from typing import Any
from pearl.knowledge.audit import RetrievalAudit, RetrievalAuditRejection, RetrievalAuditSelection
from pearl.state.events import KnowledgeRequestEvent, KnowledgeResponseEvent
__all__ = ['KnowledgeAgent', 'retrieval_audit_from_mapping', 'retrieval_audit_to_mapping']
_logger = logging.getLogger(__name__)

def retrieval_audit_to_mapping(audit: RetrievalAudit) -> dict[str, Any]:
    """The typed audit as a JSON-only mapping (the blackboard carries no objects)."""
    return {'catalog_identity': audit.catalog_identity, 'catalog_size': audit.catalog_size, 'corpus_hash': audit.corpus_hash, 'query_features': list(audit.query_features), 'selected': [{'protocol_id': item.protocol_id, 'version': item.version, 'review_status': item.review_status, 'approved': item.approved, 'score': item.score, 'rank': item.rank} for item in audit.selected], 'rejected': [{'protocol_id': item.protocol_id, 'version': item.version, 'review_status': item.review_status, 'approved': item.approved, 'score': item.score, 'rank': item.rank, 'reason': item.reason} for item in audit.rejected]}

def retrieval_audit_from_mapping(mapping: Mapping[str, Any]) -> RetrievalAudit:
    """Rebuild the typed audit; every validation of the typed classes applies."""
    if not isinstance(mapping, Mapping):
        raise TypeError('retrieval audit must be a mapping')
    selected = tuple((RetrievalAuditSelection(protocol_id=item['protocol_id'], version=item['version'], review_status=item['review_status'], approved=item['approved'], score=item['score'], rank=item['rank']) for item in mapping.get('selected', ())))
    rejected = tuple((RetrievalAuditRejection(protocol_id=item['protocol_id'], version=item['version'], review_status=item['review_status'], approved=item['approved'], score=item['score'], rank=item.get('rank'), reason=item['reason']) for item in mapping.get('rejected', ())))
    return RetrievalAudit(catalog_identity=mapping['catalog_identity'], catalog_size=mapping['catalog_size'], corpus_hash=mapping['corpus_hash'], query_features=tuple(mapping.get('query_features', ())), selected=selected, rejected=rejected)

def _observation_packet(event: KnowledgeRequestEvent) -> Any:
    """The request's public observation as the packet shape providers accept."""
    payload = getattr(event, 'observation', None)
    if not isinstance(payload, Mapping) or not payload:
        return None
    from pearl.runtime.contracts import EvidencePacket
    return EvidencePacket(evidence_ids=tuple((str(item) for item in payload.get('evidence_ids', ()))), observations=tuple((dict(item) for item in payload.get('observations', ()) if isinstance(item, Mapping))), provenance=str(payload.get('provenance', '') or ''))
