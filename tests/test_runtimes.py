"""The five runtimes: manifests, Pi packaging, the install doc and the Antigravity adapter."""

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import (
    REPO,
    Render,
    assert_fails_cleanly,
    describe,
    install_and_check,
    read_json,
    read_text,
    remove,
    run,
    run_ok,
    write_text,
)

# by default


@pytest.fixture(scope="module")
def repo(render: Render) -> Path:
    return render(
        {"repo_name": "demo-skills", "description": "Demo.", "github_owner": "acme", "keywords": "alpha, beta"}
    )


def test_generates_and_verifies_the_claude_code_and_codex_manifests(repo: Path) -> None:
    for path in [
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".codex-plugin/plugin.json",
        ".agents/plugins/marketplace.json",
    ]:
        data = read_json(repo / path)
        name = data.get("name")
        if name is None:
            name = (data.get("interface") or {}).get("displayName")
        assert name == "demo-skills", path
    install_and_check(repo)


def test_derives_the_pi_keyword_skills_entry_and_files_allowlist_from_the_skills_on_disk(repo: Path) -> None:
    pkg = read_json(repo / "package.json")
    assert pkg["keywords"] == ["alpha", "beta", "pi-package"]
    assert pkg["pi"]["skills"] == ["./skills/hello"]
    assert "skills/hello/SKILL.md" in pkg["files"], "the published files list the skill"
    assert "docs/installation.md" not in pkg["files"], "the published files exclude unrelated repository files"
    assert (repo / "skills/hello/SKILL.md").exists(), "the Pi skills path exists"
    assert pkg["scripts"]["check"].startswith("node scripts/check-repo.mjs"), "authored scripts survive the merge"
    assert pkg["devDependencies"].get("ai-rulez"), "authored devDependencies survive the merge"


def test_documents_all_five_runtimes_and_the_open_opencode_question(repo: Path) -> None:
    doc = read_text(repo / "docs/installation.md")
    assert re.search(r"claude plugin marketplace add acme/demo-skills", doc)
    assert re.search(r"codex plugin marketplace add", doc)
    assert re.search(r"\.agents/skills/", doc)
    # OpenCode deprecates the object form `skills: { paths: [...] }`.
    assert re.search(r'"skills": \["/absolute/path/to/demo-skills/skills"\]', doc)
    assert not re.search(r'"paths"', doc)
    assert re.search(r"published config schema", doc)
    assert re.search(r"Reading a clone is not an install", doc)
    assert re.search(r"Report the install as done only after the route's confirm step succeeds", doc)
    assert not re.search(r"or read a `SKILL\.md`", doc)
    # The manual route's confirm step must not be satisfiable by a clone alone.
    manual = next((line for line in doc.split("\n") if line.startswith("| Manual |")), None)
    assert manual is not None
    assert re.search(r"it is not an install", manual)
    assert not re.search(r"rev-parse", manual)
    assert re.search(r"pi install npm:demo-skills", doc)
    assert re.search(r"pi install git:github\.com/acme/demo-skills", doc)
    # The agent-facing page: a prompt, instructions for the reading agent and a
    # route table with install, update and confirm columns.
    assert re.search(
        r"Install the demo-skills skills: pick the best installation method for\n"
        r"you from https://github\.com/acme/demo-skills/blob/main/docs/installation\.md",
        doc,
    )
    assert re.search(r"^## For agents reading this page$", doc, re.M)
    assert re.search(r"^\| Runtime \| Install \| Update \| Confirm \|$", doc, re.M)
    for runtime in ["Claude Code", "Codex", "OpenCode", "Pi", "Antigravity", "Manual"]:
        assert re.search(rf"^\| {runtime} \|", doc, re.M), f"{runtime} row"
    assert not re.search(r"scoop", doc, re.I), "no text borrowed from another repo"
    assert re.search(r"five runtimes", doc)
    assert re.search(r"agy plugin install https://github\.com/acme/demo-skills", doc)
    assert re.search(r"> \*\*Unverified\.\*\* Installing from a Git URL has not been exercised", doc)
    # Confirm the installed plugin, not a clone: `agy plugin validate` checks a source directory.
    assert re.search(r"\| Antigravity \|[^\n]*`agy plugin list` shows the plugin as installed and enabled", doc)
    # Caveats that must survive: copied skills are verified, not just the
    # clone, and the Codex update route is flagged as unverified.
    # Per skill: a plain `diff -r` of the two directories would also report
    # destination-only skills that came from other sources.
    assert re.search(
        r'for d in <clone>/skills/\*/; do diff -r "\$d" "<destination>/\$\(basename "\$d"\)"; done` prints nothing',
        doc,
    )
    assert not re.search(r"`diff -r <clone>/skills <destination>`", doc)
    assert re.search(
        r"`marketplace upgrade` applies to Git marketplaces, not a local path; this update route has not been verified",
        doc,
    )
    # A bare `pi update` updates Pi itself; a package needs its source.
    assert re.search(r"`pi update npm:demo-skills`", doc)
    assert re.search(r"`pi update git:github\.com/acme/demo-skills`", doc)
    assert not re.search(r"`pi update`, then", doc)
    assert re.search(r"No npm route", doc)
    assert not re.search(r"Open question", doc)
    assert "{{" not in doc and "{%" not in doc, "no unrendered template syntax"


