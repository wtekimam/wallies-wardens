#!/usr/bin/env python3
"""herdr pet: one Mochi per Firstmate worker, plus one (blue, first) for the main Firstmate session, in a Herdr pane (a strip on top of the Firstmate tab, or a popup).

Read-only view of a Firstmate home. The main session's mood is the agent_status of the Herdr pane whose cwd is the home
(`herdr pane list`, once per poll). Per worker it reads only state/<id>.meta, the tail of
state/<id>.status, the mtime of state/<id>.turn-ended and the mtime of state/<id>.inbox/handled/.
It never writes under the Firstmate home and never runs Firstmate scripts.

  python3 pet.py            live pane: read status every 3s, animate about twice a second, redraw only changed lines
  python3 pet.py --once     print one frame to stdout and exit (--once --strip: the strip's frame)
  python3 pet.py --pin      open the pet as a strip on top of the Firstmate tab unless one is open (startup hook)

PET_ANIMATE=0 (environment, or a line in the plugin config file) keeps the Mochis still.
"""
import functools, math, os, re, sys, time, zlib

POLL = 3                 # seconds between polls
ASLEEP_SECS = 30 * 60    # no status or turn activity this long (and not calling) -> asleep
HUNGER_STEP = 10 * 60    # one heart lost per this long spent calling without a new message
PARTY_SECS = 30          # how long a merged worker parties before its cup lands in the trophy row
ANIM = 0.5               # seconds between animation frames (status files are still read every POLL)
SHOWN = 8                # creatures on screen; the rest become "+N more"
DEFAULT_HOME = os.path.expanduser("~/Documents/firstmate")

# ---- tiny markup: {#rrggbb} fg, {@rrggbb} bg, {b} bold, {/} reset (lifted from the design build.py) ----
TAG = re.compile(r"\{(?:([#@])([0-9a-fA-F]{6})|(b)|(/))\}")
FG, DIM, FRAME = "#c0caf5", "#565f89", "#3b4261"

def parse(s):
    segs, fg, bg, bold, pos = [], None, None, False, 0
    for m in TAG.finditer(s):
        if m.start() > pos: segs.append((s[pos:m.start()], fg, bg, bold))
        if m.group(1) == "#": fg = "#" + m.group(2)
        elif m.group(1) == "@": bg = "#" + m.group(2)
        elif m.group(3): bold = True
        else: fg = bg = None; bold = False
        pos = m.end()
    if pos < len(s): segs.append((s[pos:], fg, bg, bold))
    return segs

@functools.lru_cache(maxsize=4096)  # animation redraws the same few lines over and over
def vis(s): return sum(len(t) for t, *_ in parse(s))
def rgb(h): return ";".join(str(int(h[i:i+2], 16)) for i in (1, 3, 5))

@functools.lru_cache(maxsize=4096)
def to_ansi(s):
    out, cur = [], (None, None, False)
    for t, fg, bg, bold in parse(s):
        st = (fg, bg, bold)
        if st != cur:
            codes = ["0"] + (["1"] if bold else []) + ([f"38;2;{rgb(fg)}"] if fg else []) + ([f"48;2;{rgb(bg)}"] if bg else [])
            out.append(f"\x1b[{';'.join(codes)}m"); cur = st
        out.append(t)
    return "".join(out) + "\x1b[0m"

def c(col, text, bold=False): return f"{{#{col.lstrip('#')}}}{'{b}' if bold else ''}{text}{{/}}"
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

def read_worker(state_dir, wid, now):
    meta = read_meta(os.path.join(state_dir, wid + ".meta"))
    status_path = os.path.join(state_dir, wid + ".status")
    st, text, at = status_state(tail(status_path))
    kind = meta.get("kind", "ship")
    last_active = max(mtime(status_path), mtime(os.path.join(state_dir, wid + ".turn-ended")))
    fed_at = mtime(os.path.join(state_dir, wid + ".inbox", "handled"))  # dir mtime moves when a message is handled
    spawn = meta.get("spawn_gen", "")[1:].split(".")[0]
    born = int(spawn) if spawn.isdigit() else mtime(os.path.join(state_dir, wid + ".meta"))

    bubble, sub = "", ""
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
                pane=meta.get("herdr_pane_id"), merge_ready=mood == "party" or (mood == "calling" and kind != "scout" and st == "done"))

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
                hn="main session", acc="collar", colour=MAIN, ws=p.get("workspace_id"), tab=p.get("tab_id"), pane=p.get("pane_id"), merge_ready=False)

