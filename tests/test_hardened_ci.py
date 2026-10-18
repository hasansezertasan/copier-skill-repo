"""The rendered repo's hardened CI, judged through `node scripts/check-repo.mjs`."""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import (
    Render,
    assert_fails_cleanly,
    describe,
    read_text,
    run,
    run_ok,
    write_text,
)

Transform = Callable[[str], str]
Pattern = re.Pattern[str] | str | None

CHECK_FILE = ".github/workflows/check.yml"

NOT_PINNED = re.compile(r"not pinned by commit SHA")
FLOW = re.compile(r"flow style is not supported")
UNSUPPORTED = re.compile(
    r"anchors, aliases and tags are not supported|unsupported line|unexpected sequence item|nested block"
)
UNSCOPED = re.compile(r"unscoped permissions")
SHA = "a" * 40
CHECKOUT = re.compile(r"- uses: actions/checkout@[0-9a-f]{40}")
JOB_PERMISSIONS = re.compile(r"^ {4}permissions:\n {6}contents: read$", re.M)
TOP_PERMISSIONS = re.compile(r"^permissions: \{\}$", re.M)
STEPS_TO_END = re.compile(r" {4}steps:\n[\s\S]*\Z")


@pytest.fixture(scope="module")
def repo(render: Render) -> Path:
    repo = render({"repo_name": "demo-skills", "description": "Demo."})
    run_ok("npm", "ci", cwd=repo)
    return repo


def workflow(repo: Path) -> str:
    return read_text(repo / CHECK_FILE)


def run_repo_check(repo: Path) -> subprocess.CompletedProcess:
    return run("node", "scripts/check-repo.mjs", cwd=repo)


def check_repo(repo: Path, files: dict[str, str], pattern: Pattern) -> None:
    """Runs the repository check with `files` written into the rendered repo
    (path -> content), then restores it. `pattern=None` expects the check to pass."""
    originals: dict[Path, str | None] = {}
    for path, content in files.items():
        full = repo / path
        originals[full] = read_text(full) if full.exists() else None
        full.parent.mkdir(parents=True, exist_ok=True)
        write_text(full, content)
    try:
        result = run_repo_check(repo)
        if pattern:
            assert_fails_cleanly(result, pattern)
        else:
            assert result.returncode == 0, describe(result)
    finally:
        for full, original in originals.items():
            if original is None:
                full.unlink(missing_ok=True)
            else:
                write_text(full, original)


def mutate(repo: Path, transform: Transform, pattern: Pattern) -> None:
    """Mutates the rendered check workflow; the mutation must change it."""
    original = workflow(repo)
    mutated = transform(original)
    assert mutated != original, "the mutation did not change the workflow"
    check_repo(repo, {CHECK_FILE: mutated}, pattern)


# JavaScript's String.replace replaces the first match only, with a literal
# replacement; these keep that meaning.
def sub1(pattern: re.Pattern[str], replacement: str) -> Transform:
    return lambda text: pattern.sub(lambda _match: replacement, text, count=1)


def replace1(old: str, new: str) -> Transform:
    return lambda text: text.replace(old, new, 1)


def with_checkout(replacement: str) -> Transform:
    return sub1(CHECKOUT, replacement)


def with_job_permissions(replacement: str) -> Transform:
    return sub1(JOB_PERMISSIONS, replacement)


def with_step(step: str) -> Transform:
    return replace1("      - run: npm ci\n", "      - run: npm ci\n" + step)


def with_job(job: str) -> Transform:
    return sub1(re.compile(r"^jobs:\n", re.M), "jobs:\n" + job)


def reusable_job(ref: str) -> Transform:
    return with_job("  extra:\n    permissions: {}\n    uses: " + ref + "\n")


def then(*transforms: Transform) -> Transform:
    def apply(text: str) -> str:
        for transform in transforms:
            text = transform(text)
        return text

    return apply


def rejects(label: str, transform: Transform, pattern: Pattern) -> object:
    return pytest.param(transform, pattern, id=f"rejects {label}")


def accepts(label: str, transform: Transform) -> object:
    return pytest.param(transform, id=f"accepts {label}")


# the rendered workflow