def test_ships_a_readme_skeleton_that_points_at_the_install_doc(repo: Path) -> None:
    readme = read_text(repo / "README.md")
    assert re.search(r"^# Demo Skills$", readme, re.M)
    assert re.search(r"docs/installation\.md", readme)
    assert re.search(
        r"\[!\[skills\.sh\]\(https://skills\.sh/b/[^/]+/demo-skills\)\]\(https://skills\.sh/[^/]+/demo-skills\)",
        readme,
    )


# the Antigravity adapter

ADAPTER = "plugin.json"
ADAPTER_DESCRIPTION = 'Skills "quoted" with \U0001f600 and a \\ backslash.'
ANTIGRAVITY_SCHEMA = "https://antigravity.google/schemas/v1/plugin.json"


@pytest.fixture(scope="module")
def adapter_repo(render: Render) -> Path:
    return render({"repo_name": "demo-skills", "description": ADAPTER_DESCRIPTION})


def check(directory: Path) -> subprocess.CompletedProcess:
    return run("node", "scripts/check-repo.mjs", cwd=directory)


def check_ok(directory: Path) -> None:
    result = check(directory)
    assert result.returncode == 0, describe(result)


def drift(repo: Path, change: Callable[[str], str], pattern: str) -> None:
    """Runs `change` on the adapter, expects the check to fail, then restores it."""
    original = read_text(repo / ADAPTER)
    try:
        write_text(repo / ADAPTER, change(original))
        assert_fails_cleanly(check(repo), pattern)
    finally:
        write_text(repo / ADAPTER, original)


def test_is_a_root_plugin_json_built_from_the_answers(adapter_repo: Path) -> None:
    assert read_json(adapter_repo / ADAPTER) == {
        "$schema": ANTIGRAVITY_SCHEMA,
        "name": "demo-skills",
        "description": ADAPTER_DESCRIPTION,
    }
    check_ok(adapter_repo)


def test_fails_the_check_when_the_description_drifts_from_the_generated_manifest(adapter_repo: Path) -> None:
    drift(
        adapter_repo,
        lambda text: text.replace("quoted", "changed", 1),
        r"plugin\.json: description .* does not match \.claude-plugin/plugin\.json",
    )


def test_fails_the_check_when_the_name_drifts(adapter_repo: Path) -> None:
    drift(
        adapter_repo,
        lambda text: text.replace('"demo-skills"', '"other-skills"', 1),
        r'plugin\.json: name "other-skills" does not match',
    )


def test_fails_the_check_when_the_adapter_file_is_missing(adapter_repo: Path) -> None:
    original = read_text(adapter_repo / ADAPTER)
    (adapter_repo / ADAPTER).unlink()
    try:
        assert_fails_cleanly(check(adapter_repo), r"plugin\.json: cannot read as JSON \(ENOENT\)")
    finally:
        write_text(adapter_repo / ADAPTER, original)


# host-loaded root components
#
# Both catalogs install the repository root, so a path Claude or Codex loads
# from an installed plugin by default would ship. ai-rulez reports these as
# AR9T0, but the template turns that rule off for the adapter above.

ROOT_FILES = [".mcp.json", ".app.json", ".lsp.json", "settings.json"]
ROOT_DIRECTORIES = ["hooks", "agents", "commands", "bin", "output-styles", "workflows", "themes", "monitors"]


def shipping(repo: Path, path: str, make: Callable[[Path], None]) -> None:
    """Creates `path` in the rendered repo, expects the check to name it, then removes it."""
    full = repo / path
    make(full)
    try:
        assert_fails_cleanly(check(repo), "root component: " + path.replace(".", "\\."))
    finally:
        remove(full)


@pytest.mark.parametrize("path", ROOT_FILES)
def test_fails_the_check_when_a_file_exists_at_the_root(adapter_repo: Path, path: str) -> None:
    shipping(adapter_repo, path, lambda full: write_text(full, "{}\n"))


@pytest.mark.parametrize("path", ROOT_DIRECTORIES)
def test_fails_the_check_when_a_directory_exists_at_the_root_even_empty(adapter_repo: Path, path: str) -> None:
    shipping(adapter_repo, path, lambda full: full.mkdir())


def test_fails_the_check_on_a_dangling_symlink_at_a_root_component_path(adapter_repo: Path) -> None:
    shipping(adapter_repo, "hooks", lambda full: full.symlink_to(full.parent / "no-such-target"))


