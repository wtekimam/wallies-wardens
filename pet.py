#!/usr/bin/env python3
"""Wallie's Wardens: one Mochi per Firstmate worker, plus one (blue, first) for the main Firstmate session, in a Herdr pane (a strip on top of the Firstmate tab, or a popup).

Read-only view of a Firstmate home. The main session's mood is the agent_status of the Herdr pane whose cwd is the home
(`herdr pane list`, once per poll). Per worker it reads only state/<id>.meta, the tail of
state/<id>.status, the mtime of state/<id>.turn-ended and the mtime of state/<id>.inbox/handled/.
What needs the captain (a worker's newest unresolved needs-decision or blocked line, or a done line waiting on review) is shown from the same status tail;
its title and hold come from data/backlog.md, its report is data/<id>/report.md when that exists, its PR the meta file's pr=.
Trophies and the captain's log (one entry a day, from templates) come from state/fleet-ledger.jsonl (read by byte offset, only new lines each poll).
Every PR shown is an OSC 8 hyperlink to its URL; Herdr opens it on Ctrl-click.
It never writes under the Firstmate home and never runs Firstmate scripts.

  python3 pet.py            live pane: read status every 3s, animate about twice a second, redraw only changed lines
  python3 pet.py --once     print one frame to stdout and exit (--once --strip: the strip's frame)
  python3 pet.py --pin      open the pet as a strip on top of the Firstmate tab unless one is open (startup hook)

PET_ANIMATE=0 (environment, or a line in the plugin config file) keeps the Mochis still.
"""
import datetime, functools, json, math, os, re, sys, time, unicodedata, zlib

POLL = 3                 # seconds between polls
ASLEEP_SECS = 30 * 60    # no status or turn activity this long (and not calling) -> asleep
HUNGER_STEP = 10 * 60    # one heart lost per this long spent calling without a new message
PARTY_SECS = 30          # how long a worker parties after a merge record for it arrives
ANIM = 0.5               # seconds between animation frames (status files are still read every POLL)
SHOWN = 8                # creatures on screen; the rest become "+N more"
DEFAULT_HOME = os.path.expanduser("~/Documents/firstmate")

# ---- tiny markup: {#rrggbb} fg, {@rrggbb} bg, {b} bold, {/} reset (lifted from the design build.py); {>url} opens a link, {>} closes it ----
URL = r"https?://[!-z|~]+"  # printable ASCII without the markup's braces: nothing in it can break out of the OSC 8 sequence
TAG = re.compile(r"\{(?:([#@])([0-9a-fA-F]{6})|(b)|(/)|>(" + URL + r")?)\}")
# one palette for every view: text, quiet text, lines; headings and what needs you; keys, numbers and times; trophies
FG, SUB, DIM, FRAME = "#c0caf5", "#a9b1d6", "#8089b3", "#3b4261"  # DIM: 5:1 on Tokyo Night's background, readable for times and secondary text
HEAD, KEY, GOLD, LIVE, HEART = "#bb9af7", "#e0af68", "#f7d774", "#9ece6a", "#f7768e"

def parse(s):  # -> [(text, fg, bg, bold, link)]; {/} resets the colours but not the link
    segs, fg, bg, bold, ln, pos = [], None, None, False, None, 0
    for m in TAG.finditer(s):
        if m.start() > pos: segs.append((s[pos:m.start()], fg, bg, bold, ln))
        if m.group(1) == "#": fg = "#" + m.group(2)
        elif m.group(1) == "@": bg = "#" + m.group(2)
        elif m.group(3): bold = True
        elif m.group(4): fg = bg = None; bold = False
        else: ln = m.group(5)
        pos = m.end()
    if pos < len(s): segs.append((s[pos:], fg, bg, bold, ln))
    return segs

def width(t): return len(t) if t.isascii() else sum(1 + (unicodedata.east_asian_width(ch) in "WF") for ch in t)  # ⚓ takes two columns

@functools.lru_cache(maxsize=4096)  # animation redraws the same few lines over and over
def vis(s): return sum(width(t) for t, *_ in parse(s))
def rgb(h): return ";".join(str(int(h[i:i+2], 16)) for i in (1, 3, 5))

@functools.lru_cache(maxsize=4096)
def to_ansi(s):
    out, cur, ln = [], (None, None, False), None
    for t, fg, bg, bold, url in parse(s):
        st = (fg, bg, bold)
        if st != cur:
            codes = ["0"] + (["1"] if bold else []) + ([f"38;2;{rgb(fg)}"] if fg else []) + ([f"48;2;{rgb(bg)}"] if bg else [])
            out.append(f"\x1b[{';'.join(codes)}m"); cur = st
        if url != ln: out.append(f"\x1b]8;;{url or ''}\x1b\\"); ln = url  # OSC 8: a terminal hyperlink, zero columns wide
        out.append(t)
    return "".join(out) + ("\x1b]8;;\x1b\\" if ln else "") + "\x1b[0m"  # a link never runs past its line

