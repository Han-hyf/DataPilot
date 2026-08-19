from __future__ import annotations

from types import SimpleNamespace

import pytest

from llm import DeepSeekLLM, LLMError


class FakeCompletions:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        message = SimpleNamespace(content=next(self.contents))
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_llm(contents):
    llm = DeepSeekLLM.__new__(DeepSeekLLM)
    llm.model = "test-model"
    completions = FakeCompletions(contents)
    llm.client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return llm, completions


def test_json_completion_retries_empty_response():
    llm, completions = fake_llm(["", '{"sql":"SELECT 1"}'])
    assert llm._json_completion([]) == {"sql": "SELECT 1"}
    assert completions.calls == 2


def test_json_completion_extracts_object_from_code_fence():
    llm, completions = fake_llm(['```json\n{"sql":"SELECT 1"}\n```'])
    assert llm._json_completion([]) == {"sql": "SELECT 1"}
    assert completions.calls == 1


def test_json_completion_stops_after_two_invalid_responses():
    llm, completions = fake_llm(["not-json", "[]"])
    with pytest.raises(LLMError, match="已重试 2 次"):
        llm._json_completion([])
    assert completions.calls == 2
