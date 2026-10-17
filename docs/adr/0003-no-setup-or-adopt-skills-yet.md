# No setup or adopt skills yet; keep the CONTRIBUTING checklist and an adoption recipe

Decided 2026-10-17, after scoop-bucket-skills and homebrew-tap-skills were adopted, ghost-library-skills was in review and scoop had run its first `copier update`. The design (`docs/design.md`) deferred this: v1 ships no `setup` or `adopt` skills, to be decided once two repos were adopted and the repeated steps were known.

## Repeated steps

Across the three adoptions and the update, these repeated: deriving the answers from the repo's existing files; undoing what the render clobbers (`README.md`, the version in `package.json` and the release manifest, the placeholder skill); reconciling `.ai-rulez/config.toml` without losing the repo's preset, opt-outs and shared resources; replacing the old version carrier, release guard and task runner; keeping the repo's Python tests behind `npm test` and one extra CI step; layering repo content onto `CONTRIBUTING.md` and `docs/installation.md`; fixing stale command references; writing an ADR of the differences; and, after the merge, renaming the required check to `check`. Review bots raised the same themes each round: documentation claiming more than the recorded evidence, stale references, and the disabled `AR9T0` rule. The update conflicted on the repo's README, `config.toml` and `CONTRIBUTING.md`. The full list is in `docs/adopting.md`.

## Decision

Add no skills yet. Keep the one-time setup checklist in the template's `CONTRIBUTING.md` and record the recipe in `docs/adopting.md`. Revisit after infra-copilot is adopted and `gitops-skills` exists, which are the only remaining adoption and the only planned new repo.

## Why

- **Cost against use.** One adoption and one new repo remain. A skill needs a spec, evals and upkeep alongside the template.
- **Most repetition was template defects.** The README skeleton conflicting with every adopter's README, the version reset, the `AR9T0` gap (fixed in v0.3.0) and the installation-page gaps each cost steps that fixing the template removes. Automating them would have hidden the defects.
- **The steps that need judgment stay manual either way:** what to keep in the config, which differences are deliberate, and what each ADR says.

## Considered Options

- **`adopt` skill** modeled on copier-pyproject's, living in the new skill repo. Worth it if more adoptions follow infra-copilot; not worth it for one.
- **`adopt` and `update` skills.** The update path is proven once; one data point is too few.
- **`setup` skill.** Setup is `copier copy` plus the GitHub checklist already in `CONTRIBUTING.md`, so it adds the least.
- **Defer the decision** until infra-copilot is adopted. Rejected: the condition the design set, two adopted repos, is met, and the recipe is cheap to write now.

## Consequences

- Revisit trigger: infra-copilot adopted and `gitops-skills` created, or a fifth repo asking for the same steps.
- If skills are added later, they belong in the new skill repo, so this decision connects to its name and starting version.
