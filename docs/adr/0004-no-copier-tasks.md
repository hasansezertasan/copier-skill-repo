# No Copier `_tasks`: the user generates after rendering

Decided 2026-10-18, while adopting the copier-copier scaffolding (#62). The template used to declare `_tasks` (`npm install`, `npm run generate`) so a render came out with its generated output. `docs/design.md` recorded that choice.

## Decision

Remove `_tasks`. A `_message_after_copy` tells the user to run `npm install && npm run generate` after the render. A `_message_after_update` says the same after every `copier update`, once conflicts are resolved: Copier prints only `_message_after_copy` on copy, so without the second message update users would never see the instruction. The template's own tests run the same two commands after copying.

## Why

- **Tasks force `--trust`.** Copier refuses to run `_tasks` without it, and Renovate's copier manager cannot pass it, so template-update PRs for adopted repos never opened.
- **Tasks ran at the wrong moment during an update.** They generated before the user could resolve conflicts in `.ai-rulez/config.toml`, and generating without the repo's `shared_resources` rewrote every skill. `docs/adopting.md` already told adopters to skip them.
- **Nothing is lost.** Generated output was never stored in the template, so the user still builds it; only who runs the command changes.

## Consequences

- Breaking for consumers: `copier copy` no longer leaves `skills/`, the plugin manifests or `package-lock.json` behind. The message says what to run.
- `--trust` and `--skip-tasks` are no longer needed in any recipe.
- Tests render, then generate explicitly; the `package.json` layout test renders without generating on purpose.

## Adopting copier-copier

Decided in the same change: this repo adopts copier-copier selectively (cobo files, `.config/mise.toml`, branch-name, PR-title and cobo-drift workflows, `LICENSE`, `.copier-answers.yml`) and moves release-please to the `simple` type with `.github/` config and `version.txt`. The Python tooling (`pyproject.toml`, `uv.lock`, pytest) is adopted too, and the tests are written in pytest, which drives the template through Copier's own interpreter. That leaves two files that `copier update` recreates and this repo must not carry; `docs/adopting.md` lists them and says to delete them.

## Considered Options

- **Keep `_tasks`.** Rejected for the two reasons above.
- **Generate from a post-render script the template ships.** Rejected: it is `_tasks` by another name and needs the same trust.
