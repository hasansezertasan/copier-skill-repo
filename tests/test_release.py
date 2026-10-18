"""Release safeguards: the release-merge guard, the regenerate and push jobs."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    FIVE_MINUTES,
    Render,
    assert_fails_cleanly,
    describe,
    git_ok,
    read_json,
    read_text,
    run,
    run_ok,
    scratch_env,
    write_text,
)


@pytest.fixture(scope="module")
def repo(render: Render) -> Path:
    return render({"repo_name": "demo-skills", "description": "Demo."})


def release_merge_run(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, pulls: Any, sha: str
) -> subprocess.CompletedProcess:
    file = tmp_path_factory.mktemp("pulls") / "pulls.json"
    write_text(file, pulls if isinstance(pulls, str) else json.dumps(pulls))
    return run("node", "scripts/release-merge.mjs", "--pulls", str(file), "--sha", sha, cwd=repo)


@pytest.fixture
def release_merge(repo: Path, tmp_path_factory: pytest.TempPathFactory):
    def _release_merge(pulls: Any, sha: str) -> str:
        result = release_merge_run(repo, tmp_path_factory, pulls, sha)
        assert result.returncode == 0, describe(result)
        return result.stdout.strip()

    return _release_merge


def pr(sha: str, **overrides: Any) -> dict[str, Any]:
    return {
        "merged_at": "2026-10-16T00:00:00Z",
        "base": {"ref": "main"},
        "labels": [{"name": "autorelease: pending"}],
        "merge_commit_sha": sha,
        **overrides,
    }


def release_workflow(repo: Path) -> str:
    return read_text(repo / ".github/workflows/release.yml")


def test_allows_the_sole_pending_release_merged_as_the_validated_commit(release_merge) -> None:
    assert release_merge([[pr("abc")]], "abc") == "is-release-merge=true"
    assert (
        release_merge([[pr("old", labels=[{"name": "autorelease: tagged"}])], [pr("abc")]], "abc")
        == "is-release-merge=true"
    )


def test_refuses_a_stale_pending_merge_on_a_later_commit(release_merge) -> None:
    assert release_merge([[pr("abc")]], "later") == "is-release-merge=false"


def test_refuses_two_pending_merges_even_when_one_matches(release_merge) -> None:
    assert release_merge([[pr("abc")], [pr("def")]], "abc") == "is-release-merge=false"


def test_ignores_unmerged_other_branch_and_unlabelled_pull_requests(release_merge) -> None:
    noise = [pr("abc", merged_at=None), pr("abc", base={"ref": "dev"}), pr("abc", labels=[])]
    assert release_merge([noise], "abc") == "is-release-merge=false"
    assert release_merge([[*noise, pr("abc")]], "abc") == "is-release-merge=true"


def test_refuses_when_there_is_no_pending_release_at_all(release_merge) -> None:
    assert release_merge([[]], "abc") == "is-release-merge=false"


def test_fails_cleanly_on_unreadable_input_and_bad_usage(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    assert_fails_cleanly(release_merge_run(repo, tmp_path_factory, "not json", "abc"), r"cannot read as JSON")
    assert_fails_cleanly(
        release_merge_run(repo, tmp_path_factory, {"not": "pages"}, "abc"), r"expected an array of pages"
    )
    assert_fails_cleanly(run("node", "scripts/release-merge.mjs", cwd=repo), r"usage")


def test_wires_the_guard_a_non_cancelling_concurrency_group_and_the_dispatch_check(repo: Path) -> None:
    release = release_workflow(repo)
    assert re.search(r"^concurrency:\n  group: release\n  cancel-in-progress: false$", release, re.M)
    assert re.search(r"node scripts/release-merge\.mjs", release)
    assert re.search(
        r"skip-github-release: \$\{\{ steps\.release-merge\.outputs\.is-release-merge != 'true' \}\}", release
    )
    check = read_text(repo / ".github/workflows/check.yml")
    # No `ref` input: it would let a run report on a commit other than the one
    # the check is bound to, so the check could pass a head it never validated.
    assert re.search(r"^  workflow_dispatch:$", check, re.M)
    assert not re.search(r"inputs", check)
    contributing = read_text(repo / "CONTRIBUTING.md")
    assert re.search(r"gh workflow run check\.yml --ref release-please--branches--main", contributing)
    assert re.search(r"^## Release flow$", contributing, re.M)
    assert re.search(r"^## Recovery$", contributing, re.M)
    assert re.search(r"sole pending release", contributing)
    assert re.search(r"`publish` job then publishes the package to npm", contributing)
    assert not re.search(r"scoop", contributing, re.I)


def test_regenerates_the_plugin_output_without_running_dependency_code_next_to_a_write_token(repo: Path) -> None:
    release = release_workflow(repo)
    # Job bodies, keyed by job id.
    without_comments = "\n".join(line for line in release.split("\n") if not re.search(r"^\s*#", line))
    jobs_text = re.split(r"^jobs:\n", without_comments, flags=re.M)[1]
    jobs = {
        match[1]: match[2]
        for match in re.finditer(r"^  ([a-z-]+):\n([\s\S]*?)(?=^  [a-z-]+:\n|(?![\s\S]))", jobs_text, re.M)
    }
    assert jobs.get("regenerate") and jobs.get("push"), "regenerate and push jobs exist"
    # release-please and push hold write tokens: neither installs packages or
    # runs an npm script. release-please runs only its own dependency-free node
    # script; push runs no node at all.
    for job_id in ["release-please", "push"]:
        assert re.search(r"contents: write", jobs[job_id]), f"{job_id} holds the write token"
        assert not re.search(r"\bnpm\b", jobs[job_id]), f"{job_id} runs no npm"
    assert not re.search(r"setup-node|\bnode\b", jobs["push"]), "push runs no node"
    # regenerate runs npm with read-only access and no stored credentials.
    assert re.search(r"permissions:\n      contents: read\n", jobs["regenerate"])
    assert not re.search(r"write", jobs["regenerate"])
    assert re.search(r"persist-credentials: false", jobs["regenerate"])
    assert re.search(r"npm ci\n\s+npm run generate", jobs["regenerate"])
    # Commit, then check the committed tree, then hand over: strict validation
    # fails on uncommitted generated output.
    assert re.search(
        r'git commit -m "chore: regenerate plugin output for the release"[\s\S]*npm run check\n\s+'
        r"git diff --binary HEAD~1 HEAD",
        jobs["regenerate"],
    )
    # Whatever the allowlist did not stage is discarded before that check, so it
    # reads the committed tree and not leftover generated files.
    assert re.search(
        r'git commit -m "chore: regenerate plugin output for the release"\n\s+git restore --worktree -- \.\n\s+'
        r"git clean -fdq\n\s+npm run check\n\s+git diff --binary HEAD~1 HEAD",
        jobs["regenerate"],
    )
    assert re.search(
        r"if: \$\{\{ steps\.regenerate\.outputs\.changed == 'true' \}\}\n\s+uses: actions/upload-artifact@[0-9a-f]{40}",
        jobs["regenerate"],
    )
    # push applies only generated paths, from the artifact, and pushes the branch.
    assert re.search(r"needs: \[release-please, regenerate\]", jobs["push"])
    assert re.search(r"actions/download-artifact@[0-9a-f]{40}", jobs["push"])
    assert re.search(r"Refusing to push: \$path is not generated output", jobs["push"])
    assert re.search(r'git apply --index "\$patch"', jobs["push"])
    assert re.search(r'git push origin "HEAD:\$BRANCH"', jobs["push"])
    assert re.search(r"read-only job runs `npm run generate`", read_text(repo / "CONTRIBUTING.md"))


# the push job's patch allowlist
#
# The push job's own shell, run for real in a scratch git repo with the final
# `git push` stubbed out.


def push_script(repo: Path) -> str:
    release = release_workflow(repo)
    # `\n  push:\n    needs` is the job; a bare `push:` also starts the `on:` trigger.
    job = release[release.index("\n  push:\n    needs") :]
    body = re.split(r"\n(?=  [a-z-]+:\n)", job[job.index("run: |\n") + len("run: |\n") :], maxsplit=1)[0]
    script = "\n".join(re.sub(r"^ {10}", "", line, count=1) for line in body.split("\n"))
    assert re.search(r'git push origin "HEAD:\$BRANCH"', script)
    return script.replace('git push origin "HEAD:$BRANCH"', "true", 1)


def apply_patch(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, files: dict[str, str]
) -> tuple[bool, bool, str]:
    """Applies a patch that writes `files` over a baseline commit; reports the
    script's success, whether it made a commit, and its stderr."""
    directory = tmp_path_factory.mktemp("copier-skill-repo-")
    git_ok("init", "-q", "-b", "main", cwd=directory)
    write_text(directory / ".ai-rulez-generated.json", "{}\n")
    write_text(directory / "AGENTS.md", "old\n")
    git_ok("add", "-A", cwd=directory)
    git_ok("commit", "-q", "-m", "base", cwd=directory)
    for path, text in files.items():
        (directory / path).parent.mkdir(parents=True, exist_ok=True)
        write_text(directory / path, text)
    git_ok("add", "-A", cwd=directory)
    patch_path = tmp_path_factory.mktemp("copier-skill-repo-") / "regenerate.patch"
    diff = subprocess.run(
        ["git", "diff", "--cached", "--binary"],
        cwd=directory,
        capture_output=True,
        check=True,
        env=scratch_env(),
        timeout=FIVE_MINUTES,
    )
    patch_path.write_bytes(diff.stdout)
    git_ok("reset", "-q", "--hard", cwd=directory)
    git_ok("clean", "-qfd", cwd=directory)
    before = git_ok("rev-parse", "HEAD", cwd=directory).stdout
    result = run(
        "bash",
        "-ec",
        push_script(repo),
        cwd=directory,
        env={**scratch_env(), "RUNNER_TEMP": str(patch_path.parent), "BRANCH": "release-please--branches--main"},
    )
    committed = git_ok("rev-parse", "HEAD", cwd=directory).stdout != before
    if result.returncode == 0:
        return True, committed, ""
    return False, committed, result.stderr


