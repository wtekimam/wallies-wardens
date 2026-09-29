"""python3 -m unittest test_pet  -- fixture Firstmate-style state dirs, no live home touched."""
import os, subprocess, sys, tempfile, time, unittest, zlib
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

    def test_four_shown_then_more(self):
        for i in range(6): self.h.worker(f"demo-t{i}", lines=[f"working [at={NOW}]: go"], born=NOW - 600 + i)
        p = pet.Pet(self.h.root)
        out = self.plain(pet.render(p.poll(NOW), p.trophies))
        self.assertIn("+2 more", out[0])
        self.assertIn("4 demo · t3", "\n".join(out))
        self.assertNotIn("demo · t4", "\n".join(out))
        self.assertTrue(all(len(l) == pet.W for l in out), [len(l) for l in out])

    def test_accessories_per_project_colour_shared(self):
        a = self.h.worker("demo-one", lines=[f"working [at={NOW}]: go"], born=NOW - 900)
        b = self.h.worker("demo-two", lines=[f"working [at={NOW}]: go"], born=NOW - 800)
        c = self.h.worker("other-one", project="other", lines=[f"working [at={NOW}]: go"])
        ws = {w["id"]: w for w in pet.Pet(self.h.root).poll(NOW)}
        self.assertEqual((ws[a]["acc"], ws[b]["acc"], ws[c]["acc"]), (None, "collar", None))
        self.assertEqual(pet.colour_of("demo"), pet.colour_of("demo"))

    def test_trophy_after_merge_only(self):
        merged = self.h.worker("demo-merge", lines=[f"done [at={NOW}]: PR https://x/pull/1"])
        dropped = self.h.worker("demo-drop", lines=[f"working [at={NOW}]: go"])
        p = pet.Pet(self.h.root)
        p.poll(NOW)
        for wid in (merged, dropped): os.remove(os.path.join(self.h.state, wid + ".meta"))
        ws = p.poll(NOW + 3)
        self.assertEqual([(w["id"], w["mood"]) for w in ws], [(merged, "party")])
        self.assertEqual(p.trophies, [])
        ws = p.poll(NOW + 3 + pet.PARTY_SECS)
        self.assertEqual(ws, [])
        self.assertEqual([t[:2] for t in p.trophies], [("demo", "merge")])
        self.assertIn("demo · merge", "\n".join(self.plain(pet.render(ws, p.trophies))))
        self.assertEqual(pet.Pet(self.h.root).trophies, [])  # a fresh process starts with no cups

    def test_sprites_match_the_agreed_mochi(self):
        # crc32 of every mood x colour x accessory as drawn by the approved design (herdr-pet-tamagotchi-alts/build.py).
        # A change here means the pet no longer looks like the Mochi the captain picked.
        s = "\n".join("\n".join(pet.creature(m, a, i)) for m in pet.MC for i in range(8) for a in pet.ACCS)
        self.assertEqual(zlib.crc32(s.encode()), 406192193)
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
        for i in range(6): self.h.worker(f"demo-t{i}", lines=[f"needs-decision [at={NOW}]: A or B"], born=NOW - 600 + i)
        p = pet.Pet(self.h.root)
        p.trophies = [("demo", f"cup{i}", "12:0" + str(i)) for i in range(9)]
        ws = p.poll(NOW)
        lines = pet.draw(ws, p.trophies, pet.STRIP_ROWS)
        out = self.plain(lines)
        self.assertEqual(len(out), pet.STRIP_ROWS)
        self.assertTrue(all(len(l) == pet.W for l in out), [len(l) for l in out])
        self.assertIn("+2 more", out[0])
        sprite = pet.creature("calling", ws[0]["acc"], pet.colour_of("demo"))
        self.assertIn(pet.center(sprite[2], pet.CW), lines[3])  # the real sprite, not a face
        self.assertIn("4 demo · t3", out[7])
        self.assertIn("calling", out[8])
        self.assertIn("♥", out[9])
        self.assertIn('"your call!"', out[10])
        self.assertIn("demo · cup8 12:08", out[11])  # newest cup first
        self.assertIn("earlier", out[11])
        self.assertIn("q close", out[11])

    def test_strip_empty(self):
        out = self.plain(pet.render_strip([], []))
        self.assertEqual(len(out), pet.STRIP_ROWS)
        self.assertIn("no workers aboard", "\n".join(out))
        self.assertIn("none yet", out[-2])
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
        self.assertEqual(pet.strip_amount(6, 30, 8), 0)  # already short: leave it

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
