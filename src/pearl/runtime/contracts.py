"""Immutable operation values and an execution-only dispatcher."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze(v) for v in value)
    return value

@dataclass(frozen=True)
class ActionSpec:
    action_type: str = ''
    params: Mapping[str, Any] = field(default_factory=dict)
    action_id: str = ''
    provenance: str = ''
    def __post_init__(self):
        object.__setattr__(self, 'params', _freeze(dict(self.params)))

@dataclass(frozen=True)
class ActionResult:
    action_id: str = ''
    action_type: str = ''
    ok: bool = False
    observation: Mapping[str, Any] = field(default_factory=dict)
    error: str = ''

@dataclass(frozen=True)
class ProceedSignal:
    plan_id: str = ''
    actions: tuple[ActionSpec, ...] = ()
    validation_summary: str = ''
    @property
    def action_ids(self):
        return [a.action_id for a in self.actions]

class Actor:
    def __init__(self, execute):
        if not callable(execute):
            raise TypeError('Actor requires an execute-only callable')
        self._execute = execute
    def execute(self, proceed_signal):
        if not isinstance(proceed_signal, ProceedSignal):
            raise TypeError('Actor.execute consumes a ProceedSignal only')
        return [self._execute(a) for a in proceed_signal.actions]
