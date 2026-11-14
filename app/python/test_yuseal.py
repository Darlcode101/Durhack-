"""Run on a laptop or the UNO Q:  python3 -m unittest test_yuseal -v   (from app/python)

Walks the whole YuSeal v2 flow with software stand-ins for the YubiKey and the STM32,
then checks the real C++ microcontroller code (app/sketch/yuseal_mcu.h) gives the same
bytes as the Python model. The C++ check is skipped if g++ isn't installed.
"""
import copy
import os
import shutil
import subprocess
import tempfile
import time
import unittest

import yuseal as ys

RP = "guardian.yuduino.local"
ALICE = "0xA1B2C3D4E5F60718293A4B5C6D7E8F9012A1F3"
MALLORY = "0xDEADBEEF00000000000000000000000000A1F3"  # same last 4 characters as ALICE
BOOK = {ALICE: "ALICE"}
REQ = {"action": "transfer", "amount": "10", "asset": "GBP", "to": ALICE}
PIN, DURESS_PIN = "ABCABCAB", "ABCABCAb"  # duress = same presses, last one held long

CALM = {"duress_score": 0.1, "signals": [], "reasoning": ""}
UNSURE = {"duress_score": 0.5, "signals": ["tremor"], "reasoning": ""}
SCARED = {"duress_score": 0.9, "signals": ["tremor", "second face"], "reasoning": ""}


