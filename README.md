# herdr pet

A Herdr pane that shows each Firstmate worker, and the main Firstmate session, as Mochi, a small amber cat-eared critter.
It opens by itself as a strip at the top of the Firstmate tab, and as a full popup on demand.
Each Mochi shows its worker's mood with a small idle animation, gets hungry while it waits on you,
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

Without Herdr, run `python3 pet.py` in any terminal at least 80 columns wide. Run `python3 pet.py --once` to print one frame and exit, or `--once --strip` for the strip's frame.

## The startup strip

A `[[startup]]` hook runs `pet.py --pin` once each time Herdr starts, after it restores the session:

1. If a pet pane is already open and running, it does nothing, so a second run never opens a second strip.
   Herdr restores a closed session's pet pane as a bare shell, not the pet. `--pin` closes that shell and opens a fresh strip.
2. Otherwise it opens the pet in a split under the pane whose cwd is the Firstmate home.
   With no such pane, it uses the focused pane of the active tab.
   Herdr only splits right or down, so it then swaps the two panes (`herdr pane swap`) to put the pet on top.
3. It opens without focus. A swap focuses a pane, so `--pin` puts focus back where it was: the same pane, or your other tab or workspace.
   It then sizes the strip to 13 rows, not counting pane borders, or 23 when the workers need a second row of Mochis.
   After that the strip resizes itself: it grows when a second row appears and shrinks back when it goes (`herdr pane resize` on its own pane).
   A strip you resize by hand is left alone until the number of rows changes again.

To close the strip, press `q` in it. It comes back on the next Herdr start.
To stop it for good, run `herdr plugin disable firstmate.pet` (`enable` to undo).

It can't live inside Herdr's agents sidebar.
Herdr plugins can only open terminal panes (overlay, popup, split, tab or zoomed) and can't draw in the sidebar.
A tiled strip on top of the Firstmate tab is the closest fit.

**Layout:** up to eight Mochis, as many across as the pane is wide (four at 80 columns, eight at 156), wrapping to a second row.
Any more workers show as `+N more` in the title.
When the pane is too short for the full panel (19 rows, or 29 with a second row of Mochis), the pet draws the strip:
the same Mochis, each with its label, mood, hearts and bubble, and the trophies and keys on one line.
The strip needs 13 rows, or 23 with a second row. It redraws when the pane is resized.

## Config

The Firstmate home is read from, in order:

1. the `FM_HOME` environment variable
2. an `FM_HOME=/path` line in `$(herdr plugin config-dir firstmate.pet)/config`
3. `~/Documents/firstmate`

**Animation:** each Mochi moves a little, two frames per mood, about twice a second: busy and asleep breathe (asleep at half speed),
calling jumps, training and party bounce, sick shivers. Neighbours move out of step.
To keep them still, set `PET_ANIMATE=0`, either in the environment or as a line in the same config file.
With eight animated Mochis the pane used about 0.4% of one CPU core, measured over 3 minutes (about 0.2% still).

## Keys

| key | action |
|---|---|
| `1`-`8` | focus that worker's workspace and tab (`herdr workspace focus`, then `herdr tab focus`, using the ids in its meta). The popup closes; the strip stays |
| `r` | redraw |
| `q` | close |
| `Esc` | close the popup (the strip ignores it, so arrow keys don't close it) |

## What it reads

Every 3 seconds, for each `state/<id>.meta` in the Firstmate home, it reads:

- `state/<id>.meta`: project, kind, spawn time, Herdr ids
- the last 8 KB of `state/<id>.status`
- the mtime of `state/<id>.turn-ended` and of `state/<id>.inbox/handled/`

For the main session it reads the `agent_status` of the Herdr pane whose cwd is the Firstmate home, from `herdr pane list` (once every 3 seconds, the same poll).

It never runs `bin/fm-*`, never reads pane contents, and never writes under the Firstmate home.
Only `--pin`, the pinned strip and the poll's `pane list` call Herdr.
`--pin` calls `pane list`, `workspace list`, `pane process-info`, `plugin pane open`, `pane swap`, and `pane close` for a restored shell.
To put focus back it calls `workspace focus`, `tab focus`, `pane neighbor` or `pane focus`.
To size the strip, `--pin` and the strip call `pane neighbor`, `pane layout`, `pane get` and `pane resize`.
The strip does that only when its row count changes.
Status files are read every 3 seconds whether or not the Mochis animate. Between reads, only the lines that changed are redrawn.

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

**Main session:** one extra Mochi, always first (key `1`), labelled `main · firstmate`. It shows only while Herdr has a pane whose cwd is the Firstmate home; with none (or without Herdr, or `--once` outside it) there is no main Mochi and no error. It counts toward the eight.
Its mood comes from that pane's `agent_status`, not from status files:

| `agent_status` | mood | text under the label |
|---|---|---|
| `working` | busy | main session |
| `blocked` | calling | `"needs you!"` |
| `idle` (also `done`, `unknown`) | asleep | main session |

It has no hearts (the line reads `main session`), no accessory rotation (always the collar), and no focus cost: `1` focuses its workspace and tab like any worker.

**Hunger:** five solid hearts (●, hollow ○ when lost). They drain by one every 10 minutes, and only while the worker is calling (waiting on you). A new handled inbox message fills them again. That covers your prompts and Firstmate's, including while you are away. A worker that stops calling is also full again. Nothing else drains hunger.

**Look:** every worker is the Mochi from the approved design, in every layout. The test suite checks each mood, colour and accessory against it.

**Colours and accessories:** the main session is blue, a ninth colour no project gets, with an orange collar so it shows. Each project gets one of eight colours from a stable hash of its name. Workers in the same project share the colour.
Every worker wears an accessory, given in this order within its project: collar, scarf, cap, sunglasses, mask, then round again.
A worker keeps its accessory, and a newcomer takes the first one free in its project.
The collar is cyan, except on a teal Mochi, where it is red so it shows.

**Trophies:** when the record of a PR-ready (or merged) worker disappears, its Mochi parties for 30 seconds. Then it leaves a gold cup labelled `project · task`. Cups live only in the pane's memory, so closing the pane or restarting the session clears them.

## Test

```sh
python3 -m unittest test_pet
```
