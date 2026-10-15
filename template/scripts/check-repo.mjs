// Dependency-free repository check: the hardening rules CI relies on.
// Run by `npm run check` from the repo root; exits non-zero and lists every
// violation. Line-based on purpose (no YAML parser), so it expects the usual
// block-style layout: top-level keys at column 0, job ids at two spaces.
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const problems = [];
const yamlFiles = (dir) =>
  existsSync(dir)
    ? readdirSync(dir, { recursive: true }).filter((name) => /\.ya?ml$/.test(name)).map((name) => join(dir, name))
    : [];

const workflows = yamlFiles(".github/workflows");
if (workflows.length === 0) problems.push(".github/workflows: no workflows found");

const readLines = (path) => readFileSync(path, "utf8").replace(/\r\n/g, "\n").split("\n");

// Workflows and local composite actions both reference third-party actions.
for (const path of [...workflows, ...yamlFiles(".github/actions")]) {
  readLines(path).forEach((line, index) => {
    const code = line.replace(/\s#.*$/, "");
    for (const [, ref] of code.matchAll(/\buses:\s*["']?([^\s"',}]+)/g)) {
      // Local actions have no SHA to pin.
      if (ref.startsWith("./")) continue;
      if (!/@[0-9a-f]{40}$/.test(ref) && !/^docker:\/\/.+@sha256:[0-9a-f]{64}$/.test(ref)) {
        problems.push(`${path}:${index + 1}: \`${ref}\` is not pinned by commit SHA`);
      }
    }
  });
}

for (const path of workflows) {
  const lines = readLines(path).map((line) => line.replace(/\s+#.*$/, "").trimEnd());

  if (!lines.includes("permissions: {}")) {
    problems.push(`${path}: top-level \`permissions: {}\` is required`);
  }

  // Every job declares its own permissions block.
  const start = lines.indexOf("jobs:");
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => /^\S/.test(line));
  const jobsBlock = start < 0 ? [] : end < 0 ? rest : rest.slice(0, end);
  const jobIds = jobsBlock.flatMap((line, i) => (/^ {2}[\w-]+:$/.test(line) ? [i] : []));
  jobIds.forEach((from, n) => {
    const body = jobsBlock.slice(from + 1, jobIds[n + 1] ?? jobsBlock.length);
    // A job that calls a reusable workflow still scopes what it hands down.
    if (!body.some((line) => /^ {4}permissions:/.test(line))) {
      problems.push(`${path}: job \`${jobsBlock[from].trim().slice(0, -1)}\` has no permissions block`);
    }
  });
}

if (problems.length > 0) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`check-repo: ${workflows.length} workflow(s) ok`);
