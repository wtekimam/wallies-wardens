# Wallie's Wardens

A Herdr pane that shows each Firstmate worker, and the main Firstmate session, as Mochi, a small amber cat-eared critter.
It opens by itself as a strip at the top of the Firstmate tab, and as a full popup on demand.
Each Mochi shows its worker's mood with a small idle animation, gets hungry while it waits on you,
and leaves a gold cup in a trophy column at the right edge for every project Firstmate records a merge for.
A captain's log keeps a short entry for each day the fleet worked, and every PR it shows is a link you can Ctrl-click.

Plain python3 (stdlib only) with no dependencies. It makes no network calls.
It writes one thing only: an answer you send from the needs-you view (`d`), which goes to Firstmate as a note in your inbox (see Answering). Nothing else is written.

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
   It then sizes the strip to 13 rows, not counting pane borders, plus 11 for each further row of Mochis (24 for a second row).
   After that the strip resizes itself: it grows when a row appears and shrinks back when one goes (`herdr pane resize` on its own pane).
   A strip you resize by hand is left alone until the number of rows changes again.

To close the strip, press `q` in it. It comes back on the next Herdr start.
To stop it for good, run `herdr plugin disable firstmate.pet` (`enable` to undo).

It can't live inside Herdr's agents sidebar.
Herdr plugins can only open terminal panes (overlay, popup, split, tab or zoomed) and can't draw in the sidebar.
A tiled strip on top of the Firstmate tab is the closest fit.

**Title:** Herdr's pane label already says `Wallie's Wardens`, so the frame's own title is a crew summary instead: `⚓ 4 aboard · 1 needs you · 2 landed today`.
`aboard` counts the workers (not the main session), `needs you` counts what waits on you (see `d`), and `landed today` counts today's merges, whichever span the trophies show. A part that would say 0 is left out, except `aboard`.
On the right of the title bar: `+N more` when more workers than fit, and `● live 3s`.

**Layout:** the frame fills the pane's width (at least 80 columns). Up to eight Mochis, as many across as fit beside the trophy column (two at 80 columns, six at 156, eight at 180), wrapping to more rows, the grid two columns in from the left border on every width (on a wide pane the space between the Mochis and the trophy column stays empty).
Any more workers show as `+N more` in the title.
Each Mochi has a two-line label: `N project` (`1 main` for the main session), then the task or session name.
Each line is cut to the column width on its own and centred under the sprite.
The trophy column (24 columns wide) sits at the right edge with one cup per project: the project name and, flush right so the counts line up, `×N` (this week's merges, or today's after `w`), the project with the newest merge on top, and a `this week: N` (`today: N`) total under the heading. `+N more` counts the projects that don't fit.
Its divider joins the frame: `┴` where it meets the footer rule or the bottom border, `┬` where it meets the top border when no title text sits there.
Press `t` for the trophy room: it replaces the Mochis and the column with a full-width list, grouped by project (cup and `project ×N`, newest project first), then one line per merge with its local time, task name (without the leading `<project>-`) and `PR #<n>` (a link to the PR, see Links) or `local`. Trophies flow into as many columns as the pane is wide; if they still do not fit, `a` and `s` page through them. `t` again returns to the Mochis.
Press `d` for what needs you: it swaps the Mochis for a full-width list of cards headed `needs you · N`, oldest wait first. Each card leads with what you have to do:

| card | when |
|---|---|
| `decide` | the worker's newest unresolved `needs-decision` line (a `resolved` or `captain-held` line closes it, the same rule that makes a Mochi call) |
| `unblock` | its newest unresolved `blocked` line |
| `review` | a `done` line waiting on your review (the worker has a `pr=` in its meta file, or is a scout) that isn't merged |