# ---- the pet: keeps accessories stable, parties merged workers and keeps their cups (process memory only) ----
class Pet:
    def __init__(self, home, list_panes=None):  # list_panes() -> Herdr's pane list; None (no Herdr) means no main Mochi
        self.home, self.list_panes = home, list_panes
        self.state = os.path.join(home, "state")
        self.accs, self.seen, self.ghosts, self.trophies = {}, {}, [], []

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
        for wid, w in self.seen.items():  # record gone: a merge-ready worker was torn down after landing
            if wid not in live and w["merge_ready"]:
                self.ghosts.append({**w, "mood": "party", "bubble": "", "sub": "merged!", "gone": now})
        self.seen = {w["id"]: w for w in workers}
        for g in [g for g in self.ghosts if now - g["gone"] >= PARTY_SECS]:
            self.ghosts.remove(g)
            self.trophies.append((g["project"], short_task(g["id"], g["project"]), time.strftime("%H:%M", time.localtime(g["gone"]))))
        return self.main_mochi(now) + workers + self.ghosts

    def main_mochi(self, now):  # the Firstmate session's own pane, if Herdr has one; any Herdr trouble means none
        if not self.list_panes: return []
        try: p = next((p for p in self.list_panes() if same_dir(p.get("cwd"), self.home) and not is_pet(p)), None)
        except Exception: return []
        return [main_worker(p)] if p else []

# ---- layout: 80 columns, wider when the pane fits more cells ----
W, CW, CH = 80, 19, 10  # minimum frame width; one creature cell's width and height
MC = dict(busy="7dcfff", training="ff9e64", calling="bb9af7", sick="9ece6a", asleep="7d8fd0", party="e0af68")