class Device:
    """One enrolled YuDuino: STM32 (SoftMcu) + Linux side + YubiKey, and a guardian that knows it."""

    def __init__(self):
        self.yk = ys.SoftYubiKey()
        k_mcu = os.urandom(32)
        self.mcu = ys.SoftMcu(k_mcu, PIN, DURESS_PIN)
        # Enrolment: one correct PIN on the buttons releases the salt; wrap the ML-DSA key under it.
        self.mcu.begin("ENROL", bytes(32))
        self.mcu.type_pin(PIN)
        salt = self.mcu.unlock_salt()
        self.mcu.seal(0)
        self.store, pq = ys.create_keystore(self.yk.hmac_secret(salt))
        self.verifier = ys.Verifier(RP, address_book=dict(BOOK))
        self.verifier.members["jonah"] = ys.Member(
            self.yk.public_key, pq.public_key(), ys.mcu_keys(k_mcu)[1])
        self.log = []
        self.linux_view = []  # everything the Linux side learns during approvals

    def approve(self, pin, gemini, request=REQ, veto=False, linux_score=None):
        """The Linux-side flow from docs/BUILD-FLOW.md. Returns the envelope, or None if denied."""
        nonce = self.verifier.new_nonce()
        core, text = ys.build_core(request, BOOK, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        if not self.mcu.begin(text, digest):                    # 1. STM32 shows the text
            return None
        self.mcu.type_pin(pin)                                  # 2. person presses the PIN
        salt = self.mcu.unlock_salt()                           # 3. salt only after a correct PIN
        self.linux_view.append(("salt", salt))
        if salt is None:
            return None
        assertion = self.yk.assert_(RP, digest)                 # 4. YubiKey touch
        key = ys.unlock(self.store, self.yk.hmac_secret(salt))
        score = ys.gemini_to_score(gemini) if linux_score is None else linux_score
        tag = self.mcu.seal(score, veto)                        # 5. STM32 decides and tags
        self.linux_view.append(("tag_len", len(tag)))
        prev = self.log[-1]["hash"] if self.log else ys.GENESIS
        env = ys.make_envelope(core, assertion, tag, prev, key)
        ys.log_append(self.log, env, key)
        return env


class ApprovalTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def outcome(self, env, request=REQ, **kw):
        r = self.d.verifier.check(env, request, **kw)
        return r["public"], r["internal"]

    def test_calm_approval_executes(self):
        self.assertEqual(self.outcome(self.d.approve(PIN, CALM)), ("accepted", "execute"))

    def test_duress_pin_looks_identical_but_holds(self):
        normal = self.d.approve(PIN, CALM)
        duress = self.d.approve(DURESS_PIN, CALM)
        self.assertEqual(normal.keys(), duress.keys())
        for k in ("core", "mcu", "pq_sig"):  # same sizes (the YubiKey's ECDSA length varies at random in both)
            self.assertEqual(len(ys.canonical(normal[k])), len(ys.canonical(duress[k])), k)
        self.assertEqual(self.outcome(normal), ("accepted", "execute"))
        self.assertEqual(self.outcome(duress), ("accepted", "hold_and_alert"))

    def test_linux_learns_nothing_about_the_duress_pin(self):
        self.d.approve(PIN, CALM)
        normal_view = list(self.d.linux_view)
        self.d.linux_view.clear()
        self.d.approve(DURESS_PIN, CALM)
        self.assertEqual(normal_view, self.d.linux_view)  # same salt, same tag length

    def test_gemini_duress_and_step_up(self):
        self.assertEqual(self.outcome(self.d.approve(PIN, SCARED)), ("accepted", "hold_and_alert"))
        self.assertEqual(self.outcome(self.d.approve(PIN, UNSURE)),
                         ("need_second_approver", "need_second_approver"))

    def test_fail_closed(self):
        for bad in (None, {}, {"duress_score": "x"}, {"duress_score": -1}, {"duress_score": 7}):
            self.assertEqual(ys.gemini_to_score(bad), -1)
        for score in (-1, 101, 1000, None, "5", 0.2, True):
            self.assertEqual(ys.decide_status(False, score, False), ys.DURESS, score)
        self.assertEqual(self.outcome(self.d.approve(PIN, None)), ("accepted", "hold_and_alert"))
        self.assertEqual(self.outcome(self.d.approve(PIN, CALM, veto=True)), ("accepted", "hold_and_alert"))

    def test_wrong_pin_gives_nothing_and_locks_after_five(self):
        for _ in range(5):
            self.assertIsNone(self.d.approve("AAAAAAAA", CALM))
        self.assertEqual(self.d.mcu.state, ys.SoftMcu.LOCKED)
        self.assertIsNone(self.d.approve(PIN, CALM))  # even the right PIN, until power cycle

    def test_presses_without_grip_do_not_count(self):
        self.d.mcu.begin("PAY 10 GBP TO ALICE", bytes(32))
        self.d.mcu.type_pin(PIN, grip=False)
        self.assertIsNone(self.d.mcu.unlock_salt())

    def test_session_times_out(self):
        self.d.mcu.begin("PAY 10 GBP TO ALICE", bytes(32), now_ms=0)
        t = self.d.mcu.type_pin(PIN)
        self.d.mcu.tick(t + 91000)
        self.assertIsNone(self.d.mcu.seal(0))

    def test_tag_is_one_shot(self):
        self.d.approve(PIN, CALM)
        self.assertIsNone(self.d.mcu.seal(0))
        self.assertIsNone(self.d.mcu.unlock_salt())


class RootedLinuxTest(unittest.TestCase):
    """The attacker controls the Linux side and waits for a genuine approval."""

    def setUp(self):
        self.d = Device()
        self.d.verifier.address_book[MALLORY] = "MALLORY"

    def test_cannot_swap_request_under_a_real_touch(self):
        # User sees and approves "PAY 10 GBP TO ALICE". Malware gets the YubiKey and ML-DSA key
        # to sign a payment to MALLORY instead, and reuses the STM32's tag.
        good = self.d.approve(PIN, CALM)
        evil_req = {**REQ, "to": MALLORY}
        nonce = self.d.verifier.new_nonce()
        book = {**BOOK, MALLORY: "MALLORY"}
        core, _ = ys.build_core(evil_req, book, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        salt = ys.hmac256(self.d.mcu._k_pin, b"unlock-salt")  # malware cached it earlier
        key = ys.unlock(self.d.store, self.d.yk.hmac_secret(salt))
        forged = ys.make_envelope(core, self.d.yk.assert_(RP, digest), ys.unb64(good["mcu"]), ys.GENESIS, key)
        r = self.d.verifier.check(forged, evil_req)
        self.assertEqual(r["internal"], "reject")
        self.assertIn("buttons and display", r["reason"])

    def test_cannot_show_one_thing_and_sign_another(self):
        # Malware asks the STM32 to show ALICE's payment but hands it the digest of MALLORY's.
        evil_req = {**REQ, "to": MALLORY}
        book = {**BOOK, MALLORY: "MALLORY"}
        nonce = self.d.verifier.new_nonce()
        core, _ = ys.build_core(evil_req, book, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        self.d.mcu.begin("PAY 10 GBP TO ALICE", digest)
        self.d.mcu.type_pin(PIN)
        salt = self.d.mcu.unlock_salt()
        key = ys.unlock(self.d.store, self.d.yk.hmac_secret(salt))
        tag = self.d.mcu.seal(10)
        forged = ys.make_envelope(core, self.d.yk.assert_(RP, digest), tag, ys.GENESIS, key)
        self.assertEqual(self.d.verifier.check(forged, evil_req)["internal"], "reject")

    def test_cannot_turn_duress_into_normal(self):
        duress = self.d.approve(DURESS_PIN, CALM)
        normal = self.d.approve(PIN, CALM)
        frank = copy.deepcopy(duress)
        frank["mcu"] = normal["mcu"]  # tag from another approval
        self.assertEqual(self.d.verifier.check(frank, REQ)["internal"], "reject")


class ProtocolTest(unittest.TestCase):
    def setUp(self):
        self.d = Device()

    def test_swapped_destination_rejected(self):
        self.d.verifier.address_book[MALLORY] = "MALLORY"
        env = self.d.approve(PIN, CALM)
        self.assertEqual(self.d.verifier.check(env, {**REQ, "to": MALLORY})["internal"], "reject")

    def test_replay_rejected(self):
        env = self.d.approve(PIN, CALM)
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "execute")
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "reject")

    def test_expiry_is_timed_by_the_guardian(self):
        env = self.d.approve(PIN, CALM)
        self.assertEqual(self.d.verifier.check(env, REQ, now=time.time() + 600)["internal"], "reject")

    def test_no_touch_rejected(self):
        env = self.d.approve(PIN, CALM)
        ad = bytearray(ys.unb64(env["yk"]["authenticator_data"]))
        ad[32] = 0  # clear the user-present flag
        env["yk"]["authenticator_data"] = ys.b64(bytes(ad))
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "reject")

    def test_other_service_rejected(self):
        env = self.d.approve(PIN, CALM)
        self.d.verifier.rp_id = "evil.example"
        self.assertEqual(self.d.verifier.check(env, REQ)["internal"], "reject")

    def test_danger_actions_always_need_a_second_approver(self):
        req = {"action": "add_address", "label": "BOB", "address": MALLORY}
        env = self.d.approve(PIN, CALM, request=req)
        self.assertEqual(self.d.verifier.check(env, req)["internal"], "need_second_approver")

    def test_audit_log_tamper_evident(self):
        for _ in range(3):
            self.d.approve(PIN, CALM)
        pub = self.d.verifier.members["jonah"].pq_pub
        self.assertTrue(ys.log_verify(self.d.log, pub))
        self.d.log[1]["who"] = "someone_else"
        self.assertFalse(ys.log_verify(self.d.log, pub))

    def test_merkle_root_changes_with_any_entry(self):
        leaves = [os.urandom(32).hex() for _ in range(5)]
        root = ys.merkle_root(leaves)
        leaves[3] = os.urandom(32).hex()
        self.assertNotEqual(root, ys.merkle_root(leaves))


