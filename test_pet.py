"""python3 -m unittest test_pet  -- fixture Firstmate-style state dirs, no live home touched."""
import datetime, json, os, re, subprocess, sys, tempfile, time, unittest, zlib
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

class Decisions(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def plain(self, lines): return [pet.TAG.sub("", l) for l in lines]

    def test_fold_open_resolved_and_blocked(self):
        k = lambda wid, *lines, **kw: self.h.read(self.h.worker(wid, lines=list(lines), **kw))["decision"]
        d = k("demo-a", f"needs-decision [key=k] [at={NOW - 120}]: A or B", f"working [at={NOW}]: x")  # status_state's rule: an unresolved ask stays the newest state only until a later line
        self.assertIsNone(d)
        d = k("demo-b", f"working [at={NOW - 600}]: go", f"needs-decision [key=k] [at={NOW - 120}]: ship A or B?")
        self.assertEqual((d["kind"], d["text"], d["waiting"], d["report"], d["pr"]), ("needs-decision", "ship A or B?", "2m", "", ""))
        self.assertIsNone(k("demo-c", f"needs-decision [key=k] [at={NOW - 9}]: A?", f"resolved [key=k] [at={NOW}]: A"))
        self.assertIsNone(k("demo-d", f"blocked [key=k] [at={NOW - 9}]: CI", f"captain-held [key=k] [at={NOW}]: wait"))
        self.assertEqual(k("demo-e", f"blocked [at={NOW - 3600}]: CI red")["kind"], "blocked")
        self.assertIsNone(k("demo-f", f"done [at={NOW}]: PR https://x/pull/1"))

    def test_links(self):
        wid = self.h.worker("demo-l", lines=[f"needs-decision [at={NOW}]: A or B"], pr="https://x/pull/7")
        os.makedirs(os.path.join(self.h.root, "data", wid)); open(os.path.join(self.h.root, "data", wid, "report.md"), "w").close()
        d = self.h.read(wid)["decision"]
        self.assertEqual((d["report"], d["pr"]), (os.path.join(self.h.root, "data", wid, "report.md"), "https://x/pull/7"))

    def test_backlog_title_and_hold(self):
        os.makedirs(os.path.join(self.h.root, "data"))
        with open(os.path.join(self.h.root, "data", "backlog.md"), "w") as f:
            f.write("# Backlog\n## In flight\n- [ ] demo-r - garmin: post-race rehaul (incl. load) (repo: g) (kind: task) (since 2026-10-01) (hold: x) (hold-kind: captain) (hold-until: 2026-10-25)\n"
                    "- [ ] demo-s - why the chart is empty (repo: m) (kind: scout) (since 2026-10-09)\n  - [ ] not-a-task - indented\n")
        r = self.h.read(self.h.worker("demo-r", lines=[f"done [at={NOW}]: PR https://x/pull/9 checks green"], pr="https://x/pull/9"))["decision"]
        s = self.h.read(self.h.worker("demo-s", kind="scout", lines=[f"done [at={NOW}]: report"]))["decision"]
        n = self.h.read(self.h.worker("demo-n", lines=[f"needs-decision [at={NOW}]: q"]))["decision"]
        self.assertEqual([(x["title"], x["hold"]) for x in (r, s, n)], [("post-race rehaul (incl. load)", "2026-10-25"), ("why the chart is empty", ""), ("", "")])

    def test_view(self):
        wid = self.h.worker("demo-l", lines=[f"needs-decision [at={NOW - 300}]: found X; blocked on Y; need a choice"], pr="https://x/pull/7")
        ws = [self.h.read(wid), self.h.read(self.h.worker("demo-q", lines=[f"working [at={NOW}]: go"]))]
        out = self.plain(pet.draw(ws, [], 40, view="d"))
        self.assertEqual(len(out), pet.FULL_ROWS)
        body = "\n".join(out)
        for s in ("needs you · 1", "demo", "decide", "waiting 5m", "found X; blocked on Y; need a choice", "waiting 5m · PR #7", "d back", "t trophies"):
            self.assertIn(s, body)
        self.assertNotIn("demo-q", body)
        self.assertNotIn("building", body)  # the Mochis are replaced
        self.assertIn("d needs you (1)", "\n".join(self.plain(pet.draw(ws, [], 40))))
        strip = self.plain(pet.draw(ws, [], pet.STRIP_ROWS, view="d"))
        self.assertIn("d back", strip[0])
        self.assertEqual(len(strip), pet.STRIP_ROWS)
        self.assertIn("d needs you (1)", self.plain(pet.draw(ws, [], pet.STRIP_ROWS))[0])
        self.assertTrue(all(pet.vis(l) == pet.W for l in strip))

    def test_count_in_hint(self):
        mk = lambda n: [self.h.read(self.h.worker(f"demo-n{i}", lines=[f"needs-decision [at={NOW - i}]: q"])) for i in range(n)]
        for n in (0, 1, 3):
            ws = mk(n)
            for out in (pet.draw(ws, [], 40, 156), pet.draw(ws, [], pet.STRIP_ROWS, 156)):
                body = "\n".join(self.plain(out))
                self.assertIn(f"d needs you ({n})" if n else "d needs you", body)
                self.assertEqual("(" in body.split("d needs you")[1][:2], n > 0)
        raw = "\n".join(pet.draw(mk(1), [], 40, 156))
        self.assertIn(pet.c(pet.HEAD, " needs you (1)", True), raw)  # the accent, not dim
        self.assertNotIn(pet.c(pet.DIM, " needs you"), "\n".join(pet.draw(mk(1), [], 40, 156)))
        self.assertIn(pet.c(pet.DIM, " needs you"), "\n".join(pet.draw(mk(0), [], 40, 156)))
        self.assertIn("d needs you (3)", self.plain(pet.draw(mk(3), [], pet.STRIP_ROWS, 60))[0])  # tight: the count still shows, later hints drop first

    def test_review_card(self):
        a = self.h.read(self.h.worker("demo-r", lines=[f"done [at={NOW - 300}]: ready"], pr="https://x/pull/9"))
        s = self.h.read(self.h.worker("demo-s", kind="scout", lines=[f"done [at={NOW - 900}]: report ready"]))
        m = self.h.read(self.h.worker("demo-m", lines=[f"done [at={NOW}]: merged https://x/pull/8"], pr="https://x/pull/8"))
        n = self.h.read(self.h.worker("demo-n", lines=[f"done [at={NOW}]: local"]))
        self.assertEqual((a["decision"]["kind"], a["decision"]["pr"]), ("review", "https://x/pull/9"))
        self.assertEqual(s["decision"]["kind"], "review")
        self.assertIsNone(m["decision"]); self.assertIsNone(n["decision"])
        self.assertEqual([x["id"] for x in pet.decisions_of([a, s, m, n])], ["demo-s", "demo-r"])  # oldest wait first
        body = "\n".join(self.plain(pet.draw([a, s], [], 40, view="d")))
        for t in ("needs you · 2", "review & merge PR #9 · ready", "read the report · report ready", "waiting 15m"): self.assertIn(t, body)

    def test_cards_lead_with_the_action(self):
        ws = [self.h.read(self.h.worker(f"demo-{k}", lines=[f"{st} [at={NOW - i}]: x"], pr="https://x/pull/1" if st == "done" else ""))
              for i, (k, st) in enumerate((("a", "needs-decision"), ("b", "blocked"), ("c", "done")))]
        heads = [self.plain(pet.decision_card(x, 78))[0] for x in ws]
        self.assertEqual([h.split()[1] for h in heads], ["decide", "unblock", "review"])
        self.assertEqual({h.index("demo") for h in heads}, {11})  # the project lines up under any action

    def test_empty_and_overflow(self):
        self.assertIn("needs you · none", self.plain(pet.draw([], [], 40, view="d"))[2])
        ws = [self.h.read(self.h.worker(f"demo-t{i}", lines=[f"needs-decision [at={NOW - i}]: q{i}"])) for i in range(6)]
        out = self.plain(pet.draw(ws, [], 40, 156, view="d"))  # six Mochis fit one row at 156 columns: 11 lines
        self.assertEqual(len(out), pet.FULL_ROWS)
        self.assertIn("+3 more", "\n".join(out))  # heading + 3 cards of 3 lines would not leave a line for it: 2 cards fit
        self.assertIn("t5", "\n".join(out))  # oldest wait (at=NOW-5) first
        self.assertNotIn("t0", "\n".join(out))

    def test_calling_label_tag(self):
        w = self.h.read(self.h.worker("demo-tagged", lines=[f"needs-decision [at={NOW}]: which colour for the bikeshed"]))
        label = self.plain(pet.cell(1, w))[7]
        self.assertIn("tagged · which", label)
        self.assertLessEqual(len(label), pet.CW)
        self.assertEqual(len(pet.cell(1, w)), pet.CH)
        busy = self.h.read(self.h.worker("demo-plain", lines=[f"working [at={NOW}]: go"]))
        self.assertNotIn("·", self.plain(pet.cell(1, busy))[7])

    def test_once_cli_shows_tag(self):
        self.h.worker("demo-cli", lines=[f"needs-decision [at={int(time.time())}]: pick one"], active=time.time())
        out = subprocess.run([sys.executable, pet.__file__, "--once"], env={**os.environ, "FM_HOME": self.h.root}, capture_output=True, text=True, check=True).stdout
        self.assertIn("pick one", re.sub(r"\x1b\[[0-9;]*m", "", out))

class Title(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def plain(self, lines): return [pet.TAG.sub("", l) for l in lines]
    def crew(self, calls=1, busy=3):
        return ([pet.main_worker(dict(agent_status="working"))] +
                [self.h.read(self.h.worker(f"demo-c{i}", lines=[f"needs-decision [at={NOW - i}]: q"])) for i in range(calls)] +
                [self.h.read(self.h.worker(f"demo-b{i}", lines=[f"working [at={NOW}]: go"])) for i in range(busy)])

    def test_crew_summary_not_the_name(self):
        out = self.plain(pet.render(self.crew(), [], landed=2))
        self.assertTrue(out[0].startswith("╭─ ⚓ 4 aboard · 1 needs you · 2 landed today ─"), out[0])  # the main session is not a worker
        self.assertNotIn("Wallie", "\n".join(out))  # Herdr's pane label already names it
        self.assertIn("2 need you", self.plain(pet.render(self.crew(2), []))[0])
        self.assertTrue(self.plain(pet.render(self.crew(0, 1), []))[0].startswith("╭─ ⚓ 1 aboard ─"))  # nothing waiting, nothing landed: just who is aboard
        self.assertTrue(self.plain(pet.render([], []))[0].startswith("╭─ ⚓ 0 aboard ─"))
        self.assertTrue(self.plain(pet.render_strip(self.crew(), [], 240, landed=2))[0].startswith("╭─ ⚓ 4 aboard · 2 landed today ─"))  # the strip's "d needs you (1)" says it once

    def test_anchor_is_two_columns(self):
        self.assertEqual((pet.vis("⚓ 4"), pet.vis(pet.c(pet.FG, "⚓"))), (4, 2))
        for out in (pet.render(self.crew(), [], landed=2), pet.render_strip(self.crew(), [], landed=2)):
            self.assertEqual({pet.vis(l) for l in out}, {pet.W})

    def test_tight_bar_drops_least_important_first(self):
        crew = self.crew(1, 8)
        bar = lambda width, **kw: self.plain(pet.render_strip(crew, [], width, landed=12, **kw))[0]
        wide = bar(240)
        for t in ("⚓ 9 aboard · 12 landed today", "+2 more", "q close", "d needs you (1)", "t trophies", "c log", "w week"): self.assertIn(t, wide)
        tight = bar(80)  # 80 columns: the last hints go, then "landed today"; "t trophies" would go next
        for t in ("⚓ 9 aboard", "+2 more", "q close", "d needs you (1)", "t trophies"): self.assertIn(t, tight)
        for t in ("landed", "c log", "w week"): self.assertNotIn(t, tight)
        self.assertIn("⚓ 9 aboard · 12 landed today", bar(100))  # "landed today" outlives "c log"
        self.assertNotIn("c log", bar(100))
        quiet = self.plain(pet.render_strip(self.crew(0, 9), [], 80, landed=12))[0]  # nothing waits: "t trophies" outlives "landed today"
        self.assertIn("t trophies", quiet)
        full = self.plain(pet.render(crew, [], 80, landed=12))[0]  # the full panel's hints live in the footer, so its title keeps every part
        self.assertIn("⚓ 9 aboard · 1 needs you · 12 landed today", full)

    def test_landed_counts_today_in_either_span(self):
        with open(os.path.join(self.h.state, "fleet-ledger.jsonl"), "w") as f:
            for task, ts in (("a-old", NOW - 3 * 86400), ("a-one", NOW - 60), ("a-two", NOW - 30)): f.write(json.dumps(dict(v=1, ts=ts, event="task.merged", task=task, via="local")) + "\n")
        p = pet.Pet(self.h.root)
        p.poll(NOW)
        today = sum(datetime.date.fromtimestamp(ts) == datetime.date.fromtimestamp(NOW) for ts in (NOW - 60, NOW - 30))
        self.assertEqual(p.landed, today)
        p.week = False
        p.poll(NOW)
        self.assertEqual(p.landed, today)

    def test_dividers_join_the_frame(self):
        out = [l.replace("⚓", "⚓ ") for l in self.plain(pet.render(self.crew(), []))]  # one character a column
        j = 1 + pet.W - 2 - pet.TW
        self.assertEqual((out[0][j], out[-3][j], out[-3][0], out[-3][-1]), ("┬", "┴", "├", "┤"))  # the trophy column joins the top and the footer rule
        self.assertTrue(all(l[j] == "│" for l in out[1:-3]))
        strip = self.plain(pet.render_strip(self.crew(), []))
        self.assertEqual(strip[-1][j], "┴")
        for view in "tdl": self.assertNotIn("┴", "".join(self.plain(pet.render(self.crew(), [], view=view))))  # full-width views have no column

    def test_long_wait_stays_in_its_cell(self):
        for waited in (5 * 60, 2 * 3600, 4 * 86400 + 13 * 3600):
            x = self.h.read(self.h.worker(f"demo-w{waited}", lines=[f"needs-decision [at={NOW - waited}]: q"], active=NOW - waited))
            self.assertEqual({pet.vis(l) for l in pet.cell(1, x)}, {pet.CW})
        self.assertIn("●●●●● 4d 13h", pet.TAG.sub("", pet.cell(1, dict(x, hunger=5))[9]))

    def test_mochi_grid_centred_and_frame_fills_the_pane(self):
        out = self.plain(pet.render_strip(self.crew(0, 1), [], 80))
        row = out[1][1:1 + pet.W - 2 - pet.TW]
        left, right = len(row) - len(row.lstrip()), len(row) - len(row.rstrip())
        self.assertLessEqual(abs(left - right), 3)  # the slack beside the trophy column is shared, not all on the right
        self.assertEqual({pet.vis(l) for l in pet.render_strip(self.crew(), [], 150)}, {150})

class Keys(unittest.TestCase):
    LEFT = set("qwertasdfgzxcvb")

    def test_every_hint_is_a_left_hand_key(self):
        ws = [pet.main_worker(dict(agent_status="blocked"))]
        bars = [pet.TAG.sub("", l) for view in (None, "t", "d", "c") for l in (pet.render(ws, [], 240, view=view)[-2], pet.render_strip(ws, [], 240, view=view)[0])]
        keys = {k for b in bars for k in re.findall(r"(?:^|  |· )([a-z]) (?:trophies|needs you|log|week|today|redraw|close|back|prev|next)", b)}
        self.assertEqual(keys, set("qtdcwr"))
        self.assertTrue(keys <= self.LEFT)
        self.assertIn("c log", bars[0])
        pages = pet.TAG.sub("", pet.page_keys(0, 2))
        self.assertIn("a prev s next", pages)
        self.assertTrue(set(re.findall(r"\b([a-z]) (?:prev|next)", pages)) <= self.LEFT)

    def test_old_right_hand_keys_still_work(self):
        self.assertEqual(pet.ALIASES, dict(l="c", n="s", p="a"))

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
        self.assertTrue(all(pet.vis(l) == pet.W for l in out), [pet.vis(l) for l in out])

    def test_layout_one_to_nine(self):
        for n in range(1, 10):  # 80 columns: the trophy column leaves two Mochis across, so up to four rows
            rows = -(-min(n, 8) // 2)
            self.assertEqual(pet.grid(n), (2, rows, pet.W))
            self.assertEqual(pet.strip_rows(n), pet.STRIP_ROWS + pet.CH * (rows - 1))
            ws = [dict(id=f"demo-t{i}", project="demo", mood="busy", bubble="", sub="", age="1m", hunger=5, hn="fed", acc="cap") for i in range(n)]
            out = self.plain(pet.render_strip(ws, []))
            self.assertEqual(len(out), pet.strip_rows(n))
            self.assertTrue(all(pet.vis(l) == pet.W for l in out), (n, [pet.vis(l) for l in out]))
            self.assertEqual(("+1 more" in out[0]), n == 9)
        self.assertEqual(pet.grid(8, 240), (8, 1, 240))  # a wide pane fits all eight in one row; the frame fills the pane
        self.assertEqual(pet.grid(8, 160), (6, 2, 160))
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
        p.week = False
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
        self.assertRegex(col[2], r"p29 +×1 $")  # newest project on top
        self.assertIn("last 12:09", col[3])
        self.assertRegex(col[4], r"p28 +×1 $")
        self.assertIn("+28 more", col[6])  # overflow counts projects: 30 total, 2 shown
        self.assertIn("none yet today", pet.TAG.sub("", "".join(pet.trophy_col([], 4))))
        self.assertNotIn("more", "".join(pet.TAG.sub("", l) for l in pet.trophy_col(items[:2], 8)))

    def test_trophy_week_window(self):
        at = lambda d, h=12, m=0: time.mktime((2026, 9, d, h, m, 0, 0, 0, -1))  # Sep 21 2026 is a Monday
        merged = [dict(task=f"a-{n}", ts=ts, project="a", ref="") for n, ts in
                  (("sun", at(20, 23, 59)), ("mon", at(21, 0, 0)), ("wed", at(23, 14, 5)), ("sun2", at(27, 23, 59)), ("next", at(28, 0, 0)))]
        names = lambda now, week: [t[1] for t in pet.trophies_today(merged, now, week)]
        self.assertEqual(names(at(23, 15), True), ["mon", "wed", "sun2"])  # Monday 00:00 through Sunday; the Sunday before and Monday after are out
        self.assertEqual(names(at(27, 23, 59), True), ["mon", "wed", "sun2"])
        self.assertEqual(names(at(28, 1), True), ["next"])
        self.assertEqual(names(at(23, 15), False), ["wed"])  # today alone is unchanged
        self.assertEqual([t[2] for t in pet.trophies_today(merged, at(23, 15), True)][1], "Wed 14:05")
        self.assertEqual(pet.trophies_today(merged, at(23, 15))[0][2], "14:05")

    def test_trophy_week_toggle(self):
        self.ledger(dict(v=1, ts=NOW - 3 * 86400, event="task.merged", task="a-old", via="local"),
                    dict(v=1, ts=NOW, event="task.merged", task="a-new", via="local"))
        p = pet.Pet(self.h.root)
        self.assertTrue(p.week)  # opens on this week
        p.poll(NOW)
        self.assertEqual(len(p.trophies), 2 if time.localtime(NOW).tm_wday >= 3 else 1)  # three days back is this week only from Thursday on
        p.week = False
        p.poll(NOW)
        self.assertEqual([t[1] for t in p.trophies], ["a new"])
        items = [("a", "x", "Mon 09:00", "fix-x", "PR #7")]
        col = [pet.TAG.sub("", l) for l in pet.trophy_col(items, 8, True)]
        self.assertIn("trophies · this week", col[0])
        self.assertIn("this week: 1", col[1])
        self.assertIn("last Mon 09:00", col[3])
        self.assertIn("none yet this week", "".join(pet.TAG.sub("", l) for l in pet.trophy_col([], 4, True)))
        out = [pet.TAG.sub("", l) for l in pet.trophy_room(items, 4, 70, True)]
        self.assertIn("trophy room · this week", out[0])
        self.assertIn("Mon 09:00 fix-x PR #7", out[2])
        ws = [pet.main_worker(dict(agent_status="working"))]
        self.assertIn("w week", "".join(pet.TAG.sub("", l) for l in pet.render(ws, items)))
        self.assertIn("w today", "".join(pet.TAG.sub("", l) for l in pet.render(ws, items, week=True)))
        self.assertIn("w today", pet.TAG.sub("", pet.draw(ws, items, pet.STRIP_ROWS, 120, week=True)[0]))

    def test_trophies_group_by_project_newest_first(self):
        items = [("a", "x", "09:00", "x", ""), ("b", "y", "10:00", "y", ""), ("a", "z", "11:00", "z", ""), (None, "q", "12:00", "q", "")]
        self.assertEqual([(p, len(ts)) for p, ts in pet.by_project(items)], [(None, 1), ("a", 2), ("b", 1)])
        col = [pet.TAG.sub("", l) for l in pet.trophy_col(items, 12)]
        self.assertIn("today: 4", col[1])
        self.assertRegex(col[2], r"no project +×1 $")
        self.assertRegex(col[4], r" a +×2 $")  # counts flush right, so they line up
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
        self.assertEqual([t[3:] for t in p.trophies], [("one", "PR #42", "https://github.com/o/r/pull/42"), ("a-two", "local", "")])

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
        self.assertIn("none yet today", pet.TAG.sub("", pet.trophy_room([], 3, 70)[0]))

    def test_trophy_room_flows_across_the_width(self):
        txt = lambda ls: [pet.TAG.sub("", l) for l in ls]
        items = [(f"p{i % 3}", "t", f"{i:02d}:00", f"task{i}", "local") for i in range(12)]  # 3 projects x 4 merges = 15 lines
        for w, _ in ((70, 1), (78, 2), (108, 3), (180, 5)):
            out = txt(pet.trophy_room(items, 11, w))
            self.assertEqual((len(out), {len(l) for l in out}), (11, {w}))
            shown = " ".join(out)
            if w >= 108: self.assertTrue(all(f"task{i}" in shown for i in range(12)), w)  # all of it at once
        self.assertEqual(len(pet.trophy_pages(items, 11, 108)), 1)
        self.assertEqual(len(pet.trophy_pages(items, 11, 108)[0]), 2)  # 15 lines, 10 a column: side by side, not paged
        self.assertEqual(txt(pet.trophy_room(items, 11, 108))[2].count("task"), 2)
        # more than fits in one column (10 lines) at 70 wide: paged, every merge on exactly one page, header says so
        pages = pet.trophy_pages(items, 11, 70)
        self.assertGreater(len(pages), 1)
        seen = [i for pg in range(len(pages)) for i in range(12) if f"task{i} " in " ".join(txt(pet.trophy_room(items, 11, 70, page=pg))) + " "]
        self.assertEqual(sorted(seen), list(range(12)))
        self.assertIn(f"page 2/{len(pages)}", txt(pet.trophy_room(items, 11, 70, page=1))[0])
        self.assertIn("page 1/", txt(pet.trophy_room(items, 11, 70, page=-5))[0])  # out of range clamps
        self.assertIn(f"page {len(pages)}/", txt(pet.trophy_room(items, 11, 70, page=99))[0])
        self.assertNotIn("page", txt(pet.trophy_room(items[:2], 11, 70))[0])
        self.assertIn("a prev s next", txt(pet.trophy_room(items, 11, 70))[0])
        # a project longer than a column carries on in the next one under a "↳" line; no header ends a column alone
        many = [("big", "t", "09:00", f"m{i}", "") for i in range(14)]
        cols = pet.trophy_pages(many, 11, 78)[0]
        self.assertTrue(pet.TAG.sub("", cols[1][0]).strip().startswith("↳ big"))
        self.assertEqual(len(cols[0]), 10)

    def test_trophy_room_paging_in_the_frame(self):
        ws = [pet.main_worker(dict(agent_status="working"))]
        items = [("demo", "t", "12:00", f"t{i}", "local") for i in range(30)]
        for width in (80, 120, 200):
            a, b = pet.draw(ws, items, 40, width, view="t"), pet.draw(ws, items, 40, width, view="t", page=1)
            self.assertEqual({len(pet.TAG.sub("", l)) for l in a}, {len(pet.TAG.sub("", l)) for l in b})
            self.assertEqual(len(a), len(pet.draw(ws, items, 40, width)))

    def test_room_toggle_keeps_the_height(self):
        ws = [pet.main_worker(dict(agent_status="working"))]
        items = [("demo", "t", "12:00", "t", "local")] * 5
        for rows in (pet.STRIP_ROWS, 40):
            a, b = pet.draw(ws, items, rows), pet.draw(ws, items, rows, view="t")
            self.assertEqual(len(a), len(b))
            self.assertNotIn("main", "".join(pet.TAG.sub("", l) for l in b[3:-3]))
        self.assertIn("t trophies", "".join(pet.TAG.sub("", l) for l in pet.draw(ws, items, 40)))
        self.assertIn("t back", "".join(pet.TAG.sub("", l) for l in pet.draw(ws, items, 40, view="t")))
        self.assertIn("t back", pet.TAG.sub("", pet.draw(ws, items, pet.STRIP_ROWS, view="t")[0]))
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

class Links(unittest.TestCase):
    URL = "https://github.com/o/r/pull/42"
    OPEN, CLOSE = f"\x1b]8;;{URL}\x1b\\", "\x1b]8;;\x1b\\"

    def test_link_takes_no_columns(self):
        s = "a " + pet.link(self.URL, pet.c(pet.DIM, "PR #42")) + " b"
        self.assertEqual(pet.vis(s), len("a PR #42 b"))
        self.assertEqual(pet.TAG.sub("", s), "a PR #42 b")
        self.assertEqual(pet.vis(pet.padr(s, 20)), 20)
        self.assertEqual(pet.vis(pet.center(s, 20)), 20)
        out = pet.to_ansi(s)
        self.assertEqual(out.count(self.OPEN), 1)
        self.assertEqual(re.sub(r"\x1b\]8;;[^\x1b]*\x1b\\|\x1b\[[0-9;]*m", "", out), "a PR #42 b")  # OSC 8 wraps only the PR text
        self.assertEqual(sorted([out.index(self.OPEN), out.index("PR #42"), out.index(self.CLOSE), out.index(" b")]),
                         [out.index(self.OPEN), out.index("PR #42"), out.index(self.CLOSE), out.index(" b")])
        self.assertTrue(pet.to_ansi("{>" + self.URL + "}open").endswith(self.CLOSE + "\x1b[0m"))  # a link never runs past its line

    def test_only_plain_urls_link(self):
        for bad in ("", None, "javascript:alert(1)", "https://x/pull/1\x1b]8;;evil", "https://x/{b}", "https://x /pull/1"):
            self.assertEqual(pet.link(bad, "PR"), "PR", bad)

    def test_review_card_says_what_and_links_the_pr_once(self):
        d = dict(kind="review", text=f"PR {self.URL} checks green", waiting="4d 13h", at=0, report="/fm/data/x/report.md", pr=self.URL,
                 title="post-race training-engine rehaul", hold="2026-10-25")
        x = dict(id="demo-x", project="demo", decision=d)
        lines = pet.decision_card(x, 120)
        self.assertEqual([pet.TAG.sub("", l) for l in lines], [" ● review  demo · post-race training-engine rehaul", "   review & merge PR #42 · checks green",
                                                               "   waiting 4d 13h · report data/x/report.md · on hold to 2026-10-25"])
        out = "".join(pet.to_ansi(l) for l in lines)
        self.assertEqual(out.count(self.OPEN), 1)  # the PR once, as a short link to the full URL
        self.assertIn(self.OPEN + "PR #42" + self.CLOSE, out)
        self.assertNotIn(self.URL, pet.TAG.sub("", "".join(lines)))
        for w in (60, 40, 24):  # narrow: every line is cut to the width, never past it
            for l in pet.decision_card(x, w): self.assertLessEqual(pet.vis(l), w)
        bare = pet.TAG.sub("", "\n".join(pet.decision_card(dict(x, decision=dict(d, report="", pr="", title="", hold="", text="report ready")), 80)))
        self.assertEqual(bare, " ● review  demo · x\n   read the report · report ready\n   waiting 4d 13h")  # a scout: no PR, the short task name

    def test_decide_card_keeps_its_question(self):
        d = dict(kind="needs-decision", text=f"ship A or B? see {self.URL}", waiting="5m", at=0, report="", pr=self.URL)
        lines = [pet.TAG.sub("", l) for l in pet.decision_card(dict(id="demo-x", project="demo", decision=d), 80)]
        self.assertEqual(lines[1:], ["   ship A or B? see PR #42", "   waiting 5m · PR #42"])

    def test_trophy_room_links_prs_with_a_url_only(self):
        items = [("a", "x", "09:00", "fix-x", "PR #42", self.URL), ("a", "y", "10:00", "y", "PR #7", ""), ("a", "z", "11:00", "z", "local", "")]
        lines = pet.trophy_room(items, 6, 70)
        self.assertEqual({pet.vis(l) for l in lines}, {70})
        out = "\n".join(pet.to_ansi(l) for l in lines)
        self.assertEqual(out.count("\x1b]8;;https"), 1)  # PR #7 has no URL in its record: plain text, never a guessed link
        self.assertIn(self.OPEN + "PR #42" + "\x1b[0m" + self.CLOSE, out)
        self.assertIn("09:00 fix-x PR #42", pet.TAG.sub("", "".join(lines)))

    def test_frames_stay_square_with_links(self):
        h = Home()
        try:
            ws = [h.read(h.worker("demo-l", lines=[f"done [at={NOW}]: ready"], pr=self.URL))]
            items = [("demo", "l", "12:00", "l", "PR #42", self.URL)] * 3
            for rows, width, view in ((40, 80, "d"), (40, 80, "t"), (pet.STRIP_ROWS, 80, "d"), (pet.STRIP_ROWS, 156, "t")):
                out = pet.draw(ws, items, rows, width, view=view)
                self.assertEqual(len({pet.vis(l) for l in out}), 1, (rows, width, view))
                self.assertIn("\x1b]8;;https", "".join(pet.to_ansi(l) for l in out))
        finally: h.tmp.cleanup()

class CaptainsLog(unittest.TestCase):
    def setUp(self): self.h = Home()
    def tearDown(self): self.h.tmp.cleanup()

    def at(self, d, hr=12, m=0): return int(time.mktime((2026, 10, d, hr, m, 0, 0, 0, -1)))
    def plain(self, lines): return [pet.TAG.sub("", l) for l in lines]

    def ledger(self, *recs):
        with open(os.path.join(self.h.state, "fleet-ledger.jsonl"), "a") as f: f.write("".join(json.dumps(dict(v=1, **r)) + "\n" for r in recs))

    def st(self, d, hr, task, state, text="x"): return dict(ts=self.at(d, hr), event="task.status", task=task, state=state, key=None, text=text)

    def fleet(self):
        a = self.at
        self.ledger(dict(ts=a(8, 9), event="task.dispatched", task="kara-x", project="/p/client-kara"),
                    dict(ts=a(8, 9), event="task.dispatched", task="portal-y", project="kara-portal"),
                    self.st(8, 10, "kara-x", "needs-decision"), self.st(8, 11, "kara-x", "needs-decision", "again"),  # asked twice: one decision
                    self.st(8, 12, "portal-y", "blocked"), self.st(8, 13, "portal-y", "failed"),
                    self.st(8, 14, "kara-x", "working"),  # a later line closes the ask without an answer
                    self.st(8, 15, "kara-x", "needs-decision", "token?"),
                    self.st(9, 9, "kara-x", "resolved"), self.st(9, 9, "kara-x", "resolved"),  # a repeated record counts once
                    self.st(9, 10, "kara-x", "done"), self.st(9, 10, "kara-x", "done", "again"),
                    dict(ts=a(9, 11), event="task.merged", task="kara-x", via="pr", pr="https://github.com/o/client-kara/pull/25"),
                    dict(ts=a(9, 12), event="task.merged", task="portal-y", via="pr", pr="https://github.com/o/kara-portal/pull/4"),
                    dict(ts=a(9, 13), event="task.merged", task="pet-z", via="local"), dict(ts=a(9, 14), event="task.merged", task="pet-w", via="local"),
                    dict(ts=a(9, 15), event="task.dispatched", task="kara-v", project="client-kara"),
                    self.st(9, 16, "kara-v", "needs-decision"), self.st(9, 17, "portal-q", "blocked"),
                    dict(ts=a(7, 10), event="task.dispatched", task="gone-u", project="garmin"), self.st(7, 11, "gone-u", "paused"),
                    dict(ts=a(1, 10), event="task.cleaned_up", task="gone-u"))
        p = pet.Pet(self.h.root)
        p.poll(a(9, 18))
        return p

    def test_one_entry_per_day_newest_first(self):
        p = self.fleet()
        text = [(d.isoformat(), pet.TAG.sub("", " ".join(ws))) for d, ws in p.log]
        self.assertEqual([d for d, _ in text], ["2026-10-09", "2026-10-08", "2026-10-07", "2026-10-01"])
        self.assertEqual(text[0][1], "Day 2026-10-09. One task set sail. Two PRs landed (client-kara #25, kara-portal #4). Two local branches landed (pet-z, pet-w). "
                                     "One task reported done. One decision raised, one answered. One blocker hit. client-kara waits on your call. portal-q is stuck on a blocker.")
        self.assertEqual(text[1][1], "Day 2026-10-08. Two tasks set sail. Two decisions raised. One blocker hit. One task ran aground (kara-portal). client-kara waited on your call.")
        self.assertEqual(text[2][1], "Day 2026-10-07. One task set sail.")
        self.assertEqual(text[3][1], "Day 2026-10-01. Quiet seas.")  # records, but nothing the log tells

    def test_prs_link_and_locals_count(self):
        p = self.fleet()
        words = p.log[0][1]
        self.assertIn("\x1b]8;;https://github.com/o/client-kara/pull/25\x1b\\", "".join(pet.to_ansi(w) for w in words))
        self.ledger(dict(ts=self.at(9, 17), event="task.merged", task="pet-z", via="local"))
        p.poll(self.at(9, 18))
        self.assertIn("Three local branches landed (pet-z ×2, pet-w).", pet.TAG.sub("", " ".join(p.log[0][1])))
        log = p.log
        p.poll(self.at(9, 19))
        self.assertIs(p.log, log)  # nothing new in the ledger: not rebuilt
        p.poll(self.at(10, 9))
        self.assertIn("client-kara waited on your call.", pet.TAG.sub("", " ".join(p.log[0][1])))  # a new day: yesterday's waits are past tense

    def test_view_fits_and_pages(self):
        p = self.fleet()
        for w in (60, 78, 154):  # the frame's room is never under 78; 60 still fits the heading
            pages = pet.log_pages(p.log, 11, w)
            for pg in range(len(pages)):
                out = pet.log_room(p.log, 11, w, pg)
                self.assertEqual((len(out), {pet.vis(l) for l in out}), (11, {w}))
            seen = " ".join(" ".join(self.plain(pet.log_room(p.log, 11, w, pg))) for pg in range(len(pages)))
            self.assertTrue(all(f"Day 2026-10-0{d}" in seen for d in (1, 7, 8, 9)), w)  # every day on some page
        self.assertEqual(len(pet.log_pages(p.log, 30, 154)), 1)
        self.assertGreater(len(pet.log_pages(p.log, 11, 60)), 1)
        self.assertIn("page 2/", self.plain(pet.log_room(p.log, 11, 60, 1))[0])
        self.assertIn("captain's log · four days", self.plain(pet.log_room(p.log, 11, 78))[0])
        self.assertIn("nothing logged yet", self.plain(pet.log_room([], 11, 78))[0])
        self.assertEqual(pet.wrap([pet.c(pet.FG, "x" * 50)], 10), [pet.c(pet.FG, "x" * 9 + "…")])  # too long for any line: cut, not overflowing

    def test_view_in_the_frame(self):
        p = self.fleet()
        ws = [pet.main_worker(dict(agent_status="working"))]
        for rows in (40, pet.STRIP_ROWS):
            a, b = pet.draw(ws, [], rows), pet.draw(ws, [], rows, view="c", log=p.log)
            self.assertEqual((len(a), {pet.vis(l) for l in b}), (len(b), {pet.W}))
            body = "\n".join(self.plain(b))
            self.assertIn("Day 2026-10-09.", body)
            self.assertIn("c back", body)
            self.assertNotIn("main session", body)  # the Mochis are replaced
        self.assertIn("c log", "\n".join(self.plain(pet.draw(ws, [], 40))))
        self.assertIn("c log", self.plain(pet.draw(ws, [], pet.STRIP_ROWS, 120))[0])
        self.assertIn("c back", self.plain(pet.draw(ws * 9, [], pet.STRIP_ROWS, 60, view="c"))[0])  # tight: the open log's way back stays

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
        self.assertTrue(all(pet.vis(l) == pet.W for l in out), [pet.vis(l) for l in out])
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
        self.assertRegex(out[3], r"demo +×60 │$")  # one cup for the whole project
        self.assertIn("last 12:059", out[4])
        self.assertNotIn("more", out[5][-pet.TW:])  # a single project never overflows
        self.assertTrue(all(o[-pet.TW - 1] == "│" for o in out[1:-1]))  # the column sits at the right edge

    def test_strip_empty(self):
        out = self.plain(pet.render_strip([], []))
        self.assertEqual(len(out), pet.STRIP_ROWS)
        self.assertIn("no workers aboard", "\n".join(out))
        self.assertIn("none yet today", out[2])
        self.assertTrue(all(pet.vis(l) == pet.W for l in out))

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
