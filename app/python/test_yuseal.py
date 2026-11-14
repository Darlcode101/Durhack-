"""Run on a laptop or the UNO Q:  python3 -m unittest test_yuseal -v   (from app/python)

Walks the whole YuSeal flow with a software stand-in for the YubiKey.
"""
import copy
import os
import time
import unittest

import yuseal as ys

RP = "guardian.yuduino.local"
REQ = {"action": "transfer", "amount": "10", "asset": "GBP", "to": "0xA1B2C3D4E5F6a1f3"}


class Setup:
    def __init__(self):
        self.yk = ys.SoftYubiKey()
        self.device_secret = os.urandom(32)
        self.store, pq = ys.create_keystore(self.yk, self.device_secret, "ABCA", "CBAC")
        g_kem, g_x = ys.mlkem.MLKEM768PrivateKey.generate(), ys.x25519.X25519PrivateKey.generate()
        k0, msg = ys.seal_root_device_side(g_kem.public_key(), g_x.public_key())
        self.device_chain = ys.SealChain(k0)
        self.verifier = ys.Verifier(RP)
        guardian_chain = ys.SealChain(ys.seal_root_guardian_side(msg, g_kem, g_x))
        self.verifier.members["jonah"] = ys.Member(self.yk.public_key, pq.public_key(), guardian_chain)
        self.log = []

    def approve(self, pin, gemini, request=REQ, veto=False):
        nonce = self.verifier.new_nonce()
        secret = self.yk.hmac_secret(ys.pin_salt(pin, ys.unb64(self.store["salt"])))
        mode, key = ys.unlock(self.store, secret, self.device_secret)
        if mode is None:
            return None
        core = ys.build_core(request, service=RP, approver="jonah", device="unoq-1", nonce=nonce)
        digest = ys.core_digest(core)
        assertion = self.yk.assert_(RP, digest)  # the touch
        status = ys.decide_status(pin_mode=mode, gemini=gemini, onboard_veto=veto)
        sealed = self.device_chain.seal(status, {"score": (gemini or {}).get("score")}, digest)
        prev = self.log[-1]["hash"] if self.log else ys.GENESIS
        env = ys.make_envelope(core, assertion, sealed, prev, key)
        ys.log_append(self.log, env, key)
        return env


CALM = {"duress": False, "score": 0.1, "reasons": []}
SCARED = {"duress": True, "score": 0.9, "reasons": ["tremor", "second face"]}


class YuSealTest(unittest.TestCase):
    def setUp(self):
        self.s = Setup()

    def test_calm_approval_executes(self):
        env = self.s.approve("ABCA", CALM)
        r = self.s.verifier.check(env, REQ)
        self.assertEqual((r["public"], r["internal"]), ("accepted", "execute"))

    def test_duress_pin_looks_identical_but_holds(self):
        normal = self.s.approve("ABCA", CALM)
        duress = self.s.approve("CBAC", CALM)
        # Same structure and sizes: an observer can't tell them apart. (The YubiKey's ECDSA
        # signature varies by a byte or two at random in BOTH modes, so it's left out here.)
        self.assertEqual(normal.keys(), duress.keys())
        for k in ("core", "sealed", "pq_sig"):
            self.assertEqual(len(ys.canonical(normal[k])), len(ys.canonical(duress[k])), k)
        self.assertEqual(self.s.verifier.check(normal, REQ)["internal"], "execute")
        r = self.s.verifier.check(duress, REQ)
        self.assertEqual((r["public"], r["internal"]), ("accepted", "hold_and_alert"))

    def test_gemini_flags_duress(self):
        r = self.s.verifier.check(self.s.approve("ABCA", SCARED), REQ)
        self.assertEqual((r["public"], r["internal"]), ("accepted", "hold_and_alert"))

    def test_fail_closed_when_gemini_missing_or_malformed(self):
        for bad in (None, {}, {"duress": False}, {"duress": False, "score": "nan?"},
                    {"duress": False, "score": -1}):
            self.assertEqual(ys.decide_status(pin_mode="normal", gemini=bad, onboard_veto=False), ys.DURESS)

    def test_wrong_pin_unlocks_nothing(self):
        self.assertIsNone(self.s.approve("AAAA", CALM))

    def test_swapped_destination_rejected(self):
        env = self.s.approve("ABCA", CALM)
        evil = {**REQ, "to": "0xATTACKER000000"}
        self.assertEqual(self.s.verifier.check(env, evil)["internal"], "reject")

    def test_replay_rejected(self):
        env = self.s.approve("ABCA", CALM)
        self.assertEqual(self.s.verifier.check(env, REQ)["internal"], "execute")
        self.assertEqual(self.s.verifier.check(env, REQ)["internal"], "reject")

    def test_expired_rejected(self):
        env = self.s.approve("ABCA", CALM)
        self.assertEqual(self.s.verifier.check(env, REQ, now=time.time() + 600)["internal"], "reject")

    def test_flipping_sealed_box_breaks_pq_signature(self):
        a = self.s.approve("ABCA", CALM)
        b = self.s.approve("CBAC", CALM)
        frank = copy.deepcopy(b)
        frank["sealed"] = a["sealed"]  # try to swap a "normal" box into a duress approval
        self.assertEqual(self.s.verifier.check(frank, REQ)["internal"], "reject")

    def test_no_touch_rejected(self):
        env = self.s.approve("ABCA", CALM)
        ad = bytearray(ys.unb64(env["yk"]["authenticator_data"]))
        ad[32] = 0  # clear the user-present flag
        env["yk"]["authenticator_data"] = ys.b64(bytes(ad))
        self.assertEqual(self.s.verifier.check(env, REQ)["internal"], "reject")

    def test_forward_secrecy_of_sealed_status(self):
        env = self.s.approve("CBAC", CALM)  # duress
        # An attacker who seizes the device afterwards has only the advanced chain key.
        # Even pretending the counter is still at the old position, the old key can't be rebuilt.
        seized = ys.SealChain(self.s.device_chain.key, env["sealed"]["ctr"] - 1)
        with self.assertRaises(ys.InvalidTag):
            seized.open(env["sealed"], ys.core_digest(env["core"]))

    def test_unknown_action_refused_on_device(self):
        with self.assertRaises(ValueError):
            ys.render_display({"action": "mystery"})

    def test_audit_log_tamper_evident(self):
        for _ in range(3):
            self.s.approve("ABCA", CALM)
        pub = self.s.verifier.members["jonah"].pq_pub
        self.assertTrue(ys.log_verify(self.s.log, pub))
        self.s.log[1]["who"] = "someone_else"
        self.assertFalse(ys.log_verify(self.s.log, pub))

    def test_merkle_root_changes_with_any_entry(self):
        leaves = [os.urandom(32).hex() for _ in range(5)]
        root = ys.merkle_root(leaves)
        leaves[3] = os.urandom(32).hex()
        self.assertNotEqual(root, ys.merkle_root(leaves))


if __name__ == "__main__":
    unittest.main()
