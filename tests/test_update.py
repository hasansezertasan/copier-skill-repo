"""`copier update` from one tagged template state to the next."""

import json
import re
import shutil
from pathlib import Path

import pytest
from conftest import copier, describe, git_ok, read_json, read_text, template_source, write_text

CONFLICT = re.compile(r"<<<<<<<|>>>>>>>")


def edit(directory: Path, path: str, old: str, new: str) -> None:
    before = read_text(directory / path)
    assert old in before, f"{path} lacks {json.dumps(old)}"
    write_text(directory / path, before.replace(old, new, 1))


def copier_ok(*args: str, cwd: Path) -> None:
    result = copier(*args, "--defaults", cwd=cwd)
    assert result.returncode == 0, f"copier {args[0]} failed: {describe(result)}"


@pytest.fixture(scope="module")
def updated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """`repo` carries local edits; `gone` replaced and deleted the placeholder skill."""
    # The earlier template state: a git repo of the working tree, tagged.
    source = template_source(tmp_path_factory)
    git_ok("init", "-q", "-b", "main", cwd=source)
    git_ok("add", "-A", cwd=source)
    git_ok("commit", "-q", "-m", "earlier state", cwd=source)
    git_ok("tag", "v1.0.0", cwd=source)

    repo = tmp_path_factory.mktemp("copier-skill-repo-") / "demo-skills"
    data_file = tmp_path_factory.mktemp("copier-skill-repo-") / "answers.json"
    write_text(data_file, json.dumps({"repo_name": "demo-skills", "description": "Demo."}))
    gone = tmp_path_factory.mktemp("copier-skill-repo-") / "demo-skills"
    for dest in [repo, gone]:
        copier_ok("copy", "--vcs-ref", "v1.0.0", "--data-file", str(data_file), str(source), str(dest), cwd=source)
        git_ok("init", "-q", "-b", "main", cwd=dest)
        git_ok("add", "-A", cwd=dest)
        git_ok("commit", "-q", "-m", "chore: generate", cwd=dest)

    # A second repo replaced the placeholder with its own skill and deleted it.
    shutil.rmtree(gone / ".ai-rulez/skills/hello")
    (gone / ".ai-rulez/skills/real").mkdir(parents=True)
    write_text(gone / ".ai-rulez/skills/real/SKILL.md", "---\nname: real\ndescription: Real.\n---\n")
    git_ok("add", "-A", cwd=gone)
    git_ok("commit", "-q", "-m", "chore: replace placeholder", cwd=gone)

    # Local edits: repo-owned files, and a local edit inside template-owned ones.
    write_text(repo / "README.md", "# My own README\n")
    skill = repo / ".ai-rulez/skills/hello/SKILL.md"
    write_text(skill, f"{read_text(skill)}\nLocal addition.\n")
    (repo / ".ai-rulez/skills/real").mkdir(parents=True)
    write_text(repo / ".ai-rulez/skills/real/SKILL.md", "---\nname: real\ndescription: Real.\n---\n")
    write_text(repo / "CHANGELOG.md", "# Changelog\n\n## 0.3.0\n")
    write_text(repo / ".release-please-manifest.json", '{ ".": "0.3.0" }\n')
    edit(repo, "package.json", '"version": "0.0.0"', '"version": "0.3.0"')
    edit(
        repo,
        "CONTRIBUTING.md",
        "- Node comes from `.node-version`.",
        "- Node comes from `.node-version`.\n- Local rule: ask before merging.",
    )
    git_ok("add", "-A", cwd=repo)
    git_ok("commit", "-q", "-m", "chore: local edits", cwd=repo)

    # The template moves on: it changes template-owned and repo-owned files alike.
    edit(
        source,
        "template/CONTRIBUTING.md.jinja",
        "## Commits and pull requests",
        "## Commits and pull requests\n\n> Template note.",
    )
    edit(source, "template/package.json.jinja", '"node": ">=22"', '"node": ">=24"')
    edit(source, "template/package.json.jinja", '"ai-rulez": "5.3.0"', '"ai-rulez": "5.4.0"')
    edit(
        source,
        "template/.ai-rulez/skills/{{ placeholder_skill }}/SKILL.md.jinja",
        "Placeholder skill",
        "Template placeholder",
    )
    edit(source, "template/.release-please-manifest.json", '"0.0.0"', '"0.0.1"')
    git_ok("add", "-A", cwd=source)
    git_ok("commit", "-q", "-m", "later state", cwd=source)
    git_ok("tag", "v1.1.0", cwd=source)

    for dest in [repo, gone]:
        copier_ok("update", "--vcs-ref", "v1.1.0", cwd=dest)
    return repo, gone


