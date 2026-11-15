"""Run on a laptop or the UNO Q:  python3 -m unittest test_yuseal -v   (from app/python)

Walks the whole YuSeal v3 (zero-input mouse) flow with software stand-ins for the YubiKey and
the STM32, then checks the real C++ microcontroller code (app/sketch/yuseal_mcu.h) gives the
same bytes as the Python model. The C++ check is skipped if g++ isn't installed.
"""
import copy
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import unittest

import approve as ap
import yuseal as ys

RP = "guardian.yuduino.local"
ALICE = "0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"
MALLORY = "0xDEADBEEF00000000000000000000000000A1F3"  # same last 4 characters as ALICE
BOOK = {ALICE: "ALICE"}
REQ = {"action": "transfer", "amount": "10", "asset": "GBP", "to": ALICE}

CALM = {"duress_score": 0.1, "signals": [], "reasoning": ""}
UNSURE = {"duress_score": 0.5, "signals": ["tremor"], "reasoning": ""}
SCARED = {"duress_score": 0.9, "signals": ["tremor", "second face"], "reasoning": ""}

# ys.FEATURE_NAMES order: grip, tremor, humidity, temp, moisture, click_hold, still, speed, impulse, n
OWNER = [720, 1200, 4500, 3050, 410, 85, 600, 3200, 900, 30]
STRANGER = [250, 6800, 7600, 2400, 1500, 190, 150, 9000, 2500, 30]


def owner_like(rng):
    """A feature vector near the owner's habits, with a little everyday noise."""
    return [int(v * (1 + rng.uniform(-0.05, 0.05))) for v in OWNER]


