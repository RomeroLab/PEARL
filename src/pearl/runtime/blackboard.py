"""Typed, ordered public evidence with identical camera access for every role."""
from collections import deque
from copy import deepcopy
from pearl.state.events import ObservationEvent
ROLES = ('reasoner', 'actor', 'predictor', 'knowledge', 'watchdog')

class Blackboard:
    def __init__(self, *, event_sink=None):
        self.event_log = []
        self._subscriptions = {}
        self._publishing = False
        self._queue = deque()
        self._event_sink = event_sink
    def subscribe(self, event_type, handler):
        self._subscriptions.setdefault(event_type, []).append(handler)
    def unsubscribe(self, event_type, handler):
        handlers = self._subscriptions.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)
    def publish(self, event):
        event.trace_sequence = len(self.event_log) + 1
        if self._event_sink:
            self._event_sink(event.to_dict())
        self.event_log.append(event)
        self._queue.append(event)
        if self._publishing:
            return
        self._publishing = True
        try:
            while self._queue:
                current = self._queue.popleft()
                for kind, handlers in list(self._subscriptions.items()):
                    if isinstance(current, kind):
                        for handler in list(handlers):
                            handler(current)
        finally:
            self._publishing = False
            self._queue.clear()
    def camera_for(self, role):
        if role not in ROLES:
            raise ValueError('Unknown role')
        for e in reversed(self.event_log):
            if isinstance(e, ObservationEvent) and e.observation_type == 'camera':
                return deepcopy(e.payload)
        return {'evidence_ids': [], 'measurements': []}
    def public_events(self, *, excluded_observation_types=()):
        return deepcopy([e.to_dict() for e in self.event_log if not (
            e.event_type == 'observation' and getattr(e, 'observation_type', None) in excluded_observation_types)])
