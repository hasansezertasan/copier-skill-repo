// The single test seam: render the template, then judge the rendered repo only
// through its own check and its files. Nothing here inspects template internals.
import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const templateRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const workDirs = [];

function render(data) {
  const dest = mkdtempSync(join(tmpdir(), "copier-skills-"));
  workDirs.push(dest);
  const dataArgs = Object.entries(data).flatMap(([k, v]) => ["--data", `${k}=${v}`]);
  execFileSync(
    "copier",
    ["copy", "--defaults", "--trust", "--quiet", ...dataArgs, templateRoot, dest],
    { stdio: "inherit" },
  );
  return dest;
}

const readJson = (dir, path) => JSON.parse(readFileSync(join(dir, path), "utf8"));

after(() => workDirs.forEach((dir) => rmSync(dir, { recursive: true, force: true })));

describe("rendered with default answers", () => {
  let repo;
  before(() => {
    repo = render({ repo_name: "demo-skills", description: "Demo skills for testing." });
  });

  test("passes its own check with no generated-output drift", () => {
    execFileSync("npm", ["run", "check"], { cwd: repo, stdio: "inherit" });
  });

  test("ships the placeholder skill under its default name", () => {
    assert.ok(existsSync(join(repo, ".ai-rulez/skills/hello/SKILL.md")));
    assert.ok(existsSync(join(repo, "skills/hello/SKILL.md")));
  });

  test("derives repository URL, marketplace name and display name from the answers", () => {
    const plugin = readJson(repo, ".claude-plugin/plugin.json");
    assert.equal(plugin.name, "demo-skills");
    assert.equal(plugin.repository, "https://github.com/hasansezertasan/demo-skills");
    assert.equal(readJson(repo, ".claude-plugin/marketplace.json").name, "demo-skills");
    assert.equal(
      readJson(repo, ".codex-plugin/plugin.json").interface.displayName,
      "Demo Skills",
    );
  });

  test("uses package.json as the version source", () => {
    const pkg = readJson(repo, "package.json");
    assert.equal(pkg.version, "0.1.0");
    assert.equal(readJson(repo, ".claude-plugin/plugin.json").version, pkg.version);
    assert.match(pkg.devDependencies["ai-rulez"], /^5\.\d+\.\d+$/);
    assert.ok(pkg.scripts.check && pkg.scripts.generate);
  });

  test("commits an answers file holding exactly the agreed questions", () => {
    const answers = readFileSync(join(repo, ".copier-answers.yml"), "utf8");
    const keys = [...answers.matchAll(/^([a-z_]+):/gm)]
      .map((m) => m[1])
      .filter((key) => !key.startsWith("_"))
      .sort();
    assert.deepEqual(keys, [
      "author_name",
      "author_url",
      "description",
      "github_owner",
      "keywords",
      "license",
      "placeholder_skill",
      "publish_to_npm",
      "repo_name",
    ]);
  });
});

describe("rendered with non-default answers", () => {
  let repo;
  before(() => {
    repo = render({
      repo_name: "acme-widget-skills",
      description: "Skills for widgets.",
      placeholder_skill: "widget-check",
      github_owner: "acme",
      author_name: "Acme Dev",
      author_url: "https://github.com/acme-dev",
    });
  });

  test("names the placeholder skill from the answer and still passes check", () => {
    assert.ok(existsSync(join(repo, "skills/widget-check/SKILL.md")));
    assert.ok(!existsSync(join(repo, "skills/hello")));
    execFileSync("npm", ["run", "check"], { cwd: repo, stdio: "inherit" });
  });

  test("threads owner and author answers into the manifests", () => {
    const plugin = readJson(repo, ".claude-plugin/plugin.json");
    assert.equal(plugin.repository, "https://github.com/acme/acme-widget-skills");
    assert.deepEqual(plugin.author, { name: "Acme Dev", url: "https://github.com/acme-dev" });
  });
});

test("the template stores no generated output", () => {
  const entries = readdirSync(join(templateRoot, "template"), { withFileTypes: true }).map(
    (entry) => entry.name,
  );
  for (const generated of ["skills", ".claude-plugin", ".codex-plugin", ".agents"]) {
    assert.ok(!entries.includes(generated), `template ships generated ${generated}`);
  }
});
