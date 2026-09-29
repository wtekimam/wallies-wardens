"""python3 -m unittest test_pet  -- fixture Firstmate-style state dirs, no live home touched."""
import json, os, subprocess, sys, tempfile, time, unittest, zlib
import pet

NOW = 1790000000

class Home:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.state = os.path.join(self.root, "state")
        os.makedirs(self.state)

    def worker(self, wid, project="demo", kind="ship", lines=(), born=NOW - 600, active=NOW - 60, fed=NOW - 3600, pr=""):
        meta = os.path.join(self.state, wid + ".meta")
        with open(meta, "w") as f:
            f.write(f"project=/x/projects/{project}\nkind={kind}\nspawn_gen=s{born}.1.2\n"
                    f"herdr_workspace_id=w1\nherdr_tab_id=w1:t2\nherdr_pane_id=w1:p2\n" + (f"pr={pr}\n" if pr else ""))
        status = os.path.join(self.state, wid + ".status")
        if lines:
            with open(status, "w") as f: f.write("".join(l + "\n" for l in lines))
            os.utime(status, (active, active))
        handled = os.path.join(self.state, wid + ".inbox", "handled")
        os.makedirs(handled, exist_ok=True)
        os.utime(handled, (fed, fed))
        return wid

    def read(self, wid, now=NOW): return pet.read_worker(self.state, wid, now)

