# Demo recordings

Two asciicasts + GIFs that drive the README. Reproducible from the shell scripts in this directory.

| File | Length | Purpose |
|---|---|---|
| `pitch.gif` / `pitch.cast` / `pitch.sh` | ~5s | "What is weft and why is it useful" — shows a workflow status and a guard rejection blocking `git push` |
| `walkthrough.gif` / `walkthrough.cast` / `walkthrough.sh` | ~25s | Full lifecycle on the `generic` template — start, three step transitions, event log audit |

## How they were recorded

```bash
# Requires: asciinema, agg (asciicast → GIF converter)
brew install asciinema agg
pip install -e ".[dev]"   # so the `weft` console script is on PATH

cd docs/demos
asciinema rec --overwrite --cols 90 --rows 16 --command ./pitch.sh pitch.cast
asciinema rec --overwrite --cols 90 --rows 22 --command ./walkthrough.sh walkthrough.cast

agg --theme monokai --font-size 14 pitch.cast pitch.gif
agg --theme monokai --font-size 14 walkthrough.cast walkthrough.gif
```

The shell scripts call the real `weft` CLI — there is no fakery in the output. The typed-command effect uses a small `printf` loop with sleeps so the cast is paced for human viewing instead of running at machine speed.

`pitch.sh` runs against a pre-existing workflow in `/tmp/weft-gif/.claude/weft/`. To recreate that state:

```bash
cd /tmp/weft-gif
weft start feature-workflow
weft step complete   # advance past gather-context to scope-check
```

`walkthrough.sh` creates and tears down its own scratch directory.
