# herdr pet

A Herdr pane that shows each Firstmate worker as Mochi, a small amber cat-eared critter.
It opens by itself as a short strip at the bottom of the Firstmate tab, and as a full popup on demand.
Each Mochi shows its worker's mood, grows as the task moves along, gets hungry while it waits on you,
and leaves a gold cup in a trophy row after its PR lands.

Plain python3 (stdlib only) with no dependencies. It makes no network calls and writes nothing.

## Install

```sh
herdr plugin link /path/to/herdr-pet
```

Needs Herdr 0.9 or newer. The strip appears on the next Herdr start. To get it now, or back after closing it:

```sh
herdr plugin action invoke firstmate.pet.pin     # the strip, same as at startup
herdr plugin pane open --plugin firstmate.pet --entrypoint pet   # the full panel as a popup
```

Without Herdr, run `python3 pet.py` in any 80-column terminal. Run `python3 pet.py --once` to print one frame and exit, or `--once --compact` for the strip's frame.

## The startup strip

A `[[startup]]` hook runs `pet.py --pin` once each time Herdr starts, after it restores the session:

1. If a pet pane is already open and running, it does nothing, so a second run never opens a second strip.
   Herdr restores a closed session's pet pane as a bare shell, not the pet. `--pin` closes that shell and opens a fresh strip.
2. Otherwise it splits the pane whose cwd is the Firstmate home (downwards) and opens the pet under it.
   With no such pane, it uses the focused pane of the active tab.
3. It opens without focus, so your cursor stays where it was, then shrinks the strip to about 8 rows.

To close the strip, press `q` in it. It comes back on the next Herdr start.
To stop it for good, run `herdr plugin disable firstmate.pet` (`enable` to undo).

It can't live inside Herdr's agents sidebar.
Herdr plugins can only open terminal panes (overlay, popup, split, tab or zoomed) and can't draw in the sidebar.
A tiled strip under the Firstmate tab is the closest fit.

**Layout:** when the pane is shorter than 19 rows, the pet draws a compact one-line-per-worker view (face, task, mood, age, hearts and bubble) with trophies on one line. It needs 7 rows for four workers.
A taller pane gets the full panel. It redraws when the pane is resized.

## Config

The Firstmate home is read from, in order:

1. the `FM_HOME` environment variable
2. an `FM_HOME=/path` line in `$(herdr plugin config-dir firstmate.pet)/config`
3. `~/Documents/firstmate`

## Keys

| key | action |
|---|---|
| `1`-`4` | focus that worker's workspace and tab (`herdr workspace focus`, then `herdr tab focus`, using the ids in its meta). The popup closes; the strip stays |
| `r` | redraw |
| `q` | close |
| `Esc` | close the popup (the strip ignores it, so arrow keys don't close it) |

## What it reads

Every 3 seconds, for each `state/<id>.meta` in the Firstmate home, it reads:

- `state/<id>.meta`: project, kind, spawn time, pr, Herdr ids
- the last 8 KB of `state/<id>.status`
- the mtime of `state/<id>.turn-ended` and of `state/<id>.inbox/handled/`

It never runs `bin/fm-*`, never reads panes, and never writes under the Firstmate home.
Only `--pin` calls Herdr (`pane list`, `pane process-info`, `plugin pane open`, `pane layout`, `pane resize`, and `pane close` for a restored shell).
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

Four creatures fit at once, in both layouts. Any more workers show as `+N more` in the title.

## Test

```sh
python3 -m unittest test_pet
```