class Moods(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def check(self, lines, mood, bubble="", **kw):
        w = self.h.read(self.h.worker("demo-task", lines=lines, **kw))
        self.assertEqual(w["mood"], mood)
        self.assertEqual(w["bubble"], bubble)
        return w

    def test_busy_before_first_status(self): self.check([], "busy")
    def test_busy(self): self.check([f"working [at={NOW}]: building the thing"], "busy")
    def test_training(self): self.check([f"working [at={NOW}]: running no-mistakes validation"], "training")
    def test_paused_on_validation(self): self.check([f"paused [at={NOW}]: no-mistakes run in progress"], "training")
    def test_decision_calls(self): self.check([f"needs-decision [at={NOW}]: A or B"], "calling", "your call!")
    def test_resolved_decision_back_to_busy(self):
        self.check([f"needs-decision [key=k] [at={NOW}]: A or B", f"resolved [key=k] [at={NOW}]: A"], "busy")
    def test_pr_ready(self): self.check([f"done [at={NOW}]: PR https://x/pull/1"], "calling", "PR ready!")
    def test_report_ready(self): self.check([f"done [at={NOW}]: report written"], "calling", "report ready!", kind="scout")
    def test_blocked_sick(self): self.check([f"blocked [at={NOW}]: CI red"], "sick")
    def test_failed_sick(self): self.check([f"failed [at={NOW}]: gave up"], "sick")
    def test_merged_party(self): self.check([f"done [at={NOW}]: merged into main"], "party")
    def test_asleep_when_silent(self):
        self.check([f"working [at={NOW - 7200}]: building"], "asleep", active=NOW - pet.ASLEEP_SECS - 60)
    def test_calling_never_sleeps(self):
        self.check([f"needs-decision [at={NOW - 7200}]: A or B"], "calling", bubble="your call!", active=NOW - 7200)

class Hunger(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def test_drains_only_while_calling_and_feeds_on_message(self):
        waited = 2 * pet.HUNGER_STEP + 30
        wid = self.h.worker("demo-a", lines=[f"needs-decision [at={NOW - waited}]: A or B"], active=NOW - waited)
        self.assertEqual(self.h.read(wid)["hunger"], 3)
        handled = os.path.join(self.h.state, wid + ".inbox", "handled")
        os.utime(handled, (NOW - 5, NOW - 5))  # a message was handled: fed back to full
        self.assertEqual(self.h.read(wid)["hunger"], 5)
        self.assertEqual(self.h.read(wid, NOW + pet.HUNGER_STEP)["hunger"], 4)  # and drains again from the feed

    def test_long_busy_or_afk_is_not_hungry(self):
        wid = self.h.worker("demo-b", lines=[f"working [at={NOW - 86400}]: building"], active=NOW - 86400)
        self.assertEqual(self.h.read(wid)["hunger"], 5)

    def test_leaving_calling_feeds(self):
        wid = self.h.worker("demo-c", lines=[f"needs-decision [key=k] [at={NOW - 9999}]: A?", f"resolved [key=k] [at={NOW}]: A"])
        self.assertEqual(self.h.read(wid)["hunger"], 5)

class Panel(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def plain(self, lines): return [pet.TAG.sub("", l) for l in lines]

    def test_eight_shown_then_more(self):
        for i in range(10): self.h.worker(f"demo-t{i}", lines=[f"working [at={NOW}]: go"], born=NOW - 600 + i)
        p = pet.Pet(self.h.root)
        out = self.plain(pet.render(p.poll(NOW), p.trophies))
        self.assertIn("+2 more", out[0])
        self.assertIn("8 demo", "\n".join(out))
        self.assertNotIn("9 demo", "\n".join(out))
        self.assertTrue(all(len(l) == pet.W for l in out), [len(l) for l in out])

    def test_layout_one_to_nine(self):
        for n in range(1, 10):  # 80 columns: the trophy column leaves two Mochis across, so up to four rows
            rows = -(-min(n, 8) // 2)
            self.assertEqual(pet.grid(n), (2, rows, pet.W))
            self.assertEqual(pet.strip_rows(n), pet.STRIP_ROWS + pet.CH * (rows - 1))
            ws = [dict(id=f"demo-t{i}", project="demo", mood="busy", bubble="", sub="", age="1m", hunger=5, hn="fed", acc="cap") for i in range(n)]
            out = self.plain(pet.render_strip(ws, []))
            self.assertEqual(len(out), pet.strip_rows(n))
            self.assertTrue(all(len(l) == pet.W for l in out), (n, [len(l) for l in out]))
            self.assertEqual(("+1 more" in out[0]), n == 9)
        self.assertEqual(pet.grid(8, 240), (8, 1, 8 * pet.CW + 4 + pet.TW))  # a wide pane fits all eight in one row
        self.assertEqual(pet.grid(8, 160), (6, 2, 6 * pet.CW + 4 + pet.TW))
        self.assertEqual(pet.grid(3, 40), (2, 2, pet.W))  # narrower than 80 keeps the 80-column frame
        self.assertEqual(pet.layout_for(pet.FULL_ROWS, 8, 240), "full")
        self.assertEqual(pet.layout_for(pet.FULL_ROWS, 8), "strip")  # four rows need a taller pane for the full panel
        self.assertEqual(pet.layout_for(pet.FULL_ROWS + 3 * pet.CH, 8), "full")

    def test_accessories_everyone_wears_one(self):
        ids = [self.h.worker(f"demo-t{i}", lines=[f"working [at={NOW}]: go"], born=NOW - 900 + i) for i in range(7)]
        c = self.h.worker("other-one", project="other", lines=[f"working [at={NOW}]: go"])
        p = pet.Pet(self.h.root)
        ws = {w["id"]: w for w in p.poll(NOW)}
        self.assertEqual([ws[i]["acc"] for i in ids], ["collar", "scarf", "cap", "sunglasses", "mask", "collar", "scarf"])
        self.assertEqual(ws[c]["acc"], "collar")  # a lone worker is not bare
        os.remove(os.path.join(self.h.state, ids[1] + ".meta"))
        self.h.worker("demo-new", lines=[f"working [at={NOW}]: go"], born=NOW)
        ws = {w["id"]: w for w in p.poll(NOW + 3)}
        self.assertEqual(ws["demo-new"]["acc"], "scarf")  # a newcomer takes the first free one; the others keep theirs
        self.assertEqual(ws[ids[2]]["acc"], "cap")
        self.assertEqual(pet.colour_of("demo"), pet.colour_of("demo"))

    def test_accessories_show_on_the_sprite(self):
        for i in range(len(pet.PROJECT_PALS)):
            bare = pet.creature("busy", None, i)
            self.assertEqual(len({bare} | {pet.creature("busy", a, i) for a in pet.ACCS}), 1 + len(pet.ACCS))

    def test_animation_frames(self):
        for m in pet.MC:
            for a in pet.ACCS:
                f0, f1 = pet.creature(m, a, 6, 0), pet.creature(m, a, 6, 1)
                self.assertNotEqual(f0, f1, (m, a))  # every mood moves
                self.assertEqual(len(f1), 6)
                self.assertTrue(all(pet.vis(l) == 12 for l in f1))  # same footprint: the cell never jitters
        self.assertEqual(pet.creature("busy", "cap", 0), pet.creature("busy", "cap", 0, 0))  # frame 0 is the still
        ws = [dict(id="demo-a", project="demo", mood="busy", bubble="", sub="", age="1m", hunger=5, hn="fed", acc="cap"),
              dict(id="demo-b", project="demo", mood="asleep", bubble="", sub="", age="1m", hunger=5, hn="fed", acc="scarf")]
        c = lambda t: [pet.cell(i, w, t)[:6] for i, w in enumerate(ws, 1)]
        self.assertNotEqual(c(0)[0], c(1)[0])  # busy moves every tick
        self.assertEqual(c(0)[1], c(1)[1])  # asleep breathes at half speed
        self.assertNotEqual(c(1)[1], c(2)[1])
        self.assertEqual(pet.cell(1, ws[0])[:6], [pet.center(x, pet.CW) for x in pet.creature("busy", "cap", pet.colour_of("demo"))])  # still: frame 0 for all

    def test_label_two_lines(self):
        w = dict(id="kara-web-unhide", project="kara-website", mood="busy", bubble="", sub="", age="1m", hunger=5, hn="fed", acc="cap")
        cell = [pet.TAG.sub("", l) for l in pet.cell(2, w)]
        self.assertEqual((cell[6].strip(), cell[7].strip()), ("2 kara-website", "unhide"))
        long = dict(w, id="x-" + "y" * 40, project="p" * 40)
        cell = [pet.TAG.sub("", l) for l in pet.cell(12, long)]
        self.assertEqual((len(cell[6]), len(cell[7])), (pet.CW, pet.CW))
        self.assertEqual(cell[6].strip(), "12 " + "p" * 14 + "…")  # each line is cut to the column on its own, one column free
        self.assertTrue(cell[7].strip().endswith("…") and len(cell[7].strip()) == pet.CW - 1)

    THREE = json.dumps(dict(v=1, ts=NOW - 5, event="task.merged", task="a-three", via="pr")) + "\n"

    def ledger(self, *recs, raw=""):
        with open(os.path.join(self.h.state, "fleet-ledger.jsonl"), "a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in recs) + raw)

    def test_ledger_merges_pr_and_local_and_junk(self):
        pet_ = pet.Pet(self.h.root)
        self.assertEqual(pet_.poll(NOW), [])  # no ledger file yet
        self.assertEqual(pet_.trophies, [])
        self.ledger(dict(v=1, ts=NOW - 50, event="task.dispatched", task="a-one", project="/x/projects/alpha"),
                    dict(v=1, ts=NOW - 40, event="task.merged", task="a-one", via="pr", pr="https://x/pull/1"),
                    dict(v=1, ts=NOW - 30, event="task.merged", task="a-two", via="local", extra=[1]),
                    dict(v=1, ts=NOW - 20, event="task.future", task="a-one"), dict(ts="x", event="task.merged", task="bad"),
                    dict(v=1, ts=NOW - 40, event="task.merged", task="a-one", via="pr"),  # a repeated record is one trophy
                    raw="\nnot json\n[1]\n" + self.THREE[:20])  # blank, malformed, non-object, then a half-written last line
        pet_.poll(NOW)
        self.assertEqual([t[:2] for t in pet_.trophies], [("alpha", "one"), (None, "a two")])
        self.ledger(raw=self.THREE[20:])  # the line is completed later: now it counts
        pet_.poll(NOW + 3)
        self.assertEqual(len(pet_.trophies), 3)
        off = pet_.ledger.off
        pet_.poll(NOW + 6)
        self.assertEqual(pet_.ledger.off, off)  # only new bytes are read
        fresh = pet.Pet(self.h.root)
        fresh.poll(NOW)
        self.assertEqual(len(fresh.trophies), 3)  # persists across restarts
        open(os.path.join(self.h.state, "fleet-ledger.jsonl"), "w").close()  # truncated: start over
        pet_.poll(NOW + 9)
        self.assertEqual(pet_.trophies, [])

    def test_project_lookup_order(self):
        self.h.worker("m-meta", project="frommeta")
        self.h.worker("m-both", project="frommeta")
        self.ledger(dict(v=1, ts=NOW, event="task.dispatched", task="m-both", project="/p/fromledger"),
                    dict(v=1, ts=NOW, event="task.dispatched", task="m-null", project=None),
                    *[dict(v=1, ts=NOW, event="task.merged", task=t, via="local") for t in ("m-meta", "m-both", "m-null")])
        p = pet.Pet(self.h.root)
        p.poll(NOW)
        self.assertEqual(sorted(t[:2] for t in p.trophies if t[0]), [("fromledger", "both"), ("frommeta", "meta")])
        self.assertEqual([t[:2] for t in p.trophies if not t[0]], [(None, "m null")])  # neither: project omitted

    def test_project_falls_back_to_projects_md(self):
        os.makedirs(os.path.join(self.h.root, "data"))
        with open(os.path.join(self.h.root, "data", "projects.md"), "w") as f:
            f.write("# Projects\n\n- sb [x] - short\n- sbmail [no-mistakes] - Purchase orders\n")
        self.ledger(*[dict(v=1, ts=NOW, event="task.merged", task=t, via="local") for t in ("sbmail-inbound-line-search", "sbmailer-x", "sb-y")])
        p = pet.Pet(self.h.root)
        p.poll(NOW)
        self.assertEqual(sorted((t[0], t[3]) for t in p.trophies if t[0]), [("sb", "y"), ("sbmail", "inbound-line-search")])  # longest match wins; sbmailer-x has none

    def test_only_todays_merges(self):
        day = 86400
        self.ledger(*[dict(v=1, ts=NOW + k * day, event="task.merged", task=n, via="local") for n, k in (("old", -2), ("yest", -1), ("now", 0), ("later", 1))])
        p = pet.Pet(self.h.root)
        p.poll(NOW)
        self.assertEqual([t[1] for t in p.trophies], ["now"])
        p.poll(NOW + day)
        self.assertEqual([t[1] for t in p.trophies], ["later"])

    def test_party_on_new_merge_for_a_shown_worker(self):
        wid = self.h.worker("demo-merge", lines=[f"done [at={NOW}]: PR https://x/pull/1"])
        self.ledger(dict(v=1, ts=NOW - 900, event="task.merged", task=wid, via="pr"))  # backlog at startup: no party
        p = pet.Pet(self.h.root)
        self.assertEqual(p.poll(NOW)[0]["mood"], "calling")
        self.ledger(dict(v=1, ts=NOW, event="task.merged", task=wid, via="pr"), dict(v=1, ts=NOW, event="task.merged", task="gone-one", via="local"))
        w = p.poll(NOW + 3)[0]
        self.assertEqual((w["mood"], w["sub"], w["bubble"]), ("party", "merged!", ""))
        self.assertEqual(p.poll(NOW + 3 + pet.PARTY_SECS - 1)[0]["mood"], "party")
        self.assertEqual(p.poll(NOW + 3 + pet.PARTY_SECS)[0]["mood"], "calling")  # the party ends; the cup is already in the column
        self.assertEqual(len(p.trophies), 3)

    def test_trophy_column(self):
        items = [(f"p{i}", "t", "12:0" + str(i % 10), "t", "local") for i in range(30)]
        col = [pet.TAG.sub("", l) for l in pet.trophy_col(items, 8)]
        self.assertEqual(len(col), 8)
        self.assertTrue(all(len(l) == pet.TW for l in col))
        self.assertIn("today: 30", col[1])
        self.assertIn("p29 ×1", col[2])  # newest project on top
        self.assertIn("last 12:09", col[3])
        self.assertIn("p28 ×1", col[4])
        self.assertIn("+28 more", col[6])  # overflow counts projects: 30 total, 2 shown
        self.assertIn("none yet today", pet.TAG.sub("", "".join(pet.trophy_col([], 4))))
        self.assertNotIn("more", "".join(pet.TAG.sub("", l) for l in pet.trophy_col(items[:2], 8)))

    def test_trophies_group_by_project_newest_first(self):
        items = [("a", "x", "09:00", "x", ""), ("b", "y", "10:00", "y", ""), ("a", "z", "11:00", "z", ""), (None, "q", "12:00", "q", "")]
        self.assertEqual([(p, len(ts)) for p, ts in pet.by_project(items)], [(None, 1), ("a", 2), ("b", 1)])
        col = [pet.TAG.sub("", l) for l in pet.trophy_col(items, 12)]
        self.assertIn("today: 4", col[1])
        self.assertIn("no project ×1", col[2])
        self.assertIn("a ×2", col[4])
        self.assertIn("last 11:00", col[5])  # the newest merge of the project

    def test_room_name_and_ref(self):
        self.assertEqual(pet.room_name("alpha-fix-it", "alpha"), "fix-it")
        self.assertEqual(pet.room_name("alpha", "alpha"), "alpha")
        self.assertEqual(pet.room_name("beta-x", "alpha"), "beta-x")
        self.assertEqual(pet.room_name("beta-x", None), "beta-x")
        self.ledger(dict(v=1, ts=NOW - 3, event="task.dispatched", task="a-one", project="/x/a"),
                    dict(v=1, ts=NOW - 2, event="task.merged", task="a-one", via="pr", pr="https://github.com/o/r/pull/42"),
                    dict(v=1, ts=NOW - 1, event="task.merged", task="a-two", via="local"))
        p = pet.Pet(self.h.root)
        p.poll(NOW)
        self.assertEqual([t[3:] for t in p.trophies], [("one", "PR #42"), ("a-two", "local")])

    def test_trophy_room(self):
        items = [("a", "x", "09:00", "fix-x", "PR #7"), ("b", "y", "10:00", "y", "local"), ("a", "z", "11:00", "z", "PR #9")]
        out = [pet.TAG.sub("", l) for l in pet.trophy_room(items, 9, 70)]
        self.assertEqual((len(out), {len(l) for l in out}), (9, {70}))
        self.assertIn("trophy room", out[0])
        self.assertIn("a ×2", out[1])  # newest project first (a's 11:00 beats b's 10:00)
        self.assertIn("11:00 z PR #9", out[2])
        self.assertIn("09:00 fix-x PR #7", out[3])
        self.assertIn("b ×1", out[4])
        self.assertIn("10:00 y local", out[5])
        out = [pet.TAG.sub("", l) for l in pet.trophy_room(items, 5, 70)]  # b's header would be last: cut it, count its merge
        self.assertIn("09:00 fix-x", out[3])
        self.assertIn("+1 more", out[4])
        out = [pet.TAG.sub("", l) for l in pet.trophy_room(items, 3, 70)]  # a's header without any merge is dropped too
        self.assertIn("+3 more", out[1])
        self.assertIn("none yet today", pet.TAG.sub("", pet.trophy_room([], 3, 70)[0]))

    def test_room_toggle_keeps_the_height(self):
        ws = [pet.main_worker(dict(agent_status="working"))]
        items = [("demo", "t", "12:00", "t", "local")] * 5
        for rows in (pet.STRIP_ROWS, 40):
            a, b = pet.draw(ws, items, rows), pet.draw(ws, items, rows, room=True)
            self.assertEqual(len(a), len(b))
            self.assertNotIn("main", "".join(pet.TAG.sub("", l) for l in b[3:-3]))
        self.assertIn("t trophies", "".join(pet.TAG.sub("", l) for l in pet.draw(ws, items, 40)))
        self.assertIn("t back", "".join(pet.TAG.sub("", l) for l in pet.draw(ws, items, 40, room=True)))
        self.assertIn("t back", pet.TAG.sub("", pet.draw(ws, items, pet.STRIP_ROWS, room=True)[0]))
        self.assertIn("t trophies", pet.TAG.sub("", pet.draw(ws, items, pet.STRIP_ROWS)[0]))

    def test_sprites_match_the_agreed_mochi(self):
        # crc32 of every mood x colour x accessory (frame 0) as drawn by the approved design (herdr-pet-tamagotchi-alts/build.py),
        # except the teal collar, red instead of cyan so it shows. A change here means the pet no longer looks like the Mochi the captain picked.
        s = "\n".join("\n".join(pet.creature(m, a, i)) for m in pet.MC for i in range(8) for a in [None] + pet.ACCS)
        self.assertEqual(zlib.crc32(s.encode()), 2099815327)
        self.assertTrue(all(len(pet.creature(m)) == 6 for m in pet.MC))

    def test_focus_cmds(self):
        self.assertEqual(pet.focus_cmds(dict(ws="w1", tab="w1:t2"), "h"), [["h", "workspace", "focus", "w1"], ["h", "tab", "focus", "w1:t2"]])

    def test_short_task(self):
        self.assertEqual(pet.short_task("kara-web-unhide", "kara-website"), "unhide")
        self.assertEqual(pet.short_task("aml-universal-features", "research"), "aml universal features")

    def test_once_cli(self):
        self.h.worker("demo-cli", lines=[f"working [at={int(time.time())}]: go"], active=time.time())
        out = subprocess.run([sys.executable, pet.__file__, "--once"], env={**os.environ, "FM_HOME": self.h.root},
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("demo", out)
        self.assertIn("busy", out)

    def test_hearts_solid_and_hollow(self):
        h = self.plain([pet.hearts(3)])[0]
        self.assertEqual((h, pet.vis(pet.hearts(3))), ("●●●○○", 5))
        self.assertNotIn("♥", pet.hearts(5))

class MainMochi(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def pet(self, status="working", cwd=None, n=0):
        for i in range(n): self.h.worker(f"demo-t{i}", lines=[f"working [at={NOW}]: go"], born=NOW - 600 + i)
        panes = [dict(pane_id="w1:p9", cwd="/elsewhere", agent_status="working"),
                 dict(pane_id="w1:p1", cwd=cwd or self.h.root, agent_status=status, workspace_id="w1", tab_id="w1:t1")]
        return pet.Pet(self.h.root, lambda: panes)

    def test_first_and_own_colour(self):
        ws = self.pet(n=2).poll(NOW)
        self.assertEqual([w["id"] for w in ws], ["firstmate", "demo-t0", "demo-t1"])
        m = ws[0]
        self.assertEqual((m["colour"], m["acc"], m["hunger"]), (pet.MAIN, "collar", None))
        self.assertNotIn(pet.MAIN, {pet.colour_of(p) for p in ("demo", "kara-website", "x", "y")})  # never a project colour
        self.assertEqual(pet.colour_of("anything") < len(pet.PROJECT_PALS), True)
        self.assertNotIn(pet.PALS[pet.MAIN]["B"], [p["B"] for p in pet.PROJECT_PALS])
        self.assertNotEqual(pet.PALS[pet.MAIN]["L"], pet.PALS[pet.MAIN]["B"])  # collar shows on the body
        self.assertEqual(pet.focus_cmds(m), [["herdr", "workspace", "focus", "w1"], ["herdr", "tab", "focus", "w1:t1"]])
        lines = pet.render(ws, [])
        self.assertIn(pet.center(pet.creature("busy", "collar", pet.MAIN)[2], pet.CW), "\n".join(lines))
        out = "\n".join(pet.TAG.sub("", l) for l in lines)
        self.assertIn("1 main", out)
        self.assertIn("firstmate", out)
        self.assertIn("main session", out)
        self.assertTrue(all(pet.vis(l) == pet.W for l in lines))

    def test_absent_without_home_pane_or_herdr(self):
        self.assertEqual(self.pet(cwd="/elsewhere").poll(NOW), [])
        self.assertEqual(pet.Pet(self.h.root).poll(NOW), [])  # no Herdr
        def boom(): raise FileNotFoundError("herdr")
        self.assertEqual(pet.Pet(self.h.root, boom).poll(NOW), [])  # Herdr gone: never an error

    def test_mood_from_agent_status(self):
        got = {s: self.pet(s).poll(NOW)[0] for s in ("working", "idle", "blocked", "done", "unknown")}
        self.assertEqual({s: (w["mood"], w["bubble"]) for s, w in got.items()},
                         dict(working=("busy", ""), idle=("asleep", ""), blocked=("calling", "needs you!"), done=("asleep", ""), unknown=("asleep", "")))

    def test_counts_toward_eight(self):
        ws = self.pet(n=8).poll(NOW)
        self.assertEqual(len(ws), 9)
        out = [pet.TAG.sub("", l) for l in pet.render_strip(ws, [])]
        self.assertIn("+1 more", out[0])
        self.assertIn("8 demo", "\n".join(out))
        self.assertIn("t6", "\n".join(out))
        self.assertNotIn("t7", "\n".join(out))
        self.assertEqual(len(out), pet.strip_rows(9))

class Strip(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def plain(self, lines): return [pet.TAG.sub("", l) for l in lines]

    def test_layout_follows_height(self):
        self.assertEqual(pet.layout_for(pet.FULL_ROWS), "full")
        self.assertEqual(pet.layout_for(pet.FULL_ROWS - 1), "strip")
        self.assertEqual(len(pet.draw([], [], 40)), pet.FULL_ROWS)  # the full panel is exactly FULL_ROWS tall
        self.assertEqual(len(pet.draw([], [], pet.STRIP_ROWS)), pet.STRIP_ROWS)  # and the strip STRIP_ROWS
        self.assertEqual(len(pet.draw([], [], 3)), 3)  # a tiny pane is clipped, never scrolled

    def test_strip_draws_mochi(self):
        for i in range(10): self.h.worker(f"demo-t{i}", lines=[f"needs-decision [at={NOW}]: A or B"], born=NOW - 600 + i)
        p = pet.Pet(self.h.root)
        p.trophies = [("demo", f"cup{i}", "12:0" + str(i), f"cup{i}", "") for i in range(60)]
        ws = p.poll(NOW)
        p.trophies = [("demo", f"cup{i}", "12:0" + str(i), f"cup{i}", "") for i in range(60)]
        self.assertEqual(len(pet.draw(ws, p.trophies, pet.STRIP_ROWS)), pet.STRIP_ROWS)  # a short pane clips, never scrolls
        rows = pet.strip_rows(len(ws))  # eight Mochis, two across: four rows
        lines = pet.draw(ws, p.trophies, rows)
        out = self.plain(lines)
        self.assertEqual((len(out), rows), (2 + 4 * pet.CH, pet.STRIP_ROWS + 3 * pet.CH))
        self.assertTrue(all(len(l) == pet.W for l in out), [len(l) for l in out])
        self.assertIn("+2 more", out[0])
        self.assertIn("q close", out[0])
        sprite = pet.creature("calling", ws[1]["acc"], pet.colour_of("demo"))
        self.assertIn(pet.center(sprite[2], pet.CW), lines[3])  # the real sprite, not a face
        self.assertIn("2 demo", out[7])  # project on its own line, the task under it
        self.assertIn("t1", out[8])
        self.assertIn("calling", out[9])
        self.assertIn("●●●●●", out[10])
        self.assertIn('"your call!"', out[11])
        self.assertIn("7 demo", out[1 + 3 * pet.CH + 6])
        self.assertIn("trophies · today", out[1])
        self.assertIn("today: 60", out[2])
        self.assertIn("demo ×60", out[3])  # one cup for the whole project
        self.assertIn("last 12:059", out[4])
        self.assertNotIn("more", out[5][-pet.TW:])  # a single project never overflows
        self.assertTrue(all(o[-pet.TW - 1] == "│" for o in out[1:-1]))  # the column sits at the right edge

    def test_strip_empty(self):
        out = self.plain(pet.render_strip([], []))
        self.assertEqual(len(out), pet.STRIP_ROWS)
        self.assertIn("no workers aboard", "\n".join(out))
        self.assertIn("none yet today", out[2])
        self.assertTrue(all(len(l) == pet.W for l in out))

class Pin(unittest.TestCase):
    HOME, ROOT = "/fm", "/plugins/firstmate.pet"
    WS = [dict(workspace_id="w1", active_tab_id="w1:t1", focused=False), dict(workspace_id="w2", active_tab_id="w2:t3", focused=True)]
    def pane(self, pid, cwd, **kw): return dict(pane_id=pid, cwd=cwd, tab_id=pid.replace(":p", ":t"), **kw)

    def test_opens_under_the_firstmate_pane(self):
        panes = [self.pane("w2:p3", "/x", focused=True), self.pane("w1:p1", self.HOME)]
        self.assertEqual(pet.pin_target(panes, self.WS, self.HOME), "w1:p1")

    def test_falls_back_to_the_active_tab(self):
        panes = [self.pane("w1:p1", "/a"), self.pane("w2:p3", "/b"), self.pane("w2:p4", "/c", focused=True)]
        panes[2]["tab_id"] = "w2:t3"
        self.assertEqual(pet.pin_target(panes, self.WS, self.HOME), "w2:p4")
        self.assertEqual(pet.pin_target(panes[:2], self.WS, self.HOME), "w2:p3")
        self.assertFalse(pet.pin_target([], self.WS, self.HOME))

    def test_realpath_match(self):
        with tempfile.TemporaryDirectory() as d:
            link = d + "-link"
            os.symlink(d, link)
            try: self.assertEqual(pet.pin_target([self.pane("w1:p1", os.path.realpath(d))], self.WS, link), "w1:p1")
            finally: os.remove(link)

    def test_pet_pane_found_by_label_only(self):
        self.assertTrue(pet.is_pet(self.pane("w1:p2", self.ROOT, label=pet.TITLE)))
        self.assertFalse(pet.is_pet(self.pane("w1:p3", self.ROOT)))  # a shell in the plugin dir is not the pet

    def test_restored_shell_is_not_a_running_pet(self):  # shapes from `herdr pane process-info`
        live = dict(foreground_processes=[dict(cmdline="python3 /plugins/firstmate.pet/pet.py")])
        husk = dict(foreground_processes=[dict(cmdline="-zsh")])
        self.assertTrue(pet.running_pet(live))
        self.assertFalse(pet.running_pet(husk))
        self.assertFalse(pet.running_pet({}))

    def test_strip_amount(self):
        self.assertEqual(pet.strip_amount(20, 20, 8), 0.3)  # 40-row tab: 20 -> 8 rows
        self.assertEqual(pet.strip_amount(8, 32, 18), -0.25)  # a second row: 8 -> 18 rows
        self.assertEqual(pet.strip_amount(8, 32, 8), 0)  # already right: leave it

    def test_animate_setting(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "config"), "w") as f: f.write("PET_ANIMATE=off\n")
            env = {k: v for k, v in os.environ.items() if k != "PET_ANIMATE"}
            code = "import pet; print(pet.animate())"
            run = lambda e: subprocess.run([sys.executable, "-c", code], env=e, cwd=os.path.dirname(pet.__file__), capture_output=True, text=True).stdout.strip()
            self.assertEqual(run(env), "True")
            self.assertEqual(run({**env, "HERDR_PLUGIN_CONFIG_DIR": d}), "False")
            self.assertEqual(run({**env, "PET_ANIMATE": "0"}), "False")

    def test_refocus_after_swap(self):
        fm = self.pane("w1:p1", self.HOME)
        nb = lambda d: {"right": "w1:p2"}.get(d)
        self.assertEqual(pet.refocus_cmds(None, fm, nb), [])
        self.assertEqual(pet.refocus_cmds(fm, fm, nb), [])  # focus was on the Firstmate pane: swap keeps it there
        other_tab = dict(pane_id="w2:p5", tab_id="w2:t3", workspace_id="w2")
        self.assertEqual(pet.refocus_cmds(other_tab, fm, nb), [["workspace", "focus", "w2"], ["tab", "focus", "w2:t3"]])
        beside = dict(pane_id="w1:p2", tab_id="w1:t1", workspace_id="w1")
        self.assertEqual(pet.refocus_cmds(beside, fm, nb), [["pane", "focus", "--pane", "w1:p1", "--direction", "right"]])

if __name__ == "__main__":
    unittest.main()
