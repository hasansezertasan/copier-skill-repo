"""Shared helpers for the template tests.

The single test seam: render the template, then judge the rendered repo only
through its own check and its files. The one exception is the guard that the
template itself ships no generated output.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".git", ".venv", "__pycache__", ".pytest_cache", "node_modules")
FIVE_MINUTES = 5 * 60

# A thrown error would print the source line holding the message, so a clean
# failure must carry no stack trace.
STACK_TRACE = re.compile(r"\n\s+at .*:\d+:\d+")

Render = Callable[..., Path]


def scratch_env() -> dict[str, str]:
    """The environment for every subprocess that touches a scratch repository.

    Git's repository-location variables (GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE, ...)
    are inherited when the tests run from a Git hook, and would point `git reset
    --hard`, `git clean` and `git commit` at the invoking repository instead of
    the scratch directory.
    """
    return {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=scratch_env() if env is None else env,
        timeout=FIVE_MINUTES,
    )


def describe(result: subprocess.CompletedProcess) -> str:
    return f"{' '.join(map(str, result.args))} exited {result.returncode}\n{result.stdout}\n{result.stderr}"


def run_ok(*args: str, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    result = run(*args, cwd=cwd, env=env)
    assert result.returncode == 0, describe(result)
    return result


def copier(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return run(sys.executable, "-m", "copier", *args, cwd=cwd)


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return run(
        "git",
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        *args,
        cwd=cwd,
    )


def git_ok(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    result = git(*args, cwd=cwd)
    assert result.returncode == 0, describe(result)
    return result


def assert_fails_cleanly(result: subprocess.CompletedProcess, pattern: str | re.Pattern[str]) -> None:
    """A clean failure: exit status 1, the expected message, and no crash."""
    assert result.returncode == 1, describe(result)
    assert not STACK_TRACE.search(result.stderr), result.stderr
    assert re.search(pattern, result.stderr), result.stderr


# Byte-exact text I/O: universal-newline translation would hide CR and CRLF.
def read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(read_text(path))


def remove(path: Path) -> None:
    """Removes a file, symlink or directory if it exists."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def template_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A plain copy of the working tree's template, so a render never depends on
    git tags, HEAD or uncommitted changes in this checkout."""
    source = tmp_path_factory.mktemp("copier-skill-repo-")
    shutil.copy2(REPO / "copier.yml", source / "copier.yml")
    shutil.copytree(REPO / "template", source / "template")
    return source


def render_copy(
    tmp_path_factory: pytest.TempPathFactory, data: dict[str, Any], dest_name: str | None = None
) -> tuple[subprocess.CompletedProcess, Path]:
    """Runs only `copier copy`, so only Copier's own answers validation can reject."""
    source = template_source(tmp_path_factory)
    # The destination folder name is the default repo_name, so a test can pick it.
    dest = tmp_path_factory.mktemp("copier-skill-repo-") / (dest_name or "project")
    # A data file (JSON is valid YAML) delivers answers exactly as written, so
    # control characters reach the template's validators instead of failing in
    # the command-line parser first.
    data_file = tmp_path_factory.mktemp("copier-skill-repo-") / "answers.json"
    write_text(data_file, json.dumps(data, ensure_ascii=False))
    result = copier(
        "copy", "--defaults", "--quiet", "--data-file", str(data_file), str(source), str(dest), cwd=source
    )
    return result, dest


def render_repo(
    tmp_path_factory: pytest.TempPathFactory,
    data: dict[str, Any],
    dest_name: str | None = None,
    *,
    generate: bool = True,
) -> Path:
    """Renders the template. It has no `_tasks`, so the generate step a user runs
    after the copy runs here too, unless the caller wants the bare copy."""
    result, dest = render_copy(tmp_path_factory, data, dest_name)
    assert result.returncode == 0, describe(result)
    if generate:
        run_ok("npm", "install", cwd=dest)
        run_ok("npm", "run", "generate", cwd=dest)
    return dest


def install_and_check(repo: Path) -> None:
    """What CI will run in a fresh checkout: a clean install from the committed
    lockfile, then the repo's own check."""
    run_ok("npm", "ci", cwd=repo)
    run_ok("npm", "run", "check", cwd=repo)


@pytest.fixture(scope="session")
def render(tmp_path_factory: pytest.TempPathFactory) -> Render:
    """`render(data, dest_name=None, *, generate=True)` returns the rendered repo."""

    def _render(data: dict[str, Any], dest_name: str | None = None, *, generate: bool = True) -> Path:
        return render_repo(tmp_path_factory, data, dest_name, generate=generate)

    return _render


@pytest.fixture
def versioned_template(tmp_path) -> Path:
    """A throwaway git copy of this repo, tagged v0.0.0, so `copier update` has history."""
    src = tmp_path / "template-src"
    shutil.copytree(REPO, src, ignore=IGNORE)
    git("init", "-q", "-b", "main", cwd=src)
    git("add", "-A", cwd=src)
    git("commit", "-q", "-m", "chore: initial", cwd=src)
    git("tag", "v0.0.0", cwd=src)
    return src
