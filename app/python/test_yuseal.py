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

RP = "yuduino.local"
ALICE = "0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"
MALLORY = "0xDEADBEEF00000000000000000000000000A1F3"  # same last 4 characters as ALICE
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
    """One enrolled YuDuino in a mouse: STM32 (SoftMcu) + Linux side + YubiKey + a verifier that knows it."""

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
        self.verifier = ys.Verifier(RP)
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

    def approve(self, model=CALM, request=REQ, veto=False, features=None, grip=True, click=True, wait_ms=100):
        """The Linux-side flow from docs/BUILD-FLOW.md. Returns the envelope, or None if the STM32 won't arm."""
        nonce = self.verifier.new_nonce()
        core = ys.build_core(request, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
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
        tag = self.mcu.seal(ys.model_to_score(model), veto)   # 5. STM32 decides and tags
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
        return r["public"], r["verdict"]

    def test_calm_owner_approval_executes(self):
        self.assertEqual(self.outcome(self.d.approve()), ("accepted", "normal"))

    def test_no_touch_is_needed(self):
        env = self.d.approve()
        ad = ys.unb64(env["yk"]["authenticator_data"])
        self.assertEqual(ad[32] & 1, 0)  # user-present flag is off, and it still passes
        self.assertEqual(self.outcome(env), ("accepted", "normal"))

    def test_duress_looks_identical_from_outside_but_holds(self):
        normal, duress = self.d.approve(CALM), self.d.approve(SCARED)
        self.assertEqual(normal.keys(), duress.keys())
        for k in ("core", "mcu", "attest", "pq_sig"):
            self.assertEqual(len(ys.canonical(normal[k])), len(ys.canonical(duress[k])), k)
        self.assertEqual(self.outcome(normal), ("accepted", "normal"))
        self.assertEqual(self.outcome(duress), ("accepted", "duress"))

    def test_linux_learns_nothing_about_the_status(self):
        self.d.approve(CALM)
        calm_view = [v for v in self.d.linux_view]
        self.d.linux_view.clear()
        self.d.approve(SCARED)
        self.assertEqual(calm_view, self.d.linux_view)  # same salt, same tag length

    def test_model_duress_and_step_up(self):
        self.assertEqual(self.outcome(self.d.approve(SCARED)), ("accepted", "duress"))
        self.assertEqual(self.outcome(self.d.approve(UNSURE)), ("step_up", "step_up"))

    def test_fail_closed(self):
        for bad in (None, {}, {"duress_score": "x"}, {"duress_score": -1}, {"duress_score": 7}):
            self.assertEqual(ys.model_to_score(bad), -1)
        for score in (-1, 101, 1000, None, "5", 0.2, True):
            self.assertEqual(ys.decide_status(score, False), ys.DURESS, score)
        self.assertEqual(self.outcome(self.d.approve(None)), ("accepted", "duress"))
        self.assertEqual(self.outcome(self.d.approve(CALM, veto=True)), ("accepted", "duress"))

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
        self.assertEqual((r["public"], r["verdict"]), ("accepted", "normal"))
        r = self.d.verifier.check(self.d.approve(SCARED), REQ)
        self.assertEqual((r["public"], r["verdict"]), ("accepted", "duress"))

    def test_wrong_slot_key_rejected(self):
        env = self.d.approve(CALM)
        env["yk"]["response"] = ys.b64(os.urandom(20))
        self.assertEqual(self.d.verifier.check(env, REQ)["verdict"], "reject")

    def test_no_downgrade_either_way(self):
        env = self.d.approve(CALM)  # an HMAC-SHA1 proof sent for a FIDO2 member
        fido = Device()
        fido.verifier.members["jonah"].yk_pub = fido.yk.public_key
        fido_env = fido.approve(CALM)
        self.assertEqual(fido.verifier.check(env, REQ)["verdict"], "reject")
        d2 = Device(yk=ys.SoftYubiKeyHmac())  # a FIDO2 proof sent for an HMAC-SHA1 member
        self.assertEqual(d2.verifier.check(fido_env, REQ)["verdict"], "reject")


class RootedLinuxTest(unittest.TestCase):
    """The attacker controls the Linux side and waits for a genuine approval."""

    def setUp(self):
        self.d = Device()

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
        core = ys.build_core(evil_req, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        salt = ys.hmac256(self.d.mcu._k_rel, b"unlock-salt")  # malware cached it earlier
        key = ys.unlock(self.d.store, self.d.yk.hmac_secret(salt))
        forged = ys.make_envelope(core, self.d.yk.assert_(RP, digest), ys.unb64(good["mcu"]),
                                  ys.unb64(good["attest"]), ys.GENESIS, key)
        r = self.d.verifier.check(forged, evil_req)
        self.assertEqual(r["verdict"], "reject")
        self.assertIn("no valid tag", r["reason"])

    def test_cannot_arm_for_another_digest_without_a_fresh_click(self):
        # Malware asks the STM32 to arm for a MALLORY payment with no click: refused.
        evil_req = {**REQ, "to": MALLORY}
        nonce = self.d.verifier.new_nonce()
        core = ys.build_core(evil_req, service=RP, approver="jonah",
                             device="unoq-1", nonce=nonce)
        self.assertFalse(self.d.mcu.arm(ys.core_digest(core), self.d.t + 20000, OWNER))

    def test_cannot_turn_duress_into_normal(self):
        duress = self.d.approve(SCARED)
        normal = self.d.approve(CALM)
        frank = copy.deepcopy(duress)
        frank["mcu"] = normal["mcu"]  # tag from another approval
        self.assertEqual(self.d.verifier.check(frank, REQ)["verdict"], "reject")

    def test_cannot_change_the_attested_sensor_summary(self):
        def doctor(env):  # make a stranger's hand look like the owner's after the fact
            env["attest"] = ys.b64(ys.unb64(env["attest"])[:3] + ys.features_bytes(OWNER))
        r = self.forge(doctor, features=STRANGER)
        self.assertEqual(r["verdict"], "reject")  # tag no longer matches (and so does the ML-DSA seal)

    def test_cannot_backdate_the_click(self):
        def doctor(env):
            raw = bytearray(ys.unb64(env["attest"]))
            raw[0], raw[1] = 0x20, 0x00
            env["attest"] = ys.b64(bytes(raw))
        self.assertEqual(self.forge(doctor)["verdict"], "reject")


class OwnerCheckTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def go(self, **kw):
        env = self.d.approve(**kw)
        return self.d.verifier.check(env, REQ)

    def test_owner_like_hand_is_accepted(self):
        r = self.go()
        self.assertEqual((r["owner_band"], r["verdict"]), (ys.OWNER_LIKE, "normal"))

    def test_a_stranger_is_quietly_rejected_and_looks_like_any_other_failure(self):
        r = self.go(features=STRANGER)
        self.assertEqual((r["verdict"], r["public"]), ("unknown_hand", ys.FAIL_PUBLIC))
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
            self.assertEqual(r["verdict"], "step_up")
        else:  # the blend can land on either side: it must never pass as plain owner AND execute
            self.assertIn(r["owner_band"], (ys.NOT_OWNER, ys.OWNER_LIKE))

    def test_learning_period_is_advisory_only(self):
        d = Device(baseline=False)
        env = d.approve(features=STRANGER)
        r = d.verifier.check(env, REQ)
        self.assertEqual((r["owner_band"], r["verdict"]), (ys.LEARNING, "normal"))

    def test_only_passed_normal_approvals_teach_the_baseline(self):
        m = self.d.verifier.members["jonah"]
        n = len(m.baseline.samples)
        self.go(features=STRANGER)           # rejected: must not teach
        self.go(model=SCARED)               # duress: must not teach
        self.assertEqual(len(m.baseline.samples), n)
        m.unknown_hands.clear()
        m.locked = False
        self.go()                            # a normal owner approval teaches
        self.assertEqual(len(m.baseline.samples), n + 1)

    def test_duress_from_a_stranger_is_still_just_a_failure(self):
        r = self.go(model=SCARED, features=STRANGER)
        self.assertEqual(r["public"], ys.FAIL_PUBLIC)

    def test_every_failure_path_gives_the_same_public_answer(self):
        env = self.d.approve()
        wrong_req = self.d.verifier.check(env, {**REQ, "amount": "11"})
        replay = self.d.verifier.check(env, REQ)
        self.assertEqual(replay["verdict"], "normal")
        replay = self.d.verifier.check(env, REQ)
        self.assertEqual({wrong_req["public"], replay["public"]}, {ys.FAIL_PUBLIC})


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def test_swapped_destination_rejected(self):
        env = self.d.approve()
        self.assertEqual(self.d.verifier.check(env, {**REQ, "to": MALLORY})["verdict"], "reject")

    def test_replay_rejected(self):
        env = self.d.approve()
        self.assertEqual(self.d.verifier.check(env, REQ)["verdict"], "normal")
        self.assertEqual(self.d.verifier.check(env, REQ)["verdict"], "reject")

    def test_expiry_is_timed_by_the_verifier(self):
        env = self.d.approve()
        self.assertEqual(self.d.verifier.check(env, REQ, now=time.time() + 600)["verdict"], "reject")

    def test_touch_is_enforced_only_when_a_deployment_asks(self):
        env = self.d.approve()
        with self.assertRaises(ValueError):
            ys.verify_yubikey_assertion(self.d.yk.public_key, env["yk"], RP, ys.core_digest(env["core"]),
                                        require_up=True)

    def test_other_service_rejected(self):
        env = self.d.approve()
        self.d.verifier.rp_id = "evil.example"
        self.assertEqual(self.d.verifier.check(env, REQ)["verdict"], "reject")

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
        for msg in ("abc", "a transfer request", "x" * 200):
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

    def test_profile_key_matches(self):
        k = os.urandom(32)
        self.assertEqual(self.run_cpp([f"provision {k.hex()}", "profile"])[1], ys.mcu_profile_key(k).hex())

    def test_baseline_matches_python(self):
        rng = random.Random(5)
        py, lines, vals = ys.HourBaseline(), [], []
        for i in range(1500):                      # past BL_CAP, so the rolling window is exercised
            v = [45 + rng.uniform(-2, 2), 400 + rng.uniform(-30, 30), 0.02 + rng.uniform(0, 0.01), 31 + rng.uniform(-.5, .5)]
            vals.append(v)
            py.add(9, v)
            lines.append("bl_add 9 " + " ".join(repr(x) for x in v))
        probe = [60.0, 520.0, 0.08, 33.0]
        out = self.run_cpp(lines + ["bl_count 9", "bl_count 10", "bl_z 9 " + " ".join(map(repr, probe)),
                                    "bl_z 10 1 2 3 4", "bl_export 9"])
        tail = out[len(lines):]
        self.assertEqual((tail[0], tail[1], tail[3]), ("%d" % ys.BL_CAP, "0", "-"))
        for a, b in zip(map(float, tail[2].split()), py.z(9, probe)):
            self.assertAlmostEqual(a, b, places=6)
        self.assertEqual(bytes.fromhex(tail[4]), py.export_hour(9))
        # and an exported hour restores, and bad bytes are refused
        back = self.run_cpp(["bl_import 3 " + tail[4], "bl_count 3", "bl_import 3 " + "ff" * ys.BL_HOUR_BYTES])
        self.assertEqual(back, ["1", "%d" % ys.BL_CAP, "0"])

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
            return json.dumps({"temp_c": 31.0, "humidity": 45.0, "shake_rms": 0.01, "grip": 1 if self.grip_now else 0,
                               "moisture": 400, "hold_ms": 80, "state": m.state})
        if name == "seal_approval":
            tag = m.seal(int(args[0]), args[1] == "1")
            return tag.hex() if tag else "-"
        if name == "get_profile_key":
            return m.profile_key().hex()
        if name == "baseline_add":      # the STM32 reads the sensors itself; Linux only gives the hour
            if not self.grip_now:
                return "0"
            m.baseline.add(int(args[0]), self.body())
            return "1"
        if name == "baseline_z":
            z = m.baseline.z(int(args[0]), self.body())
            return " ".join(f"{x:.4f}" for x in z) if z else "-"
        if name == "baseline_export":
            return m.baseline.export_hour(int(args[0])).hex()
        if name == "baseline_import":
            return "1" if m.baseline.import_hour(int(args[0]), bytes.fromhex(args[1])) else "0"
        raise AssertionError(name)

    grip_now = True

    def body(self):                     # humidity, moisture, shake_rms, temp_c
        return [45.0 + self.rng.uniform(-1, 1), 400 + self.rng.uniform(-20, 20), 0.01, 31.0]


class LinuxFlowTest(unittest.TestCase):
    def setUp(self):
        self.verifier = ys.Verifier(RP)
        self.k_mcu = os.urandom(32)
        self.mcu = ys.SoftMcu(self.k_mcu)
        self.yk = ys.SoftYubiKey()
        self.tmp = tempfile.mkdtemp()
        self.state = ap.DeviceState(os.path.join(self.tmp, "device.json"))
        self.bridge = FakeBridge(self.mcu)
        self.results = []

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def package(self):
        body = ap.enrol(bridge=self.bridge, yk=self.yk, state=self.state,
                        user="jonah", device="unoq-1", rp_id=RP, sleep=lambda s: None)
        body["k_tag"] = ys.b64(ys.mcu_keys(self.k_mcu)[1])
        return body

    def learn(self):
        # a supervised learning period: normal owner approvals build the baseline
        m = self.verifier.members["jonah"]
        for _ in range(ys.LEARNING_MIN):
            m.baseline.add(owner_like(random.Random(len(m.baseline.samples))), time.gmtime().tm_hour)

    def enrol(self):
        self.verifier.enrol("jonah", self.package())
        self.learn()

    def approve(self, model_fn=lambda w, c=None: CALM, timeout_s=5, **kw):
        bridge = FakeBridge(self.mcu, **kw)
        bridge.t = self.bridge.t + 10_000
        self.bridge = bridge
        nonce = self.verifier.new_nonce()
        out = ap.approve(bridge=bridge, yk=self.yk, state=self.state, request=REQ, nonce=nonce,
                         rp_id=RP, model_fn=model_fn, sleep=lambda s: None, timeout_s=timeout_s)
        r = self.verifier.check(out["envelope"], REQ)
        self.results.append(r)
        return r

    def test_enrol_then_calm_and_duress_look_identical_to_the_requester(self):
        self.enrol()
        a = self.approve()
        b = self.approve(model_fn=lambda w, c=None: SCARED)
        self.assertEqual((a["public"], b["public"]), ("accepted", "accepted"))
        self.assertEqual([r["verdict"] for r in self.results], ["normal", "duress"])

    def test_hmac_sha1_mode_through_the_whole_stack(self):
        self.yk = ys.SoftYubiKeyHmac()
        body = self.package()
        self.assertEqual(body["yk_pub_der"], "")
        with self.assertRaises(ValueError):  # neither a FIDO2 key nor an HMAC key given
            self.verifier.enrol("jonah", body)
        body["yk_hmac_key"] = ys.b64(self.yk.key)
        self.verifier.enrol("jonah", body)
        self.learn()
        self.assertEqual(self.approve()["public"], "accepted")
        self.assertEqual(self.results[-1]["verdict"], "normal")

    def test_verifier_state_round_trips_through_json(self):
        self.enrol()
        self.approve()
        again = ys.Verifier.from_json(self.verifier.to_json())
        nonce = again.new_nonce()
        out = ap.approve(bridge=FakeBridge(self.mcu, t0=self.bridge.t + 10_000), yk=self.yk, state=self.state,
                         request=REQ, nonce=nonce, rp_id=RP, model_fn=lambda w, c=None: CALM, sleep=lambda s: None)
        self.assertEqual(again.check(out["envelope"], REQ)["verdict"], "normal")

    def test_state_survives_a_restart(self):
        self.enrol()
        self.approve()
        self.state = ap.DeviceState(self.state.path)  # reload from disk, as after a power cut
        self.assertEqual(self.approve()["public"], "accepted")
        self.assertTrue(ys.log_verify(self.state.data["log"], ys.mldsa.MLDSA65PublicKey.from_public_bytes(
            ys.unb64(self.state.data["pq_pub"]))))

    def test_model_down_means_hold(self):
        self.enrol()
        self.assertEqual(self.approve(model_fn=lambda w, c=None: None)["public"], "accepted")
        self.assertEqual(self.results[-1]["verdict"], "duress")

    def test_missing_sensor_is_a_veto(self):
        self.assertTrue(ap.onboard_veto([]))
        self.assertTrue(ap.onboard_veto([{"temp_c": None, "humidity": 40, "shake_rms": 0, "moisture": 1}]))
        self.assertFalse(ap.onboard_veto([{"temp_c": 30, "humidity": 40, "shake_rms": 0.1, "moisture": 400}]))

    def test_no_click_signs_nothing_and_the_model_is_never_asked(self):
        self.enrol()
        asked = []
        with self.assertRaises(ap.Refused):
            self.approve(model_fn=lambda w, c=None: asked.append(1), clicks=False, timeout_s=0.2)
        self.assertEqual((asked, self.results), ([], []))

    def test_no_palm_on_the_grip_signs_nothing(self):
        self.enrol()
        with self.assertRaises(ap.Refused):
            self.approve(grip=False, timeout_s=0.2)

    def test_stranger_is_rejected_through_the_whole_stack(self):
        self.enrol()
        r = self.approve(features=ys_stranger())
        self.assertEqual(r["public"], ys.FAIL_PUBLIC)
        self.assertEqual(r["verdict"], "unknown_hand")

    def test_other_yubikey_cannot_unlock_the_key(self):
        self.enrol()
        self.yk = ys.SoftYubiKey()
        with self.assertRaises(ap.Refused):
            self.approve()

    def test_linux_only_calls_the_expected_bridge_handlers(self):
        self.enrol()
        self.approve()
        self.assertLessEqual(set(self.bridge.calls),
                             {"arm_approval", "get_unlock_salt", "get_attest", "get_features", "seal_approval", "baseline_z"})


def ys_stranger():
    return list(STRANGER)


class HourBaselineTest(unittest.TestCase):
    def test_exact_mean_and_variance_then_rolling(self):
        b = ys.HourBaseline()
        xs = [10.0, 12.0, 14.0, 16.0]
        for x in xs:
            b.add(2, [x, x, x, x])
        n, mean, var = b.s[2][0]
        self.assertEqual((n, mean), (4, 13.0))
        self.assertAlmostEqual(var, 5.0)                      # population variance of 10,12,14,16
        for _ in range(3 * ys.BL_CAP):
            b.add(2, [100.0] * 4)
        self.assertEqual(b.s[2][0][0], ys.BL_CAP)             # the count is capped: a slow rolling window
        self.assertAlmostEqual(b.s[2][0][1], 100.0, places=0)  # and it follows a changed normal

    def test_no_z_score_until_enough_data(self):
        b = ys.HourBaseline()
        for _ in range(ys.BL_MIN_N - 1):
            b.add(5, [1.0, 2.0, 3.0, 4.0])
        self.assertIsNone(b.z(5, [1.0, 2.0, 3.0, 4.0]))
        b.add(5, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(b.z(5, [1.0, 2.0, 3.0, 4.0]), [0.0] * 4)
        self.assertIsNone(b.z(6, [1.0, 2.0, 3.0, 4.0]))       # other hours stay empty

    def test_an_odd_reading_scores_high(self):
        rng = random.Random(2)
        b = ys.HourBaseline()
        for _ in range(200):
            b.add(9, [45 + rng.uniform(-1, 1), 400 + rng.uniform(-20, 20), 0.02, 31 + rng.uniform(-.3, .3)])
        z = b.z(9, [60, 600, 0.02, 31])
        self.assertGreater(z[0], 5)
        self.assertGreater(z[1], 5)

    def test_import_refuses_nonsense(self):
        b = ys.HourBaseline()
        self.assertFalse(b.import_hour(1, b"\xff" * ys.BL_HOUR_BYTES))
        self.assertFalse(b.import_hour(1, b"short"))


class ProfileTest(unittest.TestCase):
    """The profile at rest: AES-256-GCM under a key from the STM32."""

    def setUp(self):
        import userprofile as up
        self.up, self.tmp = up, tempfile.mkdtemp()
        self.key = os.urandom(32)
        self.p = up.Profile(lambda: self.key, self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_round_trip_and_nothing_readable_on_disk(self):
        secret = b"baseline-and-weights" * 10
        self.p.save("baseline.bin", secret)
        raw = open(os.path.join(self.tmp, "baseline.bin"), "rb").read()
        self.assertNotIn(b"baseline-and-weights", raw)
        self.assertEqual(self.p.load("baseline.bin"), secret)
        self.assertEqual(oct(os.stat(os.path.join(self.tmp, "baseline.bin")).st_mode & 0o777), "0o600")

    def test_stolen_board_wrong_key_tamper_and_swap_all_fail(self):
        self.p.save("baseline.bin", b"x" * 50)
        other = self.up.Profile(lambda: os.urandom(32), self.tmp)          # a different board's key
        self.assertIsNone(other.load("baseline.bin"))
        path = os.path.join(self.tmp, "baseline.bin")
        raw = bytearray(open(path, "rb").read())
        raw[-1] ^= 1
        open(path, "wb").write(bytes(raw))
        self.assertIsNone(self.p.load("baseline.bin"))                      # tampered
        self.p.save("baseline.bin", b"x" * 50)
        shutil.copy(path, os.path.join(self.tmp, "model-jonah.eim"))
        self.assertIsNone(self.p.load("model-jonah.eim"))                   # one file swapped for another
        self.assertIsNone(self.p.load("missing"))

    def test_no_key_from_the_stm32_means_nothing_is_readable(self):
        self.p.save("baseline.bin", b"y")
        dead = self.up.Profile(lambda: None, self.tmp)
        with self.assertRaises(ValueError):
            dead.load("baseline.bin")

    def test_baseline_survives_a_power_cut_via_the_encrypted_copy(self):
        mcu = ys.SoftMcu(os.urandom(32))
        bridge = FakeBridge(mcu)
        for _ in range(50):
            self.assertTrue(self.up.learn_tick(bridge, 9))
        before = mcu.baseline.export_hour(9)
        self.p.persist_baseline(bridge)
        fresh = FakeBridge(ys.SoftMcu(os.urandom(32)))                      # the STM32 rebooted: RAM empty
        self.assertEqual(fresh.mcu.baseline.count(9), 0)
        self.assertEqual(self.p.restore_baseline(fresh), 24)
        self.assertEqual(fresh.mcu.baseline.export_hour(9), before)

    def test_only_the_stm32_adds_readings_and_only_with_a_palm_on(self):
        bridge = FakeBridge(ys.SoftMcu(os.urandom(32)), grip=True)
        bridge.grip_now = False
        self.assertFalse(self.up.learn_tick(bridge, 9))
        self.assertEqual(bridge.mcu.baseline.count(9), 0)

    def test_the_model_is_encrypted_and_decrypts_only_into_ram(self):
        eim = os.path.join(self.tmp, "m.eim")
        open(eim, "wb").write(b"\x7fELF-model-weights")
        self.p.import_model("jonah", eim)
        self.assertNotIn(b"model-weights", open(os.path.join(self.tmp, "model-jonah.eim"), "rb").read())
        path = self.p.open_model("jonah")
        try:
            self.assertEqual(open(path, "rb").read(), b"\x7fELF-model-weights")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)
        finally:
            os.unlink(path)
        self.assertIsNone(self.p.open_model("nobody"))


class LearnerTest(unittest.TestCase):
    def setUp(self):
        import learner, userprofile as up
        self.tmp = tempfile.mkdtemp()
        self.mcu = ys.SoftMcu(os.urandom(32))
        self.bridge = FakeBridge(self.mcu)
        self.profile = up.Profile(lambda: self.mcu.profile_key(), self.tmp)
        self.recent = os.path.join(self.tmp, "recent.json")
        learner.RECENT_PATH = self.recent
        self.t = [1_000_000.0]
        self.lr = learner.Learner(self.bridge, self.profile, clock=lambda: self.t[0], sleep=lambda s: self.t.__setitem__(0, self.t[0] + s))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_demo_seeding_gives_a_baseline_and_training_rows(self):
        self.lr.run(minutes=15)
        import edge_model as em
        rows = self.profile.training_rows()
        self.assertGreaterEqual(len(rows), 14)                       # about one per minute, samples discarded
        self.assertTrue(all(len(r) == len(em.FEATURE_NAMES) for r in rows))
        hour = time.localtime(1_000_000.0).tm_hour
        self.assertGreaterEqual(self.mcu.baseline.count(hour), 800)
        self.assertIsNotNone(self.profile.load("baseline.bin"))      # persisted, encrypted
        self.assertEqual(self.lr.buf, [])                            # raw samples are gone

    def test_nothing_is_learned_without_a_hand_or_during_an_approval(self):
        self.bridge.grip_now = False
        for _ in range(30):
            self.lr.tick()
            self.t[0] += 1
        self.assertEqual((self.lr.added, self.lr.buf), (0, []))
        self.assertFalse(self.lr.flush_minute())                     # too little hand time: no row

    def test_the_last_minute_is_kept_for_the_transaction_and_no_more(self):
        import learner
        self.lr.run(minutes=3)
        w = learner.recent_window(self.t[0], self.recent)
        self.assertTrue(55 <= len(w) <= 61)                          # one minute, not the whole run
        self.assertTrue(all(self.t[0] - r["t"] <= 60 for r in w))
        self.assertEqual(learner.recent_window(self.t[0] + 120, self.recent), [])   # stale: ignored
        self.assertEqual(learner.recent_window(self.t[0], self.recent + ".none"), [])

    def test_the_transaction_scores_the_last_minute_against_the_baseline(self):
        import learner
        self.lr.run(minutes=2)
        learner.RECENT_PATH = self.recent
        old = time.time
        time.time = lambda: self.t[0]
        try:
            w = ap._scoring_window([{"temp_c": 30}])
        finally:
            time.time = old
        self.assertGreater(len(w), 50)
        self.assertEqual(w[-1], {"temp_c": 30})                      # the post-click readings come last

    def test_the_training_file_is_encrypted_at_rest(self):
        self.lr.run(minutes=3)
        raw = open(os.path.join(self.tmp, "training.bin"), "rb").read()
        self.assertTrue(raw.startswith(b"YP1"))
        self.assertNotIn(b"[[", raw)


class EdgeModelTest(unittest.TestCase):
    """The on-device Edge Impulse model's integration point, with a fake runner (no .eim file needed)."""

    class Runner:
        def __init__(self, probs=None, boom=False):
            self.probs, self.boom, self.seen = probs or {"calm": 0.9, "duress": 0.1}, boom, []

        def classify(self, features):
            self.seen.append(features)
            if self.boom:
                raise RuntimeError("model fault")
            return {"result": {"classification": self.probs}}

    WINDOW = [{"temp_c": 31.0, "humidity": 40.0, "shake_rms": 0.02, "moisture": 400, "grip": 1},
              {"temp_c": 31.2, "humidity": 46.0, "shake_rms": 0.30, "moisture": 520, "grip": 1}]

    def test_feature_vector_has_the_declared_names_in_order(self):
        import edge_model as em
        v = em.feature_vector(self.WINDOW, {"faces": 2, "sweat_z": 3.1})
        self.assertEqual(len(v), len(em.FEATURE_NAMES))
        named = dict(zip(em.FEATURE_NAMES, v))
        self.assertAlmostEqual(named["humidity_delta"], 6.0)
        self.assertAlmostEqual(named["shake_rms_max"], 0.30)
        self.assertEqual((named["grip_fraction"], named["faces"], named["sweat_z"], named["move_z"]), (1.0, 2.0, 3.1, 0.0))
        self.assertEqual(named["hour_z_humidity"], 0.0)

    def test_duress_probability_becomes_the_score(self):
        import edge_model as em
        runner = self.Runner({"calm": 0.2, "duress": 0.8})
        r = em.EdgeModel(runner=runner).score(self.WINDOW)
        self.assertEqual(ys.model_to_score(r), 80)
        self.assertEqual(r["source"], "edge_impulse")
        self.assertEqual(len(runner.seen), 1)

    def test_no_model_file_means_no_verdict_which_fails_closed(self):
        import edge_model as em
        m = em.EdgeModel(path="/nonexistent/model.eim")
        self.assertFalse(m.ready)
        self.assertIsNone(m.score(self.WINDOW))
        self.assertEqual(ys.model_to_score(None), -1)
        self.assertEqual(ys.decide_status(-1, False), ys.DURESS)

    def test_model_faults_and_nonsense_never_look_calm(self):
        import edge_model as em
        self.assertIsNone(em.EdgeModel(runner=self.Runner(boom=True)).score(self.WINDOW))
        self.assertIsNone(em.EdgeModel(runner=self.Runner({"calm": 1.0})).score(self.WINDOW))  # no duress class
        self.assertIsNone(em.EdgeModel(runner=self.Runner({"duress": 7.0})).score(self.WINDOW))
        self.assertIsNone(em.EdgeModel(runner=self.Runner()).score([]))

    def test_anomaly_model_maps_to_a_duress_score(self):
        import edge_model as em

        class Anomaly:
            def __init__(self, a): self.a = a
            def classify(self, f): return {"result": {"anomaly": self.a}}

        score = lambda a: em.EdgeModel(runner=Anomaly(a), limit=1.0).score(self.WINDOW)
        self.assertEqual(ys.model_to_score(score(0.2)), 10)          # normal for this user
        self.assertEqual(ys.model_to_score(score(1.0)), 50)          # at the limit: step-up
        self.assertEqual(ys.model_to_score(score(1.5)), 75)          # clearly unusual: duress
        self.assertEqual(ys.model_to_score(score(9.0)), 100)
        self.assertEqual(ys.decide_status(75, False), ys.DURESS)
        self.assertEqual(ys.decide_status(50, False), ys.STEP_UP)

    def test_model_score_goes_through_the_whole_flow(self):
        import edge_model as em
        d = Device()
        m = em.EdgeModel(runner=self.Runner({"calm": 0.05, "duress": 0.95}))
        env = d.approve(model=m.score(self.WINDOW))
        self.assertEqual(d.verifier.check(env, REQ)["verdict"], "duress")


if __name__ == "__main__":
    unittest.main()