class DisplayTest(unittest.TestCase):
    def test_destination_shown_by_name(self):
        self.assertEqual(ys.render_display(REQ, BOOK), "PAY 10 GBP TO ALICE")

    def test_lookalike_address_refused(self):
        with self.assertRaises(ValueError):  # same ending as ALICE, but not in the book
            ys.render_display({**REQ, "to": MALLORY}, BOOK)

    def test_duplicate_names_refused(self):
        with self.assertRaises(ValueError):
            ys.render_display(REQ, {ALICE: "ALICE", MALLORY: "ALICE"})

    def test_hidden_or_unknown_fields_refused(self):
        for bad in ({**REQ, "memo": "x"}, {"action": "mystery"}, {"action": "transfer", "amount": "10"},
                    {**REQ, "amount": "10 GBP TO BOB"}, {**REQ, "amount": "-5"}, {**REQ, "asset": "G B"}):
            with self.assertRaises(ValueError):
                ys.render_display(bad, BOOK)

    def test_new_address_shown_in_full(self):
        text = ys.render_display({"action": "add_address", "label": "BOB", "address": MALLORY}, BOOK)
        self.assertEqual(text.replace(" ", "").split("=")[1], MALLORY)
        self.assertLessEqual(len(text), ys.MAX_TEXT)

    def test_different_requests_never_share_a_display(self):
        book = {ALICE: "ALICE", MALLORY: "MALLORY"}
        reqs = [REQ, {**REQ, "amount": "100"}, {**REQ, "asset": "ETH"}, {**REQ, "to": MALLORY},
                {"action": "delegate", "to": ALICE}, {"action": "login", "service": "dash", "user": "jonah"},
                {"action": "login", "service": "dash", "user": "Jonah"}]
        self.assertEqual(len({ys.render_display(r, book) for r in reqs}), len(reqs))


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

    def press_lines(self, pin, t=1000, grip=1):
        lines = []
        for ch in pin:
            lines.append(f"down {ch.upper()} {grip} {t}")
            t += 1000 if ch.islower() else 150
            lines.append(f"up {t}")
            t += 250
        lines.append(f"tick {t + 1500}")
        return lines

    def scenario(self, pin, score, veto, text="PAY 10 GBP TO ALICE"):
        k = os.urandom(32)
        k_pin, k_tag = ys.mcu_keys(k)
        digest = os.urandom(32)
        lines = [f"provision {k.hex()} {ys.pin_tag(k_pin, PIN).hex()} {ys.pin_tag(k_pin, DURESS_PIN).hex()} {len(PIN)}",
                 f"begin {digest.hex()} 0 {text}", *self.press_lines(pin), "salt", f"seal {score} {veto}", "seal 0 0"]
        out = self.run_cpp(lines)
        soft = ys.SoftMcu(k, PIN, DURESS_PIN)
        soft.begin(text, digest)
        soft.type_pin(pin)
        salt, tag = soft.unlock_salt(), soft.seal(score, bool(veto))
        return out[-3], out[-2], out[-1], salt, tag, k_tag, digest

    def test_sha256_matches(self):
        for msg in ("abc", "PAY 10 GBP TO ALICE", "x" * 200):
            self.assertEqual(self.run_cpp([f"sha {msg}"])[0], ys.sha256(msg.encode()).hex())

    def test_tags_match_python_for_every_path(self):
        for pin in (PIN, DURESS_PIN):
            for score in (-1, 0, 39, 40, 69, 70, 100, 101):
                for veto in (0, 1):
                    c_salt, c_tag, c_again, salt, tag, k_tag, digest = self.scenario(pin, score, veto)
                    self.assertEqual((c_salt, c_tag), (salt.hex(), tag.hex()), (pin, score, veto))
                    self.assertEqual(c_again, "-")  # one-shot
                    want = ys.decide_status(pin == DURESS_PIN, score, bool(veto))
                    self.assertEqual(tag, ys.mcu_tag(k_tag, want, ys.sha256(b"PAY 10 GBP TO ALICE"), digest))

    def test_wrong_pin_and_bad_text(self):
        c_salt, c_tag, _, salt, tag, _, _ = self.scenario("CCCCCCCC", 0, 0)
        self.assertEqual((c_salt, c_tag, salt, tag), ("-", "-", None, None))
        out = self.run_cpp([f"provision {'00' * 32} {'00' * 32} {'00' * 32} 8", f"begin {'00' * 32} 0 " + "x" * 97,
                            f"begin {'00' * 32} 0 tab\there"])
        self.assertEqual(out[1:], ["0", "0"])

    def test_lockout_after_five_wrong_pins(self):
        k = os.urandom(32)
        k_pin, _ = ys.mcu_keys(k)
        lines = [f"provision {k.hex()} {ys.pin_tag(k_pin, PIN).hex()} {ys.pin_tag(k_pin, DURESS_PIN).hex()} 8"]
        for _ in range(5):
            lines += [f"begin {'11' * 32} 0 HELLO", *self.press_lines("AAAAAAAA")]
        lines += ["state", f"begin {'11' * 32} 0 HELLO"]
        out = self.run_cpp(lines)
        self.assertEqual(out[-2:], ["3 0", "0"])


