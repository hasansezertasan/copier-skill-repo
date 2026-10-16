// Dependency-free repository check: the hardening rules CI relies on.
// Run by `npm run check` from the repo root; exits non-zero and lists every
// violation. Line-based on purpose (no YAML parser), so it reads only block-style
// YAML: top-level keys at column 0, job ids at two spaces (plain or quoted),
// `uses:` as a key of a step under `steps:` or of a job, block scalars (`run: |`)
// skipped. Anything outside that subset fails the check instead of passing it:
// flow collections other than `{}` and `[]`, anchors and aliases, and other job
// indentation. Local actions outside
// .github/actions are not followed.
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
  return readLines(path).map((raw, index) => {
    const indent = raw.length - raw.trimStart().length;
    if (scalarIndent >= 0) {
      if (raw.trim() === "" || indent > scalarIndent) return "";
      scalarIndent = -1;
    }
    // A quoted key is the same key: `"steps":` reads as `steps:`.
    const line = stripComment(raw).replace(/^(\s*(?:-\s+)?)(["'])([\w-]+)\2(\s*:)/, "$1$3$4");
    if (/:\s*[|>][+-]?\d*[+-]?$/.test(line)) scalarIndent = indent;
    // Fail closed on flow collections, which the line reader cannot follow.
    // Expressions and quoted text may hold brackets, so they are ignored here.
    const bare = line.replace(/\$\{\{.*?\}\}/g, "").replace(/"[^"]*"|'[^']*'/g, "");
    if (/(?:^\s*-\s*|:\s+)(?:\{(?!\s*\})|\[(?!\s*\]))/.test(bare)) {
      problems.push(`${path}:${index + 1}: flow style is not supported; use block style`);
    }
    if (/(?:^\s*(?:-\s+)?|:\s+|-\s+)[&*][\w-]|^\s*<<\s*:/.test(bare)) {
      problems.push(`${path}:${index + 1}: anchors and aliases are not supported; repeat the value`);
    }
    return line;
  });
};

// A job's `permissions:` must be `{}` or a block of scopes set to read, write
// or none: no scalar such as `write-all`, no expression, no empty block.
const SCOPE = /^ {6}[\w-]+:\s*(["']?)(read|write|none)\1$/;
const scopedPermissions = (value, children) =>
  value === "{}" || (value === "" && children.length > 0 && children.every((line) => SCOPE.test(line)));

// Workflows and local composite actions both reference third-party actions.
// A step's `uses:` is the key of a list item under `steps:`; a job's is a key of
// the job. Any other `uses` key (matrix values, env, inputs) is not a reference.
const USES = /^["']?uses["']?\s*:\s*["']?([^\s"',}]*)/;
const checkUses = (path, lines, index, value) => {
  let ref = value;
  let at = index;
  if (ref === "") {
    // The value may sit on the following line.
    at = lines.findIndex((next, i) => i > index && next.trim() !== "");
    ref = at < 0 ? "" : lines[at].trim().replace(/^["']|["']$/g, "");
  }
  // Local actions have no SHA to pin.
  if (ref.startsWith("./")) return;
  if (!/@[0-9a-f]{40}$/.test(ref) && !/^docker:\/\/.+@sha256:[0-9a-f]{64}$/.test(ref)) {
    problems.push(`${path}:${at + 1}: \`${ref}\` is not pinned by commit SHA`);
  }
};

for (const path of [...workflows, ...yamlFiles(".github/actions")]) {
  const lines = readYaml(path);
  const parents = []; // block keys that open a list or mapping
  const steps = []; // open step items: the dash column and the column of their keys
  lines.forEach((line, index) => {
    if (line.trim() === "") return;
    const indent = line.length - line.trimStart().length;
    const dash = /^\s*-(?:\s+|$)/.exec(line);
    while (parents.length > 0 && parents.at(-1).indent >= indent + (dash ? 1 : 0)) parents.pop();
    while (steps.length > 0 && steps.at(-1).dash >= indent) steps.pop();
    const opens = /^\s*([\w-]+)\s*:$/.exec(line);
    if (opens && !dash) parents.push({ indent, name: opens[1] });
    if (dash && parents.at(-1)?.name === "steps") {
      // A dash alone on its line puts the step's keys on the next line.
      const keyAt = dash[0].length > line.trim().length ? lines.findIndex((next, i) => i > index && next.trim() !== "") : -1;
      const key = keyAt < 0 ? dash[0].length : lines[keyAt].length - lines[keyAt].trimStart().length;
      steps.push({ dash: indent, key });
    }
    const isStepKey = dash ? parents.at(-1)?.name === "steps" : steps.at(-1)?.key === indent;
    const match = isStepKey ? USES.exec(line.slice(dash ? dash[0].length : indent)) : null;
    if (match) checkUses(path, lines, index, match[1]);
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
    // A job that calls a reusable workflow carries `uses:` at job level.
    const jobUses = body.findIndex((line) => /^ {4}uses\s*:/.test(line));
    if (jobUses >= 0) checkUses(path, lines, start + 2 + from + jobUses, USES.exec(body[jobUses].trim())[1]);
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
  // Each workflow is read twice, so the same line can be reported twice.
  console.error([...new Set(problems)].join("\n"));
  process.exit(1);
}
console.log(`check-repo: ${workflows.length} workflow(s) ok`);
