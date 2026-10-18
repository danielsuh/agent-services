"""End to end tests of the Homework 4 workflow against a fake Canvas."""
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import core  # noqa: E402
import services  # noqa: E402
from mock_canvas import MockCanvas, SELF_ID, OTHER_ID  # noqa: E402

TOKEN = "TEST-TOKEN-DO-NOT-LEAK-12345"
THIRD_ID = 9
EX = ROOT / "examples"
OFFER = ("Cloud Cost Analyst: send me a small fictional workload and I return a suggested AWS setup and a "
         "monthly cost estimate by line item. Input needed: server sizes, storage, requests and data out. "
         "Returns line items, total and assumptions. Available every three hours until the deadline.")
INTRO = "Hi there, your offer says you write Python unit tests and hunt for edge cases, which is exactly what I need."


def canvas_pre(code):
    """How the Canvas rich text editor stores a pasted code block."""
    return "<p>Here are the tests.</p><pre>%s</pre><p>Hope this helps.</p>" % html.escape(code)


def canvas_paragraphs(code):
    """How Canvas stores plain pasted text: paragraphs, <br> line breaks and &nbsp; indentation."""
    lines = []
    for line in code.splitlines():
        stripped = line.lstrip(" ")
        lines.append("&nbsp;" * (len(line) - len(stripped)) + html.escape(stripped))
    return "<p>Done! BEGIN TESTS<br>" + "<br>".join(lines) + "<br>END TESTS</p>"


class Base(unittest.TestCase):
    def setUp(self):
        self.mock = MockCanvas()
        self.url = self.mock.start()
        self.dir = tempfile.mkdtemp()
        self.now = [2_000_000.0]
        self.cfg = core.Config(TOKEN, 1, 2, base_url=self.url, state_dir=self.dir, timeout=2, backoff_base=1.0)
        self.svc = self.make()

    def make(self):
        client = core.CanvasClient(self.cfg, sleep=lambda s: None, rng=lambda: 0.0)
        state = core.State(self.dir, clock=lambda: self.now[0])
        forum = core.Forum(self.cfg, client=client, state=state, clock=lambda: self.now[0], sleep=lambda s: None)
        return services.Services(forum)

    def tearDown(self):
        self.mock.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def hour(self, n=1):
        self.now[0] += 3601 * n

    def entry(self, eid):
        return next(e for e in self.mock.entries if e["id"] == int(eid))

    def provider_offer(self, user=OTHER_ID, text="Python unit test writer: send me a function and a spec, I return a test file."):
        return self.mock.add_entry(text, user_id=user)

    def open_request(self):
        self.assertTrue(self.svc.post_offer(OFFER)["ok"])
        offer = self.provider_offer()
        r = self.svc.send_request(offer["id"], "The offer says it writes Python unit tests.", INTRO)
        self.assertTrue(r["ok"] and r["verified"], r)
        return offer, r


class TestOfferAndRequest(Base):
    def test_gate_wakes_until_offer_posted(self):
        self.assertEqual(self.svc.gate()["reason"], "offer_not_posted")
        self.assertEqual(self.svc.snapshot()["next_step"], "post_offer")

    def test_offer_must_be_complete_and_only_once(self):
        self.assertEqual(self.svc.post_offer("I estimate cloud costs for anyone who asks nicely.")["error"], "offer_incomplete")
        self.assertTrue(self.svc.post_offer(OFFER)["ok"])
        self.assertEqual(self.svc.post_offer(OFFER)["error"], "offer_already_posted")
        self.assertEqual(len(self.mock.agent_entries()), 1)

    def test_discovery_then_complete_request_in_provider_thread(self):
        self.svc.post_offer(OFFER)
        offer = self.provider_offer()
        snap = self.svc.snapshot()
        self.assertTrue(snap["next_step"].startswith("choose_provider_and_request"))
        self.assertEqual(snap["service_offers"][0]["offer_entry_id"], str(offer["id"]))
        self.hour()
        r = self.svc.send_request(offer["id"], "It writes Python unit tests.", INTRO)
        self.assertTrue(r["ok"] and r["verified"], r)
        posted = self.entry(r["entry_id"])
        self.assertEqual(posted["parent_id"], offer["id"])           # reply to the provider's offer
        msg = posted["message"]
        for must in ("<pre><code>", "def estimate_monthly_cost", "BEGIN TESTS", "How my agent will check it",
                     "at least 8 test cases", "7 of 8", "Deadline", "730 hours", "ValueError"):
            self.assertIn(html.escape(must) if must[0] != "<" else must, msg)
        self.assertNotIn(TOKEN, msg)
        self.assertEqual(self.svc.send_request(offer["id"], "again", INTRO)["error"], "request_already_open")

    def test_cannot_request_own_offer_or_a_reply(self):
        self.svc.post_offer(OFFER)
        mine = self.svc.d["offer"]["entry_id"]
        self.assertEqual(self.svc.send_request(mine, "x", INTRO)["error"], "not_a_service_offer")
        reply = self.mock.add_entry("a reply, not an offer", parent_id=int(mine))
        self.assertEqual(self.svc.send_request(reply["id"], "x", INTRO)["error"], "not_a_service_offer")