class Device:
    """One enrolled YuDuino in a mouse: STM32 (SoftMcu) + Linux side + YubiKey + a guardian that knows it."""

    def __init__(self, baseline=True, yk=None):
        self.rng = random.Random(1)
        self.yk = yk or ys.SoftYubiKey()
        k_mcu = os.urandom(32)
        self.mcu = ys.SoftMcu(k_mcu)
        self.t = 10_000  # STM32 clock, ms
        # Enrolment: one real click arms the STM32, which releases the salt; wrap the ML-DSA key under it.
        self.click()
        assert self.mcu.arm(bytes(32), self.t, OWNER)
        salt = self.mcu.unlock_salt()
        self.mcu.seal(0)
        self.store, pq = ys.create_keystore(self.yk.hmac_secret(salt))
        self.verifier = ys.Verifier(RP, address_book=dict(BOOK))
        m = ys.Member(self.yk.public_key, pq.public_key(), ys.mcu_keys(k_mcu)[1],
                      getattr(self.yk, "key", None))
        if baseline:
            hour = time.gmtime().tm_hour
            for _ in range(30):
                m.baseline.add(owner_like(self.rng), hour)
        self.verifier.members["jonah"] = m
        self.log = []
        self.linux_view = []  # everything the Linux side learns during approvals

    def click(self, grip=True, hold=70):
        self.t += 5000
        self.mcu.click_down(self.t, grip)
        self.t += hold
        self.mcu.click_up(self.t)
        self.t += 100

    def approve(self, gemini=CALM, request=REQ, veto=False, features=None, grip=True, click=True, wait_ms=100):
        """The Linux-side flow from docs/BUILD-FLOW.md. Returns the envelope, or None if the STM32 won't arm."""
        nonce = self.verifier.new_nonce()
        core, _ = ys.build_core(request, BOOK, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        if click:
            self.click(grip)                                    # 1. the person's ordinary click
        self.t += wait_ms
        f = owner_like(self.rng) if features is None else features
        if not self.mcu.arm(digest, self.t, f):                 # 2. Linux arms; refused without a fresh click
            return None
        salt = self.mcu.unlock_salt()                           # 3. salt only once armed
        attest = self.mcu.attest()
        self.linux_view.append(("salt", salt))
        assertion = self.yk.assert_(RP, digest)                 # 4. YubiKey, no touch
        key = ys.unlock(self.store, self.yk.hmac_secret(salt))
        tag = self.mcu.seal(ys.gemini_to_score(gemini), veto)   # 5. STM32 decides and tags
        self.linux_view.append(("tag_len", len(tag)))
        prev = self.log[-1]["hash"] if self.log else ys.GENESIS
        env = ys.make_envelope(core, assertion, tag, attest, prev, key)
        ys.log_append(self.log, env, key)
        return env


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def outcome(self, env, request=REQ, **kw):
        r = self.d.verifier.check(env, request, **kw)
        return r["public"], r["internal"]

    def test_calm_owner_approval_executes(self):
        self.assertEqual(self.outcome(self.d.approve()), ("accepted", "execute"))

    def test_no_touch_is_needed(self):
        env = self.d.approve()
        ad = ys.unb64(env["yk"]["authenticator_data"])
        self.assertEqual(ad[32] & 1, 0)  # user-present flag is off, and it still passes
        self.assertEqual(self.outcome(env), ("accepted", "execute"))

    def test_duress_looks_identical_from_outside_but_holds(self):
        normal, duress = self.d.approve(CALM), self.d.approve(SCARED)
        self.assertEqual(normal.keys(), duress.keys())
        for k in ("core", "mcu", "attest", "pq_sig"):
            self.assertEqual(len(ys.canonical(normal[k])), len(ys.canonical(duress[k])), k)
        self.assertEqual(self.outcome(normal), ("accepted", "execute"))
        self.assertEqual(self.outcome(duress), ("accepted", "hold_and_alert"))

    def test_linux_learns_nothing_about_the_status(self):
        self.d.approve(CALM)
        calm_view = [v for v in self.d.linux_view]
        self.d.linux_view.clear()
        self.d.approve(SCARED)
        self.assertEqual(calm_view, self.d.linux_view)  # same salt, same tag length

    def test_gemini_duress_and_step_up(self):
        self.assertEqual(self.outcome(self.d.approve(SCARED)), ("accepted", "hold_and_alert"))
        self.assertEqual(self.outcome(self.d.approve(UNSURE)), ("need_second_approver", "need_second_approver"))

    def test_fail_closed(self):
        for bad in (None, {}, {"duress_score": "x"}, {"duress_score": -1}, {"duress_score": 7}):
            self.assertEqual(ys.gemini_to_score(bad), -1)
        for score in (-1, 101, 1000, None, "5", 0.2, True):
            self.assertEqual(ys.decide_status(score, False), ys.DURESS, score)
        self.assertEqual(self.outcome(self.d.approve(None)), ("accepted", "hold_and_alert"))
        self.assertEqual(self.outcome(self.d.approve(CALM, veto=True)), ("accepted", "hold_and_alert"))

    def test_nothing_without_a_click(self):
        self.d.click()
        self.assertIsNone(self.d.approve(click=False, wait_ms=2000))  # the click is 2 s old

    def test_click_is_single_use(self):
        self.assertIsNotNone(self.d.approve())
        self.assertIsNone(self.d.approve(click=False))  # same click can't arm twice

    def test_no_palm_on_the_grip_no_arm(self):
        self.assertIsNone(self.d.approve(grip=False))

    def test_session_times_out(self):
        self.d.click()
        self.assertTrue(self.d.mcu.arm(bytes(32), self.d.t, OWNER))
        self.d.mcu.tick(self.d.t + 31000)
        self.assertIsNone(self.d.mcu.seal(0))

    def test_tag_is_one_shot(self):
        self.d.approve()
        self.assertIsNone(self.d.mcu.seal(0))
        self.assertIsNone(self.d.mcu.unlock_salt())
        self.assertIsNone(self.d.mcu.attest())

    def test_rate_limit(self):
        ok = 0
        for _ in range(ys.RATE_MAX + 3):
            self.d.click()
            ok += self.d.mcu.arm(bytes(32), self.d.t, OWNER)
            self.d.mcu.seal(0)
        self.assertEqual(ok, ys.RATE_MAX - 1)  # enrolment already used one arm


class HmacSha1FallbackTest(unittest.TestCase):
    """The YubiKey's HMAC-SHA1 challenge-response slot (no touch) instead of FIDO2."""

    def setUp(self):
        self.d = Device(yk=ys.SoftYubiKeyHmac())

    def test_calm_and_duress_work_the_same(self):
        r = self.d.verifier.check(self.d.approve(CALM), REQ)
        self.assertEqual((r["public"], r["internal"]), ("accepted", "execute"))
        r = self.d.verifier.check(self.d.approve(SCARED), REQ)
        self.assertEqual((r["public"], r["internal"]), ("accepted", "hold_and_alert"))

    def test_wrong_slot_key_rejected(self):
        env = self.d.approve(CALM)
        env["yk"]["response"] = ys.b64(os.urandom(20))
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "reject")

    def test_no_downgrade_either_way(self):
        env = self.d.approve(CALM)  # an HMAC-SHA1 proof sent for a FIDO2 member
        fido = Device()
        fido.verifier.members["jonah"].yk_pub = fido.yk.public_key
        fido_env = fido.approve(CALM)
        self.assertEqual(fido.verifier.check(env, REQ)["internal"], "reject")
        d2 = Device(yk=ys.SoftYubiKeyHmac())  # a FIDO2 proof sent for an HMAC-SHA1 member
        self.assertEqual(d2.verifier.check(fido_env, REQ)["internal"], "reject")