def test_pushes_generated_commands_and_pi_prompts_too(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    ok, committed, stderr = apply_patch(repo, tmp_path_factory, {"commands/a.md": "x\n", ".pi/prompts/a.md": "x\n"})
    assert [ok, committed] == [True, True], stderr


def test_pushes_generated_output_including_an_exact_agents_md(
    repo: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    ok, committed, stderr = apply_patch(
        repo,
        tmp_path_factory,
        {".ai-rulez-generated.json": '{"a":1}\n', "AGENTS.md": "new\n", "skills/new/SKILL.md": "x\n"},
    )
    assert [ok, committed] == [True, True], stderr


@pytest.mark.parametrize(
    "path",
    [
        "AGENTS.md.evil",
        ".github/workflows/evil.yml",
        "skills-evil/x",
        ".agents-evil/x",
        "commands-evil/x",
        ".pi-evil/x",
        ".ai-rulez-generated.json.evil",
        "package.json",
    ],
)
def test_refuses(repo: Path, tmp_path_factory: pytest.TempPathFactory, path: str) -> None:
    ok, committed, stderr = apply_patch(repo, tmp_path_factory, {path: "x\n"})
    assert ok is False
    assert committed is False
    assert re.search(r"Refusing to push: .* is not generated output", stderr), stderr


def test_starts_the_regenerate_jobs_staging_from_a_clean_index(repo: Path) -> None:
    # Dependency code from `npm ci` may stage files; only the listed paths may
    # enter the commit.
    assert re.search(
        r"npm run generate\n(\s+#[^\n]*\n)+\s+git reset -q\n(\s+#[^\n]*\n)+\s+for path in ", release_workflow(repo)
    )


def test_a_release_bump_fails_the_check_until_the_output_is_regenerated(render: Render) -> None:
    # release-please bumps these files and cannot touch the hash ledger.
    bumped = render({"repo_name": "bump-skills", "description": "Demo."})
    run_ok("npm", "ci", cwd=bumped)

    def bump(path: str, update) -> None:
        data = read_json(bumped / path)
        update(data)
        write_text(bumped / path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    bump("package.json", lambda d: d.update(version="0.2.0"))
    bump(".release-please-manifest.json", lambda d: d.update({".": "0.2.0"}))
    bump(".claude-plugin/plugin.json", lambda d: d.update(version="0.2.0"))
    bump(".claude-plugin/marketplace.json", lambda d: d["plugins"][0].update(version="0.2.0"))
    bump(".codex-plugin/plugin.json", lambda d: d.update(version="0.2.0"))
    # The release guard is satisfied: every version moved together.
    run_ok("node", "scripts/release-guard.mjs", "--publish", cwd=bumped)
    result = run("npm", "run", "check", cwd=bumped)
    output = result.stdout + result.stderr
    assert result.returncode != 0, describe(result)
    assert re.search(r"Drifted plugin outputs", output) and re.search(r"\.ai-rulez-generated\.json", output), output
    run_ok("npm", "run", "generate", cwd=bumped)
    run_ok("npm", "run", "check", cwd=bumped)


def test_keeps_both_workflows_within_the_hardened_ci_rules(repo: Path) -> None:
    run_ok("node", "scripts/check-repo.mjs", cwd=repo)
