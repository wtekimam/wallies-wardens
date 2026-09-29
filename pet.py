#!/usr/bin/env python3
"""herdr pet: one Mochi per Firstmate worker, in a Herdr pane (a strip under the Firstmate tab, or a popup).

Read-only view of a Firstmate home. Per worker it reads only state/<id>.meta, the tail of
state/<id>.status, the mtime of state/<id>.turn-ended and the mtime of state/<id>.inbox/handled/.
It never writes under the Firstmate home and never runs Firstmate scripts.

  python3 pet.py            live pane: poll every 3s, redraw only when the frame changes
  python3 pet.py --once     print one frame to stdout and exit (--once --compact: the short-strip frame)
  python3 pet.py --pin      open the pet as a short strip in the Firstmate tab unless one is open (startup hook)
"""
import os, re, sys, time, zlib

POLL = 3                 # seconds between polls
ASLEEP_SECS = 30 * 60    # no status or turn activity this long (and not calling) -> asleep
HUNGER_STEP = 10 * 60    # one heart lost per this long spent calling without a new message
PARTY_SECS = 30          # how long a merged worker parties before its cup lands in the trophy row
SHOWN = 4                # creatures on screen; the rest become "+N more"
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

def vis(s): return sum(len(t) for t, *_ in parse(s))
def rgb(h): return ";".join(str(int(h[i:i+2], 16)) for i in (1, 3, 5))

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

def put(g, edits, over=False, body=False):  # over: only empty cells (props never clobber the creature); body: only creature cells
    for r, col, s in edits:
        for i, ch in enumerate(s):
            if ch == "_" or not (0 <= col + i < 12 and 0 <= r < 12): continue
            empty = g[r][col + i] == "."
            if not (over and not empty or body and empty): g[r][col + i] = ch
    return g

def up(g):  # hop: whole sprite one pixel up
    return g[1:] + [["."] * 12] if all(x == "." for x in g[0]) else g