The hint reads `d needs you (N)` in the heading colour while N > 0, and plain dim `d needs you` at none. Each card has three lines, each cut to the width:
1. the action, the project and what the work is: the task's title from the home's `data/backlog.md` (without a leading `project:`), else the short task name
2. what to do: for `decide` and `unblock`, the status line's text; for `review`, `review & merge PR #<n>` (or `read the report` for a scout) and what is left of the `done` line, such as `checks green`. A PR URL in the text reads as `PR #<n>`.
3. `waiting 4d 13h`, then the PR (`pr=` in the meta file) when line 2 doesn't already show it, the report (`data/<id>/report.md`, when it exists) and `on hold to <date>` (the backlog's `hold-until`) when there are any.

Every PR shows once, as a short `PR #<n>` link to its URL. No scrolling: what doesn't fit ends in `+N more`, and an empty list says `none`. `d` again returns to the Mochis.
One card is picked (`▸`), and you can answer it here instead of in chat with Firstmate (see Answering). The picked card always shows; cards before it make room.
A Mochi that is calling about a decision also gets a short tag on its second label line: `task · <decision text>`, cut to fit.
Press `c` for the captain's log: it swaps the Mochis for one entry per day the ledger has records for, newest day first, wrapped to the pane width (see Rules). When the entries don't fit, `a` and `s` page through them. `c` again returns to the Mochis.
The footer, under a rule that joins the frame, shows `t trophies`, `d needs you (N)`, `c log`, `w today` (`w week` once toggled) (`back` for the open view), `r redraw` and `q close`.
When the pane is too short for the full panel (16 rows, plus 11 per further row of Mochis), the pet draws the strip:
the same Mochis and trophy column, with `q close`, `t trophies`, `d needs you (N)`, `c log` and `w today` after `● live 3s` in the title bar. The title there leaves out `needs you`, since `d needs you (N)` says it on the same line.
When the bar is tight, the least important part goes first: `w`, then `c`, then `landed today`, then `t`, then `needs you`, then `d`. `⚓ N aboard`, `+N more` and `q close` always stay. With something waiting, `d` outlives `t`; with the log open, `c back` outlives both. `t`, `d` and `c` work there too, and the strip keeps its height when you switch.
The strip needs 13 rows, plus 11 per further row. It redraws when the pane is resized.

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
| `t` | toggle the trophy room (the Mochis come back on the next `t`) |
| `a` / `s` | previous / next page of the trophy room or the log (only when it has more than one) |
| `d` | toggle what needs you: decisions, blockers and reviews (the Mochis come back on the next `d`) |
| `c` | toggle the captain's log (the Mochis come back on the next `c`) |
| `w` | switch the trophy column and room between this week (the default; calendar week from Monday, local time) and today; in the week the room shows each merge as `Mon 14:05` |
| `r` | redraw |
| `q` | close |
| `Esc` | close the popup (the strip ignores it, so arrow keys don't close it) |

In the needs-you view (`d`):

| key | action |
|---|---|
| `a` / `s` | pick the previous / next card |
| `1`–`9` | answer with that option, when the card's text lists options |
| `e` | type an answer; `Enter` ends it, Backspace deletes, Ctrl-U clears |
| `f` | send the answer shown on the card |
| `Esc` | cancel the answer (it closes nothing while an answer is open) |

While you type an answer, or while one waits for `f`, every key belongs to it: `q`, `t`, `d` and the rest are letters of the answer or wait, and only `Esc` (or Ctrl-C, which closes the pane) gets out.

Every key sits under the left hand, except `Enter` to end a typed answer. The old `l` (log) and `n` / `p` (pages and, in `d`, cards) still work but are not shown.

## Answering

Press `d`, pick a card with `a` / `s`, then answer it:

1. When the card's text lists options, the picked card shows them numbered (`1 (a) accept the PR with no CI`). Options are read from the free text in three forms: lettered or numbered marks in order (`(a) … (b) …`, `a) … b) …`, `(1) … (2) …`), `Options: A …; B …`, or a closing question `X, Y, or Z?`, each part kept as written (`Should I squash the commits or keep them?` gives `1 Should I squash the commits` and `2 keep them`). A repeated mark later in the text (`Recommend (a)`) is not an option. A card whose text lists none shows no numbers.
2. Press the option's number, or `e` to type any answer and `Enter` to end it. Any card can be answered this way: `decide`, `unblock` or `review`.
3. The card shows the exact answer, `send › <answer>`, with `f send to Firstmate · Esc cancel`. Nothing is sent until you press `f`. `Esc` drops the answer.
4. After `f` the card shows a receipt: `✓ sent to Firstmate (note <id>) · <answer>`, `✓ already sent …` for a repeat, or `✗` and what went wrong. A failed send is never retried; send it again yourself.
   A decision that closes while its answer waits for `f` is not answered: `✗ not sent: it closed before f`.

`f` runs the Firstmate home's own `bin/fm-inbox.sh note --request-id <id> --json -- <text>` (with `FM_HOME` set to that home), the same path as a note you write to Firstmate, so Firstmate reads it at its next check and decides what to do. Nothing happens on its own.
The note stands alone: it names the project and task, the task's backlog title, which decision it answers (its `[key=…]` and when it was raised) with the decision's full text, and your answer, in its first line so Firstmate's summary of the note shows it.
The request id is `wardens-` and a hash of the task, the decision (its key, its `at=` and its text) and the answer, so pressing `f` again on the same answer replays the first note instead of sending a second. A different answer, or the same question raised again later, is a new note.

## What it reads

Every 3 seconds, for each `state/<id>.meta` in the Firstmate home, it reads:

- `state/<id>.meta`: project, kind, spawn time, Herdr ids
- the last 8 KB of `state/<id>.status`
- the mtime of `state/<id>.turn-ended` and of `state/<id>.inbox/handled/`
- whether `data/<id>/report.md` exists, only for a worker that needs you
- `data/backlog.md`, for the title and `hold-until` of a worker that needs you, read again only when its mtime changes
- `state/fleet-ledger.jsonl`, for trophies and the captain's log (see below). It remembers a byte offset, so each poll parses only the lines appended since the last, and it stops at a half-written last line until its newline arrives.
  A missing file, blank or malformed lines, and unknown events or members are ignored.
  A truncated file starts the trophies over.

For the main session it reads the `agent_status` of the Herdr pane whose cwd is the Firstmate home, from `herdr pane list` (once every 3 seconds, the same poll).

It never reads pane contents and never writes under the Firstmate home itself. The one Firstmate script it runs is `bin/fm-inbox.sh note`, only when you press `f` on an answer (see Answering); that script saves the note in the home's inbox. It runs no other `bin/fm-*`.
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
| party | `done` line says merged/landed, or a merge record for it arrives in the ledger (30 s) | merged! |

**Main session:** one extra Mochi, always first, labelled `1 main` over `firstmate`. It shows only while Herdr has a pane whose cwd is the Firstmate home; with none (or without Herdr, or `--once` outside it) there is no main Mochi and no error. It counts toward the eight.
Its mood comes from that pane's `agent_status`, not from status files:

| `agent_status` | mood | text under the label |
|---|---|---|
| `working` | busy | main session |
| `blocked` | calling | `"needs you!"` |
| `idle` (also `done`, `unknown`) | asleep | main session |

It has no hearts (the line reads `main session`), no accessory rotation (always the collar).

**Hunger:** five solid hearts (●, hollow ○ when lost), then `fed` or `waiting 25m` (just `4d 13h` when the word would not fit the cell). They drain by one every 10 minutes, and only while the worker is calling (waiting on you). A new handled inbox message fills them again. That covers your prompts and Firstmate's, including while you are away. A worker that stops calling is also full again. Nothing else drains hunger.

**Look:** every worker is the Mochi from the approved design, in every layout. The test suite checks each mood, colour and accessory against it, pixel by pixel.
Each sprite pixel is half a cell. Every cell split between two colours, or between a colour and the background, is drawn as an upper half block `▀` (in reverse video when only its lower half is coloured), so every split in a line falls at the same height. Ghostty draws `▀` and `▄` each `round(height / 2)` tall, so in an odd-height cell (8×17 at 1x with its built-in font) mixing them would put one-pixel steps in the sprite's edges.
The frame has rounded corners. Every view shares one palette (Tokyo Night): headings, the title's `needs you` and the calling tag in violet; key letters, label numbers, times and dates in amber; cups and their counts in gold; names in light text, task names a shade quieter, moods and card actions in their mood colours, everything else in a dim that still reads at 5:1 on the dark background, lines in the frame colour.

**Colours and accessories:** the main session is blue, a ninth colour no project gets, with an orange collar so it shows. Each project gets one of eight colours from a stable hash of its name. Workers in the same project share the colour.
Every worker wears an accessory, given in this order within its project: collar, scarf, cap, sunglasses, mask, then round again.
A worker keeps its accessory, and a newcomer takes the first one free in its project.
The collar is cyan, except on a teal Mochi, where it is red so it shows.

**Trophies:** every `task.merged` record in the Firstmate home's fleet activity ledger (`state/fleet-ledger.jsonl`) counts toward its project's gold cup (`×N`), whether the PR merged on GitHub or a local-only branch landed.
The project comes from the task's `task.dispatched` record, else the `project=` basename in `state/<id>.meta`, else the longest project name in the home's `data/projects.md` that the task id starts with (followed by `-`), else it is left out.
Both views show this calendar week's merges by default (Monday 00:00 local onward, headed `this week`); `w` narrows them to today (local day of the record's `ts`). The room reads `PR #<n>` from the record's `pr` URL, or `local` for `via: local`. Cups come from the file, so closing the pane or restarting keeps them.
When a merge record arrives for a Mochi that is still shown, it parties for 30 seconds. Records already in the file at startup, or for a Mochi that is gone, don't party.
A merge only counts when Firstmate records it and the ledger is on for that home (the `config/fleet-ledger` flag, see Firstmate's `docs/fleet-ledger.md`). With the flag off there are no cups.
A repeated record for the same task and time counts once.

**Captain's log:** built from the same ledger, so it needs the ledger on too, and it is kept for as long as the ledger file is.
Each entry is put together from fixed sentences, in this order, leaving out any that would say nothing:

| sentence | from |
|---|---|
| `Day 2026-10-09.` | the local day of the records' `ts` |
| `Three tasks set sail.` | `task.dispatched` |
| `Two PRs landed (client-kara #25, kara-portal #4).` | `task.merged` with a PR; each `#<n>` is a link to its PR |
| `Two local branches landed (herdr-pet ×2).` | `task.merged` with `via: local` |
| `Four tasks reported done.` | `task.status` `done`, once per task a day |
| `Two decisions raised, one answered.` | `needs-decision` lines, then the `resolved` or `captain-held` lines that close one |
| `One blocker hit, one cleared.` | the same for `blocked` |
| `One task ran aground (garmin).` | `failed` |
| `client-kara waits on your call.` / `mapa is stuck on a blocker.` | the tasks still on an open decision or blocker after the day's last record (`waited` / `was` for past days) |

A day with records but none of these reads `Quiet seas.`
Projects are named the same way as for trophies, else the task id is used.
A decision stays open until a `resolved` or `captain-held` line, any later status line of that task, its merge, or its cleanup (`task.cleaned_up`). Asking it again while it is open does not count as a new one.
Repeated status records (same task, time, state and text) count once.

**Links:** every PR Wardens shows is an OSC 8 terminal hyperlink to the full PR URL: the needs-you card's `PR #<n>` (from `pr=` in the meta file, or a PR URL in its status line), the trophy room's `PR #<n>` and the log's `#<n>` (from the ledger record's `pr`). The text and its width don't change.
In Herdr, Ctrl-click opens it (on macOS too while Herdr captures the mouse, as Herdr's docs describe). In a plain terminal that supports OSC 8, use that terminal's link click, often Cmd-click. A terminal without OSC 8 shows the same text, not clickable.
A merge record with no PR URL is never linked, and only plain `http(s)://` URLs are.

## Test

```sh
python3 -m unittest test_pet
```
