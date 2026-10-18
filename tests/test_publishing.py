"""Release and docs with publish_to_npm on (the default) and off."""

import re
import subprocess
from pathlib import Path

import pytest
from conftest import REPO, Render, assert_fails_cleanly, describe, read_json, read_text, run, write_text


@pytest.fixture(scope="module")
def published(render: Render) -> Path:
    return render({"repo_name": "demo-skills", "description": "Demo."})


@pytest.fixture(scope="module")
def private(render: Render) -> Path:
    return render({"repo_name": "demo-skills", "description": "Demo.", "publish_to_npm": False})


def run_in(repo: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return run("node", f"scripts/{script}", *args, cwd=repo)


def run_in_ok(repo: Path, script: str, *args: str) -> None:
    result = run_in(repo, script, *args)
    assert result.returncode == 0, describe(result)


def release_workflow(repo: Path) -> str:
    return read_text(repo / ".github/workflows/release.yml")


# release: publishing to npm (the default)


def test_lets_release_please_own_the_version_changelog_and_manifest(published: Path) -> None:
    assert read_json(published / ".release-please-manifest.json") == {".": "0.0.0"}
    assert not (published / "CHANGELOG.md").exists(), "release-please creates the changelog itself"
    root_config = read_json(published / "release-please-config.json")
    config = root_config["packages"]["."]
    assert config["release-type"] == "node"
    # Without a release tag release-please starts at 1.0.0 whatever the seeded
    # manifest says; `initial-version` is what makes the first release 0.1.0.
    assert config["initial-version"] == "0.1.0"
    # Tags are plain `vX.Y.Z`. With the default, release-please adds the package
    # name to the tag, no longer matches an earlier `v0.3.0`, and cannot find the
    # last release (scoop-bucket-skills tagged `scoop-bucket-skills-v0.2.0`).
    assert config["include-component-in-tag"] is False
    assert root_config["bump-minor-pre-major"] is True
    # The default grouped title omits the version, so release-please cannot
    # recognise the merged release PR and silently creates no tag
    # (googleapis/release-please#2712).
    assert re.search(r"\$\{version\}", root_config["group-pull-request-title-pattern"])
    assert sorted(file["path"] for file in config["extra-files"]) == [
        ".claude-plugin/marketplace.json",
        ".claude-plugin/plugin.json",
        ".codex-plugin/plugin.json",
    ]


def test_has_a_publish_job_with_trusted_publishing_and_provenance(published: Path) -> None:
    workflow = release_workflow(published)
    assert re.search(r"^  publish:$", workflow, re.M)
    assert re.search(r"id-token: write", workflow)
    assert re.search(r"npm publish --provenance", workflow)
    assert re.search(r"release-guard\.mjs --publish", workflow)
    assert re.search(r"issues: write", workflow)


def test_keeps_the_release_workflow_within_the_hardened_ci_rules(published: Path) -> None:
    run_in_ok(published, "check-repo.mjs")


def test_passes_its_own_release_guard(published: Path) -> None:
    run_in_ok(published, "release-guard.mjs", "--publish")


def test_stops_the_release_when_a_plugin_manifest_drifts_from_package_json(published: Path) -> None:
    path = published / ".codex-plugin/plugin.json"
    original = read_text(path)
    write_text(path, original.replace('"version": "0.0.0"', '"version": "9.9.9"', 1))
    try:
        assert_fails_cleanly(
            run_in(published, "release-guard.mjs", "--publish"), r'\.codex-plugin/plugin\.json: version "9\.9\.9"'
        )
    finally:
        write_text(path, original)


def test_stops_the_release_when_a_publishing_repo_is_private(published: Path) -> None:
    assert_fails_cleanly(run_in(published, "release-guard.mjs", "--private"), r'must be "private": true')


def test_rejects_a_missing_or_unknown_mode(published: Path) -> None:
    assert_fails_cleanly(run_in(published, "release-guard.mjs"), r"usage")
    assert_fails_cleanly(run_in(published, "release-guard.mjs", "--bogus"), r"usage")


# release: not publishing to npm


def test_has_no_publish_job_no_provenance_and_no_id_token_permission(private: Path) -> None:
    workflow = release_workflow(private)
    assert not re.search(r"^  publish:$", workflow, re.M)
    assert not re.search(r"provenance|id-token|npm publish", workflow)
    assert re.search(r"release-guard\.mjs --private", workflow)


def test_is_private_keeps_the_release_workflow_hardened_and_passes_its_guard(private: Path) -> None:
    assert read_json(private / "package.json")["private"] is True
    run_in_ok(private, "check-repo.mjs")
    run_in_ok(private, "release-guard.mjs", "--private")


def test_stops_the_release_when_the_package_is_not_private(private: Path) -> None:
    assert_fails_cleanly(
        run_in(private, "release-guard.mjs", "--publish"), r'"private": true, but the repo publishes'
    )


# publish_to_npm


def test_is_publishable_by_default(published: Path) -> None:
    assert "private" not in read_json(published / "package.json")


def test_marks_the_package_private_when_turned_off(private: Path) -> None:
    assert read_json(private / "package.json")["private"] is True


# contributing doc


def test_carries_the_setup_checklist_layouts_and_conventions_with_npm_setup_when_publishing(
    render: Render,
) -> None:
    doc = read_text(
        render({"repo_name": "demo-skills", "description": "Demo.", "github_owner": "acme"}) / "CONTRIBUTING.md"
    )
    assert re.search(r"^# Contributing to Demo Skills$", doc, re.M)
    assert re.search(r"create and approve pull requests", doc)
    assert re.search(r"`check` status check", doc)
    assert re.search(r"close and reopen", doc, re.I)
    assert re.search(r"after each update", doc)
    assert re.search(r"Publish the `0\.0\.0` placeholder once by hand", doc)
    assert re.search(r"trusted publisher: .*owner `acme`, repository `demo-skills`, workflow `release\.yml`", doc)
    assert re.search(r"references/", doc)
    assert re.search(r"evals/", doc)
    assert re.search(r"Conventional Commits", doc)
    assert "{{" not in doc and "{%" not in doc, "no unrendered template syntax"


def test_drops_the_npm_step_when_not_publishing(private: Path) -> None:
    doc = read_text(private / "CONTRIBUTING.md")
    assert not re.search(r"trusted publisher", doc, re.I)
    assert re.search(r"no npm setup is needed", doc)
    assert re.search(r"nothing is published to a registry", doc)
    assert not re.search(r"publishes the package to npm|failed `publish` job", doc)


def test_is_template_owned_copier_update_is_free_to_merge_it() -> None:
    assert not re.search(r"CONTRIBUTING", read_text(REPO / "copier.yml"))
