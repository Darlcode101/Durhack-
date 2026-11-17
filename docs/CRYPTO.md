# YuSeal: the crypto

Back to the [README](../README.md) or [how it works](HOW-IT-WORKS.md).

YuSeal is the approval format. The code is in [`app/python/yuseal.py`](../app/python/yuseal.py) (envelope, verifier, owner check, key store, audit log) and [`app/sketch/yuseal_mcu.h`](../app/sketch/yuseal_mcu.h) (the STM32 core, SHA-256 and HMAC only, about 1 KB of RAM). It only needs Python's `cryptography` 48 or newer, which has ML-DSA built in. The suite name in every envelope is `YS3`.

## Three proofs

Every approval carries three proofs made by three different pieces of hardware. The verifier checks all of them, and someone with two still can't approve.

| Proof | Made by | What it shows |
|---|---|---|
| ES256 signature | YubiKey 5 (FIDO2) | this person's key signed this exact request |
| HMAC-SHA-256 tag | the STM32 | a real click with a palm on the grip happened just before, for this request and this sensor summary, plus the hidden status |
| ML-DSA-65 signature | the Linux side | this device sealed all of the above at this point in the log, in a way a quantum computer can't forge |

The tag is:

```
HMAC(K_TAG, "YS3/tag" | status | request digest | click age (2 bytes) | grip (1 byte) | SHA-256("YS3/features" | ten int32 features))
```

## Keys

`tools/provision.py` makes one 32-byte secret, `K_MCU`, which goes into the sketch as `secrets.h` and never touches the Linux side. The STM32 derives three keys from it:

- the release key, which makes the unlock salt
- the tag key, which makes the tags (the verifier gets a copy so it can check them)
- the profile key, which encrypts the user's baseline, training rows and model on the board

The ML-DSA-65 key lives on Linux, wrapped with AES-256-GCM under a key derived (HKDF-SHA-256) from the YubiKey's `hmac-secret` for the STM32's salt. The STM32 only releases that salt after a real click, so a copied key file is useless without both the YubiKey and the board. The salt is the same whatever the outcome, so Linux learns nothing about the status from it.

## The STM32 core

The whole argument rests on this small piece, so it's kept short enough to check by hand. It:

1. timestamps each click from the switch tap and records whether the palm was on the grip
2. arms only for a click under 1.5 seconds old with a palm on the grip, once per click, at most 10 times per 10 minutes
3. releases the unlock salt while armed
4. attests the click age, grip and sensor summary
5. takes the model's score (a whole number 0 to 100) and a veto flag, decides the status, and returns one tag. The session times out after 30 seconds.

Anything missing or out of range means duress. The C++ and the Python twin (`SoftMcu`) are tested against each other byte for byte.

## The envelope

```json
{
  "core":   {"v": 3, "suite": "YS3", "type": "transfer", "rp": "yuduino.local",
             "who": "jonah", "device": "unoq-1", "request": "<SHA-256 of the request>",
             "nonce": "<from the verifier>"},
  "yk":     {"authenticator_data": "...", "client_data_json": "...", "signature": "..."},
  "mcu":    "<32-byte tag>",
  "attest": "<click age, grip and sensor summary>",
  "prev":   "<hash of the previous audit log entry>",
  "pq_sig": "<ML-DSA-65 over all of the above>"
}
```

Moving any part from one envelope to another breaks at least one signature. There are tests for each case.

## What the verifier checks

`Verifier.check()` does these in order, and any failure returns the same plain "unavailable":

1. the user isn't locked
2. the suite and service ID are right
3. the request hash matches the request it's about to run
4. the nonce was issued by this verifier, hasn't been used, and is under 2 minutes old
5. the YubiKey signature and the ML-DSA signature verify
6. the click was under 1.5 seconds old with a palm on the grip
7. the tag matches exactly one of normal, step-up or duress
8. the owner check on the attested sensor summary (see [HOW-IT-WORKS.md](HOW-IT-WORKS.md#the-owner-check))

The verifier can make an outcome stricter but never more lenient. Under duress it answers "accepted" like a normal approval and reports the real verdict only to the customer's own system.

## Audit chain

Each envelope includes the hash of the previous log entry, and the log entry is signed with ML-DSA. Editing, deleting or reordering an entry breaks the chain, and there's a test for that. The log stores envelope hashes, not statuses, so reading it doesn't reveal which approvals were duress.

## Weak spots

- **No trusted display.** Malware on the laptop can show one request and send another.
- **Click piggybacking.** The STM32 sees a click, not which click. Malware could arm its own request in the 1.5 second window after an ordinary click.
- **`K_MCU` is in STM32 flash.** Anyone who can read the chip gets it unless the debug port is locked. The UNO Q has no certified secure element.
- **The YubiKey half is classical.** A quantum attacker could forge the ES256 signature, but would still need the ML-DSA key and a tag.
- **The arm rate limit is in RAM**, so a power cycle resets it. The verifier's lock after repeated failures covers that.
- **Linux passes the score.** A compromised Linux side could report "calm". The STM32's veto on missing or impossible sensor readings is the only guard against that.
- **It's hackathon code.** Bugs are far more likely than a break in ML-DSA.