def test_pins_every_action_reference_by_commit_sha(repo: Path) -> None:
    uses = re.findall(r"^\s*(?:-\s*)?uses:\s*(\S+)", workflow(repo), re.M)
    assert len(uses) > 0
    for ref in uses:
        assert re.search(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$", ref), ref


def test_denies_permissions_at_the_top_level_and_scopes_them_per_job(repo: Path) -> None:
    assert TOP_PERMISSIONS.search(workflow(repo))
    assert JOB_PERMISSIONS.search(workflow(repo))


def test_runs_unfiltered_and_is_callable_from_another_workflow(repo: Path) -> None:
    text = workflow(repo)
    assert re.search(r"^ {2}workflow_call:", text, re.M)
    assert re.search(r"^ {2}pull_request:", text, re.M)
    # A `push` trigger would run every job twice per pull-request commit, and
    # again on `main`, where release.yml already calls this workflow.
    assert not re.search(r"^ {2}push:", text, re.M)
    assert not re.search(r"^\s*(paths|paths-ignore|branches|branches-ignore|tags):", text, re.M)


def test_runs_the_repositorys_own_check(repo: Path) -> None:
    assert re.search(r"run: npm run check$", workflow(repo), re.M)
    assert re.search(r"run: npm ci$", workflow(repo), re.M)


def test_fails_when_generated_output_is_stale(repo: Path) -> None:
    file = repo / "skills/hello/SKILL.md"
    original = read_text(file)
    write_text(file, f"{original}\nhand edit\n")
    try:
        result = run("npm", "run", "check", cwd=repo)
        assert result.returncode != 0, describe(result)
        assert re.search(r"drift|out of date|stale|differ|generate", result.stderr + result.stdout, re.I)
    finally:
        write_text(file, original)


def test_has_a_repository_check_with_no_dependencies(repo: Path) -> None:
    script = read_text(repo / "scripts/check-repo.mjs")
    for specifier in re.findall(r"""(?:\bfrom|\bimport\s*\(?|\brequire\()\s*["']([^"']+)["']""", script):
        assert re.search(r"^node:", specifier), specifier


def test_passes_its_own_check(repo: Path) -> None:
    result = run_repo_check(repo)
    assert result.returncode == 0, describe(result)


# action pinning

ACTION_PINNING_REJECTS = [
    rejects("an unpinned step", with_checkout("- uses: actions/checkout@v4"), NOT_PINNED),
    rejects(
        "an unpinned step behind other keys",
        with_checkout("- name: checkout\n        uses: actions/checkout@v4"),
        NOT_PINNED,
    ),
    rejects(
        "an unpinned step after a short first key",
        with_checkout("- env:\n          X: y\n        uses: actions/checkout@v4"),
        NOT_PINNED,
    ),
    rejects(
        "an unpinned step after a with: first key",
        with_checkout("- with:\n          a: b\n        uses: actions/checkout@v4"),
        NOT_PINNED,
    ),
    rejects(
        "an unpinned step after a folded first key",
        with_checkout("- name: >-\n          Check out\n        uses: actions/checkout@v4"),
        NOT_PINNED,
    ),
    rejects(
        "an unpinned step after a literal first key",
        with_checkout("- if: |\n          true\n        uses: actions/checkout@v4"),
        NOT_PINNED,
    ),
    rejects(
        "an unpinned step whose dash is on its own line",
        with_checkout("-\n        uses: actions/checkout@v4"),
        NOT_PINNED,
    ),
    rejects("an unpinned step with a quoted uses key", with_checkout('- "uses": actions/checkout@v4'), NOT_PINNED),
    rejects(
        "an unpinned step under a quoted steps key",
        then(replace1("    steps:\n", '    "steps":\n'), with_checkout("- uses: actions/checkout@v4")),
        NOT_PINNED,
    ),
    rejects("a uses value on the next line", with_checkout("- uses:\n          actions/checkout@v4"), UNSUPPORTED),
    rejects(
        "a docker image ending in 40 hex characters",
        with_checkout(f"- uses: docker://evil/img:latest@{SHA}"),
        NOT_PINNED,
    ),
    rejects(
        "a docker image with a short digest",
        with_checkout("- uses: docker://alpine@sha256:" + "b" * 63),
        NOT_PINNED,
    ),
    rejects("a reference with a second @ revision", with_checkout(f"- uses: actions/checkout@v4@{SHA}"), NOT_PINNED),
    rejects(
        "an unpinned reusable workflow on a job",
        reusable_job("owner/repo/.github/workflows/build.yml@v1"),
        NOT_PINNED,
    ),
    rejects(
        "an unpinned reusable workflow behind a quoted key",
        with_job('  extra:\n    permissions: {}\n    "uses": owner/repo/.github/workflows/b.yml@v1\n'),
        NOT_PINNED,
    ),
    rejects("an empty uses value", with_checkout("- uses:"), r"`uses:` has no value|unsupported|nested block"),
]

ACTION_PINNING_ACCEPTS = [
    accepts("a pinned reusable workflow on a job", reusable_job(f"owner/repo/.github/workflows/build.yml@{SHA}")),
    accepts("a local reusable workflow on a job", reusable_job("./.github/workflows/build.yml")),
    accepts("a local action", with_checkout("- uses: ./.github/actions/setup")),
    accepts("a quoted pinned reference", with_checkout(f'- uses: "actions/checkout@{SHA}"')),
    accepts("a pinned docker image", with_checkout("- uses: docker://alpine@sha256:" + "c" * 64)),
    accepts("a pinned reference followed by a comment", with_checkout(f"- uses: actions/checkout@{SHA} # v4")),
    accepts("a uses key that is not a step key", with_step("        env:\n          uses: harmless\n")),
    accepts(
        "a uses key in a matrix entry",
        replace1(
            "    steps:\n",
            "    strategy:\n      matrix:\n        include:\n          - os: ubuntu-latest\n"
            "            uses: ordinary\n    steps:\n",
        ),
    ),
    accepts(
        "uses text inside a run block",
        with_step("      - run: |-\n          echo uses: actions/checkout@v4\n          - uses: actions/checkout@v4\n"),
    ),
    accepts("uses text inside a single-line run command", with_step('      - run: echo "uses: actions/checkout@v4"\n')),
    accepts("a commented-out step", with_step("      # - uses: actions/checkout@v4\n")),
]


@pytest.mark.parametrize(("transform", "pattern"), ACTION_PINNING_REJECTS)
def test_action_pinning_rejects(repo: Path, transform: Transform, pattern: Pattern) -> None:
    mutate(repo, transform, pattern)


@pytest.mark.parametrize("transform", ACTION_PINNING_ACCEPTS)
def test_action_pinning_accepts(repo: Path, transform: Transform) -> None:
    mutate(repo, transform, None)


def test_rejects_an_unpinned_step_in_a_local_composite_action(repo: Path) -> None:
    check_repo(
        repo,
        {
            ".github/actions/setup/action.yml": (
                "name: setup\nruns:\n  using: composite\n  steps:\n    - uses: actions/checkout@v4\n"
            )
        },
        NOT_PINNED,
    )


def test_accepts_a_pinned_step_in_a_local_composite_action(repo: Path) -> None:
    check_repo(
        repo,
        {
            ".github/actions/setup/action.yml": (
                f"name: setup\nruns:\n  using: composite\n  steps:\n    - uses: actions/checkout@{SHA}\n"
            )
        },
        None,
    )


def test_ignores_yaml_under_github_actions_that_is_not_an_action(repo: Path) -> None:
    check_repo(repo, {".github/actions/setup/fixtures/data.yml": "steps:\n  - uses: actions/checkout@v4\n"}, None)


def test_scans_a_workflow_in_a_nested_directory_and_with_the_yaml_extension(repo: Path) -> None:
    check_repo(
        repo,
        {
            ".github/workflows/nested/extra.yaml": (
                "permissions: {}\njobs:\n  a:\n    permissions: {}\n    steps:\n      - uses: actions/checkout@v4\n"
            )
        },
        NOT_PINNED,
    )


# permissions

TOP_LEVEL_REQUIRED = r"top-level `permissions: \{\}` is required"

PERMISSIONS_REJECTS = [
    rejects("missing top-level permissions", sub1(re.compile(r"^permissions: \{\}\n", re.M), ""), TOP_LEVEL_REQUIRED),
    rejects("a top-level write-all", sub1(TOP_PERMISSIONS, "permissions: write-all"), TOP_LEVEL_REQUIRED),
    rejects(
        "a top-level block of scopes", sub1(TOP_PERMISSIONS, "permissions:\n  contents: read"), TOP_LEVEL_REQUIRED
    ),
    rejects(
        "a job without permissions",
        with_job("  extra:\n    runs-on: ubuntu-latest\n    steps: []\n"),
        r"job `extra` has no permissions block",
    ),
    rejects(
        "a quoted job id without permissions",
        with_job('  "extra":\n    runs-on: ubuntu-latest\n    steps: []\n'),
        r"job `extra` has no permissions block",
    ),
    rejects(
        "a last job without permissions",
        lambda t: t.rstrip() + "\n  last:\n    runs-on: ubuntu-latest\n    steps: []\n",
        r"job `last` has no permissions block",
    ),
    rejects(
        "a middle job without permissions",
        lambda t: t.rstrip()
        + "\n  middle:\n    runs-on: ubuntu-latest\n    steps: []\n  tail:\n    permissions: {}\n    steps: []\n",
        r"job `middle` has no permissions block",
    ),
    *[
        rejects(f"job permissions set to {label}", with_job_permissions("    permissions: " + value), UNSCOPED)
        for label, value in [
            ("write-all", "write-all"),
            ("quoted write-all", '"write-all"'),
            ("read-all", "read-all"),
            ("an expression", "${{ inputs.permissions }}"),
            ("write-all with a trailing comment", "write-all # why not"),
        ]
    ],
    rejects("an empty permissions block", with_job_permissions("    permissions:"), UNSCOPED),
    rejects(
        "a permission level that is not read, write or none",
        with_job_permissions("    permissions:\n      contents: admin"),
        UNSCOPED,
    ),
    rejects(
        "a valid scope next to an invalid one",
        with_job_permissions("    permissions:\n      contents: read\n      id-token: admin"),
        UNSCOPED,
    ),
    rejects("an inline permissions mapping", with_job_permissions("    permissions: { contents: read }"), FLOW),
]

PERMISSIONS_ACCEPTS = [
    accepts("an empty permissions mapping", with_job_permissions("    permissions: {}")),
    accepts("an empty permissions mapping with a space", with_job_permissions("    permissions: { }")),
    accepts("a top-level empty mapping with a space", sub1(TOP_PERMISSIONS, "permissions: { }")),
    accepts(
        "a block of several scopes",
        with_job_permissions("    permissions:\n      contents: read\n      id-token: write # publish"),
    ),
    accepts(
        "quoted permission levels",
        with_job_permissions("    permissions:\n      contents: \"read\"\n      id-token: 'write'"),
    ),
    accepts(
        "a comment between scopes",
        with_job_permissions("    permissions:\n      contents: read\n      # for the release\n      id-token: write"),
    ),
    accepts("permission scopes indented four spaces", with_job_permissions("    permissions:\n        contents: read")),
]


@pytest.mark.parametrize(("transform", "pattern"), PERMISSIONS_REJECTS)
def test_permissions_rejects(repo: Path, transform: Transform, pattern: Pattern) -> None:
    mutate(repo, transform, pattern)


@pytest.mark.parametrize("transform", PERMISSIONS_ACCEPTS)
def test_permissions_accepts(repo: Path, transform: Transform) -> None:
    mutate(repo, transform, None)


# fails closed on YAML it cannot read

FAILS_CLOSED_REJECTS = [
    rejects(
        "a flow-mapping step",
        with_checkout("- { name: x, with: { a: b }, uses: actions/checkout@v4 }"),
        FLOW,
    ),
    rejects("a minimal flow-mapping step", with_checkout("- { uses: actions/checkout@v4 }"), FLOW),
    rejects(
        "a flow node on its own line",
        sub1(STEPS_TO_END, "    steps:\n      [{uses: actions/checkout@v4}]\n"),
        FLOW,
    ),
    rejects(
        "a flow-style job",
        with_job("  extra: { runs-on: ubuntu-latest, steps: [{ uses: actions/checkout@v4 }] }\n"),
        FLOW,
    ),
    rejects("a multi-line flow sequence", with_step("        with: [\n          a\n        ]\n"), FLOW),
    rejects(
        "a flow sequence of steps",
        replace1("    steps:\n", "    steps: [{ uses: actions/checkout@v4 }]\n    old:\n"),
        FLOW,
    ),
    rejects("steps written as a flow list of words", sub1(STEPS_TO_END, "    steps: [a, b]\n"), FLOW),
    rejects(
        "an anchor on a job",
        with_job("  extra: &anchor\n    runs-on: ubuntu-latest\n    steps: []\n"),
        UNSUPPORTED,
    ),
    rejects("an alias value", with_step("        env: *shared\n"), UNSUPPORTED),
    rejects(
        "a merge key",
        replace1("    runs-on: ubuntu-latest\n", "    runs-on: ubuntu-latest\n    <<: *defaults\n"),
        UNSUPPORTED,
    ),
    rejects("a tag on steps", replace1("    steps:\n", "    steps: !!seq\n"), UNSUPPORTED),
    rejects(
        "a tag on a job",
        with_job("  extra: !!map\n    runs-on: ubuntu-latest\n    steps: []\n"),
        UNSUPPORTED,
    ),
    rejects("an explicit key", replace1("    steps:\n", "    ? steps\n    :\n"), UNSUPPORTED),
    rejects("an escaped quoted key", with_checkout('- "u\\u0073es": actions/checkout@v4'), UNSUPPORTED),
    rejects(
        "a compact JSON-style steps value",
        sub1(STEPS_TO_END, '    "steps":[{"uses":"actions/checkout@v4"}]\n'),
        UNSUPPORTED,
    ),
    rejects("a multi-line plain scalar", with_step("        name: first\n          second\n"), r"nested block"),
    rejects(
        "a multi-line quoted scalar",
        with_step('        name: "first\n          second"\n'),
        r"quoted scalars|nested block|unsupported",
    ),
    rejects(
        "a duplicate key",
        with_job_permissions("    permissions: {}\n    permissions: write-all"),
        r"duplicate key `permissions`",
    ),
    rejects(
        "a duplicate uses key",
        with_checkout(f"- uses: actions/checkout@{SHA}\n        uses: actions/checkout@v4"),
        r"duplicate key `uses`",
    ),
    rejects("an upper-case protected key", with_checkout("- USES: actions/checkout@v4"), r"must be lowercase"),
    rejects("a second document", lambda t: t + "---\njobs:\n", r"multiple documents"),
    rejects("a tab indent", with_step("\tname: x\n"), r"tabs are not supported"),
    rejects(
        "a lone carriage return",
        with_step("        name: a\r        uses: actions/checkout@v4\n"),
        r"unsupported line break characters",
    ),
    rejects(
        "inconsistent job indentation",
        with_job("    extra:\n        runs-on: ubuntu-latest\n        steps: []\n"),
        r"inconsistent indentation",
    ),
    rejects(
        "a jobs mapping without jobs",
        sub1(re.compile(r"^jobs:\n[\s\S]*\Z", re.M), "jobs:\nenv:\n  A: b\n"),
        r"`jobs:` has no jobs",
    ),
    rejects(
        "a workflow with no jobs mapping",
        sub1(re.compile(r"^jobs:", re.M), "tasks:"),
        r"no `jobs:` mapping found",
    ),
]

FAILS_CLOSED_ACCEPTS = [
    accepts(
        "an empty flow collection and expressions",
        with_step('      - run: echo "${{ github.sha }} [a] {b}"\n        env: {}\n'),
    ),
    accepts("quoted text holding brackets and colons", with_step('      - name: "result: [ok]"\n        run: true\n')),
    accepts(
        "a flow list of plain words",
        replace1("  pull_request:\n", "  pull_request:\n    branches: [main, release-1.0]\n"),
    ),
    accepts(
        "a matrix of flow lists",
        replace1("    steps:\n", "    strategy:\n      matrix:\n        node: [18, 20]\n    steps:\n"),
    ),
    accepts(
        "a dash and an asterisk inside a command",
        with_step("      - name: Deploy - *prod* only\n        run: rm -rf -- *tmp\n"),
    ),
    accepts("a folded scalar", with_step("      - run: >-\n          npm ci &&\n          npm test\n")),
    accepts(
        "a block scalar on the first key of a step",
        with_step("      - name: |\n          multi\n          line\n        run: echo ok\n"),
    ),
    accepts("a document start marker", lambda t: "---\n" + t),
    accepts("a byte order mark", lambda t: "\ufeff" + t),
    accepts("CRLF line endings", lambda t: t.replace("\n", "\r\n")),
]


@pytest.mark.parametrize(("transform", "pattern"), FAILS_CLOSED_REJECTS)
def test_fails_closed_rejects(repo: Path, transform: Transform, pattern: Pattern) -> None:
    mutate(repo, transform, pattern)


@pytest.mark.parametrize("transform", FAILS_CLOSED_ACCEPTS)
def test_fails_closed_accepts(repo: Path, transform: Transform) -> None:
    mutate(repo, transform, None)


def test_accepts_jobs_indented_four_spaces_consistently(repo: Path) -> None:
    check_repo(
        repo,
        {
            ".github/workflows/four.yml": (
                "permissions: {}\njobs:\n    a:\n        permissions: {}\n        steps:\n            - run: true\n"
            )
        },
        None,
    )


def test_rejects_a_job_indented_four_spaces_without_permissions(repo: Path) -> None:
    check_repo(
        repo,
        {".github/workflows/four.yml": "permissions: {}\njobs:\n    a:\n        runs-on: x\n"},
        r"job `a` has no permissions block",
    )


def test_reports_a_missing_workflows_directory(repo: Path, tmp_path: Path) -> None:
    result = run("node", str(repo / "scripts/check-repo.mjs"), cwd=tmp_path)
    assert_fails_cleanly(result, r"no workflows found")


def test_reports_a_directory_named_like_a_workflow(repo: Path) -> None:
    directory = repo / ".github/workflows/dir.yml"
    directory.mkdir()
    try:
        assert_fails_cleanly(run_repo_check(repo), r"dir\.yml: not a readable file")
    finally:
        directory.rmdir()