class RootedLinuxTest(unittest.TestCase):
    """The attacker controls the Linux side and waits for a genuine approval."""

    def setUp(self):
        self.d = Device()
        self.d.verifier.address_book[MALLORY] = "MALLORY"

    def forge(self, mutate, request=REQ, **kw):
        env = self.d.approve(**kw)
        mutate(env)
        return self.d.verifier.check(env, request)

    def test_cannot_swap_request_under_a_real_click(self):
        # The person clicks for ALICE's payment. Malware gets the YubiKey and ML-DSA key to sign a
        # payment to MALLORY instead, and reuses the STM32's tag.
        good = self.d.approve()
        evil_req = {**REQ, "to": MALLORY}
        nonce = self.d.verifier.new_nonce()
        book = {**BOOK, MALLORY: "MALLORY"}
        core, _ = ys.build_core(evil_req, book, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        salt = ys.hmac256(self.d.mcu._k_rel, b"unlock-salt")  # malware cached it earlier
        key = ys.unlock(self.d.store, self.d.yk.hmac_secret(salt))
        forged = ys.make_envelope(core, self.d.yk.assert_(RP, digest), ys.unb64(good["mcu"]),
                                  ys.unb64(good["attest"]), ys.GENESIS, key)
        r = self.d.verifier.check(forged, evil_req)
        self.assertEqual(r["internal"], "reject")
        self.assertIn("no valid tag", r["reason"])

    def test_cannot_arm_for_another_digest_without_a_fresh_click(self):
        # Malware asks the STM32 to arm for a MALLORY payment with no click: refused.
        evil_req = {**REQ, "to": MALLORY}
        nonce = self.d.verifier.new_nonce()
        core, _ = ys.build_core(evil_req, {**BOOK, MALLORY: "MALLORY"}, service=RP, approver="jonah",
                                device="unoq-1", nonce=nonce)
        self.assertFalse(self.d.mcu.arm(ys.core_digest(core), self.d.t + 20000, OWNER))

    def test_cannot_turn_duress_into_normal(self):
        duress = self.d.approve(SCARED)
        normal = self.d.approve(CALM)
        frank = copy.deepcopy(duress)
        frank["mcu"] = normal["mcu"]  # tag from another approval
        self.assertEqual(self.d.verifier.check(frank, REQ)["internal"], "reject")

    def test_cannot_change_the_attested_sensor_summary(self):
        def doctor(env):  # make a stranger's hand look like the owner's after the fact
            env["attest"] = ys.b64(ys.unb64(env["attest"])[:3] + ys.features_bytes(OWNER))
        r = self.forge(doctor, features=STRANGER)
        self.assertEqual(r["internal"], "reject")  # tag no longer matches (and so does the ML-DSA seal)

    def test_cannot_backdate_the_click(self):
        def doctor(env):
            raw = bytearray(ys.unb64(env["attest"]))
            raw[0], raw[1] = 0x20, 0x00
            env["attest"] = ys.b64(bytes(raw))
        self.assertEqual(self.forge(doctor)["internal"], "reject")


class OwnerCheckTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def go(self, **kw):
        env = self.d.approve(**kw)
        return self.d.verifier.check(env, REQ)

    def test_owner_like_hand_is_accepted(self):
        r = self.go()
        self.assertEqual((r["owner_band"], r["internal"]), (ys.OWNER_LIKE, "execute"))

    def test_a_stranger_is_quietly_rejected_and_looks_like_any_other_failure(self):
        r = self.go(features=STRANGER)
        self.assertEqual((r["internal"], r["public"]), ("reject_unknown_hand", ys.FAIL_PUBLIC))
        bad_sig = self.d.approve()
        bad_sig["pq_sig"] = bad_sig["pq_sig"][:-4] + "AAAA"
        self.assertEqual(self.d.verifier.check(bad_sig, REQ)["public"], ys.FAIL_PUBLIC)  # same answer for a plain failure

    def test_stranger_can_retry_forever_and_never_pass_it_locks(self):
        results = [self.go(features=STRANGER) for _ in range(ys.LOCK_AFTER)]
        self.assertTrue(all(r["public"] == ys.FAIL_PUBLIC for r in results))
        self.assertTrue(self.d.verifier.members["jonah"].locked)
        self.assertIn(("jonah", "unknown hand"), self.d.verifier.alerts)
        # even the real owner is held back until a person unlocks the member
        self.assertEqual(self.go()["public"], ys.FAIL_PUBLIC)

    def test_uncertain_hand_goes_to_a_second_approver(self):
        mixed = [(a + b) // 2 for a, b in zip(OWNER, STRANGER)]
        r = self.go(features=mixed)
        if r["owner_band"] == ys.UNCERTAIN:
            self.assertEqual(r["internal"], "need_second_approver")
        else:  # the blend can land on either side: it must never pass as plain owner AND execute
            self.assertIn(r["owner_band"], (ys.NOT_OWNER, ys.OWNER_LIKE))

    def test_learning_period_is_advisory_only(self):
        d = Device(baseline=False)
        env = d.approve(features=STRANGER)
        r = d.verifier.check(env, REQ)
        self.assertEqual((r["owner_band"], r["internal"]), (ys.LEARNING, "execute"))

    def test_only_passed_normal_approvals_teach_the_baseline(self):
        m = self.d.verifier.members["jonah"]
        n = len(m.baseline.samples)
        self.go(features=STRANGER)           # rejected: must not teach
        self.go(gemini=SCARED)               # duress: must not teach
        self.assertEqual(len(m.baseline.samples), n)
        m.unknown_hands.clear()
        m.locked = False
        self.go()                            # a normal owner approval teaches
        self.assertEqual(len(m.baseline.samples), n + 1)

    def test_duress_from_a_stranger_is_still_just_a_failure(self):
        r = self.go(gemini=SCARED, features=STRANGER)
        self.assertEqual(r["public"], ys.FAIL_PUBLIC)

    def test_every_failure_path_gives_the_same_public_answer(self):
        env = self.d.approve()
        wrong_req = self.d.verifier.check(env, {**REQ, "amount": "11"})
        replay = self.d.verifier.check(env, REQ)
        self.assertEqual(replay["internal"], "execute")
        replay = self.d.verifier.check(env, REQ)
        self.assertEqual({wrong_req["public"], replay["public"]}, {ys.FAIL_PUBLIC})


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def test_swapped_destination_rejected(self):
        self.d.verifier.address_book[MALLORY] = "MALLORY"
        env = self.d.approve()
        self.assertEqual(self.d.verifier.check(env, {**REQ, "to": MALLORY})["internal"], "reject")

    def test_replay_rejected(self):
        env = self.d.approve()
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "execute")
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "reject")

    def test_expiry_is_timed_by_the_guardian(self):
        env = self.d.approve()
        self.assertEqual(self.d.verifier.check(env, REQ, now=time.time() + 600)["internal"], "reject")

    def test_touch_is_enforced_only_when_a_deployment_asks(self):
        env = self.d.approve()
        with self.assertRaises(ValueError):
            ys.verify_yubikey_assertion(self.d.yk.public_key, env["yk"], RP, ys.core_digest(env["core"]),
                                        require_up=True)

    def test_other_service_rejected(self):
        env = self.d.approve()
        self.d.verifier.rp_id = "evil.example"
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "reject")

    def test_danger_actions_always_need_a_second_approver(self):
        req = {"action": "add_address", "label": "BOB", "address": MALLORY}
        env = self.d.approve(request=req)
        self.assertEqual(self.d.verifier.check(env, req)["internal"], "need_second_approver")

    def test_audit_log_tamper_evident(self):
        for _ in range(3):
            self.d.approve()
        pub = self.d.verifier.members["jonah"].pq_pub
        self.assertTrue(ys.log_verify(self.d.log, pub))
        self.d.log[1]["who"] = "someone_else"
        self.assertFalse(ys.log_verify(self.d.log, pub))

    def test_merkle_root_changes_with_any_entry(self):
        leaves = [os.urandom(32).hex() for _ in range(5)]
        root = ys.merkle_root(leaves)
        leaves[3] = os.urandom(32).hex()
        self.assertNotEqual(root, ys.merkle_root(leaves))


