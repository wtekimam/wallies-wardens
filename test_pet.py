"""python3 -m unittest test_pet  -- fixture Firstmate-style state dirs, no live home touched."""
import os, subprocess, sys, tempfile, time, unittest
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

    def check(self, lines, mood, stage=None, bubble="", **kw):
        w = self.h.read(self.h.worker("demo-task", lines=lines, **kw))
        self.assertEqual(w["mood"], mood)
        self.assertEqual(w["bubble"], bubble)
        if stage: self.assertEqual(w["stage"], stage)
        return w

    def test_egg_before_first_status(self): self.check([], "busy", "egg")
    def test_busy_baby(self): self.check([f"working [at={NOW}]: building the thing"], "busy", "baby")
    def test_training_grown(self): self.check([f"working [at={NOW}]: running no-mistakes validation"], "training", "grown")
    def test_paused_on_validation(self): self.check([f"paused [at={NOW}]: no-mistakes run in progress"], "training", "grown")
    def test_grown_stays_after_validation(self):
        self.check([f"working [at={NOW}]: no-mistakes validation", f"working [at={NOW}]: fixing review"], "busy", "grown")
    def test_decision_calls(self): self.check([f"needs-decision [at={NOW}]: A or B"], "calling", "grown", "your call!")
    def test_resolved_decision_back_to_busy(self):
        self.check([f"needs-decision [key=k] [at={NOW}]: A or B", f"resolved [key=k] [at={NOW}]: A"], "busy")
    def test_pr_ready(self): self.check([f"done [at={NOW}]: PR https://x/pull/1"], "calling", "grown", "PR ready!")
    def test_report_ready(self): self.check([f"done [at={NOW}]: report written"], "calling", "grown", "report ready!", kind="scout")
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

    def test_every_sprite_renders(self):
        for stage in ("egg", "baby", "grown"):
            for mood in pet.MC:
                for acc in pet.ACCS:
                    self.assertEqual(len(pet.creature(mood, stage, acc, 2)), 6)

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

if __name__ == "__main__":
    unittest.main()
