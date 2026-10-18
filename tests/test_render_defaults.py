import json
import re
from pathlib import Path

import pytest
from conftest import REPO, Render, install_and_check, read_json, read_text


def node_floor_covers(declared: str, needed: str) -> bool:
    """True when the lower bound of `declared` is at least that of `needed`, so the
    declared range admits no Node release the dependency rejects. Both are
    `>=x[.y[.z]]` ranges, compared on the complete version; anything else raises
    rather than passing silently."""

    def floor(range_: str) -> list[int]:
        match = re.fullmatch(r">=\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?", range_.strip())
        if not match:
            raise ValueError(f"unsupported Node range {json.dumps(range_)}: expected >=x[.y[.z]]")
        return [int(part or 0) for part in match.groups()]

    return floor(declared) >= floor(needed)


# rendered with default answers


@pytest.fixture(scope="module")
def repo(render: Render) -> Path:
    return render({"repo_name": "demo-skills", "description": "Demo skills for testing."})


def test_passes_its_own_check_with_no_generated_output_drift(repo: Path) -> None:
    install_and_check(repo)


def test_ships_the_placeholder_skill_under_its_default_name(repo: Path) -> None:
    assert (repo / ".ai-rulez/skills/hello/SKILL.md").exists()
    assert (repo / "skills/hello/SKILL.md").exists()


def test_derives_repository_url_marketplace_name_and_display_name_from_the_answers(repo: Path) -> None:
    plugin = read_json(repo / ".claude-plugin/plugin.json")
    assert plugin["name"] == "demo-skills"
    assert plugin["repository"] == "https://github.com/hasansezertasan/demo-skills"
    assert read_json(repo / ".claude-plugin/marketplace.json")["name"] == "demo-skills"
    assert read_json(repo / ".codex-plugin/plugin.json")["interface"]["displayName"] == "Demo Skills"


def test_declares_a_node_range_its_locked_dependencies_support(repo: Path) -> None:
    # `npm run generate` and `npm run check` run the locked ai-rulez binary, so
    # the advertised minimum must not be lower than the one ai-rulez needs.
    lock = read_json(repo / "package-lock.json")
    needed = lock["packages"]["node_modules/ai-rulez"]["engines"]["node"]
    declared = read_json(repo / "package.json")["engines"]["node"]
    assert node_floor_covers(declared, needed), (
        f"engines.node {declared} admits Node versions below ai-rulez's {needed}"
    )


def test_uses_package_json_as_the_version_source(repo: Path) -> None:
    pkg = read_json(repo / "package.json")
    assert pkg["version"] == "0.0.0"
    assert read_json(repo / ".claude-plugin/plugin.json")["version"] == pkg["version"]
    assert re.search(r"^5\.\d+\.\d+$", pkg["devDependencies"]["ai-rulez"])
    assert pkg["scripts"].get("check") and pkg["scripts"].get("generate")


def test_commits_an_answers_file_holding_exactly_the_agreed_questions(repo: Path) -> None:
    answers = read_text(repo / ".copier-answers.yml")
    keys = sorted(key for key in re.findall(r"^([a-z_]+):", answers, re.M) if not key.startswith("_"))
    assert keys == [
        "author_name",
        "author_url",
        "description",
        "github_owner",
        "keywords",
        "license",
        "placeholder_skill",
        "publish_to_npm",
        "repo_name",
    ]


# rendered with no answers at all


def test_takes_repo_name_from_the_destination_folder_and_passes_its_own_check(render: Render) -> None:
    repo = render({}, "bare-skills")
    assert read_json(repo / ".claude-plugin/plugin.json")["name"] == "bare-skills"
    assert len(read_json(repo / "package.json")["description"]) > 0
    install_and_check(repo)


# rendered with non-default answers

NON_DEFAULT_DESCRIPTION = 'Skills for widgets \U0001f600 with "quotes" and a \\ backslash.'


@pytest.fixture(scope="module")
def non_default(render: Render) -> Path:
    return render(
        {
            "repo_name": "acme-widget-skills",
            "description": NON_DEFAULT_DESCRIPTION,
            "placeholder_skill": "widget-check",
            "github_owner": "acme",
            "author_name": "Acme Dev",
            "author_url": "https://github.com/acme-dev",
        }
    )


def test_names_the_placeholder_skill_from_the_answer_and_still_passes_check(non_default: Path) -> None:
    assert (non_default / "skills/widget-check/SKILL.md").exists()
    assert not (non_default / "skills/hello").exists()
    install_and_check(non_default)


def test_threads_owner_and_author_answers_into_the_manifests(non_default: Path) -> None:
    plugin = read_json(non_default / ".claude-plugin/plugin.json")
    assert plugin["repository"] == "https://github.com/acme/acme-widget-skills"
    assert plugin["description"] == NON_DEFAULT_DESCRIPTION
    assert read_json(non_default / "package.json")["description"] == plugin["description"]
    assert plugin["author"] == {"name": "Acme Dev", "url": "https://github.com/acme-dev"}


# renovate


def test_renovate_extends_the_shared_preset_with_no_custom_manager(render: Render) -> None:
    repo = render({"repo_name": "demo-skills", "description": "Demo."})
    config = read_json(repo / ".github/renovate.json")
    assert config["extends"] == ["local>hasansezertasan/renovate-config"]
    assert "customManagers" not in config


def test_compares_the_complete_node_floor_not_just_the_major() -> None:
    assert node_floor_covers(">=22", ">=22.0.0") is True
    assert node_floor_covers(">=22.12", ">=22.0.0") is True
    assert node_floor_covers(">=24", ">=22.5.0") is True
    assert node_floor_covers(">=22", ">=22.5.0") is False, "a minor bump in the dependency must be noticed"
    assert node_floor_covers(">=22.5", ">=22.5.1") is False, "a patch bump must be noticed"
    assert node_floor_covers(">=20", ">=22.0.0") is False
    with pytest.raises(ValueError, match="unsupported Node range"):
        node_floor_covers("^22", ">=22.0.0")


def test_the_template_stores_no_generated_output() -> None:
    generated = {"skills", ".claude-plugin", ".codex-plugin", ".agents", "AGENTS.md"}
    root = REPO / "template"
    found = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.relative_to(root).parts[0] in generated]
    assert found == []
