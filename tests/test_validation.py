"""Answers Copier's own prompt-time validation must reject."""

from typing import Any

import pytest
from conftest import render_copy


@pytest.fixture
def assert_rejected(tmp_path_factory: pytest.TempPathFactory):
    """Rejects at the copy, before any generate step runs, so only Copier's own
    prompt-time validation can reject the answers, and checks that the rejection
    names the expected question."""

    def _assert_rejected(question: str, overrides: dict[str, Any]) -> None:
        answers = {"repo_name": "demo-skills", "description": "Demo.", **overrides}
        result, _ = render_copy(tmp_path_factory, answers)
        assert result.returncode != 0, "the answers were accepted"
        assert f"Validation error for question '{question}'" in result.stderr, result.stderr

    return _assert_rejected


@pytest.mark.parametrize("question", ["description", "author_name", "author_url"])
@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "whitespace-only"])
def test_blank_answer_is_rejected(assert_rejected, question: str, value: str) -> None:
    assert_rejected(question, {question: value})


@pytest.mark.parametrize("question", ["description", "author_name", "author_url", "keywords"])
@pytest.mark.parametrize(
    "value", ["bad\u001bvalue", "bad\bvalue", "bad\nvalue"], ids=["escape", "backspace", "newline"]
)
def test_answer_containing_a_control_character_is_rejected(assert_rejected, question: str, value: str) -> None:
    assert_rejected(question, {question: value})


NAME_64 = "a" * 64


@pytest.mark.parametrize(
    ("question", "value"),
    [
        ("repo_name", f"{NAME_64}b"),
        ("repo_name", "Demo_Skills"),
        ("placeholder_skill", f"{NAME_64}b"),
        ("placeholder_skill", "Hello World"),
    ],
    ids=["repo_name-too-long", "repo_name-Demo_Skills", "placeholder_skill-too-long", "placeholder_skill-Hello-World"],
)
def test_name_is_rejected(assert_rejected, question: str, value: str) -> None:
    assert_rejected(question, {question: value})


@pytest.mark.parametrize(
    "github_owner",
    ['bad"owner', "acme--tools", "-acme", "acme-", "a" * 40],
    ids=["quote", "double-hyphen", "leading-hyphen", "trailing-hyphen", "too-long"],
)
def test_github_owner_is_rejected(assert_rejected, github_owner: str) -> None:
    assert_rejected("github_owner", {"github_owner": github_owner})