class SummaryTest(unittest.TestCase):
    def test_destination_shown_by_name(self):
        self.assertEqual(ys.render_summary(REQ, BOOK), "PAY 10 GBP TO ALICE")

    def test_lookalike_address_refused(self):
        with self.assertRaises(ValueError):  # same ending as ALICE, but not in the book
            ys.render_summary({**REQ, "to": MALLORY}, BOOK)

    def test_duplicate_names_refused(self):
        with self.assertRaises(ValueError):
            ys.render_summary(REQ, {ALICE: "ALICE", MALLORY: "ALICE"})

    def test_hidden_or_unknown_fields_refused(self):
        for bad in ({**REQ, "memo": "x"}, {"action": "mystery"}, {"action": "transfer", "amount": "10"},
                    {**REQ, "amount": "10 GBP TO BOB"}, {**REQ, "amount": "-5"}, {**REQ, "asset": "G B"}):
            with self.assertRaises(ValueError):
                ys.render_summary(bad, BOOK)

    def test_new_address_shown_in_full(self):
        text = ys.render_summary({"action": "add_address", "label": "BOB", "address": MALLORY}, BOOK)
        self.assertEqual(text.replace(" ", "").split("=")[1], MALLORY)
        self.assertLessEqual(len(text), ys.MAX_TEXT)

    def test_different_requests_never_share_a_display(self):
        book = {ALICE: "ALICE", MALLORY: "MALLORY"}
        reqs = [REQ, {**REQ, "amount": "100"}, {**REQ, "asset": "ETH"}, {**REQ, "to": MALLORY},
                {"action": "delegate", "to": ALICE}, {"action": "login", "service": "dash", "user": "jonah"},
                {"action": "login", "service": "dash", "user": "Jonah"}]
        self.assertEqual(len({ys.render_summary(r, book) for r in reqs}), len(reqs))


