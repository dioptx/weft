# Demo recordings

Five asciicasts + GIFs that drive the README. Each `.sh` is reproducible — drives the real `weft` CLI, no fakery.

| File set | Length | Purpose |
|---|---|---|
| `pitch.{cast,gif,sh}` | ~18s | **Agentic chain** — `preview feature-workflow` shows the 11-step tree with skill bindings + bounded loops + guards; `start` shows the agent now operating inside the contract. The "what + why" hit. |
| `walkthrough.{cast,gif,sh}` | ~25s | **First run** — full lifecycle on the `generic` template (start → 3× step complete → query). Companion to Quick Start. |
| `compose.{cast,gif,sh}` | ~16s | **Custom workflow on the fly** — heredoc-author a JSON template (`/perplexity` + `/staff-review` + `/fix-polish` + 3-iter loop), `save-template`, `preview`, `start`. |
| `extend.{cast,gif,sh}` | ~14s | **New skill** — author a `SKILL.md` under `.claude/skills/<name>/`, register a tiny template that references it via `skill: /<name>`, preview shows the chain. |
| `audit.{cast,gif,sh}` | ~16s | **Event sourcing** — `weft query` timeline, raw `events.jsonl`, delete `state.json`, `weft rebuild` reconstructs the full workflow from events alone. |

## How they were recorded

```bash
# Requires: asciinema, agg (asciicast → GIF converter)
brew install asciinema agg
pip install -e ".[dev]"   # so the `weft` console script is on PATH

cd docs/demos
asciinema rec --overwrite --cols 95  --rows 30 --command ./pitch.sh        pitch.cast
asciinema rec --overwrite --cols 90  --rows 22 --command ./walkthrough.sh  walkthrough.cast
asciinema rec --overwrite --cols 100 --rows 26 --command ./compose.sh      compose.cast
asciinema rec --overwrite --cols 100 --rows 24 --command ./extend.sh       extend.cast
asciinema rec --overwrite --cols 110 --rows 28 --command ./audit.sh        audit.cast

for cast in pitch walkthrough compose extend audit; do
  agg --theme monokai --font-size 13 ${cast}.cast ${cast}.gif
done
```

## Conventions

- **No fakery.** Each script invokes the real `weft` CLI. Output is whatever weft actually printed at that moment.
- **Self-contained.** Scripts create their own scratch directory under `/tmp/weft-<demo>.XXXXX/` and clean up on exit. Run them in any order, any number of times.
- **Human pacing.** A small `printf` + `sleep 0.03` per-char loop on each prompt lets viewers read commands as they "type." Pauses between interactions give time to absorb output.
- **No personal paths.** Scripts use `mktemp -d` and refer to no usernames, hostnames, or absolute home paths. Verified with `rg -i "dune|/Users/" .`.
