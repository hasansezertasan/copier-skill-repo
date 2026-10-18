import yaml
from conftest import copier, git


def test_template_renders_with_defaults(tmp_path, versioned_template):
    dest = tmp_path / "project"
    result = copier("copy", "--defaults", str(versioned_template), str(dest), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert (dest / ".copier-answers.yml").exists()


def test_update_to_a_new_version_only_moves_the_answers_commit(tmp_path, versioned_template):
    dest = tmp_path / "project"
    copier("copy", "--defaults", str(versioned_template), str(dest), cwd=tmp_path)
    git("init", "-q", "-b", "main", cwd=dest)
    git("add", "-A", cwd=dest)
    git("commit", "-q", "-m", "chore: render", cwd=dest)

    git("commit", "-q", "--allow-empty", "-m", "chore: release", cwd=versioned_template)
    git("tag", "v0.0.1", cwd=versioned_template)

    result = copier("update", "--defaults", "--skip-answered", cwd=dest)
    assert result.returncode == 0, result.stderr
    changed = {line[3:] for line in git("status", "--porcelain", cwd=dest).stdout.splitlines()}
    assert changed == {".copier-answers.yml"}
    answers = yaml.safe_load((dest / ".copier-answers.yml").read_text())
    assert answers["_commit"] == "v0.0.1"
