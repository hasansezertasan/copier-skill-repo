// Dependency-free repository check: the hardening rules CI relies on.
// Run by `npm run check` from the repo root; exits non-zero and lists every
// violation. Line-based on purpose (no YAML parser), so it expects the usual
// block-style layout: top-level keys at column 0, job ids at two spaces
// (plain or quoted), block scalars (`run: |`) skipped, `uses:` value on the
// same or the next line. Layouts outside that subset (other job indentation,
// flow-mapping steps with nested braces) fail the check instead of passing it.
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
// Drops full-line and trailing comments, so a commented-out line never counts.
const stripComment = (line) => line.replace(/^\s*#.*$|\s+#.*$/, "").trimEnd();

// Comment-free lines with block-scalar bodies (`run: |`, `>-`, ...) blanked, so
// text inside a script is never read as YAML structure. Line numbers are kept.
const readYaml = (path) => {
  let scalarIndent = -1;
  return readLines(path).map((raw) => {
    const indent = raw.length - raw.trimStart().length;
    if (scalarIndent >= 0) {
      if (raw.trim() === "" || indent > scalarIndent) return "";
      scalarIndent = -1;
    }
    const line = stripComment(raw);
    if (/:\s*[|>][+-]?\d*[+-]?$/.test(line)) scalarIndent = indent;
    return line;
  });
};

// A job's `permissions:` must be `{}` or scopes set to read, write or none:
// no scalar such as `write-all`, no expression, no empty block.
const SCOPE = /^[\w-]+:\s*(["']?)(read|write|none)\1$/;
const scopedPermissions = (value, children) => {
  if (value === "{}") return true;
  if (value.startsWith("{") && value.endsWith("}")) {
    const pairs = value.slice(1, -1).split(",").map((pair) => pair.trim());
    return pairs.every((pair) => SCOPE.test(pair));
  }
  return value === "" && children.length > 0 && children.every((line) => /^ {6}/.test(line) && SCOPE.test(line.trim()));
};

// Workflows and local composite actions both reference third-party actions.
const USES = /(?:^\s*(?:-\s+)*|^\s*-\s*\{(?:[^{}]*,)?\s*)["']?uses["']?\s*:\s*["']?([^\s"',}]*)/g;
for (const path of [...workflows, ...yamlFiles(".github/actions")]) {
  const lines = readYaml(path);
  lines.forEach((line, index) => {
    const refs = [...line.matchAll(USES)];
    for (const [, inline] of refs) {
      let ref = inline;
      let at = index;
      if (ref === "") {
        // The value may sit on the following line.
        at = lines.findIndex((next, i) => i > index && next.trim() !== "");
        ref = at < 0 ? "" : lines[at].trim().replace(/^["']|["']$/g, "");
      }
      // Local actions have no SHA to pin.
      if (ref.startsWith("./")) continue;
      if (!/@[0-9a-f]{40}$/.test(ref) && !/^docker:\/\/.+@sha256:[0-9a-f]{64}$/.test(ref)) {
        problems.push(`${path}:${at + 1}: \`${ref}\` is not pinned by commit SHA`);
      }
    }
    // Fail closed: a flow-mapping step the pattern cannot read is not "no action".
    if (refs.length === 0 && /^\s*-\s*\{/.test(line) && /\buses\b/.test(line)) {
      problems.push(`${path}:${index + 1}: unsupported flow-mapping step; write the step in block style`);
    }
  });
}

for (const path of workflows) {
  const lines = readYaml(path);

  if (!lines.some((line) => /^permissions\s*:\s*\{\}$/.test(line))) {
    problems.push(`${path}: top-level \`permissions: {}\` is required`);
  }

  // Every job declares its own permissions block.
  const start = lines.findIndex((line) => /^jobs\s*:$/.test(line));
  if (start < 0) problems.push(`${path}: no \`jobs:\` mapping found`);
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => /^\S/.test(line));
  const jobsBlock = start < 0 ? [] : end < 0 ? rest : rest.slice(0, end);
  // Job ids are matched at two spaces; any other width would skip every job.
  const firstJob = jobsBlock.find((line) => line.trim() !== "");
  if (firstJob && !/^ {2}\S/.test(firstJob)) problems.push(`${path}: jobs are not indented two spaces`);
  const jobIds = jobsBlock.flatMap((line, i) => (/^ {2}["']?[\w-]+["']?\s*:$/.test(line) ? [i] : []));
  jobIds.forEach((from, n) => {
    const body = jobsBlock.slice(from + 1, jobIds[n + 1] ?? jobsBlock.length);
    // A job that calls a reusable workflow still scopes what it hands down.
    const job = jobsBlock[from].trim().replace(/\s*:$/, "").replace(/^["']|["']$/g, "");
    const at = body.findIndex((line) => /^ {4}permissions\s*:/.test(line));
    if (at < 0) {
      problems.push(`${path}: job \`${job}\` has no permissions block`);
      return;
    }
    const value = body[at].replace(/^ {4}permissions\s*:\s*/, "");
    const after = body.slice(at + 1);
    const next = after.findIndex((line) => /^ {0,4}\S/.test(line));
    const children = (next < 0 ? after : after.slice(0, next)).filter((line) => line.trim() !== "");
    if (!scopedPermissions(value, children)) {
      problems.push(`${path}: job \`${job}\` has unscoped permissions; use \`{}\` or scopes set to read, write or none`);
    }
  });
}

if (problems.length > 0) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`check-repo: ${workflows.length} workflow(s) ok`);
