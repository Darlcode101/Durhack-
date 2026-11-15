"""A tiny reference verifier for trying YuDuino from the command line. The customer's own system
would call `yuseal.Verifier` directly; this only shows how.

    python3 verify_cli.py enrol <user> <package.json>     register a person from `main.py enrol`
    python3 verify_cli.py nonce                           print a one-time nonce to send with a request
    python3 verify_cli.py check <envelope.json> <request.json>

State lives in the JSON file named by VERIFIER_STATE (default verifier_state.json).
"""
import json
import os
import sys

import yuseal as ys

STATE = os.environ.get("VERIFIER_STATE", "verifier_state.json")
RP_ID = os.environ.get("FIDO_RP_ID", "yuduino.local")


def load() -> ys.Verifier:
    if os.path.exists(STATE):
        return ys.Verifier.from_json(open(STATE).read())
    return ys.Verifier(RP_ID)


def save(v: ys.Verifier):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write(v.to_json())
    os.chmod(tmp, 0o600)
    os.replace(tmp, STATE)


def main(argv):
    if len(argv) >= 4 and argv[1] == "enrol":
        v = load()
        v.enrol(argv[2], json.load(open(argv[3])))
        save(v)
        print("enrolled", argv[2])
    elif len(argv) == 2 and argv[1] == "nonce":
        v = load()
        n = v.new_nonce()
        save(v)
        print(n)
    elif len(argv) == 4 and argv[1] == "check":
        v = load()
        r = v.check(json.load(open(argv[2])), json.load(open(argv[3])))
        save(v)
        print(json.dumps(r, indent=2))
        return 0 if r["ok"] else 1
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
