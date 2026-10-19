from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

@dataclass(frozen=True)
class RetrievalAuditSelection:
    """Complete provenance for one row admitted to a reasoning envelope."""
    protocol_id: str
    version: int
    review_status: str
    approved: bool
    score: int
    rank: int

    def __post_init__(self) -> None:
        _validate_retrieval_item(self)
        if not self.approved or self.review_status != 'active':
            raise ValueError('selected retrieval rows must be active and approved')
        if isinstance(self.rank, bool) or not isinstance(self.rank, int) or self.rank < 1:
            raise ValueError('selected retrieval rank must be a positive integer')

@dataclass(frozen=True)
class RetrievalAuditRejection:
    """Complete provenance for one corpus candidate not selected."""
    protocol_id: str
    version: int
    review_status: str
    approved: bool
    score: int
    rank: None
    reason: str

    def __post_init__(self) -> None:
        _validate_retrieval_item(self)
        if self.rank is not None:
            raise ValueError('rejected retrieval rank must be None')
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError('rejected retrieval reason must be non-empty')

@dataclass(frozen=True)
class RetrievalAudit:
    """Typed, complete audit for one retrieval-enabled reasoning envelope."""
    catalog_identity: str
    catalog_size: int
    corpus_hash: str
    query_features: tuple[str, ...]
    selected: tuple[RetrievalAuditSelection, ...]
    rejected: tuple[RetrievalAuditRejection, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, 'query_features', tuple(self.query_features))
        object.__setattr__(self, 'selected', tuple(self.selected))
        object.__setattr__(self, 'rejected', tuple(self.rejected))
        if not isinstance(self.catalog_identity, str) or not self.catalog_identity.strip():
            raise ValueError('retrieval catalog identity must be non-empty')
        if isinstance(self.catalog_size, bool) or not isinstance(self.catalog_size, int) or self.catalog_size < 1:
            raise ValueError('retrieval catalog size must be a positive integer')
        if not isinstance(self.corpus_hash, str) or len(self.corpus_hash) != 64 or any((character not in '0123456789abcdef' for character in self.corpus_hash)):
            raise ValueError('retrieval corpus hash must be lowercase SHA-256')
        if not self.query_features or any((not isinstance(item, str) or not item.strip() for item in self.query_features)) or len(set(self.query_features)) != len(self.query_features):
            raise ValueError('retrieval query feature categories must be unique and non-empty')
        if any((not isinstance(item, RetrievalAuditSelection) for item in self.selected)):
            raise TypeError('retrieval selected audit must contain typed selections')
        if any((not isinstance(item, RetrievalAuditRejection) for item in self.rejected)):
            raise TypeError('retrieval rejected audit must contain typed rejections')
        if len(self.selected) + len(self.rejected) != self.catalog_size:
            raise ValueError('retrieval audit must account for every catalog candidate')
        identities = [(item.protocol_id, item.version) for item in self.selected] + [(item.protocol_id, item.version) for item in self.rejected]
        if len(set(identities)) != len(identities):
            raise ValueError('retrieval audit contains duplicate protocol identities')
        if tuple((item.rank for item in self.selected)) != tuple(range(1, len(self.selected) + 1)):
            raise ValueError('retrieval selected ranks must be contiguous and ordered')

def _validate_retrieval_item(item: Any) -> None:
    if not isinstance(item.protocol_id, str) or not item.protocol_id.strip():
        raise ValueError('retrieval protocol_id must be non-empty')
    if isinstance(item.version, bool) or not isinstance(item.version, int) or item.version < 1:
        raise ValueError('retrieval protocol version must be a positive integer')
    if not isinstance(item.review_status, str) or not item.review_status.strip():
        raise ValueError('retrieval review status must be non-empty')
    if not isinstance(item.approved, bool):
        raise TypeError('retrieval approved flag must be boolean')
    if item.approved != (item.review_status == 'active'):
        raise ValueError('retrieval approval must agree with review status')
    if isinstance(item.score, bool) or not isinstance(item.score, int) or item.score < 0:
        raise ValueError('retrieval score must be a non-negative integer')