def test_names_every_offending_path_in_one_run(adapter_repo: Path) -> None:
    write_text(adapter_repo / ".mcp.json", "{}\n")
    (adapter_repo / "hooks").mkdir()
    try:
        result = check(adapter_repo)
        assert result.returncode != 0, describe(result)
        assert re.search(r"root component: \.mcp\.json", result.stderr), result.stderr
        assert re.search(r"root component: hooks", result.stderr), result.stderr
    finally:
        remove(adapter_repo / ".mcp.json")
        remove(adapter_repo / "hooks")


# host-loaded root components: allowlist


def with_allowlist(repo: Path, content: str, body: Callable[[], None]) -> None:
    allowlist = repo / ".config" / "root-components.json"
    allowlist.parent.mkdir(parents=True, exist_ok=True)
    write_text(allowlist, content)
    (repo / "hooks").mkdir()
    try:
        body()
    finally:
        remove(repo / "hooks")
        remove(allowlist)


def test_passes_a_component_listed_with_a_reason(adapter_repo: Path) -> None:
    with_allowlist(adapter_repo, json.dumps({"hooks": "Claude SessionStart hook"}), lambda: check_ok(adapter_repo))


def test_still_fails_a_component_that_is_not_listed(adapter_repo: Path) -> None:
    with_allowlist(
        adapter_repo,
        json.dumps({"agents": "subagent"}),
        lambda: assert_fails_cleanly(check(adapter_repo), r"root component: hooks"),
    )


def test_rejects_an_empty_reason(adapter_repo: Path) -> None:
    with_allowlist(
        adapter_repo,
        json.dumps({"hooks": " "}),
        lambda: assert_fails_cleanly(check(adapter_repo), r"root-components\.json: hooks needs a non-empty reason"),
    )


def test_rejects_an_unknown_name(adapter_repo: Path) -> None:
    with_allowlist(
        adapter_repo,
        json.dumps({"hook": "typo"}),
        lambda: assert_fails_cleanly(check(adapter_repo), r'"hook" is not a root component'),
    )


def test_still_passes_with_the_adapter_and_the_generated_skills_at_the_root(adapter_repo: Path) -> None:
    check_ok(adapter_repo)


# CI runs this very command on the template repository, which has no
# generated output and therefore no adapter to compare.
def test_leaves_the_template_repositorys_own_check_passing() -> None:
    output = run_ok("node", "template/scripts/check-repo.mjs", cwd=REPO).stdout
    assert re.search(r"check-repo: \d+ workflow\(s\) ok", output)


# Valid JSON that is not an object must not slip past a truthiness guard.
@pytest.mark.parametrize("value", ["null", "false", "0", '""', "[]"])
def test_fails_the_check_when_the_adapter_is_not_an_object(adapter_repo: Path, value: str) -> None:
    drift(adapter_repo, lambda _text: f"{value}\n", r"plugin\.json: must be a JSON object")


# Codex adopts a root plugin.json that declares the portable schema as its
# manifest, so the check must hold the adapter to the Antigravity one.
@pytest.mark.parametrize(
    "schema",
    ["https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "", "https://example.com/other.json"],
    ids=json.dumps,
)
def test_fails_the_check_when_the_adapter_declares_another_schema(adapter_repo: Path, schema: str) -> None:
    drift(
        adapter_repo,
        lambda text: text.replace(ANTIGRAVITY_SCHEMA, schema, 1),
        r"plugin\.json: \$schema .* must be https://antigravity\.google/schemas/v1/plugin\.json",
    )


def test_fails_the_check_when_the_adapter_has_no_schema(adapter_repo: Path) -> None:
    drift(
        adapter_repo,
        lambda text: re.sub(r'\s*"\$schema": "[^"]*",', "", text, count=1),
        r"plugin\.json: \$schema undefined must be https://antigravity\.google/schemas/v1/plugin\.json",
    )


def test_fails_the_check_when_the_adapter_is_not_readable_json(adapter_repo: Path) -> None:
    drift(adapter_repo, lambda _text: "{ not json", r"plugin\.json: cannot read as JSON")


# runtimes, other answers


def test_keeps_the_pi_keyword_once_when_the_answer_already_has_it(render: Render) -> None:
    repo = render({"repo_name": "demo-skills", "description": "Demo.", "keywords": "pi-package, alpha"})
    assert read_json(repo / "package.json")["keywords"] == ["pi-package", "alpha"]


def test_offers_pi_from_git_only_when_not_publishing_to_npm(render: Render) -> None:
    doc = read_text(
        render({"repo_name": "demo-skills", "description": "Demo.", "publish_to_npm": False}) / "docs/installation.md"
    )
    assert not re.search(r"pi install npm:", doc)
    assert not re.search(r"pi update npm:", doc)
    assert re.search(r"`pi update git:", doc)
    assert re.search(r"pi install git:", doc)
