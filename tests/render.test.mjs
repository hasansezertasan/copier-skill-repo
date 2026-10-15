// The single test seam: render the template, then judge the rendered repo only
// through its own check and its files. The one exception is the guard that the
// template itself ships no generated output.
import { after, before, describe, test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const templateRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const workDirs = [];
const FIVE_MINUTES = 5 * 60 * 1000;

function scratchDir() {
  const dir = mkdtempSync(join(tmpdir(), "copier-skills-"));
  workDirs.push(dir);
  return dir;
}

// Render from a plain copy of the working tree so the result never depends on
// git tags, HEAD or uncommitted changes in this checkout.
function render(data, destName, extraArgs = []) {
  const source = scratchDir();
  cpSync(join(templateRoot, "copier.yml"), join(source, "copier.yml"));
  cpSync(join(templateRoot, "template"), join(source, "template"), { recursive: true });
  // The destination folder name is the default repo_name, so a test can pick it.
  const dest = destName ? join(scratchDir(), destName) : scratchDir();
  // A data file (JSON is valid YAML) delivers answers exactly as written, so
  // control characters reach the template's validators instead of failing in
  // the command-line parser first.
  const dataFile = join(scratchDir(), "answers.json");
  writeFileSync(dataFile, JSON.stringify(data));
  execFileSync("copier", ["copy", "--defaults", "--trust", "--quiet", ...extraArgs, "--data-file", dataFile, source, dest], {
    stdio: extraArgs.length ? ["ignore", "ignore", "pipe"] : "inherit",
    timeout: FIVE_MINUTES,
  });
  return dest;
}

// Renders with tasks skipped, so only Copier's own prompt-time validation can
// reject the answers, never the later `npm run generate`, and checks that the
// rejection names the expected question.
function assertRejected(question, overrides) {
  const answers = { repo_name: "demo-skills", description: "Demo.", ...overrides };
  assert.throws(
    () => render(answers, undefined, ["--skip-tasks"]),
    (error) => String(error.stderr).includes(`Validation error for question '${question}'`),
  );
}

// What CI will run in a fresh checkout: a clean install from the committed
// lockfile, then the repo's own check.
function installAndCheck(repo) {
  const options = { cwd: repo, stdio: "inherit", timeout: FIVE_MINUTES };
  execFileSync("npm", ["ci"], options);
  execFileSync("npm", ["run", "check"], options);
}

const readJson = (dir, path) => JSON.parse(readFileSync(join(dir, path), "utf8"));

after(() => workDirs.forEach((dir) => rmSync(dir, { recursive: true, force: true })));

describe("rendered with default answers", () => {
  let repo;
  before(() => {
    repo = render({ repo_name: "demo-skills", description: "Demo skills for testing." });
  });

  test("passes its own check with no generated-output drift", () => {
    installAndCheck(repo);
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

describe("rendered with no answers at all", () => {
  test("takes repo_name from the destination folder and passes its own check", () => {
    const repo = render({}, "bare-skills");
    assert.equal(readJson(repo, ".claude-plugin/plugin.json").name, "bare-skills");
    assert.ok(readJson(repo, "package.json").description.length > 0);
    installAndCheck(repo);
  });
});

describe("rendered with non-default answers", () => {
  let repo;
  before(() => {
    repo = render({
      repo_name: "acme-widget-skills",
      description: 'Skills for widgets 😀 with "quotes" and a \\ backslash.',
      placeholder_skill: "widget-check",
      github_owner: "acme",
      author_name: "Acme Dev",
      author_url: "https://github.com/acme-dev",
    });
  });

  test("names the placeholder skill from the answer and still passes check", () => {
    assert.ok(existsSync(join(repo, "skills/widget-check/SKILL.md")));
    assert.ok(!existsSync(join(repo, "skills/hello")));
    installAndCheck(repo);
  });

  test("threads owner and author answers into the manifests", () => {
    const plugin = readJson(repo, ".claude-plugin/plugin.json");
    assert.equal(plugin.repository, "https://github.com/acme/acme-widget-skills");
    assert.equal(plugin.description, 'Skills for widgets 😀 with "quotes" and a \\ backslash.');
    assert.equal(readJson(repo, "package.json").description, plugin.description);
    assert.deepEqual(plugin.author, { name: "Acme Dev", url: "https://github.com/acme-dev" });
  });
});

describe("publish_to_npm", () => {
  test("is publishable by default", () => {
    const repo = render({ repo_name: "demo-skills", description: "Demo." });
    assert.equal(readJson(repo, "package.json").private, undefined);
  });

  test("marks the package private when turned off", () => {
    const repo = render({ repo_name: "demo-skills", description: "Demo.", publish_to_npm: false });
    assert.equal(readJson(repo, "package.json").private, true);
  });
});

describe("invalid answers", () => {
  for (const question of ["description", "author_name", "author_url"]) {
    for (const [label, value] of [["empty", ""], ["whitespace-only", "   "]]) {
      test(`${question} that is ${label} is rejected`, () => {
        assertRejected(question, { [question]: value });
      });
    }
  }

  for (const question of ["description", "author_name", "author_url", "keywords"]) {
    for (const [label, value] of [["escape", "bad\u001bvalue"], ["backspace", "bad\bvalue"], ["newline", "bad\nvalue"]]) {
      test(`${question} containing ${label} is rejected`, () => {
        assertRejected(question, { [question]: value });
      });
    }
  }

  const name64 = "a".repeat(64);
  for (const [question, value] of [
    ["repo_name", `${name64}b`],
    ["repo_name", "Demo_Skills"],
    ["placeholder_skill", `${name64}b`],
    ["placeholder_skill", "Hello World"],
  ]) {
    test(`${question} ${JSON.stringify(value).slice(0, 20)} is rejected`, () => {
      assertRejected(question, { [question]: value });
    });
  }

  for (const github_owner of ['bad"owner', "acme--tools", "-acme", "acme-", "a".repeat(40)]) {
    test(`github_owner ${JSON.stringify(github_owner).slice(0, 20)} is rejected`, () => {
      assertRejected("github_owner", { github_owner });
    });
  }
});

test("the template stores no generated output", () => {
  const generated = new Set(["skills", ".claude-plugin", ".codex-plugin", ".agents", "AGENTS.md"]);
  const found = readdirSync(join(templateRoot, "template"), { recursive: true }).filter((path) =>
    generated.has(path.split("/")[0]),
  );
  assert.deepEqual(found, []);
});