@unittest.skipUnless(shutil.which("g++"), "g++ not installed")
class CppCoreTest(unittest.TestCase):
    """Drive the real microcontroller code and compare with the Python model."""

    @classmethod
    def setUpClass(cls):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        cls.tmp = tempfile.mkdtemp()
        cls.exe = os.path.join(cls.tmp, "mcu_host_test")
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", "-I", os.path.join(root, "app", "sketch"),
                        os.path.join(root, "tools", "mcu_host_test.cpp"), "-o", cls.exe], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cpp(self, lines):
        out = subprocess.run([self.exe], input="\n".join(lines) + "\n", capture_output=True, text=True, check=True)
        return out.stdout.split("\n")[:-1]

    def scenario(self, score, veto, features=OWNER, grip=1, hold=60):
        k = os.urandom(32)
        _, k_tag = ys.mcu_keys(k)
        digest = os.urandom(32)
        fs = " ".join(map(str, features))
        out = self.run_cpp([f"provision {k.hex()}", f"down {grip} 1000", f"up {1000 + hold}",
                            f"arm {digest.hex()} 1500 {fs}", "salt", "attest", f"seal {score} {veto}", "seal 0 0"])
        soft = ys.SoftMcu(k)
        soft.click_down(1000, bool(grip))
        soft.click_up(1000 + hold)
        armed = soft.arm(digest, 1500, features)
        return out[3:], armed, soft, k_tag, digest

    def test_sha256_matches(self):
        for msg in ("abc", "PAY 10 GBP TO ALICE", "x" * 200):
            self.assertEqual(self.run_cpp([f"sha {msg}"])[0], ys.sha256(msg.encode()).hex())

    def test_everything_matches_python_for_every_path(self):
        for score in (-1, 0, 39, 40, 69, 70, 100, 101):
            for veto in (0, 1):
                (arm, salt, attest, tag, again), armed, soft, k_tag, digest = self.scenario(score, veto)
                self.assertEqual(arm, "1")
                self.assertTrue(armed)
                self.assertEqual(salt, soft.unlock_salt().hex())
                want = ys.decide_status(score, bool(veto))
                self.assertEqual(again, "-")  # one-shot
                self.assertEqual(tag, ys.mcu_tag(k_tag, want, digest, 500, 1, OWNER).hex(), (score, veto))
                self.assertEqual(ys.parse_attest(bytes.fromhex(attest)), (500, 1, OWNER))

    def test_c_and_python_agree_on_the_salt_and_the_tag_bytes(self):
        k = os.urandom(32)
        digest = os.urandom(32)
        out = self.run_cpp([f"provision {k.hex()}", "down 1 100", "up 160", f"arm {digest.hex()} 400 " + " ".join(map(str, OWNER)),
                            "salt", "seal 10 0"])
        soft = ys.SoftMcu(k)
        soft.click_down(100, True)
        soft.click_up(160)
        self.assertTrue(soft.arm(digest, 400, OWNER))
        self.assertEqual((out[-2], out[-1]), (soft.unlock_salt().hex(), soft.seal(10).hex()))

    def test_c_refuses_what_python_refuses(self):
        (arm, *_), _, _, _, _ = self.scenario(0, 0, grip=0)
        self.assertEqual(arm, "0")  # no palm on the grip at the click
        k = os.urandom(32)
        d = "11" * 32
        f = " ".join(map(str, OWNER))
        out = self.run_cpp([f"provision {k.hex()}", f"arm {d} 100 {f}",             # no click at all
                            "down 1 1000", "up 1060", f"arm {d} 2600 {f}",           # click 1.6 s old
                            f"arm {d} 2400 {f}", f"arm {d} 2400 {f}", "state"])      # fresh: ok once, then armed
        self.assertEqual(out[1:], ["0", "ok", "ok", "0", "1", "0", "1 60"])

    def test_c_rate_limit(self):
        k = os.urandom(32)
        f = " ".join(map(str, OWNER))
        lines = [f"provision {k.hex()}"]
        for i in range(ys.RATE_MAX + 2):
            t = 1000 * (i + 1)
            lines += [f"down 1 {t}", f"up {t + 50}", f"arm {'22' * 32} {t + 100} {f}", "seal 0 0"]
        out = self.run_cpp(lines)
        arms = [out[1 + 4 * i + 2] for i in range(ys.RATE_MAX + 2)]
        self.assertEqual(arms.count("1"), ys.RATE_MAX)

    def test_attest_length(self):
        self.assertEqual(ys.ATTEST_LEN, 43)


