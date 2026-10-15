// Dependency-free repository check: the hardening rules CI relies on.
// Run by `npm run check`; exits non-zero and lists every violation.
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const workflowsDir = ".github/workflows";
const problems = [];

const workflows = readdirSync(workflowsDir).filter((name) => /\.ya?ml$/.test(name));
if (workflows.length === 0) problems.push(`${workflowsDir}: no workflows found`);

for (const name of workflows) {
  const path = join(workflowsDir, name);
  const lines = readFileSync(path, "utf8").split("\n");

  if (!lines.includes("permissions: {}")) {
    problems.push(`${path}: top-level \`permissions: {}\` is required`);
  }

  lines.forEach((line, index) => {
    const match = line.match(/^\s*(?:-\s*)?uses:\s*(\S+)/);
    if (!match) return;
    const ref = match[1];
    // Local actions and reusable workflows in this repo have no SHA to pin.
    if (ref.startsWith("./")) return;
    if (!/@[0-9a-f]{40}$/.test(ref)) {
      problems.push(`${path}:${index + 1}: \`${ref}\` is not pinned by commit SHA`);
    }
  });
}

if (problems.length > 0) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`check-repo: ${workflows.length} workflow(s) ok`);