def c(col, text, bold=False): return f"{{#{col.lstrip('#')}}}{'{b}' if bold else ''}{text}{{/}}"
def link(url, text): return f"{{>{url}}}{text}{{>}}" if isinstance(url, str) and re.fullmatch(URL, url) else text  # anything else stays plain text
def center(s, w):
    n = max(0, w - vis(s)); return " " * (n // 2) + s + " " * (n - n // 2)
def padr(s, w): return s + " " * max(0, w - vis(s))
def clip(t, n): return t if len(t) <= n else t[:max(0, n - 1)] + "…"

# ---- Mochi: 12x12 px grids, row 0 empty (room to hop). '.' empty; letters map through the palette then PROPS ----
def G(rows):
    assert len(rows) == 12 and all(len(r) == 12 for r in rows), rows
    return [list(r) for r in rows]

def put(g, edits, over=False):  # over: only paint empty cells (props never clobber the creature)
    for r, col, s in edits:
        for i, ch in enumerate(s):
            if ch != "_" and 0 <= col + i < 12 and 0 <= r < 12 and (not over or g[r][col + i] == "."): g[r][col + i] = ch
    return g

def up(g):  # hop: whole sprite one pixel up
    return g[1:] + [["."] * 12]

def mix(h, h2, t):
    a, b = [int(h[i:i+2], 16) for i in (1, 3, 5)], [int(h2[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))

PROPS = dict(E="#2b2118", N="#2b2118", M="#5a2230", T="#f7768e", R="#f7768e", Y="#f7d774", y="#c99a2e", C="#7dcfff", G="#9ece6a",
             P="#ff9ec7", S="#8b93b0", s="#3b4261", K="#cfe8ff", k="#8fb4d8", Z="#9db1ff", z="#7d8fd0", D="#c99a62", O="#d4e157", W="#f4f4f8", L="#7dcfff")
TINT = "BdWAb"  # sick/asleep tint touches only the creature's own colours

# The agreed Mochi (design build.py). ER = eye row, CL/CR = eye columns, MR = mouth row, HB = headband row
MOCHI = ["............", "..A......A..", "..AP....PA..", "..ABBBBBBA..", "..BBBBBBBB..", "..BEBBBBEB..",
         ".wBBBPPBBBw.", "..BBBMMBBB..", "...BBBBBB.b.", "...BWWWWB.b.", "...BWWWWBbb.", "...BB..BB..."]
ER, (CL, CR), MR, HB = 5, (3, 8), 7, 4

PROJECT_PALS = [  # eight project colours: ginger, grey, charcoal (yellow eyes), cream, brown, lilac, teal, rose
 dict(B="#ffb454", d="#e0902e", W="#fff1d6", A="#e0902e", w="#c0caf5", b="#e0902e"),
 dict(B="#9aa5b8", d="#7b879c", W="#e8ecf5", A="#7b879c", w="#c0caf5", b="#7b879c"),
 dict(B="#5f6688", d="#474d6b", W="#8a91b3", A="#474d6b", w="#c0caf5", b="#474d6b", E="#ffd866"),
 dict(B="#f3e2c0", d="#d9c39a", W="#fffaf0", A="#d9c39a", w="#c0caf5", b="#d9c39a"),
 dict(B="#b98a62", d="#8f6644", W="#ecd3b0", A="#8f6644", w="#c0caf5", b="#8f6644"),
 dict(B="#b9a4e8", d="#9682cf", W="#f0eaff", A="#9682cf", w="#c0caf5", b="#9682cf"),
 dict(B="#5fd7c0", d="#3fb8a2", W="#e0fff7", A="#3fb8a2", w="#c0caf5", b="#3fb8a2", L="#f7768e"),  # a cyan collar vanishes on teal: red
 dict(B="#ff8fa3", d="#e06a86", W="#ffe3d6", A="#e06a86", w="#c0caf5", b="#e06a86")]

MAIN_PAL = dict(B="#7aa2f7", d="#5878c8", W="#e6efff", A="#5878c8", w="#c0caf5", b="#5878c8", L="#ff9e64")  # the main session: blue, an orange collar shows on it
PALS = PROJECT_PALS + [MAIN_PAL]  # index len(PROJECT_PALS) is the main session's; colour_of never picks it
MAIN = len(PROJECT_PALS)

def colour_of(project):  # stable across runs (crc32, not hash()); collisions accepted for now per the captain
    return zlib.crc32(project.encode()) % len(PROJECT_PALS)

ACCS = ["collar", "scarf", "cap", "sunglasses", "mask"]  # every worker wears one, in this order within its project
ACC = dict(
 sunglasses=[(5, 2, "NCNNNCNN"), (6, 3, "NN"), (6, 7, "NN")], scarf=[(8, 3, "RWRWRW"), (9, 3, "R")],
 collar=[(8, 3, "LLLLLL"), (9, 5, "Y")], cap=[(1, 5, "OO"), (2, 4, "OOOO")],
 mask=[(6, 3, "KKKKKK"), (7, 3, "KkKKkK"), (8, 4, "KKKK"), (6, 2, "k"), (6, 9, "k")])
CONFETTI = [(0, 1, "P"), (0, 4, "Y"), (1, 2, "C"), (0, 8, "G"), (2, 0, "Y"), (0, 11, "P"), (2, 11, "C"), (4, 0, "G"), (1, 6, "R"), (3, 10, "Y"), (5, 11, "P")]

def shade(g, pal):  # underside shadow: body pixels with empty space below get the darker 'd'
    return [[("d" if ch == "B" and (r == 11 or g[r + 1][i] == ".") else ch) for i, ch in enumerate(row)] for r, row in enumerate(g)]

@functools.lru_cache(maxsize=None)
def creature(mood, acc=None, colour=0, f=0):  # f: animation frame 0/1; frame 0 is the approved still
    pal, g = {**PROPS, **PALS[colour]}, G(MOCHI)
    for r, col, s in ACC.get(acc, []): put(g, [(r, col, s)])
    def eyes(kind):
        if kind == "focus": put(g, [(ER - 1, CL, "NN"), (ER - 1, CR - 1, "NN")])
        elif kind == "wide": put(g, [(ER + 1, CL, "E"), (ER + 1, CR, "E")])
        elif kind == "droop":
            for x in (CL, CR): g[ER][x], g[ER + 1][x] = "B", "E"
        elif kind == "dash":  # closed eyes: asleep and party
            for x in (CL, CR): g[ER][x] = "B"
            put(g, [(ER, CL - 1, "EE"), (ER, CR, "EE")])
    def mouth(kind):
        if kind == "frown": put(g, [(MR + 1, 4, "M"), (MR + 1, 7, "M")])
        elif kind == "open": put(g, [(MR, 5, "MM"), (MR + 1, 5, "TT")])
    def arms_up(): put(g, [(6, 1, "B"), (5, 0, "B"), (6, 10, "B"), (5, 11, "B")])
    if mood == "busy":  # focused brows, swinging a hammer, sparks; frame 1 breathes up, sparks out
        eyes("focus")
        if f: g = up(g)
        put(g, [(3, 10, "SS"), (4, 10, "SS")] + [(r, 11, "D") for r in (5, 6, 7, 8)] + [(2, 10, "Y"), (1, 11, "Y"), (3, 9, "Y")] * (not f), over=True)
    elif mood == "training":  # sweatband, hop, speed lines, ground shadow; frame 1 lands
        put(g, [(HB, 2, "RRRRRRRR"), (HB, 10, "R"), (HB + 1, 11, "R"), (ER, 1, "C"), (ER + 1, 1, "C")])
        if not f: g = up(g)
        put(g, [(11, 3, "ssssss"), (5, 0, "S"), (7, 0, "S"), (9, 0, "S")], over=True)
    elif mood == "calling":  # arms up, wide eyes, mouth open, "!" mark; frame 1 jumps
        eyes("wide"); mouth("open"); arms_up()
        if f: g = up(g)
        put(g, [(0, 11, "R"), (1, 11, "R"), (3, 11, "R")], over=True)
    elif mood == "sick":  # droopy eyes, frown, a paw holding the thermometer, sweat, green tint
        eyes("droop"); mouth("frown")
        if g[7][10] == ".": g[7][10] = "B"
        put(g, [(4, 11, "W"), (5, 11, "W"), (6, 11, "W"), (7, 11, "R"), (ER - 1, 1, "C"), (ER, 1, "C")], over=True)
        if f: g = [r[1:] + ["."] for r in g]  # frame 1 shivers one pixel left
        pal = mood_pal(pal, "#9ece6a", 0.45)
    elif mood == "asleep":  # eyes shut, dim, zzz; frame 1 breathes in
        eyes("dash")
        if f: g = up(g)
        put(g, [(0, 9, "ZZZ"), (1, 10, "Z"), (2, 9, "ZZZ"), (4, 10, "zz"), (5, 10, "z")], over=True)
        pal = mood_pal(pal, "#7080c0", 0.55)
    elif mood == "party":  # arms up, happy eyes, open mouth, hop, confetti; frame 1 lands, the confetti flips
        eyes("dash"); mouth("open"); arms_up()
        if not f: g = up(g)
        put(g, [(r, 11 - x if f else x, ch) for r, x, ch in CONFETTI], over=True)
    return tuple(render_px(shade(g, pal), pal))

def mood_pal(pal, col, t): return {**pal, **{k: mix(pal[k], col, t) for k in TINT if k in pal}}

def render_px(g, pal, w=12):
    out = []
    for r in range(0, len(g), 2):
        line = ""
        for col in range(w):
            tf, bf = pal.get(g[r][col]), pal.get(g[r + 1][col])
            if not tf and not bf: line += " "
            elif tf and not bf: line += f"{{#{tf[1:]}}}▀{{/}}"
            elif bf and not tf: line += f"{{#{bf[1:]}}}▄{{/}}"
            elif tf == bf: line += f"{{#{tf[1:]}}}█{{/}}"
            else: line += f"{{#{tf[1:]}}}{{@{bf[1:]}}}▀{{/}}"
        out.append(line)
    return out

CUP = render_px([list(r) for r in ["YYYY", ".YY.", ".yy.", "yyyy"]], PROPS, 4)

# ---- reading one worker (read-only, cheap) ----
EVENT = re.compile(r"^(working|needs-decision|blocked|done|failed|paused|resolved|captain-held|note)\b((?:\s*\[[^\]]*\])*)\s*:\s?(.*)")
AT = re.compile(r"\bat=(\d+)")
VALIDATING = re.compile(r"no-mistakes|validat", re.I)
MERGED = re.compile(r"\b(merged|landed)\b", re.I)

def mtime(p):
    try: return os.stat(p).st_mtime
    except OSError: return 0.0

def read_meta(path):
    meta = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            k, sep, v = line.rstrip("\n").partition("=")
            if sep: meta[k] = v
    return meta

def tail(path, n=8192):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - n))
            lines = f.read().decode("utf-8", "replace").splitlines()
            return lines[1:] if size > n else lines
    except OSError:
        return []

