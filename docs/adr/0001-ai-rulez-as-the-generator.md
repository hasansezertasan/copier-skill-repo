# ai-rulez is the generator behind every skill repo

The scaffold treats `.ai-rulez/` as the source of truth and builds plugin manifests, marketplaces and root `skills/` with ai-rulez v5, pinned in `devDependencies`. It is the only surveyed tool (Oct 2026) that targets Claude Code, Codex, OpenCode and Pi, emits versioned plugin manifests and has CI gates (`validate --strict`, `generate --check`). Its community is small (161 stars).

## Considered Options

- **rulesync** (1.5k stars): covers all four runtimes for skills, but emits only Claude plugin manifests, so the template would own Codex packaging, version bumps and drift checks.
- **ruler, openskills, skillkit, ai-rules-sync**: no plugin manifest generation.
- **`npx skills`**: an installer, not a generator. Kept as the consumer-side install path.