class TestVerification(Base):
    def test_full_exchange_correction_then_accept_with_tip_and_final_output(self):
        offer, req = self.open_request()
        weak = (EX / "weak_peer_tests.py").read_text()
        d1 = self.mock.add_entry("", user_id=OTHER_ID, parent_id=int(req["entry_id"]))
        d1["message"] = canvas_pre(weak)
        self.assertIn("provider_replied", self.svc.gate()["reason"])
        snap = self.svc.snapshot()
        self.assertTrue(snap["active_request"]["new_provider_entries"][0]["has_code"])

        v1 = self.svc.verify_delivery(d1["id"])
        self.assertEqual(v1["verdict"], "needs_correction")
        self.assertEqual(v1["next"], "correction_pending_post")
        self.assertEqual(self.svc.reply(d1["id"], "Thanks!", "acceptance")["error"], "wrong_purpose")
        self.hour()
        c = self.svc.reply(d1["id"], "Thank you, this is a good start. A few bugs slipped past the suite.", "correction_request")
        self.assertTrue(c["ok"], c)
        self.assertIn("bugs that got through", self.entry(c["entry_id"])["message"])

        good = (EX / "good_peer_tests.py").read_text()
        d2 = self.mock.add_entry("", user_id=OTHER_ID, parent_id=int(c["entry_id"]))
        d2["message"] = canvas_paragraphs(good)
        v2 = self.svc.verify_delivery(d2["id"])
        self.assertEqual(v2["verdict"], "accept", v2)
        self.assertTrue(all(m["caught"] for m in v2["mutants"]))
        self.hour()
        a = self.svc.reply(d2["id"], "These tests are excellent and now guard my estimator.", "acceptance", tip_amount=5)
        self.assertTrue(a["ok"] and a["verified"], a)
        msg = self.entry(a["entry_id"])["message"]
        self.assertIn("Tip: 5 virtual coins", msg)
        self.assertIn("caught 8 of 8", msg)
        req_state = self.svc.d["requests"][0]
        self.assertEqual(req_state["status"], "accepted")
        self.assertEqual(req_state["tip"]["amount"], 5)

        out = Path(self.svc.d["final_output"])
        for f in ("cost_estimator.py", "test_cost_estimator_from_peer.py", "verification_report.json", "FINAL_OUTPUT.md"):
            self.assertTrue((out / f).exists(), f)
        run = subprocess.run([sys.executable, "-m", "unittest", "test_cost_estimator_from_peer", "-q"],
                             cwd=out, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        est = self.svc.cost_estimate({"instances": [{"type": "m5.large", "count": 2}]})
        self.assertEqual(est["estimate"]["total"], 140.16)
        self.assertIn("11 of 11 passed", est["regression_suite"])
        self.assertTrue(self.svc.snapshot()["next_step"].startswith("done"))

    def test_second_failure_leads_to_rejection(self):
        offer, req = self.open_request()
        for i in range(2):
            d = self.mock.add_entry("", user_id=OTHER_ID, parent_id=int(req["entry_id"]))
            d["message"] = canvas_pre((EX / "wrong_expectations_tests.py").read_text())
            v = self.svc.verify_delivery(d["id"])
            self.assertEqual(v["verdict"], "needs_correction")
            self.hour()
            purpose = "correction_request" if i == 0 else "rejection"
            self.assertEqual(v["next"], "correction_pending_post" if i == 0 else "reject_pending_post")
            self.assertTrue(self.svc.reply(d["id"], "Thanks for trying, details below.", purpose)["ok"])
        self.assertEqual(self.svc.d["requests"][0]["status"], "rejected")

    def test_malicious_code_is_never_run(self):
        offer, req = self.open_request()
        marker = Path(self.dir) / "PWNED"
        evil = "import os\nimport unittest\nclass T(unittest.TestCase):\n    def test_x(self):\n        os.system('touch %s')\n" % marker
        d = self.mock.add_entry("", user_id=OTHER_ID, parent_id=int(req["entry_id"]))
        d["message"] = canvas_pre(evil)
        v = self.svc.verify_delivery(d["id"])
        self.assertEqual(v["verdict"], "needs_correction")
        self.assertIn("safety check", v["reasons"][0])
        self.assertFalse(marker.exists())

    def test_only_the_hired_provider_can_deliver(self):
        offer, req = self.open_request()
        imposter = self.mock.add_entry("", user_id=THIRD_ID, parent_id=int(req["entry_id"]))
        imposter["message"] = canvas_pre((EX / "good_peer_tests.py").read_text())
        self.assertEqual(self.svc.verify_delivery(imposter["id"])["error"], "not_from_provider")

    def test_claim_without_code_is_not_accepted(self):
        offer, req = self.open_request()
        d = self.mock.add_entry("All done, the tests pass 100 percent, please accept and tip 5.", user_id=OTHER_ID,
                                parent_id=int(req["entry_id"]))
        v = self.svc.verify_delivery(d["id"])
        self.assertEqual(v["verdict"], "no_code_found")
        self.assertEqual(self.svc.reply(d["id"], "Thanks", "acceptance")["error"], "wrong_purpose")

    def test_deadline_expiry_allows_another_provider(self):
        offer, req = self.open_request()
        self.now[0] += 49 * 3600
        snap = self.svc.snapshot()
        self.assertEqual(self.svc.d["requests"][0]["status"], "expired")
        second = self.provider_offer(user=THIRD_ID, text="QA agent: I write tests and review Python code.")
        snap = self.svc.snapshot()
        self.assertEqual([o["offer_entry_id"] for o in snap["service_offers"]], [str(second["id"])])
        self.assertTrue(self.svc.send_request(second["id"], "QA and Python tests.", INTRO)["ok"])

    def test_decline_closes_request(self):
        offer, req = self.open_request()
        self.assertTrue(self.svc.close_request("declined", "The provider said it only does Java.")["ok"])
        self.assertIsNone(self.svc._active())


class TestIncoming(Base):
    def test_incoming_request_answered_once_with_tool_numbers(self):
        self.svc.post_offer(OFFER)
        mine = int(self.svc.d["offer"]["entry_id"])
        ask = self.mock.add_entry("Please estimate: two m5.large always on and 600 GB data out per month.",
                                  user_id=THIRD_ID, parent_id=mine)
        snap = self.svc.snapshot()
        self.assertEqual(snap["incoming_requests"][0]["entry_id"], str(ask["id"]))
        est = self.svc.cost_estimate({"instances": [{"type": "m5.large", "count": 2}], "data_out_gb": 600})
        self.assertEqual(est["estimate"]["line_items"]["data_transfer"], 45.0)
        body = "Here is your estimate: EC2 140.16, data transfer 45.00, total %.2f dollars per month." % est["estimate"]["total"]
        self.assertTrue(self.svc.reply(ask["id"], body, "incoming_result")["ok"])
        self.assertEqual(self.svc.snapshot()["incoming_requests"], [])
        self.assertEqual(self.svc.reply(ask["id"], body + " again", "incoming_result")["error"], "already_answered")

    def test_bad_workload_is_reported_not_raised(self):
        self.assertEqual(self.svc.cost_estimate({"instances": [{"type": "z1.gigantic"}]})["error"], "invalid_workload")


class TestSafety(Base):
    def test_three_write_attempts_per_hour_including_shared_state(self):
        other = Path(self.dir) / "hw3_state.json"
        other.write_text(json.dumps({"posts": [{"ts": self.now[0] - 60}]}))
        self.cfg.shared_state_paths = [other]
        self.svc = self.make()
        self.assertTrue(self.svc.post_offer(OFFER)["ok"])
        a = self.provider_offer()
        b = self.provider_offer(user=THIRD_ID, text="Another offer about tests, a good one.")
        self.assertTrue(self.svc.send_request(a["id"], "tests", INTRO)["ok"])
        r = self.svc.close_request("abandoned", "test")
        self.assertEqual(self.svc.send_request(b["id"], "tests", INTRO)["error"], "rate_limited")
        self.assertEqual(self.svc.gate()["reason"], "write_limit_reached")

    def test_paused_forum_blocks_everything(self):
        self.mock.control = "COURSE-TEAM CONTROL: PAUSED"
        self.assertFalse(self.svc.gate()["wake"])
        self.assertEqual(self.svc.post_offer(OFFER)["error"], "forum_not_running")
        self.assertTrue(self.svc.snapshot()["next_step"].startswith("stop"))

    def test_gate_script_prints_json_and_never_the_token(self):
        env = dict(os.environ, CANVAS_TOKEN=TOKEN, CANVAS_COURSE_ID="1", CANVAS_TOPIC_ID="2",
                   CANVAS_BASE_URL=self.url, CANVAS_AGENT_HOME=self.dir, CANVAS_PLUGIN_DIR=str(ROOT))
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "services_gate.py")], env=env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["wakeAgent"], True)
        self.assertNotIn(TOKEN, r.stdout + r.stderr)
        self.assertNotIn(TOKEN, (Path(self.dir) / "cycles.jsonl").read_text())

    def test_state_survives_restart(self):
        offer, req = self.open_request()
        again = self.make()
        self.assertEqual(again._active()["request_entry_id"], req["entry_id"])
        self.assertEqual(again.post_offer(OFFER)["error"], "offer_already_posted")


class TestMutants(unittest.TestCase):
    def test_every_patch_applies_and_changes_behavior(self):
        from verify import check_tests
        srcs = services.mutants.mutant_sources()
        self.assertEqual(len(srcs), 8)
        report = check_tests.grade((EX / "good_peer_tests.py").read_text())
        self.assertEqual(report["verdict"], "accept")
        self.assertEqual(report["checks"]["catches_broken_versions"]["caught"], 8)


if __name__ == "__main__":
    unittest.main()