def status_state(lines):
    """-> (state, text, at). resolved/captain-held close an open decision or blocker."""
    state, text, at = None, "", 0
    for line in lines:
        m = EVENT.match(line)
        if not m: continue
        verb, tok, body = m.groups()
        stamp = AT.search(tok or "") or AT.search(line)
        if verb == "note": continue
        if verb in ("resolved", "captain-held"):
            if state in ("needs-decision", "blocked"): state, text = "working", body
            continue
        state, text, at = verb, body, int(stamp.group(1)) if stamp else at
    return state, text, at

TITLED = re.compile(r"- \[.\] (\S+) - (.+?)(?= \((?:repo|kind|hold|hold-kind|hold-until): | \(since \d|$)")
HELD = re.compile(r"\(hold-until: ([^)\s]+)\)")

@functools.lru_cache(maxsize=4)
def backlog(path, stamp):  # -> {task id: (title, hold-until or "")} from the home's data/backlog.md; stamp (its mtime) keys the cache, so it is read again only when it changes
    out = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m, h = TITLED.match(line), HELD.search(line)
                if m: out[m[1]] = (re.sub(r"^[\w-]+: ", "", m[2].strip()), h[1] if h else "")  # "garmin: post-race rehaul" -> "post-race rehaul": the card names the project
    except OSError: pass
    return out