def grid(n, width=W):  # -> (columns, rows of creatures, frame width): as many cells across as fit, never fewer than four
    cols = min(SHOWN, (max(width, W) - 4) // CW)
    return cols, max(1, math.ceil(min(n, SHOWN) / cols)), max(W, cols * CW + 4)

def frame(title, rows, right="", w=W):
    inner = w - 2
    used = 3 + vis(title) + 1 + (vis(right) + 1 if right else 0)
    top = c(FRAME, "╭─ ") + c("bb9af7", title, True) + c(FRAME, " " + "─" * (w - 1 - used)) + (" " + right if right else "") + c(FRAME, "╮")
    return [top] + [c(FRAME, "│") + padr(r, inner) + c(FRAME, "│") for r in rows] + [c(FRAME, "╰" + "─" * inner + "╯")]

def hearts(n): return c("f7768e", "●" * n) + c(DIM, "○" * (5 - n))  # ● is solid in every terminal font; ♥ drew as an outline in Herdr

def cell(i, w, tick=None):  # tick None: the still frame
    proj = clip(w["project"], 8)
    task = clip(short_task(w["id"], w["project"]), CW - 3 - len(proj) - 3)  # one column left free between cells
    label = c("e0af68", str(i), True) + " " + c(FG, proj, True) + c(DIM, " · ") + c("a9b1d6", task)
    last = c("ffffff", f'"{w["bubble"]}"', True) if w["bubble"] else c(DIM, w["sub"])
    f = 0 if tick is None else ((tick // 2 if w["mood"] == "asleep" else tick) + i) % 2  # neighbours out of step; asleep at half speed
    body = creature(w["mood"], w.get("acc"), w.get("colour", colour_of(w["project"])), f)
    return [center(x, CW) for x in body] + [center(label, CW), center(c(MC[w["mood"]], w["mood"]) + c(DIM, f" · {w['age']}"), CW),
            center(c(DIM, w["hn"]) if w["hunger"] is None else hearts(w["hunger"]) + c(DIM, " " + w["hn"]), CW), center(last, CW)]

def trophy_rows(items):
    head = " " + c("f7d774", "trophies · this session", True)
    if not items: return ["", head + c(DIM, "   none yet: merge a PR and your pet leaves one here"), ""]
    shown, more = items[-3:], len(items) - 3
    cells = [[" " + CUP[0] + " " + c(FG, clip(p, 10), True) + c(DIM, " · ") + c("a9b1d6", clip(t, 11)),
              " " + CUP[1] + " " + c(DIM, f"merged {tm}")] for p, t, tm in shown]
    tag = c(DIM, f"   +{more} earlier") if more > 0 else ""
    return [head + tag] + ["".join(padr(cl[i], 26) for cl in cells) for i in range(2)]

def panel(workers, rows, w=W):
    more = len(workers) - SHOWN
    n = sum(not w.get("main") for w in workers)
    right = (c("e0af68", f"+{more} more", True) + c(DIM, " · ") if more > 0 else "") + c("9ece6a", "●") + c(DIM, f" live {POLL}s")
    return frame(f"herdr pet · {n} worker{'s' if n != 1 else ''}", rows, right, w)

def creatures(shown, width=W, tick=None):  # up to eight Mochis, as many across as fit, CH rows each: sprite, label, mood, hearts, bubble
    cols, _, w = grid(len(shown), width)
    if not shown: return [""] * 4 + [center(c(DIM, "no workers aboard · Mochi waits for the next task"), w - 2)] + [""] * 5
    cells = [cell(i, x, tick) for i, x in enumerate(shown, 1)]
    return ["  " + "".join(col[i] for col in cells[k:k + cols]) for k in range(0, len(cells), cols) for i in range(CH)]

def render(workers, trophies, width=W, tick=None):
    shown, w = workers[:SHOWN], grid(len(workers), width)[2]
    sep = c(FRAME, " " + "─" * (w - 4))
    rows = [""] + creatures(shown, width, tick) + [sep] + trophy_rows(trophies) + [sep, " " + c("e0af68", "r") + c(DIM, " redraw  ") + c("e0af68", "q") + c(DIM, " close")]
    return panel(workers, rows, w)

# ---- strip layout: the same Mochi rows, trophies and keys on one line, for the pinned strip ----
FULL_ROWS = 19   # the full panel's height with one row of creatures; anything shorter gets the strip
STRIP_ROWS = 13  # the strip's height with one row of creatures: frame, the creature row, one trophy line

def full_rows(n, width=W): return FULL_ROWS + CH * (grid(n, width)[1] - 1)
def strip_rows(n, width=W): return STRIP_ROWS + CH * (grid(n, width)[1] - 1)  # a second row of creatures grows the strip
def layout_for(rows, n=0, width=W): return "full" if rows >= full_rows(n, width) else "strip"

def render_strip(workers, trophies, width=W, tick=None):
    shown, w = workers[:SHOWN], grid(len(workers), width)[2]
    keys_txt = c("e0af68", "q") + c(DIM, " close")
    room = w - 2 - vis(keys_txt) - 1 - len(" trophies ")
    cups = []
    for k, (p, t, tm) in enumerate(reversed(trophies), 1):  # newest first, as many as fit
        item = f"{clip(p, 8)} · {clip(t, 8)} {tm}"
        if len("  ".join(cups + [item])) + (len(f"  +{len(trophies)} earlier") if k < len(trophies) else 0) > room: break
        cups.append(item)
    tro = " ".join([c("f7d774", " trophies", True), c(FG, "  ".join(cups)) if cups else c(DIM, "none yet")] +
                   [c(DIM, f" +{len(trophies) - len(cups)} earlier")] * (len(trophies) > len(cups)))
    return panel(workers, creatures(shown, width, tick) + [padr(tro, w - 2 - vis(keys_txt) - 1) + keys_txt + " "], w)

def draw(workers, trophies, rows, width=W, tick=None):  # -> lines for a terminal this size; never more lines than fit (that would scroll)
    lay = render if layout_for(rows, len(workers), width) == "full" else render_strip
    return lay(workers, trophies, width, tick)[:max(1, rows)]

# ---- --pin: the startup hook. Opens the pet as a strip on top of the Firstmate tab, once ----
TITLE = "Firstmate Pet"  # the pane label Herdr gives the plugin pane (manifest title)

def same_dir(a, b): return bool(a and b) and os.path.realpath(a) == os.path.realpath(b)

def is_pet(p): return p.get("label") == TITLE  # label only: a cwd match could close someone's shell in the plugin dir

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
    last, workers, tick, next_poll, asked = None, [], 0, 0, None
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
            text = [to_ansi(l) for l in draw(workers, pet.trophies, size.lines, size.columns, tick if anim else None)]
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
            if key in ("q", "\x03") or key == "\x1b" and not tiled: return  # Esc starts arrow keys too: only the popup takes it
            if key == "r": last = None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[0m\x1b[?25h\x1b[?1049l"); out.flush()

def main(argv):
    if "--pin" in argv: return pin(os.environ.get("HERDR_BIN_PATH", "herdr"), fm_home())
    herdr = os.environ.get("HERDR_BIN_PATH", "herdr")  # ponytail: one `pane list` per poll (every POLL s); a missing herdr just means no main Mochi
    pet = Pet(fm_home(), lambda: herdr_call(herdr, "pane", "list")["panes"])
    if "--once" in argv:
        lay = render_strip if "--strip" in argv else render
        print("\n".join(to_ansi(l) for l in lay(pet.poll(time.time()), pet.trophies)))
        return 0
    try: live(pet)
    except KeyboardInterrupt: pass
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
