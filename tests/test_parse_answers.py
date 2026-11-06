from types import SimpleNamespace

import pytest

from crm_sandbox.env import env as crm_env


def judge_replying(content):
    message = SimpleNamespace(content=content)

    def completion(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    return completion


@pytest.mark.parametrize(
    "reply",
    [
        '```json\n{"extracted_answers": ["CO"]}\n```',
        'Here is the answer: {"extracted_answers": ["CO"]}',
    ],
    ids=["code-fence", "text-before-json"],
)
def test_non_json_judge_reply_uses_the_regex_fallback(monkeypatch, reply):
    monkeypatch.setattr(crm_env.litellm, "completion", judge_replying(reply))
    evaluator = crm_env.Evaluator(model="judge", provider="openai")
    answer = "The state with the quickest closures is Colorado (CO)."
    assert evaluator.parse_answers(answer, "best_region_identification") == ["CO"]


def test_fenced_judge_reply_scores_a_correct_answer(monkeypatch):
    reply = '```json\n{"extracted_answers": ["CO"]}\n```'
    monkeypatch.setattr(crm_env.litellm, "completion", judge_replying(reply))
    evaluator = crm_env.Evaluator(model="judge", provider="openai")
    result = evaluator.evaluate(
        "The state with the quickest closures is Colorado (CO).",
        ["CO"],
        "exact_match",
        "best_region_identification",
        [],
    )
    assert result == {"parsed_answer": ["CO"], "reward": 1}


def test_bare_json_judge_reply_is_parsed(monkeypatch):
    reply = '{"extracted_answers": ["CO"]}'
    monkeypatch.setattr(crm_env.litellm, "completion", judge_replying(reply))
    evaluator = crm_env.Evaluator(model="judge", provider="openai")
    answer = "The state with the quickest closures is Colorado (CO)."
    assert evaluator.parse_answers(answer, "best_region_identification") == ["CO"]
