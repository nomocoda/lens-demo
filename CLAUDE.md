# lens-demo — Claude Code Instructions

## Autonomous commit and push authorization

You are authorized to commit and push to this repo without asking first, provided the work is validated:

- Tests relevant to the change pass (or are explicitly flagged as pre-existing failures out of scope)
- If the change touches worker.js prompts or eval scenarios, the live eval suite has been run and passes at or above the prior baseline
- If the change is observable in the browser preview, you have verified it in preview before committing
- Commit messages focus on the why, follow the repo's existing style, and carry the `Co-Authored-By: Claude Opus 4.7` trailer

Still stop and ask before:

- Force-pushing, amending a published commit, or any destructive git operation
- Pushing a branch other than the one currently checked out, or opening a PR
- Committing files that could contain secrets (`.env`, credentials, API keys)
- Changes that affect shared infrastructure beyond GitHub Pages (DNS, Cloudflare worker deploys, Asana/Notion writes beyond normal task comments)

The default push target for this repo is `origin/main`, which deploys to demo.nomocoda.com via GitHub Pages with a ~10 minute CDN cache.

## Demo file convention

The Lens Demo always means `index.html` at the repo root. Never `lens-experience.html` or any other `lens-*.html` file in the working tree. If a session asks you to edit "the demo" and no file is named, it is `index.html`.

## Eval gate

The full behavioral eval suite lives at `evals/reviewer.mjs`. Run with `ANTHROPIC_API_KEY` from `.env`. Soft failures retry 2x; hard-fail IDs are zero-tolerance (currently CQ-01, CC-02, CC-08). Known variance-prone scenarios: HO-05, CC-07, ML-03 — flag rather than block on single-run failure.

## Preview

A Claude Code preview server is typically running on this repo. Use mobile viewport 375x670 (iPhone + Chrome bars) to match Travis's real testing device.