# ---------------------------------------------------------------- the Linux flow (approve.py) against a fake STM32
class FakeBridge:
    """Stands in for the Bridge: wraps SoftMcu. A scripted person clicks when `clicks` is true."""

    def __init__(self, mcu, clicks=True, grip=True, features=None, t0=500_000):
        self.mcu, self.clicks, self.grip, self.features, self.calls = mcu, clicks, grip, features, []
        self.t = t0
        self.rng = random.Random(7)
        self.clicked = False

    def call(self, name, *args):
        self.calls.append(name)
        m = self.mcu
        if name == "arm_approval":
            if self.clicks and not self.clicked:          # the click lands just before the request does
                self.clicked = True
                m.click_down(self.t, self.grip)
                m.click_up(self.t + 70)
                self.t += 100
            self.t += 100
            f = self.features or owner_like(self.rng)
            return "1" if m.arm(bytes.fromhex(args[0]), self.t, f) else "0"
        if name == "get_unlock_salt":
            s = m.unlock_salt()
            return s.hex() if s else "-"
        if name == "get_attest":
            a = m.attest()
            return a.hex() if a else "-"
        if name == "get_features":
            return json.dumps({"temp_c": 31.0, "humidity": 45.0, "shake_rms": 0.01, "grip": 1,
                               "moisture": 400, "state": m.state})
        if name == "seal_approval":
            tag = m.seal(int(args[0]), args[1] == "1")
            return tag.hex() if tag else "-"
        raise AssertionError(name)


class LinuxFlowTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        import guardian
        guardian.verifier.members.clear()
        guardian.verifier.open_nonces.clear()
        guardian.verifier.alerts.clear()
        guardian.verifier.address_book.update(BOOK)
        guardian.outcomes.clear()
        guardian.RP_ID = RP
        guardian.verifier.rp_id = RP
        self.guardian_mod = guardian
        client = TestClient(guardian.app)
        self.guardian = ap.HttpGuardian(lambda path, body: client.post(path, json=body).json())
        self.k_mcu = os.urandom(32)
        self.mcu = ys.SoftMcu(self.k_mcu)
        self.yk = ys.SoftYubiKey()
        self.tmp = tempfile.mkdtemp()
        self.state = ap.DeviceState(os.path.join(self.tmp, "device.json"))
        self.bridge = FakeBridge(self.mcu)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def enrol(self):
        body = ap.enrol(bridge=self.bridge, yk=self.yk, guardian=self.guardian, state=self.state,
                        user="jonah", device="unoq-1", rp_id=RP, sleep=lambda s: None)
        body["k_tag"] = ys.b64(ys.mcu_keys(self.k_mcu)[1])
        self.assertEqual(self.guardian.enrol("jonah", body), {"ok": True})
        # a supervised learning period: a few more normal owner approvals build the baseline
        m = self.guardian_mod.verifier.members["jonah"]
        for _ in range(ys.LEARNING_MIN):
            m.baseline.add(owner_like(random.Random(len(m.baseline.samples))), time.gmtime().tm_hour)

    def approve(self, gemini_fn=lambda w: CALM, timeout_s=5, **kw):
        bridge = FakeBridge(self.mcu, **kw)
        bridge.t = self.bridge.t + 10_000
        self.bridge = bridge
        return ap.approve(bridge=bridge, yk=self.yk, guardian=self.guardian, state=self.state, request=REQ,
                          address_book=BOOK, rp_id=RP, gemini_fn=gemini_fn, sleep=lambda s: None,
                          timeout_s=timeout_s)

    def test_enrol_then_calm_and_duress_look_identical_to_the_requester(self):
        self.enrol()
        a = self.approve()
        b = self.approve(gemini_fn=lambda w: SCARED)
        self.assertEqual((a["public"], b["public"]), ("accepted", "accepted"))
        self.assertEqual([o["internal"] for o in self.guardian_mod.outcomes], ["execute", "hold_and_alert"])

    def test_hmac_sha1_mode_through_the_whole_stack(self):
        self.yk = ys.SoftYubiKeyHmac()
        body = ap.enrol(bridge=self.bridge, yk=self.yk, guardian=self.guardian, state=self.state,
                        user="jonah", device="unoq-1", rp_id=RP, sleep=lambda s: None)
        body["k_tag"] = ys.b64(ys.mcu_keys(self.k_mcu)[1])
        self.assertEqual(body["yk_pub_der"], "")
        self.assertEqual(self.guardian.enrol("jonah", body).get("detail"), "give exactly one of yk_pub_der (FIDO2) or yk_hmac_key (HMAC-SHA1)")
        body["yk_hmac_key"] = ys.b64(self.yk.key)
        self.assertEqual(self.guardian.enrol("jonah", body), {"ok": True})
        m = self.guardian_mod.verifier.members["jonah"]
        for _ in range(ys.LEARNING_MIN):
            m.baseline.add(owner_like(random.Random(len(m.baseline.samples))), time.gmtime().tm_hour)
        self.assertEqual(self.approve()["public"], "accepted")
        self.assertEqual(self.guardian_mod.outcomes[-1]["internal"], "execute")

    def test_state_survives_a_restart(self):
        self.enrol()
        self.approve()
        self.state = ap.DeviceState(self.state.path)  # reload from disk, as after a power cut
        self.assertEqual(self.approve()["public"], "accepted")
        self.assertTrue(ys.log_verify(self.state.data["log"], ys.mldsa.MLDSA65PublicKey.from_public_bytes(
            ys.unb64(self.state.data["pq_pub"]))))

    def test_gemini_down_means_hold(self):
        self.enrol()
        self.assertEqual(self.approve(gemini_fn=lambda w: None)["public"], "accepted")
        self.assertEqual(self.guardian_mod.outcomes[-1]["internal"], "hold_and_alert")

    def test_missing_sensor_is_a_veto(self):
        self.assertTrue(ap.onboard_veto([]))
        self.assertTrue(ap.onboard_veto([{"temp_c": None, "humidity": 40, "shake_rms": 0, "moisture": 1}]))
        self.assertFalse(ap.onboard_veto([{"temp_c": 30, "humidity": 40, "shake_rms": 0.1, "moisture": 400}]))

    def test_no_click_signs_nothing_and_gemini_is_never_asked(self):
        self.enrol()
        asked = []
        with self.assertRaises(ap.Refused):
            self.approve(gemini_fn=lambda w: asked.append(1), clicks=False, timeout_s=0.2)
        self.assertEqual((asked, len(self.guardian_mod.outcomes)), ([], 0))

    def test_no_palm_on_the_grip_signs_nothing(self):
        self.enrol()
        with self.assertRaises(ap.Refused):
            self.approve(grip=False, timeout_s=0.2)

    def test_stranger_is_rejected_through_the_whole_stack(self):
        self.enrol()
        r = self.approve(features=ys_stranger())
        self.assertEqual(r["public"], ys.FAIL_PUBLIC)
        self.assertEqual(self.guardian_mod.outcomes[-1]["internal"], "reject_unknown_hand")

    def test_other_yubikey_cannot_unlock_the_key(self):
        self.enrol()
        self.yk = ys.SoftYubiKey()
        with self.assertRaises(ap.Refused):
            self.approve()

    def test_linux_only_calls_the_expected_bridge_handlers(self):
        self.enrol()
        self.approve()
        self.assertLessEqual(set(self.bridge.calls),
                             {"arm_approval", "get_unlock_salt", "get_attest", "get_features", "seal_approval"})


def ys_stranger():
    return list(STRANGER)


if __name__ == "__main__":
    unittest.main()
