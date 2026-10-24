# Leave the generated `.gitignore` to the project

Decided 2026-10-24, across the copier templates (copier-copier, copier-infra) that already seed the cobo-managed boilerplate once.

## Decision

List `.gitignore` in `_skip_if_exists`. A new repo gets the template's file; after that it belongs to the repo, which may replace it with output from [cobo](https://github.com/hasansezertasan/cobo) tracked in `cobo.lock`. `copier update` preserves a file that exists and does not merge template changes into it; a deleted one is reseeded on the next update.

## Why

- **A cobo-managed file has a sealed block.** `copier update` three-way merges template-owned files, so the next change to the template's `.gitignore` would conflict with the block cobo rendered.
- **The template's copy is only a starting point.** It is a single `node_modules/` line, which a repo is expected to outgrow.

## Consequences

- Template changes to `.gitignore` no longer reach existing repos; each repo owns it.
- `tests/test_update.py` replaces the repo's `.gitignore` before an update and asserts the update leaves it alone.

## Considered Options

- **Keep merging it on update.** Rejected: conflicts with cobo-managed files.
- **Drop it from the template.** Rejected: a fresh render would start without the `node_modules/` ignore.
