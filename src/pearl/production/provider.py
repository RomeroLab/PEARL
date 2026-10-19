"""One role-scoped model request, with exact public exchanges and actual usage."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4


def count(value):
    return value if type(value) is int and value >= 0 else None


class Provider:
    def __init__(self, log_path, *, model=None, reasoning_effort=None, client=None):
        self.log_path = Path(log_path)
        if client is None:
            from dotenv import load_dotenv
            load_dotenv()
            from openai import OpenAI
            client = OpenAI(timeout=180., max_retries=0)
        self.model = model or os.environ.get('OPENAI_MODEL', 'gpt-5.6-terra')
        self.reasoning_effort = reasoning_effort or os.environ.get('OPENAI_REASONING_EFFORT', 'high')
        self.client = client

    def _write(self, row):
        with self.log_path.open('a') as f:
            f.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), **row}, allow_nan=False)+'\n')

    def __call__(self, role, messages, tools):
        eid = uuid4().hex
        request = {'model': self.model, 'messages': deepcopy(messages), 'tools': deepcopy(tools),
                   'tool_choice': 'required', 'parallel_tool_calls': False,
                   'reasoning_effort': self.reasoning_effort}
        self._write({'kind': 'request', 'exchange_id': eid, 'role': role, 'request': request})
        try:
            response = self.client.chat.completions.create(**request)
        except BaseException as exc:
            self._write({'kind': 'request_error', 'exchange_id': eid, 'role': role,
                         'error_type': type(exc).__name__, 'outcome': 'unknown_provider_usage'})
            raise
        u = response.usage
        prompt_details = getattr(u, 'prompt_tokens_details', None)
        completion_details = getattr(u, 'completion_tokens_details', None)
        usage = {'input_tokens': count(getattr(u, 'prompt_tokens', None)),
                 'output_tokens': count(getattr(u, 'completion_tokens', None)),
                 'cached_tokens': count(getattr(prompt_details, 'cached_tokens', None)),
                 'reasoning_tokens': count(getattr(completion_details, 'reasoning_tokens', None))}
        choices = response.choices
        m = choices[0].message if choices else None
        raw = {'text': getattr(m, 'content', None), 'refusal': getattr(m, 'refusal', None),
               'tool_calls': [{'id': t.id, 'name': t.function.name, 'arguments': t.function.arguments}
                              for t in (getattr(m, 'tool_calls', None) or [])]}
        self._write({'kind': 'response', 'exchange_id': eid, 'role': role, 'request_id': response.id,
                     'response_model': response.model, 'usage': usage, 'response': raw})
        if not m or getattr(m, 'refusal', None) or len(raw['tool_calls']) != 1:
            raise RuntimeError('Expected one non-refused model tool selection; response preserved')
        tool = raw['tool_calls'][0]
        try:
            args = json.loads(tool['arguments'])
        except (TypeError, ValueError) as exc:
            raise RuntimeError('Invalid model tool JSON; response preserved') from exc
        return {'name': tool['name'], 'arguments': args}