def test_leaves_repo_owned_files_untouched(updated: tuple[Path, Path]) -> None:
    repo, gone = updated
    assert read_text(repo / "README.md") == "# My own README\n"
    assert (repo / ".ai-rulez/skills/real/SKILL.md").exists()
    assert (gone / ".ai-rulez/skills/real/SKILL.md").exists()
    assert read_text(repo / "CHANGELOG.md") == "# Changelog\n\n## 0.3.0\n"
    assert read_json(repo / ".release-please-manifest.json") == {".": "0.3.0"}
    assert read_json(repo / "package.json")["version"] == "0.3.0"


def test_does_not_bring_back_a_placeholder_skill_the_repo_deleted(updated: tuple[Path, Path]) -> None:
    _, gone = updated
    assert not (gone / ".ai-rulez/skills/hello").exists()


def test_merges_a_template_change_to_the_placeholder_beside_a_local_addition(updated: tuple[Path, Path]) -> None:
    repo, _ = updated
    skill = read_text(repo / ".ai-rulez/skills/hello/SKILL.md")
    assert re.search(r"Template placeholder", skill)
    assert re.search(r"Local addition\.", skill)
    assert not CONFLICT.search(skill), "no conflict markers"


def test_merges_template_changes_into_template_owned_files_and_keeps_local_edits(
    updated: tuple[Path, Path],
) -> None:
    repo, _ = updated
    contributing = read_text(repo / "CONTRIBUTING.md")
    assert re.search(r"Template note\.", contributing)
    assert re.search(r"Local rule: ask before merging\.", contributing)
    pkg = read_json(repo / "package.json")
    assert pkg["engines"]["node"] == ">=24"
    assert pkg["devDependencies"]["ai-rulez"] == "5.4.0"
    assert not CONFLICT.search(read_text(repo / "package.json")), "no conflict markers in package.json"
    assert not CONFLICT.search(contributing), "no conflict markers"


def test_moves_the_answers_file_to_the_new_template_version(updated: tuple[Path, Path]) -> None:
    repo, _ = updated
    assert re.search(r"_commit: v1\.1\.0", read_text(repo / ".copier-answers.yml"))


def test_tells_the_user_to_generate_after_a_copy_and_after_an_update(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Without `_tasks`, the messages are the only prompt to build the generated
    output. Copier prints `_message_after_copy` on copy and `_message_after_update`
    on update (to stderr when piped), so a template missing either leaves one path
    silent."""
    source = template_source(tmp_path_factory)
    git_ok("init", "-q", "-b", "main", cwd=source)
    git_ok("add", "-A", cwd=source)
    git_ok("commit", "-q", "-m", "earlier state", cwd=source)
    git_ok("tag", "v1.0.0", cwd=source)

    dest = tmp_path_factory.mktemp("copier-skill-repo-") / "demo-skills"
    data_file = tmp_path_factory.mktemp("copier-skill-repo-") / "answers.json"
    write_text(data_file, json.dumps({"repo_name": "demo-skills", "description": "Demo."}))
    copied = copier("copy", "--defaults", "--vcs-ref", "v1.0.0", "--data-file", str(data_file), str(source), str(dest), cwd=source)
    assert copied.returncode == 0, describe(copied)
    assert "npm install && npm run generate" in copied.stdout + copied.stderr, describe(copied)

    git_ok("init", "-q", "-b", "main", cwd=dest)
    git_ok("add", "-A", cwd=dest)
    git_ok("commit", "-q", "-m", "chore: generate", cwd=dest)
    git_ok("commit", "-q", "--allow-empty", "-m", "later state", cwd=source)
    git_ok("tag", "v1.0.1", cwd=source)

    updated = copier("update", "--defaults", "--skip-answered", cwd=dest)
    assert updated.returncode == 0, describe(updated)
    assert "npm install && npm run generate" in updated.stdout + updated.stderr, describe(updated)
