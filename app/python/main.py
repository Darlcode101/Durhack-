"""Linux-side entry point. Everything runs on the UNO Q. YuDuino is only the authenticator: the
customer's own system sends a request and a nonce, and verifies the envelope that comes back
(see yuseal.Verifier and verify_cli.py).

    python3 main.py [--yk MODE] enrol <user>     once: YubiKey, one click, post-quantum key.
                                                 Prints the enrolment package (JSON) for the verifier.
    python3 main.py [--yk MODE] approve <user> '<request json>' --nonce <nonce>
                                                 one approval; prints the envelope (JSON). e.g.
        '{"action":"transfer","amount":"10","asset":"GBP","to":"0xA1..."}'
    python3 main.py learn <user> [minutes]       learn the user's normal (all day if no minutes): the STM32's
                                                 per-hour baseline plus one private training row a minute
    python3 main.py seed <user> [minutes]        the same, 15 minutes by default: a quick seeding for a demo
    python3 main.py import-model <user> <file.eim>   install the generic Edge Impulse model into the user's encrypted profile

--yk MODE (or env YK_MODE): fido (default, no touch), fido-touch, or hmac-sha1 (fallback, see
tools/setup_yk_hmac.py). Run `python3 tools/yk_probe.py` first to see which one your key allows.

Run over SSH on the board, with the App Lab sensor app running (it carries the STM32 calls via
app/dashboard/applab_relay.py). There is nothing to type or press but the mouse's own click: it
works like any mouse. See docs/HOW-IT-WORKS.md.
"""
import json
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import requests

import approve as ap
import userprofile as prof
import camera
import yuseal as ys
from bridge import StmBridge
from edge_model import edge_score
from yubikey_auth import make_yubikey

RP_ID = os.environ.get("FIDO_RP_ID", "yuduino.local")
STATE_PATH = os.environ.get("DEVICE_STATE", os.path.join(os.path.dirname(__file__), "device.json"))


def model_fn(window, context=None, user=None):
    """The transaction's duress check, all on the board. Prefer the live dashboard's (the learned
    baselines, the camera tie-break, the Edge Impulse model when the sensors are unsure); it returns
    the same format as edge_model. If the dashboard isn't running, ask that person's Edge Impulse
    model directly. No model and no dashboard means no verdict, which fails closed to duress."""
    try:
        r = requests.post(os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8080") + "/api/assess",
                          params={"label": "approval", "seconds": 2}, timeout=20)
        if r.status_code == 200 and "duress_score" in r.json():
            return r.json()
    except Exception:
        pass
    if not window:
        return None
    _, faces = camera.grab()
    profile = prof.Profile.from_bridge(StmBridge())
    return edge_score(window, {**(context or {}), "faces": faces}, user, profile)


def _progress(lr):
    print(f"  {lr.added} samples, {lr.rows} minute rows", flush=True)


def main():
    argv = sys.argv[1:]
    if "--yk" in argv:  # --yk fido (default) | fido-touch | hmac-sha1
        i = argv.index("--yk")
        os.environ["YK_MODE"] = argv[i + 1]
        del argv[i:i + 2]
    nonce = None
    if "--nonce" in argv:
        i = argv.index("--nonce")
        nonce = argv[i + 1]
        del argv[i:i + 2]
    cmds = ("enrol", "approve", "learn", "seed", "import-model")
    if len(argv) < 2 or argv[0] not in cmds or (argv[0] == "approve" and (len(argv) < 3 or not nonce)) \
            or (argv[0] == "import-model" and len(argv) < 3):
        sys.exit(__doc__)
    if argv[0] in ("learn", "seed", "import-model"):
        import learner
        user, profile = argv[1], prof.Profile.from_bridge(StmBridge())
        if argv[0] == "import-model":
            profile.import_model(user, argv[2])
            print(f"encrypted into {profile.dir}; now delete the plaintext {argv[2]}")
        else:   # learn <user> [minutes]   or   seed <user> [minutes]  (a quick 15-minute seeding)
            minutes = float(argv[2]) if len(argv) > 2 else (15.0 if argv[0] == "seed" else None)
            n = profile.restore_baseline(StmBridge())
            print(f"learning{'' if minutes is None else f' for {minutes:g} min'} (restored {n}/24 hours). "
                  "Use the mouse normally with a hand on it.", flush=True)
            lr = learner.Learner(StmBridge(), profile)
            try:
                lr.run(minutes, _progress)
            except KeyboardInterrupt:
                pass
            print(f"saved: {lr.added} samples, {lr.rows} minute rows")
        return
    state = ap.DeviceState(STATE_PATH)
    tools_out = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "out")
    if argv[0] == "enrol":
        user = argv[1]
        pkg = ap.enrol(bridge=StmBridge(), yk=make_yubikey(), state=state, user=user, device="unoq-1", rp_id=RP_ID)
        pkg["k_tag"] = json.load(open(os.path.join(tools_out, "tag_key.json")))["k_tag"]
        if os.environ.get("YK_MODE") == "hmac-sha1":
            pkg["yk_hmac_key"] = json.load(open(os.path.join(tools_out, "yk_hmac_key.json")))["yk_hmac_key"]
        print(json.dumps(pkg))  # public data plus the tag key: give it to the verifier over a trusted channel
    else:
        yk = make_yubikey(ys.unb64(state.data["credential"]))
        out = ap.approve(bridge=StmBridge(), yk=yk, state=state, request=json.loads(argv[2]), nonce=nonce,
                         rp_id=RP_ID, model_fn=lambda w, c=None: model_fn(w, c, user))
        print(json.dumps(out["envelope"]))  # the customer's verifier checks this


if __name__ == "__main__":
    main()
