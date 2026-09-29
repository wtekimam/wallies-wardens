# herdr pet

A Herdr popup pane that shows each Firstmate worker as Mochi, a small amber cat-eared critter.
Each Mochi shows its worker's mood, grows as the task moves along, gets hungry while it waits on you,
and leaves a gold cup in a trophy row after its PR lands.

Plain python3 (stdlib only) with no dependencies. It makes no network calls and writes nothing.

## Install

```sh
herdr plugin link /path/to/herdr-pet
herdr plugin pane open --plugin firstmate.pet --entrypoint pet
```

Without Herdr, run `python3 pet.py` in any 80-column terminal. Run `python3 pet.py --once` to print one frame and exit.

## Config

The Firstmate home is read from, in order:

1. the `FM_HOME` environment variable
2. an `FM_HOME=/path` line in `$(herdr plugin config-dir firstmate.pet)/config`
3. `~/Documents/firstmate`

## Keys

| key | action |
|---|---|
| `1`-`4` | focus that worker's workspace and tab (`herdr workspace focus`, then `herdr tab focus`, using the ids in its meta) and close the popup |
| `r` | redraw |
| `q` / `Esc` | close |

## What it reads

Every 3 seconds, for each `state/<id>.meta` in the Firstmate home, it reads:

- `state/<id>.meta`: project, kind, spawn time, pr, Herdr ids
- the last 8 KB of `state/<id>.status`
- the mtime of `state/<id>.turn-ended` and of `state/<id>.inbox/handled/`

It never runs `bin/fm-*`, never reads panes, and never writes under the Firstmate home.
The screen is redrawn only when the frame changes.

## Rules

**Mood** comes from the last status event. `resolved` closes an open `needs-decision` or `blocked`, and the worker goes back to busy.

| mood | when | text under the label |
|---|---|---|
| busy | `working` / `paused` | building, or investigating for a scout |
| training | `working` / `paused` line mentions no-mistakes or validation | validating |
| calling | `needs-decision`, or `done` | `"your call!"`, `"PR ready!"`, `"report ready!"` (scout) |
| sick | `blocked` / `failed` | blocked / failed |
| asleep | busy or training with no status or turn activity for 30 min | silent 45m |
| party | `done` line says merged/landed, or the record of a PR-ready worker is removed | merged! |

**Growth:**

- egg: no status line yet
- baby: from the first status line
- grown: once validation starts, a PR is recorded, or a scout reports
- ready: the calling pose

**Hunger:** five hearts. They drain by one every 10 minutes, and only while the worker is calling (waiting on you). A new handled inbox message fills them again. That covers your prompts and Firstmate's, including while you are away. A worker that stops calling is also full again. Nothing else drains hunger.

**Colours and accessories:** each project gets one of eight colours from a stable hash of its name. Workers in the same project share the colour and are told apart by accessory, in this order: none, collar, scarf, cap, sunglasses, mask.

**Trophies:** when the record of a PR-ready (or merged) worker disappears, its Mochi parties for 30 seconds. Then it leaves a gold cup labelled `project · task`. Cups live only in the pane's memory, so closing the pane or restarting the session clears them.

Four creatures fit at once. Any more workers show as `+N more` in the title.

## Test

```sh
python3 -m unittest test_pet
```