# ---------------------------------------------------------------- the Linux flow (approve.py) against a fake STM32
import json  # noqa: E402

import approve as ap  # noqa: E402


class FakeBridge:
    """Stands in for the Bridge: wraps SoftMcu, and a scripted person types `pin` when asked."""

    def __init__(self, mcu, pin, grip=True):
        self.mcu, self.pin, self.grip, self.typed, self.calls = mcu, pin, grip, False, []

    def call(self, name, *args):
        self.calls.append(name)
        m = self.mcu
        if name == "begin_approval":
            self.typed = False
            return "1" if m.begin(args[0], bytes.fromhex(args[1])) else "0"
        if name == "get_unlock_salt":
            s = m.unlock_salt()
            return s.hex() if s else "-"
        if name == "get_features":
            if not self.typed and m.state == m.PIN_ENTRY:  # the person presses the PIN while we poll
                self.typed = True
                m.type_pin(self.pin, grip=self.grip)
            return json.dumps({"temp_c": 31.0, "humidity": 45.0, "shake_rms": 0.01, "touch": 1,
                               "moisture": 400, "state": m.state, "pin_count": 0})
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
        guardian.verifier.address_book.update(BOOK)
        guardian.outcomes.clear()
        guardian.RP_ID = RP
        guardian.verifier.rp_id = RP
        self.guardian_mod = guardian
        client = TestClient(guardian.app)
        self.guardian = ap.HttpGuardian(lambda path, body: client.post(path, json=body).json())
        self.k_mcu = os.urandom(32)
        self.mcu = ys.SoftMcu(self.k_mcu, PIN, DURESS_PIN)
        self.yk = ys.SoftYubiKey()
        self.tmp = tempfile.mkdtemp()
        self.state = ap.DeviceState(os.path.join(self.tmp, "device.json"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def enrol(self):
        body = ap.enrol(bridge=FakeBridge(self.mcu, PIN), yk=self.yk, guardian=self.guardian, state=self.state,
                        user="jonah", device="unoq-1", rp_id=RP, sleep=lambda s: None)
        body["k_tag"] = ys.b64(ys.mcu_keys(self.k_mcu)[1])
        self.assertEqual(self.guardian.enrol("jonah", body), {"ok": True})

    def approve(self, pin, gemini_fn=lambda w: CALM, timeout_s=90, **kw):
        return ap.approve(bridge=FakeBridge(self.mcu, pin, **kw), yk=self.yk, guardian=self.guardian,
                          state=self.state, request=REQ, address_book=BOOK, rp_id=RP,
                          gemini_fn=gemini_fn, sleep=lambda s: None, timeout_s=timeout_s)

    def test_enrol_then_calm_and_duress_look_identical_to_the_requester(self):
        self.enrol()
        a, b = self.approve(PIN), self.approve(DURESS_PIN)
        self.assertEqual((a["public"], b["public"]), ("accepted", "accepted"))
        self.assertEqual([o["internal"] for o in self.guardian_mod.outcomes], ["execute", "hold_and_alert"])

    def test_state_survives_a_restart(self):
        self.enrol()
        self.approve(PIN)
        self.state = ap.DeviceState(self.state.path)  # reload from disk, as after a power cut
        self.assertEqual(self.approve(PIN)["public"], "accepted")
        self.assertTrue(ys.log_verify(self.state.data["log"], ys.mldsa.MLDSA65PublicKey.from_public_bytes(
            ys.unb64(self.state.data["pq_pub"]))))

    def test_gemini_down_means_hold(self):
        self.enrol()
        self.assertEqual(self.approve(PIN, gemini_fn=lambda w: None)["public"], "accepted")
        self.assertEqual(self.guardian_mod.outcomes[-1]["internal"], "hold_and_alert")

    def test_missing_sensor_is_a_veto(self):
        self.assertTrue(ap.onboard_veto([]))
        self.assertTrue(ap.onboard_veto([{"temp_c": None, "humidity": 40, "shake_rms": 0, "moisture": 1}]))
        self.assertFalse(ap.onboard_veto([{"temp_c": 30, "humidity": 40, "shake_rms": 0.1, "moisture": 400}]))

    def test_wrong_pin_signs_nothing_and_gemini_is_never_asked(self):
        self.enrol()
        asked = []
        with self.assertRaises(ap.Refused):
            self.approve("AAAAAAAA", gemini_fn=lambda w: asked.append(1))
        self.assertEqual((asked, len(self.guardian_mod.outcomes)), ([], 0))

    def test_no_grip_signs_nothing(self):
        self.enrol()
        with self.assertRaises(ap.Refused):
            self.approve(PIN, grip=False, timeout_s=0.2)

    def test_other_yubikey_cannot_unlock_the_key(self):
        self.enrol()
        self.yk = ys.SoftYubiKey()
        with self.assertRaises(ap.Refused):
            self.approve(PIN)

    def test_linux_never_calls_anything_that_reveals_the_pin(self):
        self.enrol()
        fb = FakeBridge(self.mcu, DURESS_PIN)
        ap.approve(bridge=fb, yk=self.yk, guardian=self.guardian, state=self.state, request=REQ,
                   address_book=BOOK, rp_id=RP, gemini_fn=lambda w: CALM, sleep=lambda s: None)
        self.assertLessEqual(set(fb.calls), {"begin_approval", "get_unlock_salt", "get_features", "seal_approval"})


if __name__ == "__main__":
    unittest.main()
