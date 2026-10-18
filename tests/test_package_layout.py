import json

import pytest
from conftest import Render, read_text

# `copier update` three-way merges package.json, so a fresh render must
# already have the layout `npm run generate` leaves, or every template edit
# to the file conflicts with the committed, generated one.
ANSWERS = [
    {"keywords": "beta, alpha"},
    {"keywords": "pi-package, alpha"},
    {"publish_to_npm": False},
    # Characters tojson would escape and ai-rulez writes literally.
    {
        "description": 'Rock & roll <b> "quoted" back\\slash é \U0001f600',
        "author_name": "A & B \U0001f600",
        "keywords": "r&b, \U0001f600",
    },
]


@pytest.mark.parametrize("answers", ANSWERS, ids=[json.dumps(answers) for answers in ANSWERS])
def test_is_unchanged_by_generation(render: Render, answers: dict) -> None:
    data = {"repo_name": "demo-skills", "description": "Demo.", **answers}
    un_generated = read_text(render(data, "demo-skills", generate=False) / "package.json")
    generated = read_text(render(data, "demo-skills") / "package.json")
    assert un_generated == generated