def read_worker(state_dir, wid, now):
    meta = read_meta(os.path.join(state_dir, wid + ".meta"))
    status_path = os.path.join(state_dir, wid + ".status")
    st, text, at = status_state(tail(status_path))
    kind = meta.get("kind", "ship")
    last_active = max(mtime(status_path), mtime(os.path.join(state_dir, wid + ".turn-ended")))
    fed_at = mtime(os.path.join(state_dir, wid + ".inbox", "handled"))  # dir mtime moves when a message is handled
    spawn = meta.get("spawn_gen", "")[1:].split(".")[0]
    born = int(spawn) if spawn.isdigit() else mtime(os.path.join(state_dir, wid + ".meta"))

    bubble, sub, dec = "", "", None
    review = st == "done" and not MERGED.search(text) and (meta.get("pr") or kind == "scout")  # waiting on the captain's review: a decision of its own kind
    if st in ("needs-decision", "blocked") or review:  # an open decision: its newest unresolved line (status_state already applied resolved/captain-held)
        report, bl = os.path.join(os.path.dirname(state_dir), "data", wid, "report.md"), os.path.join(os.path.dirname(state_dir), "data", "backlog.md")
        title, hold = backlog(bl, mtime(bl)).get(wid, ("", ""))
        dec = dict(kind="review" if review else st, text=text, waiting=age(max(0, now - (at or last_active))), at=at or last_active,
                   report=report if os.path.exists(report) else "", pr=meta.get("pr", ""), title=title, hold=hold)
    if st in ("blocked", "failed"): mood, sub = "sick", st
    elif st == "needs-decision": mood, bubble = "calling", "your call!"
    elif st == "done" and MERGED.search(text): mood, sub = "party", "merged!"
    elif st == "done": mood, bubble = "calling", ("report ready!" if kind == "scout" else "PR ready!")
    elif st in ("working", "paused") and VALIDATING.search(text): mood, sub = "training", "validating"
    else: mood, sub = "busy", ("investigating" if kind == "scout" else "building")
    if mood in ("busy", "training") and last_active and now - last_active > ASLEEP_SECS:
        mood, sub = "asleep", "silent " + age(now - last_active)

    hunger, hn = 5, "fed"
    if mood == "calling":
        waited = now - max(at or last_active, fed_at)
        hunger, hn = max(0, 5 - int(max(0, waited) // HUNGER_STEP)), "waiting " + age(max(0, now - (at or last_active)))
    project = os.path.basename(meta.get("project", "").rstrip("/")) or "?"
    return dict(id=wid, project=project, kind=kind, mood=mood, bubble=bubble, sub=sub, born=born,
                age=age(now - born), hunger=hunger, hn=hn, ws=meta.get("herdr_workspace_id"), tab=meta.get("herdr_tab_id"),
                pane=meta.get("herdr_pane_id"), decision=dec)

def age(secs):
    m = int(secs // 60)
    return f"{m}m" if m < 60 else f"{m // 60}h {m % 60}m" if m < 1440 else f"{m // 1440}d {m % 1440 // 60}h"

def short_task(wid, project):  # drop leading id words the project name already says: kara-web-unhide in kara-website -> unhide
    words = wid.split("-")
    while len(words) > 1 and words[0] in project: words.pop(0)
    return " ".join(words)

MAIN_MOOD = dict(working=("busy", "", "working"), blocked=("calling", "needs you!", ""))  # anything else (idle, done, unknown) is a calm doze

def main_worker(p):
    mood, bubble, sub = MAIN_MOOD.get(p.get("agent_status"), ("asleep", "", "idle"))
    return dict(id="firstmate", project="main", kind="main", main=True, mood=mood, bubble=bubble, sub=sub, born=0, age="main", hunger=None,
                hn="main session", acc="collar", colour=MAIN, ws=p.get("workspace_id"), tab=p.get("tab_id"), pane=p.get("pane_id"))

# ---- the fleet ledger: every task.merged record is one trophy; merges, launches, status lines and cleanups make the captain's log ----
STATES = ("working", "paused", "needs-decision", "blocked", "resolved", "captain-held", "done", "failed")  # the status states the log folds
class Ledger:
    """Read-only tail of state/fleet-ledger.jsonl. Keeps a byte offset, so each read parses only the lines appended since the last."""
    def __init__(self, state):
        self.state, self.path = state, os.path.join(state, "fleet-ledger.jsonl")
        self.reset()

    def reset(self): self.off, self.projects, self.merged, self.keys, self.events = 0, {}, [], set(), []  # merged: dicts of task, ts, project; events: the log's (ts, task, what)

    def meta_project(self, task):
        try: return os.path.basename(read_meta(os.path.join(self.state, task + ".meta")).get("project", "").rstrip("/")) or None
        except OSError: return None

    def project(self, task): return self.projects.get(task) or self.meta_project(task) or self.listed_project(task)

    def listed_project(self, task):  # last resort: the longest name in the home's data/projects.md that the task id starts with, then "-"
        try:
            with open(os.path.join(os.path.dirname(self.state), "data", "projects.md")) as f:
                names = [m[1] for m in (re.match(r"- (\S+) ", l) for l in f) if m]
        except OSError: return None
        return max((n for n in names if task.startswith(n + "-")), key=len, default=None)

    def read(self):  # -> the merge records that arrived since the last read; a missing file is just empty
        try: size = os.stat(self.path).st_size
        except OSError: size = 0
        if size < self.off: self.reset()  # truncated (the contract's way to empty it): start over
        if size == self.off: return []
        try:
            with open(self.path, "rb") as f: f.seek(self.off); data = f.read(size - self.off)
        except OSError: return []
        cut = data.rfind(b"\n") + 1  # a half-written last line waits for its newline
        self.off += cut
        new = []
        for line in data[:cut].split(b"\n"):
            try: rec = json.loads(line)
            except ValueError: continue  # blank or malformed
            task, ts, ev = (rec.get(k) for k in ("task", "ts", "event")) if isinstance(rec, dict) else (None, None, None)
            if not isinstance(task, str) or not isinstance(ts, (int, float)) or isinstance(ts, bool): continue
            if ev == "task.dispatched":
                proj = rec.get("project")
                if isinstance(proj, str) and os.path.basename(proj.rstrip("/")): self.projects[task] = os.path.basename(proj.rstrip("/"))
                self.events.append((ts, task, "sail"))
            elif ev == "task.status" and rec.get("state") in STATES and (task, ts, rec["state"], rec.get("text")) not in self.keys:
                self.keys.add((task, ts, rec["state"], rec.get("text")))
                self.events.append((ts, task, rec["state"]))
            elif ev == "task.cleaned_up": self.events.append((ts, task, "ashore"))
            elif ev == "task.merged" and (task, ts) not in self.keys:  # the ledger can repeat a record
                self.keys.add((task, ts))
                pr = re.search(r"/pull/(\d+)", rec["pr"]) if isinstance(rec.get("pr"), str) else None
                ref = f"PR #{pr[1]}" if pr else "local" if rec.get("via") == "local" else ""
                new.append(dict(task=task, ts=ts, project=self.project(task), ref=ref, url=rec["pr"] if pr else ""))
        self.merged += new
        return new

def room_name(task, project): return task[len(project) + 1:] if project and task.startswith(project + "-") and len(task) > len(project) + 1 else task

def trophies_today(merged, now, week=False):  # -> [(project or None, short task, "HH:MM" ("Mon HH:MM" in a week), room task name, "PR #n" / "local" / "", PR URL or "")], most recent last
    def window(ts):  # the local day, or the calendar week starting Monday
        d = datetime.date.fromtimestamp(ts)
        return d - datetime.timedelta(d.weekday()) if week else d
    return [(m["project"], short_task(m["task"], m["project"] or ""), time.strftime("%a %H:%M" if week else "%H:%M", time.localtime(m["ts"])),
             room_name(m["task"], m["project"]), m["ref"], m.get("url", ""))
            for m in sorted(merged, key=lambda m: m["ts"]) if window(m["ts"]) == window(now)]

# ---- the captain's log: one short entry per day, newest first, from templates over the ledger (no prose model, nothing written) ----
NUMS = "no one two three four five six seven eight nine ten".split()

def num(n, one, many=None): return f"{NUMS[n] if n < len(NUMS) else n} {one if n == 1 else many or one + 's'}"
def names(xs): return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]
def times(xs): return [x + (f" ×{xs.count(x)}" if xs.count(x) > 1 else "") for x in dict.fromkeys(xs)]  # herdr-pet, herdr-pet -> herdr-pet ×2
def pair(n, m, what, done):  # "Two decisions raised, one answered." / "One decision answered."
    if n: return num(n, what) + " " + done[0] + (f", {NUMS[m] if m < len(NUMS) else m} {done[1]}." if m else ".")
    return num(m, what) + " " + done[1] + "." if m else ""

def captains_log(ledger, now):  # -> [(date, [markup word, ...])], newest day first; the words wrap to any width
    days, waiting, label = {}, {}, lambda t: ledger.project(t) or t  # waiting: task -> the needs-decision or blocked it waits on
    merges = [(m["ts"], m["task"], "merged", m) for m in ledger.merged]
    for ts, task, what, *m in sorted(ledger.events + merges, key=lambda e: e[0]):
        d = days.setdefault(datetime.date.fromtimestamp(ts), dict(sail=[], prs=[], local=[], done=[], failed=[], raised=0, answered=0, hit=0, cleared=0))
        was = waiting.pop(task, None)  # any later record closes a wait (status_state's rule); a new ask or blocker reopens it below
        if what == "sail": d["sail"].append(task)
        elif what == "merged":
            pr = re.search(r"#(\d+)", m[0]["ref"])
            (d["prs"] if pr else d["local"]).append(label(task) + (" " + link(m[0]["url"], "#" + pr[1]) if pr else ""))
        elif what in ("resolved", "captain-held") and was: d["answered" if was == "needs-decision" else "cleared"] += 1
        elif what in ("done", "failed") and task not in d[what]: d[what].append(task)
        elif what in ("needs-decision", "blocked"):
            if was != what: d["raised" if what == "needs-decision" else "hit"] += 1  # a repeated ask is the same decision
            waiting[task] = what
        d["waits"] = dict(waiting)  # what still waits once the day's last record is in
    entries, today = [], datetime.date.fromtimestamp(now)
    for date, d in sorted(days.items(), reverse=True):
        said = [num(len(d["sail"]), "task") + " set sail." if d["sail"] else "",
                num(len(d["prs"]), "PR") + " landed (" + ", ".join(d["prs"]) + ")." if d["prs"] else "",
                num(len(d["local"]), "local branch", "local branches") + " landed (" + ", ".join(times(d["local"])) + ")." if d["local"] else "",
                num(len(d["done"]), "task") + " reported done." if d["done"] else "",
                pair(d["raised"], d["answered"], "decision", ("raised", "answered")), pair(d["hit"], d["cleared"], "blocker", ("hit", "cleared")),
                num(len(d["failed"]), "task") + " ran aground (" + names(sorted({label(t) for t in d["failed"]})) + ")." if d["failed"] else ""]
        said = [x[0].upper() + x[1:] for x in said if x]  # these open on a number; the waits below open on a project name, left as it is
        for kind, now_verbs, past_verbs, rest in (("needs-decision", ("waits", "wait"), ("waited", "waited"), "on your call."),
                                                  ("blocked", ("is", "are"), ("was", "were"), "stuck on a blocker.")):
            who = sorted({label(t) for t, k in d["waits"].items() if k == kind})
            if who: said.append(f"{names(who)} {(now_verbs if date == today else past_verbs)[len(who) > 1]} {rest}")
        said = " ".join(said) or "Quiet seas."
        entries.append((date, [c(KEY, f"Day {date.isoformat()}.", True)] + [c(FG, w) for w in said.split(" ")]))
    return entries

# ---- the pet: keeps accessories stable, parties workers whose merge just got recorded, lists today's trophies ----
class Pet:
    def __init__(self, home, list_panes=None):  # list_panes() -> Herdr's pane list; None (no Herdr) means no main Mochi
        self.home, self.list_panes = home, list_panes
        self.state = os.path.join(home, "state")
        self.ledger = Ledger(self.state)
        self.accs, self.party, self.trophies, self.log, self.logged, self.primed, self.week, self.landed = {}, {}, [], [], None, False, True, 0

    def poll(self, now):
        try: ids = sorted(e.name[:-5] for e in os.scandir(self.state) if e.name.endswith(".meta"))
        except OSError: ids = []
        workers = []
        for wid in ids:
            try: workers.append(read_worker(self.state, wid, now))
            except OSError: pass  # removed between scandir and read
        workers.sort(key=lambda w: (w["born"], w["id"]))
        live = {w["id"]: w["project"] for w in workers}
        for wid in [k for k in self.accs if k not in live]: del self.accs[wid]
        for w in workers:  # sticky: a worker keeps its accessory; newcomers take the first free one in their project, cycling after five
            if w["id"] not in self.accs:
                taken = [a for k, a in self.accs.items() if live[k] == w["project"]]
                self.accs[w["id"]] = next((a for a in ACCS if a not in taken), ACCS[len(taken) % len(ACCS)])
            w["acc"] = self.accs[w["id"]]
        for m in self.ledger.read():  # a merge that lands while the worker is still shown: party (the backlog read at startup does not)
            if self.primed and m["task"] in live: self.party[m["task"]] = now + PARTY_SECS
        self.primed = True
        self.party = {k: t for k, t in self.party.items() if t > now and k in live}
        for w in workers:
            if w["id"] in self.party: w.update(mood="party", bubble="", sub="merged!", hunger=5, hn="fed")
        self.trophies = trophies_today(self.ledger.merged, now, self.week)
        self.landed = len(self.trophies if not self.week else trophies_today(self.ledger.merged, now))  # the title's "N landed today", whichever span the trophies show
        if self.logged != (self.ledger.off, datetime.date.fromtimestamp(now)):  # rebuilt only when the ledger grows or the day turns
            self.log, self.logged = captains_log(self.ledger, now), (self.ledger.off, datetime.date.fromtimestamp(now))
        return self.main_mochi(now) + workers

    def main_mochi(self, now):  # the Firstmate session's own pane, if Herdr has one; any Herdr trouble means none
        if not self.list_panes: return []
        try: p = next((p for p in self.list_panes() if same_dir(p.get("cwd"), self.home) and not is_pet(p)), None)
        except Exception: return []
        return [main_worker(p)] if p else []

# ---- layout: 80 columns, or the pane's width when it is wider ----
W, CW, CH, TW = 80, 19, 11, 24  # minimum frame width; one creature cell's width and height; the trophy column's width
MC = dict(busy="7dcfff", training="ff9e64", calling="bb9af7", sick="9ece6a", asleep="7d8fd0", party="e0af68")

def grid(n, width=W):  # -> (columns, rows of creatures, frame width): as many cells across as fit beside the trophy column; the frame fills the pane
    cols = max(1, min(SHOWN, (max(width, W) - 4 - TW) // CW))
    return cols, max(1, math.ceil(min(n, SHOWN) / cols)), max(W, width)

def frame(title, rows, right="", w=W, foot=None, col=None):  # title: markup; foot: a last row under a rule; col: the inner column of a divider that joins the rules
    inner = w - 2
    used = 3 + vis(title) + 1 + (vis(right) + 1 if right else 0)
    dash, at = "─" * (w - 1 - used), -1 if col is None else col - 3 - vis(title)  # at: the divider's place in the top's dashes
    if 0 <= at < len(dash): dash = dash[:at] + "┬" + dash[at + 1:]  # when the title or hints sit over it, the divider just meets them
    top = c(FRAME, "╭─ ") + title + c(FRAME, " " + dash) + (" " + right if right else "") + c(FRAME, "╮")
    rule = lambda l, r, j: c(FRAME, l + ("─" * inner if j is None else "─" * j + "┴" + "─" * (inner - j - 1)) + r)
    side = [c(FRAME, "│") + padr(r, inner) + c(FRAME, "│") for r in rows]
    if foot is None: return [top] + side + [rule("╰", "╯", col)]
    return [top] + side + [rule("├", "┤", col), c(FRAME, "│") + padr(foot, inner) + c(FRAME, "│"), rule("╰", "╯", None)]

def hearts(n): return c(HEART, "●" * n) + c(DIM, "○" * (5 - n))  # ● is solid in every terminal font; ♥ drew as an outline in Herdr

def cell(i, w, tick=None):  # tick None: the still frame
    n = f"{i} "  # one column of each line stays free between cells
    proj = c(KEY, str(i), True) + " " + c(FG, clip(w["project"], CW - 1 - len(n)), True)
    name, tag = short_task(w["id"], w["project"]), w.get("decision") and w["decision"]["kind"] == "needs-decision" and w["decision"]["text"]
    if tag:  # a calling Mochi says what the call is about: "task · tag" on the second label line
        name = clip(name, 8)
        task = c(SUB, name) + c(HEAD, clip(" · " + tag, CW - 1 - len(name)))
    else: task = c(SUB, clip(name, CW - 1))
    last = c(FG, f'"{w["bubble"]}"', True) if w["bubble"] else c(DIM, w["sub"])
    f = 0 if tick is None else ((tick // 2 if w["mood"] == "asleep" else tick) + i) % 2  # neighbours out of step; asleep at half speed
    body = creature(w["mood"], w.get("acc"), w.get("colour", colour_of(w["project"])), f)
    mid = lambda x: center(x, CW - 1) + " "  # the sprite and its labels share one centre line; the last column stays free between cells
    return [mid(x) for x in body] + [mid(proj), mid(task), mid(c(MC[w["mood"]], w["mood"]) + c(DIM, f" · {w['age']}")),
            mid(c(DIM, w["hn"]) if w["hunger"] is None else hearts(w["hunger"]) + c(DIM, " " + clip(hunger_note(w["hn"]), CW - 7))), mid(last)]

def hunger_note(hn): return hn if len(hn) <= CW - 7 else hn.replace("waiting ", "")  # "waiting 4d 13h" outgrows the cell beside five hearts: the hearts already say it waits

def by_project(items):  # -> [(project or None, its trophies newest first)], the project with the newest merge first
    groups = {}
    for t in reversed(items): groups.setdefault(t[0], []).append(t)
    return list(groups.items())

def cup_name(p, n, room, bold=False, flush=True):  # "project ×N" in room columns; flush: the count at the right edge, so a column of counts lines up
    k = f"×{n}"
    name = clip(p or "no project", room - len(k) - 1)
    return c(FG, name, bold) + " " * (room - len(name) - len(k) if flush else 1) + c(GOLD, k)

def trophy_col(items, h, week=False):  # -> h lines of TW columns: heading, the total, then a cup with "project ×N" per project on 2 lines, "+N more" when they overflow
    span = "this week" if week else "today"
    lines = [c(FRAME, "│ ") + c(HEAD, "trophies · " + span, True)]
    if not items:
        lines.append(c(FRAME, "│ ") + c(DIM, "none yet " + span))
        return [padr(l, TW) for l in (lines + [c(FRAME, "│")] * h)[:h]]
    lines.append(c(FRAME, "│ ") + c(DIM, f"{span}: {len(items)}"))
    groups = by_project(items)
    fit = (h - 2) // 2
    if len(groups) > fit: fit = (h - 3) // 2  # keep a line for "+N more"
    for p, ts in groups[:fit]:
        lines.append(c(FRAME, "│") + c(GOLD, " " + CUP[0]) + " " + cup_name(p, len(ts), TW - 8))
        lines.append(c(FRAME, "│") + c(GOLD, " " + CUP[1]) + " " + c(DIM, "last ") + c(KEY, ts[0][2]))
    if len(groups) > fit:
        lines.append(c(FRAME, "│ ") + c(DIM, f"+{len(groups) - fit} more"))
    return [padr(l, TW) for l in (lines + [c(FRAME, "│")] * h)[:h]]

TRW = 36  # the narrowest a trophy room column gets

def trophy_pages(items, h, w):  # -> the trophy room's columns (lists of lines, h - 1 tall) cut into pages of as many columns as fit across w
    n, cap = max(1, w // TRW), h - 1
    cw, cols = w // n, [[]]
    def add(line, need=1):
        if cols[-1] and len(cols[-1]) + need > cap: cols.append([])
        cols[-1].append(padr(line, cw))
    for p, ts in by_project(items):
        head = "  " + c(GOLD, CUP[0]) + " " + cup_name(p, len(ts), cw - 9, True, False)
        add(head, 2)  # a project header never ends a column alone
        for k, (_, _, tm, name, ref, *url) in enumerate(ts):
            if len(cols[-1]) >= cap: add("  " + c(DIM, "↳ " + clip(p or "no project", cw - 6)))  # the project carries on in the next column
            room = cw - 9 - len(tm) - (len(ref) + 1 if ref else 0)
            add("  " + (c(GOLD, CUP[1]) if k == 0 else "    ") + " " + c(KEY, tm) + " " + c(FG, clip(name, room)) + (" " + link(url and url[0], c(DIM, ref)) if ref else ""))
    return [cols[i:i + n] for i in range(0, len(cols), n)] if items else [[]]

def page_keys(page, n): return c(DIM, f" · page {page + 1}/{n} · ") + c(KEY, "a") + c(DIM, " prev ") + c(KEY, "s") + c(DIM, " next") if n > 1 else ""

def trophy_room(items, h, w, week=False, page=0):  # -> h lines of w columns: the creatures' place in the trophy view; per project a cup and "project ×N", then a line per merge, flowing across the width and paged (n / p) when they still do not fit
    span = "this week" if week else "today"
    pages = trophy_pages(items, h, w)
    page = min(max(page, 0), len(pages) - 1)
    lines = [" " + c(HEAD, "trophy room · " + span, True) + c(DIM, f" · {len(items)}" if items else " · none yet " + span) + page_keys(page, len(pages))]
    cols, cw = pages[page], w // max(1, w // TRW)
    lines += ["".join(col[i] if i < len(col) else " " * cw for col in cols) for i in range(h - 1)] if cols else []
    return [padr(l, w) for l in lines] + [" " * w] * (h - len(lines))

def wrap(words, w):  # markup words -> lines at most w columns wide, a word too long for a line cut to fit
    lines, cur, used = [], [], 0
    for x in words:
        n = vis(x)
        if n > w: x, n = c(FG, clip(TAG.sub("", x), w)), w
        if cur and used + 1 + n > w: lines.append(" ".join(cur)); cur, used = [], 0
        used += n + bool(cur); cur.append(x)
    return lines + [" ".join(cur)] if cur else lines

def log_pages(entries, h, w):  # -> pages of h - 1 lines: the entries wrapped to w, a blank line between them, an entry kept on one page when it fits
    cap, pages = max(1, h - 1), [[]]
    for _, words in entries:
        block = [" " + l for l in wrap(words, w - 2)]
        if pages[-1] and len(pages[-1]) + 1 + len(block) > cap: pages.append([])
        elif pages[-1]: pages[-1].append("")
        for l in block:
            if len(pages[-1]) >= cap: pages.append([])  # longer than a page: it carries on over the next
            pages[-1].append(l)
    return pages

def log_room(entries, h, w, page=0):  # -> h lines of w columns: the creatures' place in the log view; newest day first, paged (n / p) when it does not fit
    pages = log_pages(entries, h, w)
    page = min(max(page, 0), len(pages) - 1)
    lines = [" " + c(HEAD, "captain's log", True) + c(DIM, f" · {num(len(entries), 'day')}" if entries else " · nothing logged yet") + page_keys(page, len(pages))]
    return [padr(l, w) for l in (lines + pages[page])[:h]] + [" " * w] * (h - 1 - len(pages[page]))

ACTION = {"needs-decision": ("decide", MC["calling"]), "review": ("review", "7dcfff"), "blocked": ("unblock", MC["sick"])}  # what each open item asks of the captain

PULL = re.compile(r"https?://[^\s{}]+/pull/(\d+)[^\s{}]*")

def decision_card(x, w):  # x: a worker that needs the captain -> 3 lines: the action, project and what the work is; what to do (the question, blocker, or "review & merge PR #n" and its status); the wait, PR, report and hold
    d = x["decision"]
    act, col = ACTION[d["kind"]]
    lead = " " + c(col, "●") + " " + c(col, act.ljust(7), True) + " " + c(FG, x["project"], True) + c(DIM, " · ")
    head = lead + c(FG, clip(d.get("title") or short_task(x["id"], x["project"]), max(1, w - 1 - vis(lead))))
    n = re.search(r"/pull/(\d+)", d["pr"])
    ref = f"PR #{n[1]}" if n else "PR" if d["pr"] else ""
    text = re.sub(r"\bPR (PR #\d+)", r"\1", PULL.sub(lambda m: "PR #" + m[1], d["text"] or ""))  # a raw PR URL reads as "PR #n"
    if d["kind"] == "review":  # its PR shows once, as the thing to review; what is left of the line is its status
        rest = " ".join(text.replace(ref, " ").split()).strip(" ·-:,") if ref else text
        ask = [("review & merge ", ""), (ref, d["pr"])] if ref else [("read the report", "")]
        todo = ask + [(" · " + rest, "")] * bool(rest)
    else: todo = [(text or "(no details)", "")]
    more = [("waiting " + d["waiting"], "")] + [(" · ", ""), (ref, d["pr"])] * bool(ref and d["kind"] != "review")
    more += [(" · report " + os.path.join(*d["report"].split(os.sep)[-3:]), "")] * bool(d["report"]) + [(" · on hold to " + d.get("hold", ""), "")] * bool(d.get("hold"))
    return [head, "   " + clip_links(todo, w - 5, FG), "   " + clip_links(more, w - 5, DIM)]

def clip_links(parts, n, col):  # parts: [(text, url or "")] -> their text in col, clipped to n columns like clip(), each part linked to its url over what shows of it
    cut, out, i = clip("".join(t for t, _ in parts), n), "", 0
    for t, url in parts:
        if cut[i:i + len(t)]: out += link(url, c(col, cut[i:i + len(t)]))
        i += len(t)
    return out

def decisions_of(workers): return sorted((x for x in workers if x.get("decision")), key=lambda x: x["decision"]["at"])  # longest waiting first

def decision_room(decs, h, w):  # -> h lines of w columns: the creatures' place in the needs-you view; one card each, oldest first, "+N more" when they overflow
    lines = [" " + c(HEAD, "needs you", True) + c(DIM, f" · {len(decs)}" if decs else " · none")]
    shown = 0
    for i, d in enumerate(decs):
        card = decision_card(d, w)
        if len(lines) + len(card) + (i < len(decs) - 1) > h: break  # keep a line for "+N more"
        lines += card; shown += 1
    if shown < len(decs): lines.append(" " + c(DIM, f"+{len(decs) - shown} more"))
    return [padr(l, w) for l in lines[:h]] + [" " * w] * (h - len(lines))

def crew(workers, landed):  # -> the title's parts, most important first: who is aboard, how many need the captain, how many landed today (Herdr's pane label already names the pet)
    n, d = sum(not x.get("main") for x in workers), len(decisions_of(workers))
    return [c(FG, f"⚓ {n} aboard", True), d and c(HEAD, f"{d} need{'s' * (d == 1)} you", True), landed and c(GOLD, f"{landed} landed today", True)]

def panel(workers, rows, w=W, keys=(), landed=0, foot=None, col=None):
    more = len(workers) - SHOWN
    parts, ks = crew(workers, landed), list(keys)
    if any(" needs you (" in k for k in ks): parts[1] = ""  # the strip's "d needs you (N)" already says it on this line
    title = lambda: c(DIM, " · ").join(p for p in parts if p)
    mk = lambda: (c(KEY, f"+{more} more", True) + c(DIM, " · ") if more > 0 else "") + c(LIVE, "●") + c(DIM, f" live {POLL}s") + "".join(ks)
    # a tight bar drops the least important first: the hints after the third, "landed today", the third hint, "needs you", the second hint; never "aboard", "+N more" or q
    for xs, i in [(ks, i) for i in range(len(ks) - 1, 2, -1)] + [(parts, 2), (ks, 2), (parts, 1), (ks, 1)]:
        if 5 + vis(title()) + vis(mk()) <= w - 1: break
        if i < len(xs): xs[i] = ""
    return frame(title(), rows, mk(), w, foot, col)

def creatures(shown, trophies, width=W, tick=None, view=None, decs=(), week=False, page=0, log=()):  # up to eight Mochis, as many across as fit, CH rows each: sprite, two label lines, mood, hearts, bubble; trophies down the right edge
    cols, nrows, w = grid(len(shown), width)
    if view == "t": return trophy_room(trophies, CH * nrows, w - 2, week, page)
    if view == "d": return decision_room(decs, CH * nrows, w - 2)
    if view == "c": return log_room(log, CH * nrows, w - 2, page)
    room = w - 2 - TW
    if not shown: body = [""] * 5 + [center(c(DIM, "no workers aboard · Mochi waits for the next task"), room)] + [""] * 5
    else:
        cells = [cell(i, x, tick) for i, x in enumerate(shown, 1)]
        lead = " " * max(2, (room - cols * CW) // 2)  # the grid sits centred in the room beside the trophy column
        body = [lead + "".join(col[i] for col in cells[k:k + cols]) for k in range(0, len(cells), cols) for i in range(CH)]
    return [padr(l, room) + t for l, t in zip(body, trophy_col(trophies, len(body), week))]

def hint(key, label, view, cur): return c(KEY, key) + c(DIM, " back" if view == cur else " " + label)  # the key's footer hint: "back" while its view is open

def dec_hint(view, n):  # "d needs you (N)" in the heading colour while anything waits; plain and dim at zero
    if view == "d" or not n: return hint("d", "needs you", "d", view)
    return c(KEY, "d") + c(HEAD, f" needs you ({n})", True)

def week_hint(week): return c(KEY, "w") + c(DIM, " today" if week else " week")  # flips the trophy window; the label names what it switches to

def divider(w, view): return w - 2 - TW if view is None else None  # the trophy column's left edge, which joins the frame's rules; the other views have none

def render(workers, trophies, width=W, tick=None, view=None, week=False, page=0, log=(), landed=0):
    shown, w = workers[:SHOWN], grid(len(workers), width)[2]
    col, decs = divider(w, view), decisions_of(workers)
    rows = [" " * col + c(FRAME, "│") if col is not None else ""] + creatures(shown, trophies, width, tick, view, decs, week, page, log)
    foot = (" " + hint("t", "trophies", "t", view) + "  " + dec_hint(view, len(decs)) + "  " + hint("c", "log", "c", view) + "  " + week_hint(week) + "  " +
            c(KEY, "r") + c(DIM, " redraw  ") + c(KEY, "q") + c(DIM, " close"))
    return panel(workers, rows, w, (), landed, foot, col)

# ---- strip layout: the same Mochi rows and trophy column without the spacing rows, for the pinned strip ----
FULL_ROWS = 16   # the full panel's height with one row of creatures; anything shorter gets the strip
STRIP_ROWS = 13  # the strip's height with one row of creatures: frame and the creature row

def full_rows(n, width=W): return FULL_ROWS + CH * (grid(n, width)[1] - 1)
def strip_rows(n, width=W): return STRIP_ROWS + CH * (grid(n, width)[1] - 1)  # a second row of creatures grows the strip
def layout_for(rows, n=0, width=W): return "full" if rows >= full_rows(n, width) else "strip"

def render_strip(workers, trophies, width=W, tick=None, view=None, week=False, page=0, log=(), landed=0):
    shown, w = workers[:SHOWN], grid(len(workers), width)[2]
    decs = decisions_of(workers)
    keys = [c(DIM, " · ") + x for x in (c(KEY, "q") + c(DIM, " close"), hint("t", "trophies", "t", view), dec_hint(view, len(decs)), hint("c", "log", "c", view), week_hint(week))]
    if decs and view != "d": keys.insert(1, keys.pop(2))  # something waits: "d needs you (N)" outlives "t trophies" when the bar is tight
    if view == "c": keys.insert(1, keys.pop(3))  # the open log's "c back" outlives the rest
    return panel(workers, creatures(shown, trophies, width, tick, view, decs, week, page, log), w, keys, landed, col=divider(w, view))

def draw(workers, trophies, rows, width=W, tick=None, view=None, week=False, page=0, log=(), landed=0):  # -> lines for a terminal this size; never more lines than fit (that would scroll)
    lay = render if layout_for(rows, len(workers), width) == "full" else render_strip
    return lay(workers, trophies, width, tick, view, week, page, log, landed)[:max(1, rows)]

# ---- --pin: the startup hook. Opens the pet as a strip on top of the Firstmate tab, once ----
TITLE = "Wallie's Wardens"  # the pane label Herdr gives the plugin pane (manifest title)

def same_dir(a, b): return bool(a and b) and os.path.realpath(a) == os.path.realpath(b)

def is_pet(p): return p.get("label") in (TITLE, "Firstmate Pet")  # label only: a cwd match could close someone's shell in the plugin dir

def running_pet(info):  # Herdr restores a pet pane as a bare shell, so a pet pane counts only while pet.py runs in it
    return any("pet.py" in x.get("cmdline", "") for x in info.get("foreground_processes", []))

def pin_target(panes, workspaces, home):
    """-> the pane to pin above: the one in the Firstmate home, else the focused (or first) pane of the active tab."""
    fm = next((p for p in panes if same_dir(p.get("cwd"), home)), None)
    if fm: return fm["pane_id"]
    tab = next((w.get("active_tab_id") for w in workspaces if w.get("focused")), None)
    in_tab = [p for p in panes if p.get("tab_id") == tab]
    target = next((p for p in in_tab if p.get("focused")), in_tab[0] if in_tab else None)
    return target and target["pane_id"]

def strip_amount(pet_h, target_h, rows):  # pane.resize takes a split-ratio delta: > 0 shrinks the pet to rows (borders included), < 0 grows it
    total = pet_h + target_h
    return round((pet_h - rows) / total, 3) if total else 0

def herdr_call(herdr, *args):
    import json, subprocess
    r = subprocess.run([herdr, *args], capture_output=True, text=True, timeout=10)
    out = json.loads(r.stdout or "{}")
    if "error" in out or r.returncode: raise RuntimeError(f"herdr {' '.join(args)}: {r.stdout.strip() or r.stderr.strip()}")
    return out["result"]

def fit_strip(call, pet, rows):  # make the pet pane (on top of its split) `rows` tall inside its borders
    below = call("pane", "neighbor", "--pane", pet, "--direction", "down")["neighbor"].get("neighbor_pane_id")
    h = {p["pane_id"]: p["rect"]["height"] for p in call("pane", "layout", "--pane", pet)["layout"]["panes"]}
    view = call("pane", "get", pet)["pane"]["scroll"]["viewport_rows"]
    amount = strip_amount(h.get(pet, 0), h.get(below, 0), rows + h.get(pet, 0) - view)
    if amount: call("pane", "resize", "--pane", pet, "--direction", "up" if amount > 0 else "down", "--amount", str(abs(amount)))

def refocus_cmds(was, pane, neighbor):
    """-> Herdr calls that put focus back on `was` after `pane swap` focused `pane`. neighbor(d) -> pane_id next to `pane`."""
    if not was or was["pane_id"] == pane["pane_id"]: return []
    if was.get("tab_id") != pane.get("tab_id"):
        return [c[1:] for c in focus_cmds(dict(ws=was.get("workspace_id"), tab=was.get("tab_id")))]
    d = next((d for d in ("up", "down", "left", "right") if neighbor(d) == was["pane_id"]), None)
    return [["pane", "focus", "--pane", pane["pane_id"], "--direction", d]] if d else []  # ponytail: a same-tab pane not touching the Firstmate pane keeps focus there

def pin(herdr, home):
    call = functools.partial(herdr_call, herdr)
    panes = call("pane", "list")["panes"]
    for p in [p for p in panes if is_pet(p)]:
        if running_pet(call("pane", "process-info", "--pane", p["pane_id"])["process_info"]):
            print(f"pet pane already open: {p['pane_id']}"); return 0
        call("pane", "close", p["pane_id"]); panes.remove(p)  # a restored husk: replace it
    pane = pin_target(panes, call("workspace", "list")["workspaces"], home)
    if not pane: print("no pane to pin to"); return 0
    was = next((p for p in panes if p.get("focused")), None)
    opened = call("plugin", "pane", "open", "--plugin", os.environ.get("HERDR_PLUGIN_ID", "firstmate.pet"), "--entrypoint", "pet",
                  "--placement", "split", "--direction", "down", "--target-pane", pane, "--no-focus", "--env", f"FM_HOME={home}",
                  "--env", "PET_STRIP=1")
    new = opened["plugin_pane"]["pane"]["pane_id"]
    # Herdr splits only right or down, so swap the pet above the pane. Swap focuses its source: make that the pane, then restore
    call("pane", "swap", "--source-pane", pane, "--target-pane", new)
    fm = next(p for p in panes if p["pane_id"] == pane)
    for cmd in refocus_cmds(was, fm, lambda d: call("pane", "neighbor", "--pane", pane, "--direction", d)["neighbor"].get("neighbor_pane_id")):
        call(*cmd)
    fit_strip(call, new, strip_rows(len(Pet(home, lambda: panes).poll(time.time()))))  # the strip itself refits when a second row comes or goes
    print(f"pinned pet pane {new} above {pane}"); return 0

# ---- config + live loop ----
def setting(key, default):  # the environment, then a KEY=value line in the plugin config file
    if os.environ.get(key): return os.environ[key]
    cfg = os.path.join(os.environ.get("HERDR_PLUGIN_CONFIG_DIR", ""), "config")
    try:
        for line in open(cfg, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == key and v: return v.strip().strip('"')
    except OSError: pass
    return default

def fm_home(): return os.path.expanduser(setting("FM_HOME", DEFAULT_HOME))
def animate(): return setting("PET_ANIMATE", "1").lower() not in ("0", "off", "no", "false")

ALIASES = dict(l="c", n="s", p="a")  # the old right-hand keys still work, unadvertised: every hint names a left-hand key

def focus_cmds(w, herdr="herdr"):  # the CLI has no pane focus by id: focus the worker's workspace, then its tab
    return [[herdr, "workspace", "focus", w["ws"]]] * bool(w.get("ws")) + [[herdr, "tab", "focus", w["tab"]]] * bool(w.get("tab"))

def live(pet):
    import select, signal, termios, tty
    fd, out = sys.stdin.fileno(), sys.stdout
    tiled = bool(os.environ.get("HERDR_PANE_ID"))  # a popup gets no pane id; a tiled strip stays open after a focus
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    wake_r, wake_w = os.pipe()
    os.set_blocking(wake_w, False)
    signal.signal(signal.SIGWINCH, lambda *_: None)
    signal.set_wakeup_fd(wake_w)  # a resize wakes the select below instead of waiting out the poll
    strip, anim, herdr = os.environ.get("PET_STRIP") and tiled, animate(), os.environ.get("HERDR_BIN_PATH", "herdr")
    out.write("\x1b[?1049h\x1b[?25l"); out.flush()
    last, workers, tick, next_poll, asked, view, page = None, [], 0, 0, None, None, 0
    try:
        while True:
            now = time.time()
            if now >= next_poll: workers, next_poll = pet.poll(now), now + POLL  # status files: every POLL, not every frame
            size = os.get_terminal_size(fd)
            want = strip_rows(len(workers), size.columns)
            if strip and (want, size.lines) != asked:  # the pinned strip grows for a second row of creatures, shrinks back after
                asked = (want, size.lines)
                if want != size.lines:
                    try: fit_strip(functools.partial(herdr_call, herdr), os.environ["HERDR_PANE_ID"], want)
                    except Exception: pass  # ponytail: a failed refit leaves the strip as it is; the next change retries
            text = [to_ansi(l) for l in draw(workers, pet.trophies, size.lines, size.columns, tick if anim else None, view, pet.week, page, pet.log, pet.landed)]
            if last is None or len(text) != len(last):  # first frame or resize: clear and draw it all
                out.write("\x1b[H\x1b[2J" + "\n".join(text)); out.flush()
            elif text != last:  # otherwise rewrite only the lines that changed (mostly sprite rows while animating)
                out.write("".join(f"\x1b[{n};1H{l}" for n, (l, o) in enumerate(zip(text, last), 1) if l != o)); out.flush()
            last = text
            ready = select.select([fd, wake_r], [], [], max(0, min(ANIM if anim else POLL, next_poll - time.time())))[0]
            if not ready: tick += anim
            if wake_r in ready: os.read(wake_r, 64); last = None
            if fd not in ready: continue
            key = os.read(fd, 1).decode(errors="ignore")
            key = ALIASES.get(key, key)
            if key in ("q", "\x03") or key == "\x1b" and not tiled: return  # Esc starts arrow keys too: only the popup takes it
            if key == "r": last = None
            if key == "w": pet.week, next_poll = not pet.week, 0  # the next loop polls, so the trophies are recomputed at once
            if key in ("t", "d", "c", "w"): page = 0  # a new view or span starts on its first page
            if key in ("t", "d", "c"): view = None if view == key else key  # same height in every view, so the strip never refits
            if key in ("s", "a") and view in ("t", "c"):  # page through trophies or log entries that do not fit
                _, nrows, w = grid(len(workers), size.columns)
                pages = trophy_pages(pet.trophies, CH * nrows, w - 2) if view == "t" else log_pages(pet.log, CH * nrows, w - 2)
                page = min(max(page + (1 if key == "s" else -1), 0), len(pages) - 1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[0m\x1b[?25h\x1b[?1049l"); out.flush()

def main(argv):
    if "--pin" in argv: return pin(os.environ.get("HERDR_BIN_PATH", "herdr"), fm_home())
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")  # ponytail: one `pane list` per poll (every POLL s); a missing herdr just means no main Mochi
    pet = Pet(fm_home(), lambda: herdr_call(herdr, "pane", "list")["panes"])
    if "--once" in argv:
        lay = render_strip if "--strip" in argv else render
        ws = pet.poll(time.time())
        print("\n".join(to_ansi(l) for l in lay(ws, pet.trophies, week=pet.week, landed=pet.landed)))
        return 0
    try: live(pet)
    except KeyboardInterrupt: pass
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