def mix(h, h2, t):
    a, b = [int(h[i:i+2], 16) for i in (1, 3, 5)], [int(h2[i:i+2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))

PROPS = dict(E="#2b2118", N="#2b2118", M="#5a2230", T="#f7768e", R="#f7768e", Y="#f7d774", y="#c99a2e", C="#7dcfff", G="#9ece6a",
             P="#ff9ec7", S="#8b93b0", s="#3b4261", K="#cfe8ff", k="#8fb4d8", Z="#9db1ff", z="#7d8fd0", D="#c99a62", O="#d4e157", W="#f4f4f8")
TINT = "BdWAb"  # sick/asleep tint touches only the creature's own colours

# er = eye row, ec = eye columns, tall = 2px eyes, mr = mouth row, hb = headband row, ar = raised-arm row,
# ax = arm columns, dy / cap_dy = accessory row shift; a baby's accessories are clipped to its smaller body
STAGES = dict(
 grown=dict(grid=["............", "..A......A..", "..AP....PA..", "..ABBBBBBA..", "..BBBBBBBB..", "..BEBBBBEB..",
                  ".wBBBPPBBBw.", "..BBBMMBBB..", "...BBBBBB.b.", "...BWWWWB.b.", "...BWWWWBbb.", "...BB..BB..."],
            er=5, ec=(3, 8), tall=False, mr=7, hb=4, ar=6, ax=(1, 10), dy=0, cap_dy=0),
 # baby: 6px head with big 2px eyes on a tiny body, no tail
 baby=dict(grid=["............", "............", "............", "............", "...A....A...", "...ABBBBA...",
                 "...BEBBEB...", "..wBEPPEBw..", "...BBMMBB...", "....BBBB....", "....BWWB....", "....B..B...."],
           er=6, ec=(4, 7), tall=True, mr=8, hb=5, ar=9, ax=(3, 8), dy=1, cap_dy=2),
 # egg: amber shell in the project colour, cream spots, Mochi's ear tips poking out
 egg=dict(grid=["............", "............", "............", "....A..A....", "....BBBB....", "...BBWBBB...",
                "..BBBBBBWB..", "..BWBBBBBB..", "..BBBBBWBB..", "...BBBBBB...", "....BBBB....", "............"]),
)

PROJECT_PALS = [  # eight project colours: ginger, grey, charcoal (yellow eyes), cream, brown, lilac, teal, rose
 dict(B="#ffb454", d="#e0902e", W="#fff1d6", A="#e0902e", w="#c0caf5", b="#e0902e"),
 dict(B="#9aa5b8", d="#7b879c", W="#e8ecf5", A="#7b879c", w="#c0caf5", b="#7b879c"),
 dict(B="#5f6688", d="#474d6b", W="#8a91b3", A="#474d6b", w="#c0caf5", b="#474d6b", E="#ffd866"),
 dict(B="#f3e2c0", d="#d9c39a", W="#fffaf0", A="#d9c39a", w="#c0caf5", b="#d9c39a"),
 dict(B="#b98a62", d="#8f6644", W="#ecd3b0", A="#8f6644", w="#c0caf5", b="#8f6644"),
 dict(B="#b9a4e8", d="#9682cf", W="#f0eaff", A="#9682cf", w="#c0caf5", b="#9682cf"),
 dict(B="#5fd7c0", d="#3fb8a2", W="#e0fff7", A="#3fb8a2", w="#c0caf5", b="#3fb8a2"),
 dict(B="#ff8fa3", d="#e06a86", W="#ffe3d6", A="#e06a86", w="#c0caf5", b="#e06a86")]

def colour_of(project):  # stable across runs (crc32, not hash()); collisions accepted for now per the captain
    return zlib.crc32(project.encode()) % len(PROJECT_PALS)

ACCS = [None, "collar", "scarf", "cap", "sunglasses", "mask"]  # worker #1 in a project wears nothing
ACC = dict(
 sunglasses=[(5, 2, "NCNNNCNN"), (6, 3, "NN"), (6, 7, "NN")], scarf=[(8, 3, "RWRWRW"), (9, 3, "R")],
 collar=[(8, 3, "CCCCCC"), (9, 5, "Y")], cap=[(1, 5, "OO"), (2, 4, "OOOO")],
 mask=[(6, 3, "KKKKKK"), (7, 3, "KkKKkK"), (8, 4, "KKKK"), (6, 2, "k"), (6, 9, "k")])
CONFETTI = [(0, 1, "P"), (0, 4, "Y"), (1, 2, "C"), (0, 8, "G"), (2, 0, "Y"), (0, 11, "P"), (2, 11, "C"), (4, 0, "G"), (1, 6, "R"), (3, 10, "Y"), (5, 11, "P")]

def shade(g, pal):  # underside shadow: body pixels with empty space below get the darker 'd'
    return [[("d" if ch == "B" and (r == 11 or g[r + 1][i] == ".") else ch) for i, ch in enumerate(row)] for r, row in enumerate(g)]

def creature(mood, stage="grown", acc=None, colour=0):
    st, pal = STAGES[stage], {**PROPS, **PROJECT_PALS[colour]}
    g = G(st["grid"])
    if stage == "egg":  # an egg has no face: it only dozes, sickens, calls or parties
        if mood == "asleep":
            put(g, [(0, 9, "ZZZ"), (1, 10, "Z"), (2, 9, "ZZZ")], over=True); pal = mood_pal(pal, "#7080c0", 0.55)
        elif mood == "sick": pal = mood_pal(pal, "#9ece6a", 0.45)
        elif mood == "calling": put(g, [(0, 11, "R"), (1, 11, "R"), (3, 11, "R")], over=True)
        elif mood == "party": g = up(g); put(g, CONFETTI, over=True)
        return render_px(shade(g, pal), pal)
    er, (cl, cr), tall, mr, ar, (a0, a1) = st["er"], st["ec"], st["tall"], st["mr"], st["ar"], st["ax"]
    for r, col, s in ACC.get(acc, []):
        cap = acc == "cap"
        put(g, [(r + st["cap_dy" if cap else "dy"], col, s)], body=stage == "baby" and not cap)
    def eyes(kind):
        if kind == "focus": put(g, [(er - 1, cl, "NN"), (er - 1, cr - 1, "NN")])
        elif kind == "wide": put(g, [(er - 1 if tall else er + 1, cl, "E"), (er - 1 if tall else er + 1, cr, "E")])
        elif kind == "droop":
            for x in (cl, cr):
                g[er][x] = "B"
                if not tall: g[er + 1][x] = "E"
        elif kind == "dash":  # closed eyes: asleep and party
            for x in (cl, cr):
                g[er][x] = "B"
                if tall: g[er + 1][x] = "B"
            rr = er + 1 if tall else er
            put(g, [(rr, cl - 1, "EE"), (rr, cr, "EE")])
    def mouth(kind):
        if kind == "frown": put(g, [(mr + 1, 4, "M"), (mr + 1, 7, "M")])
        elif kind == "open": put(g, [(mr, 5, "MM"), (mr + 1, 5, "TT")])
    def arms_up(): put(g, [(ar, a0, "B"), (ar - 1, a0 - 1, "B"), (ar, a1, "B"), (ar - 1, a1 + 1, "B")])
    if mood == "busy":  # focused brows, swinging a hammer, sparks
        eyes("focus")
        put(g, [(3, 10, "SS"), (4, 10, "SS")] + [(r, 11, "D") for r in (5, 6, 7, 8)] + [(2, 10, "Y"), (1, 11, "Y"), (3, 9, "Y")], over=True)
    elif mood == "training":  # sweatband, hop, speed lines, ground shadow
        hb = st["hb"]
        put(g, [(hb, cl - 1, "R" * (cr - cl + 3)), (hb, cr + 2, "R"), (hb + 1, cr + 3, "R"), (er, cl - 2, "C"), (er + 1, cl - 2, "C")])
        g = up(g)
        put(g, [(11, 3, "ssssss"), (5, 0, "S"), (7, 0, "S"), (9, 0, "S")], over=True)
    elif mood == "calling":  # arms up, wide eyes, mouth open, "!" mark
        eyes("wide"); mouth("open"); arms_up()
        put(g, [(0, 11, "R"), (1, 11, "R"), (3, 11, "R")], over=True)
    elif mood == "sick":  # droopy eyes, frown, thermometer, sweat, green tint
        eyes("droop"); mouth("frown")
        put(g, [(4, 11, "W"), (5, 11, "W"), (6, 11, "W"), (7, 11, "R"), (er - 1, cl - 2, "C"), (er, cl - 2, "C")], over=True)
        pal = mood_pal(pal, "#9ece6a", 0.45)
    elif mood == "asleep":  # eyes shut, dim, zzz
        eyes("dash")
        put(g, [(0, 9, "ZZZ"), (1, 10, "Z"), (2, 9, "ZZZ"), (4, 10, "zz"), (5, 10, "z")], over=True)
        pal = mood_pal(pal, "#7080c0", 0.55)
    elif mood == "party":  # arms up, happy eyes, open mouth, hop, confetti
        eyes("dash"); mouth("open"); arms_up(); g = up(g)
        put(g, CONFETTI, over=True)
    return render_px(shade(g, pal), pal)

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
    """-> (state, text, at, validated). resolved/captain-held close an open decision or blocker."""
    state, text, at, validated = None, "", 0, False
    for line in lines:
        m = EVENT.match(line)
        if not m: continue
        verb, tok, body = m.groups()
        stamp = AT.search(tok or "") or AT.search(line)
        if VALIDATING.search(body) and verb in ("working", "paused"): validated = True
        if verb == "note": continue
        if verb in ("resolved", "captain-held"):
            if state in ("needs-decision", "blocked"): state, text = "working", body
            continue
        state, text, at = verb, body, int(stamp.group(1)) if stamp else at
    return state, text, at, validated

def read_worker(state_dir, wid, now):
    meta = read_meta(os.path.join(state_dir, wid + ".meta"))
    status_path = os.path.join(state_dir, wid + ".status")
    st, text, at, validated = status_state(tail(status_path))
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

    if st is None: stage = "egg"
    elif validated or meta.get("pr") or (kind == "scout" and st == "done") or mood in ("calling", "party"): stage = "grown"
    else: stage = "baby"

    hunger, hn = 5, "fed"
    if mood == "calling":
        waited = now - max(at or last_active, fed_at)
        hunger, hn = max(0, 5 - int(max(0, waited) // HUNGER_STEP)), "waiting " + age(max(0, now - (at or last_active)))
    project = os.path.basename(meta.get("project", "").rstrip("/")) or "?"
    return dict(id=wid, project=project, kind=kind, mood=mood, stage=stage, bubble=bubble, sub=sub, born=born,
                age=age(now - born), hunger=hunger, hn=hn, ws=meta.get("herdr_workspace_id"), tab=meta.get("herdr_tab_id"),
                pane=meta.get("herdr_pane_id"), merge_ready=mood == "party" or (mood == "calling" and kind != "scout" and st == "done"))

def age(secs):
    m = int(secs // 60)
    return f"{m}m" if m < 60 else f"{m // 60}h {m % 60}m" if m < 1440 else f"{m // 1440}d {m % 1440 // 60}h"

def short_task(wid, project):  # drop leading id words the project name already says: kara-web-unhide in kara-website -> unhide
    words = wid.split("-")
    while len(words) > 1 and words[0] in project: words.pop(0)
    return " ".join(words)

# ---- the pet: keeps accessories stable, parties merged workers and keeps their cups (process memory only) ----
class Pet:
    def __init__(self, home):
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
        for w in workers:  # sticky: a worker keeps its accessory; newcomers take the first free one in their project
            if w["id"] not in self.accs:
                taken = [a for k, a in self.accs.items() if live[k] == w["project"]]
                self.accs[w["id"]] = next((a for a in ACCS if a not in taken), ACCS[len(taken) % len(ACCS)])
            w["acc"] = self.accs[w["id"]]
        for wid, w in self.seen.items():  # record gone: a merge-ready worker was torn down after landing
            if wid not in live and w["merge_ready"]:
                self.ghosts.append({**w, "mood": "party", "stage": "grown", "bubble": "", "sub": "merged!", "gone": now})
        self.seen = {w["id"]: w for w in workers}
        for g in [g for g in self.ghosts if now - g["gone"] >= PARTY_SECS]:
            self.ghosts.remove(g)
            self.trophies.append((g["project"], short_task(g["id"], g["project"]), time.strftime("%H:%M", time.localtime(g["gone"]))))
        return workers + self.ghosts

# ---- layout: 80 columns ----
W, CW = 80, 19
MC = dict(busy="7dcfff", training="ff9e64", calling="bb9af7", sick="9ece6a", asleep="7d8fd0", party="e0af68")

def frame(title, rows, right=""):
    inner = W - 2
    used = 3 + vis(title) + 1 + (vis(right) + 1 if right else 0)
    top = c(FRAME, "╭─ ") + c("bb9af7", title, True) + c(FRAME, " " + "─" * (W - 1 - used)) + (" " + right if right else "") + c(FRAME, "╮")
    return [top] + [c(FRAME, "│") + padr(r, inner) + c(FRAME, "│") for r in rows] + [c(FRAME, "╰" + "─" * inner + "╯")]

def hearts(n): return c("f7768e", "♥" * n) + c(DIM, "♡" * (5 - n))

def cell(i, w):
    proj = clip(w["project"], 8)
    task = clip(short_task(w["id"], w["project"]), CW - 3 - len(proj) - 3)  # one column left free between cells
    label = c("e0af68", str(i), True) + " " + c(FG, proj, True) + c(DIM, " · ") + c("a9b1d6", task)
    last = c("ffffff", f'"{w["bubble"]}"', True) if w["bubble"] else c(DIM, w["sub"])
    body = creature(w["mood"], w["stage"], w.get("acc"), colour_of(w["project"]))
    return [center(x, CW) for x in body] + [center(label, CW), center(c(MC[w["mood"]], w["mood"]) + c(DIM, f" · {w['age']}"), CW),
            center(hearts(w["hunger"]) + c(DIM, " " + w["hn"]), CW), center(last, CW)]

def trophy_rows(items):
    head = " " + c("f7d774", "trophies · this session", True)
    if not items: return ["", head + c(DIM, "   none yet: merge a PR and your pet leaves one here"), ""]
    shown, more = items[-3:], len(items) - 3
    cells = [[" " + CUP[0] + " " + c(FG, clip(p, 10), True) + c(DIM, " · ") + c("a9b1d6", clip(t, 11)),
              " " + CUP[1] + " " + c(DIM, f"merged {tm}")] for p, t, tm in shown]
    tag = c(DIM, f"   +{more} earlier") if more > 0 else ""
    return [head + tag] + ["".join(padr(cl[i], 26) for cl in cells) for i in range(2)]

def render(workers, trophies):
    shown, more = workers[:SHOWN], len(workers) - SHOWN
    if shown:
        cols = [cell(i, w) for i, w in enumerate(shown, 1)]
        rows = [""] + ["  " + "".join(col[i] for col in cols) for i in range(len(cols[0]))]
    else:
        rows = [""] * 5 + [center(c(DIM, "no workers aboard · Mochi waits for the next task"), W - 2)] + [""] * 5
    sep = c(FRAME, " " + "─" * (W - 4))
    keys = f"1-{len(shown)}" if len(shown) > 1 else "1"
    rows += [sep] + trophy_rows(trophies) + [sep, " " + (c("e0af68", keys) + c(DIM, " focus worker  ") if shown else "") +
             c("e0af68", "r") + c(DIM, " redraw  ") + c("e0af68", "q") + c(DIM, " close")]
    right = (c("e0af68", f"+{more} more", True) + c(DIM, " · ") if more > 0 else "") + c("9ece6a", "●") + c(DIM, f" live {POLL}s")
    return frame(f"herdr pet · {len(workers)} worker{'s' if len(workers) != 1 else ''}", rows, right)

# ---- compact layout: one line per worker, for a short tiled strip ----
FULL_ROWS = 19  # the full panel's height; anything shorter gets the compact strip
FACE = dict(busy="(•_•)", training="(>_<)", calling="(°o°)", sick="(×_×)", asleep="(-_-)", party="(^o^)")

def layout_for(rows): return "full" if rows >= FULL_ROWS else "compact"

def strip_row(i, w):
    face = "( · )" if w["stage"] == "egg" else FACE[w["mood"]]
    label = padr(c(FG, clip(w["project"], 10), True) + c(DIM, " · ") + c("a9b1d6", clip(short_task(w["id"], w["project"]), 11)), 24)
    mood = padr(c(MC[w["mood"]], w["mood"]) + c(DIM, f" · {w['age']}"), 19)
    last = clip(f'"{w["bubble"]}"' if w["bubble"] else w["sub"], 18)
    last = c("ffffff", last, True) if w["bubble"] else c(DIM, last)
    return (" " + c("e0af68", str(i), True) + " " + c(PROJECT_PALS[colour_of(w["project"])]["B"], face, True) + " " + label + " " +
            mood + hearts(w["hunger"]) + " " + last)

def render_compact(workers, trophies):
    shown, more = workers[:SHOWN], len(workers) - SHOWN
    rows = [strip_row(i, w) for i, w in enumerate(shown, 1)] or [center(c(DIM, "no workers aboard · Mochi waits for the next task"), W - 2)]
    keys = (f"1-{len(shown)}" if len(shown) > 1 else "1") * bool(shown)
    keys_txt = (c("e0af68", keys) + c(DIM, " focus  ") if keys else "") + c("e0af68", "q") + c(DIM, " close")  # r still redraws
    room = W - 2 - vis(keys_txt) - 1 - len(" trophies ")
    cups = []
    for k, (p, t, tm) in enumerate(reversed(trophies), 1):  # newest first, as many as fit
        item = f"{clip(p, 8)} · {clip(t, 8)} {tm}"
        if len("  ".join(cups + [item])) + (len(f"  +{len(trophies)} earlier") if k < len(trophies) else 0) > room: break
        cups.append(item)
    tro = " ".join([c("f7d774", " trophies", True), c(FG, "  ".join(cups)) if cups else c(DIM, "none yet")] +
                   [c(DIM, f" +{len(trophies) - len(cups)} earlier")] * (len(trophies) > len(cups)))
    rows.append(padr(tro, W - 2 - vis(keys_txt) - 1) + keys_txt + " ")
    right = (c("e0af68", f"+{more} more", True) + c(DIM, " · ") if more > 0 else "") + c("9ece6a", "●") + c(DIM, f" live {POLL}s")
    return frame(f"herdr pet · {len(workers)} worker{'s' if len(workers) != 1 else ''}", rows, right)

def draw(workers, trophies, rows):  # -> lines for a terminal this tall; never more lines than fit (that would scroll)
    lines = render(workers, trophies) if layout_for(rows) == "full" else render_compact(workers, trophies)
    return lines[:max(1, rows)]

# ---- --pin: the startup hook. Opens the pet as a strip at the bottom of the Firstmate tab, once ----
TITLE = "Firstmate Pet"  # the pane label Herdr gives the plugin pane (manifest title)
STRIP_ROWS = 8

def same_dir(a, b): return bool(a and b) and os.path.realpath(a) == os.path.realpath(b)

def is_pet(p): return p.get("label") == TITLE  # label only: a cwd match could close someone's shell in the plugin dir

def running_pet(info):  # Herdr restores a pet pane as a bare shell, so a pet pane counts only while pet.py runs in it
    return any("pet.py" in x.get("cmdline", "") for x in info.get("foreground_processes", []))

def pin_target(panes, workspaces, home):
    """-> the pane to split under: the one in the Firstmate home, else the focused (or first) pane of the active tab."""
    fm = next((p for p in panes if same_dir(p.get("cwd"), home)), None)
    if fm: return fm["pane_id"]
    tab = next((w.get("active_tab_id") for w in workspaces if w.get("focused")), None)
    in_tab = [p for p in panes if p.get("tab_id") == tab]
    target = next((p for p in in_tab if p.get("focused")), in_tab[0] if in_tab else None)
    return target and target["pane_id"]

def strip_amount(pet_h, target_h, rows=STRIP_ROWS):  # pane.resize takes a split-ratio delta: shrink the pet to ~rows
    total = pet_h + target_h
    return round((pet_h - rows) / total, 3) if total and pet_h > rows else 0

def pin(herdr, home):
    import json, subprocess
    def call(*args):
        r = subprocess.run([herdr, *args], capture_output=True, text=True, timeout=10)
        out = json.loads(r.stdout or "{}")
        if "error" in out or r.returncode: raise RuntimeError(f"herdr {' '.join(args)}: {r.stdout.strip() or r.stderr.strip()}")
        return out["result"]
    panes = call("pane", "list")["panes"]
    for p in [p for p in panes if is_pet(p)]:
        if running_pet(call("pane", "process-info", "--pane", p["pane_id"])["process_info"]):
            print(f"pet pane already open: {p['pane_id']}"); return 0
        call("pane", "close", p["pane_id"]); panes.remove(p)  # a restored husk: replace it
    pane = pin_target(panes, call("workspace", "list")["workspaces"], home)
    if not pane: print("no pane to pin under"); return 0
    opened = call("plugin", "pane", "open", "--plugin", os.environ.get("HERDR_PLUGIN_ID", "firstmate.pet"), "--entrypoint", "pet",
                  "--placement", "split", "--direction", "down", "--target-pane", pane, "--no-focus", "--env", f"FM_HOME={home}")
    new = opened["plugin_pane"]["pane"]["pane_id"]
    h = {p["pane_id"]: p["rect"]["height"] for p in call("pane", "layout", "--pane", new)["layout"]["panes"]}
    amount = strip_amount(h.get(new, 0), h.get(pane, 0))
    if amount: call("pane", "resize", "--pane", new, "--direction", "down", "--amount", str(amount))
    print(f"pinned pet pane {new} under {pane}"); return 0

# ---- config + live loop ----
def fm_home():
    if os.environ.get("FM_HOME"): return os.environ["FM_HOME"]
    cfg = os.path.join(os.environ.get("HERDR_PLUGIN_CONFIG_DIR", ""), "config")
    try:
        for line in open(cfg, encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "FM_HOME" and v: return os.path.expanduser(v.strip().strip('"'))
    except OSError: pass
    return DEFAULT_HOME

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
    out.write("\x1b[?1049h\x1b[?25l"); out.flush()
    last, workers = None, []
    try:
        while True:
            workers = pet.poll(time.time())
            text = "\n".join(to_ansi(l) for l in draw(workers, pet.trophies, os.get_terminal_size(fd).lines))
            if text != last:  # redraw only on change
                out.write("\x1b[H\x1b[2J" + text); out.flush(); last = text
            ready = select.select([fd, wake_r], [], [], POLL)[0]
            if wake_r in ready: os.read(wake_r, 64); last = None
            if fd not in ready: continue
            key = os.read(fd, 1).decode(errors="ignore")
            if key in ("q", "\x03") or key == "\x1b" and not tiled: return  # Esc starts arrow keys too: only the popup takes it
            if key == "r": last = None
            elif key.isdigit() and 1 <= int(key) <= min(SHOWN, len(workers)):
                w = workers[int(key) - 1]
                if w.get("gone"): continue
                import subprocess
                for cmd in focus_cmds(w, os.environ.get("HERDR_BIN_PATH", "herdr")):
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                if not tiled: return  # the popup is modal: close it so the focused worker is visible
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        out.write("\x1b[0m\x1b[?25h\x1b[?1049l"); out.flush()

def main(argv):
    if "--pin" in argv: return pin(os.environ.get("HERDR_BIN_PATH", "herdr"), fm_home())
    pet = Pet(fm_home())
    if "--once" in argv:
        lay = render_compact if "--compact" in argv else render
        print("\n".join(to_ansi(l) for l in lay(pet.poll(time.time()), pet.trophies)))
        return 0
    try: live(pet)
    except KeyboardInterrupt: pass
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
