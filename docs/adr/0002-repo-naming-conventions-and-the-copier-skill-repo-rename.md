# Copier template repos are `copier-<subject>`, skill repos are `<subject>-skills`, and this template is `copier-skill-repo`

Two naming conventions, one rule to tell them apart, and the rename that followed (decided 2026-10-17, after v0.1.2).

## Conventions

- **Copier template repos** are named `copier-<subject>`, where the subject is the kind of repo the template generates: `copier-pyproject`, `copier-homebrew-tap`, `copier-skill-repo`.
- **Skill repos** are named `<subject>-skills`: `scoop-bucket-skills`, `ghost-library-skills`, `homebrew-tap-skills`, `gitops-skills`. `infra-copilot` is the one pre-existing outlier and keeps its name.
- **Telling them apart:** a name ending in `-skills` is a skill repo; a `copier-` name that does not end in `-skills` is a template. No valid name satisfies both, so the rule cannot misfire.

## The problem

The template was named `copier-skills`. Applied mechanically, the two conventions give that same name to two opposite things:

- `copier-<subject>` with subject `skills`: a Copier template that generates skill repos (this repo).
- `<subject>-skills` with subject `copier`: a skill repo that teaches agents to manage, maintain and apply best practices to Copier template repos (a repo we want to create).

One name, two repos, and a reader cannot tell which generates which. The new skill repo would also look like an output of its own sibling.

## Decision

Rename the template to `copier-skill-repo`. The name follows `copier-<subject>` with the generated kind of repo as the subject (the same way `copier-homebrew-tap` names a homebrew tap), and it matches the glossary term **Skill repo** in `CONTEXT.md`. The name `copier-skills` is left free for the skill repo about Copier.

The conventions are guidance for the maintainer, not a template rule. The template neither enforces `<subject>-skills` nor mentions it in the `repo_name` help text, so any name that passes the existing validator stays valid, `infra-copilot` included. Decided 2026-10-17: flexibility over enforcement.

Order of work: rename the GitHub repo (GitHub redirects the old URLs), update the live references in this repo, then correct `_src_path` and links in each downstream repo, one PR each. Create the new `copier-skills` skill repo only after every adopter points at the new name; creating it earlier would break the redirect from the old template URL.

## Considered Options

| Template name | Skill repo name | Verdict |
| --- | --- | --- |
| **`copier-skill-repo`** | `copier-skills` | **Chosen.** Matches the glossary term "Skill repo" and the `copier-homebrew-tap` pattern of naming the generated kind. |
| `copier-skills` (keep) | `copier-template-skills` | Costs nothing today, but the template is then the lone exception to the `-skills` rule, and the collision logic stays one step from biting again. |
| `copier-skill-plugin` | `copier-skills` | Names the plugin, but `CONTEXT.md` lists "Plugin repo" as a term to avoid. |
| `copier-skills-repo` | `copier-skills` | One letter from `copier-skills`; easy to mistype or confuse. |
| `copier-agent-skills` | n/a | Ends in `-skills`, so by the rule it reads as a skill repo. Reintroduces the collision. |
| `copier-skillpack`, `copier-skillset` | `copier-skills` | Invented words that neither the glossary nor the ecosystem uses. |

Known cost of the chosen name: `-repo` is mildly redundant, since every name here is a repo. A bare `copier-skill` would read as one skill, not a skill repo, so the noun stays.

## Constraints checked against primary sources (Oct 2026)

- **Copier** prescribes no repo name. Public templates are discovered through the `copier-template` GitHub topic; `copier update` resolves git tags, not names. `copier-uv` (pawamoy) and the Poetry and PDM templates on that topic page show the `copier-` prefix is common; a wider claim that it is the standard was not verified.
- **Skill names** (Agent Skills specification): 1 to 64 characters of lowercase `a-z`, `0-9` and hyphens; no leading or trailing hyphen; no `--`; must equal the parent directory name. The template's `repo_name` and `placeholder_skill` validators apply the same rules and additionally require a leading letter.
- **Plugin names** (Claude Code plugin manifest): non-empty, no spaces, `@`, `:` or path separators; kebab-case recommended. `claude plugin validate` errors on names starting with `claude-`, `anthropic-`, `anthropics-` or `cc-plugin-`, and on `claude` or `anthropic` beside `official`. In this template `repo_name` is also the plugin name, the marketplace name and the npm package name, so a skill repo named `claude-<x>-skills` would fail validation. The `repo_name` validator does not check this yet.
- `<subject>-skills` has no external source; it is this project's own convention.

## Consequences

- Live references updated here: `AGENTS.md`, `package.json`, `README.md`, `CONTEXT.md`, `docs/design.md`, the template-owned `CONTRIBUTING.md.jinja` link and the placeholder skill text (both reach rendered repos through `copier update`), and a temp-directory prefix in the tests. The compare, issue and commit links in `CHANGELOG.md` were migrated too, so no file in the repo names `copier-skills` as the template; release-please writes later entries with the new URL.
- Downstream, confirmed: `scoop-bucket-skills` records `_src_path: https://github.com/hasansezertasan/copier-skills` in `.copier-answers.yml`, links the old URL in `CONTRIBUTING.md`, and names the template in its own ADR `0002-adopt-the-copier-skills-template.md` (edit the prose, keep the filename). Adoptions in flight (`ghost-library-skills`, `infra-copilot`, `homebrew-tap-skills`) should start from the new name. Code search is fuzzy and covers default branches only, so unmerged adoption branches may hold more.
- Renovate in downstream repos may track `_src_path` by URL; it should follow the redirect, which has not been verified, so correct the URL there anyway.
- Open follow-up: reject Anthropic-reserved plugin-name prefixes in the `repo_name` validator, so the failure shows at render time rather than at `claude plugin validate`.
