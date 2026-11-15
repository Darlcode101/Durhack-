# YuDuino cryptography test cases

Test cases for the **YuSeal cryptography only** ([CRYPTO.md](CRYPTO.md)): the three proofs (YubiKey, STM32 tag, ML-DSA-65), the key store, the nonce, the reference verifier's checks and the audit log. Sensors, the dashboard, the Edge Impulse model's training and the owner check are not covered here. The one exception: duress is judged only at the moment of a transaction (cases 2.11 and 5.8). Short flash steps are in [TESTING.md](TESTING.md).

Tick a case only when you saw the expected result. Write the **result, who and when** in the last column, and the exact error text for any failure. **Result key:** `P` pass, `F` fail, `-` not run.

**Status on 2026-11-15 morning:** group 1 is automated and passes on a laptop (57 tests). Groups 2 to 7 have not been run on the board.

---

## 1. Automated (laptop, no hardware)

Run: `cd app/python && python3 -m unittest test_yuseal -v`. Each row names the tests in `test_yuseal.py`.

| ID | Case | Proves | Result |
|---|---|---|---|
| 1.0 | Fresh clone, new venv, `pip install -r app/python/requirements.txt`, tests say `OK` (57) | Someone else can run it | |
| 1.1 | `test_calm_owner_approval_executes`, `test_no_touch_is_needed` | The happy path verifies all three proofs, with no YubiKey touch | |
| 1.2 | `test_duress_looks_identical_from_outside_but_holds`, `test_linux_learns_nothing_about_the_status` | The tag hides the status (normal, step-up, duress): same sizes and same salt; only the verifier can read it | |
| 1.3 | `test_model_duress_and_step_up`, `test_fail_closed` | The decision rule: a missing, garbled or out-of-range score, or a veto, means duress | |
| 1.4 | `test_nothing_without_a_click`, `test_click_is_single_use`, `test_no_palm_on_the_grip_no_arm`, `test_session_times_out`, `test_tag_is_one_shot`, `test_rate_limit` | The STM32 releases the salt and tag only for a fresh physical click, once, within its limits | |
| 1.5 | `test_cannot_swap_request_under_a_real_click`, `test_cannot_arm_for_another_digest_without_a_fresh_click` | A rooted Linux side can't change what a click approves | |
| 1.6 | `test_cannot_turn_duress_into_normal`, `test_cannot_change_the_attested_sensor_summary`, `test_cannot_backdate_the_click` | A tag can't be moved, edited or back-dated | |
| 1.7 | `ProtocolTest`: swapped destination, replay, expiry, other service, audit log, Merkle root | Request binding, one-time nonce timed by the verifier, service binding, tamper-evident log | |
| 1.8 | `HmacSha1FallbackTest`, `test_hmac_sha1_mode_through_the_whole_stack` | The no-touch fallback works and can't be used to downgrade a FIDO2 member (or the reverse) | |
| 1.9 | `test_verifier_state_round_trips_through_json` | The reference verifier's state (members, nonces, baseline) survives being saved and loaded | |
| 1.10 | `CppCoreTest` | The real STM32 C++ gives the same salt, tag and attestation bytes as the Python model, and refuses what it refuses | |
| 1.11 | `LinuxFlowTest`: wrong YubiKey can't unlock, state survives a restart, no click signs nothing | The Linux flow against a fake STM32 | |
| 1.14 | `HourBaselineTest`, `ProfileTest`, `LearnerTest`, `test_the_last_minute_is_kept_for_the_transaction_and_no_more`, `test_the_transaction_scores_the_last_minute_against_the_baseline`, `test_profile_key_matches`, `test_baseline_matches_python` | The per-hour rolling baseline (C++ and Python agree), the encrypted profile (wrong key or tampering refused), a 15-minute seeding giving a baseline and training rows, and the transaction scoring the last minute (and ignoring a stale one) | |
| 1.12 | `EdgeModelTest` | The Edge Impulse integration with a fake model: the input vector, the duress probability becoming the score, and a missing, faulty or nonsense model failing closed | |
| 1.13 | The same, 10 times in a row | Nothing depends on randomness or timing luck | |

## 2. The STM32 core on the board

The same C++ the laptop test compiled, now on the real chip.

| ID | Case | Steps | Expect | Result |
|---|---|---|---|---|
| 2.1 | It compiles for the UNO Q | App Lab with `app/sketch/` and `secrets.h` from `python3 tools/provision.py` | Builds and uploads. **Note every compile error text** | |
| 2.2 | Core on its own | `app/bringup/step4_core`, click with the palm on the grip | `armed`, then `sealed ...` once per click | |
| 2.3 | No palm | Click without touching the grip | `refused` | |
| 2.4 | One click, one arm | Trigger a second arm from the same click | `refused` | |
| 2.5 | Old click | Click, wait over 1.5 s, then arm | `refused` | |
| 2.6 | Salt only when armed | Call `get_unlock_salt` and `get_attest` with no click | Both answer `-` | |
| 2.7 | Same bytes as Python | Arm with a known digest and features, seal with score 10; compute the tag in Python with `ys.mcu_tag` and the same key | The tag matches byte for byte | |
| 2.8 | **Bridge String arguments** | `Bridge.call("arm_approval", "00"*32)` then `Bridge.call("seal_approval", "10", "0")` | Returns text, no argument error. If it errors, use the pack-into-one-string fix in `docs/BUILD-FLOW.md` §5 item 1 | |
| 2.9 | Same answer for every outcome | Seal with scores 0, 50 and 90, and with veto | Always a 64-hex-character tag, same salt each time | |
| 2.10 | Power cycle | Arm, power-cycle, ask for the salt | `-` (nothing survives a reboot) | |
| 2.11 | Duress is only judged at a transaction | Leave the app running idle for 5 minutes with the mouse in use, no approval started | No tag is made (`get_attest` and `seal_approval` answer `-`), no model run is counted, and no incident appears; the STM32 only ever decides a status inside an armed approval | |

## 3. The YubiKey

Run `python3 tools/yk_probe.py` on the board first. It prints which mode works.

| ID | Case | Expect | Result |
|---|---|---|---|
| 3.1 | Key found over the hub | Listed with `hmac-secret` (hub's own cable in the board, not the PD input) | |
| 3.2 | FIDO2 assertion with user presence off | `ok: UP flag = False` | |
| 3.3 | hmac-secret with user presence off | `ok, same secret each time: True` | |
| 3.4 | The assertion verifies | An assertion for challenge = SHA-256(core) passes `verify_yubikey_assertion` on the laptop, and fails if the challenge, service ID or one signature byte changes | |
| 3.5 | If 3.2 or 3.3 fails: touch path | `main.py --yk fido-touch` works with a tap (not zero input) | |
| 3.6 | If 3.2 or 3.3 fails: HMAC-SHA1 slot | `tools/setup_yk_hmac.py`, then `ykman otp calculate 2 <hex>` gives 40 hex characters with no blink; `main.py --yk hmac-sha1 enrol` works | |
| 3.7 | Wrong key | Enrol with one YubiKey, approve with another | `Refused: wrong YubiKey`, nothing signed | |
| 3.8 | No key plugged in | Approve with it unplugged | A clear error, nothing signed, nothing sent | |
| 3.9 | **Record the outcome** | Mode that works on our key: ______ . It decides whether we may say "zero touch" | |

## 4. The key store (the ML-DSA key at rest)

| ID | Case | Steps | Expect | Result |
|---|---|---|---|---|
| 4.0 | Seed and encrypted profile | `main.py seed jonah 15` with a hand on the mouse, then `grep` `app/python/profile/` for any readable number | A baseline and rows are saved; the files are `YP1` ciphertext only; a reboot restores the baseline | |
| 4.1 | Enrol | `main.py enrol jonah > package.json`, click once | `package.json` holds public data and the seed; `device.json` has a wrapped key, no plain key | |
| 4.2 | Plain key never on disk | `grep` the `device.json` and `.env` for the seed | Only the AES-GCM wrapped blob is stored | |
| 4.3 | Copied file is useless | Copy `device.json` to the laptop and try to unlock with another YubiKey | Fails (`unlock` returns nothing) | |
| 4.4 | Needs the click | Try to get the unlock salt from Linux with no click | `-`; the YubiKey secret can't be derived | |
| 4.5 | File permissions | `ls -l device.json` | Mode 600 | |
| 4.6 | Restart | Power-cycle the board, approve | Works; the key is unwrapped each time and not kept | |

## 5. The envelope and the verifier's checks

The reference verifier is a command line on the laptop: `python3 app/python/verify_cli.py enrol jonah package.json` once, `... nonce` for each approval, `... check envelope.json request.json` to read the result. Save the request you sent as `request.json`.

| ID | Case | Steps | Expect | Result |
|---|---|---|---|---|
| 5.1 | Real approval | `main.py approve jonah '<transfer>' --nonce <nonce> > envelope.json`, click within 5 s, then `verify_cli.py check` | `"public": "accepted"`, `"verdict": "normal"` | |
| 5.2 | All three proofs present | Print the envelope | `yk`, `mcu`, `attest` and `pq_sig` all present; `pq_sig` verifies with the enrolled ML-DSA public key | |
| 5.3 | Status stays hidden | Compare the envelope of a calm and a duress approval | Same keys, same sizes; `check` shows `"verdict": "normal"` vs `"duress"`, both `"public": "accepted"` | |
| 5.4 | No click | Run approve and do not click | Refused after about 5 s; no envelope is made | |
| 5.5 | Public answers | Compare what the requester sees for success, a bad signature, a wrong tag and a stale nonce | `accepted` for success (and duress); one identical plain `unavailable` for every failure | |
| 5.6 | No model | Stop the dashboard and install no model, approve | The approval completes and `check` shows `"verdict": "duress"` (fails closed) | |
| 5.7 | Tag key mismatch | Re-run `provision.py` on the laptop only, then approve | `check` rejects with "no valid tag" (the verifier's key must match the chip's) | |
| 5.8 | Only a transaction can raise duress | Use the mouse normally (shaky, sweaty, a second person nearby) with no approval running, then run `verify_cli.py nonce` and look at `verifier_state.json` | Nothing is raised or flagged; a duress outcome appears only for an approval made at that moment | |

## 6. Attacks to try on purpose

Each one must be rejected, and each is a thing the Binance attackers could have tried.

| ID | Case | Steps | Expect | Result |
|---|---|---|---|---|
| 6.1 | The Binance replay | Try `verify_cli.py check` with a request and no envelope | It fails; nothing is authorised | |
| 6.2 | Replay | Run `check` again on the same envelope | Rejected (nonce already used) | |
| 6.3 | Swap after approval | Change the destination or amount, keep the envelope | Rejected (request hash) | |
| 6.4 | Expiry | Wait over 2 minutes, then run `check` | Rejected (the verifier times the nonce) | |
| 6.5 | Other service | Change `FIDO_RP_ID` for the verifier | Rejected | |
| 6.6 | Forged or moved tag | Edit the `mcu` field, or paste another approval's tag | Rejected | |
| 6.7 | Doctored attestation | Edit the `attest` bytes (features, click age, grip) | Rejected | |
| 6.8 | Forged ML-DSA seal | Flip one byte of `pq_sig` | Rejected | |
| 6.9 | Forged YubiKey proof | Flip one byte of the YubiKey signature, or its challenge | Rejected | |
| 6.10 | Downgrade | Enrol in FIDO2 mode, send an HMAC-SHA1 proof (and the reverse) | Rejected | |
| 6.11 | Piggyback | Click for one request; from Linux, try to arm a different request right after | The STM32 arms once per click; the second arm is refused | |
| 6.12 | Linux compromise, honestly | With a shell on the board, call `arm_approval` with no click | Refused. **Note for the pitch: a rooted Linux side can still piggyback on a real click (CRYPTO.md weak spot 20)** | |
| 6.13 | Wrong-device tag | Use a second device's tag key | Rejected | |

## 7. The audit log

| ID | Case | Steps | Expect | Result |
|---|---|---|---|---|
| 7.1 | Log grows | After several approvals, read `device.json` log | One hash-chained entry per approval, signed with ML-DSA | |
| 7.2 | Verifies | Run `ys.log_verify` with the enrolled public key | `True` | |
| 7.3 | Edit an entry | Change one `who` or `type` | `False` | |
| 7.4 | Delete or reorder an entry | Remove the middle entry | `False` | |
| 7.5 | Status not in the log | Search the log for `D` or "duress" | Not present: only the envelope hash is logged | |
| 7.6 | Merkle root | Add an entry, recompute `merkle_root` | The root changes | |

---

## Results log

| Date and time | Who | Commit tested (`git rev-parse --short HEAD`) | Groups run | Failures (case ID and exact message) |
|---|---|---|---|---|
| | | | | |

**Blockers to settle first, in order:** 2.1 (the sketch compiles), 2.8 (Bridge String arguments), 3.2 and 3.3 (the YubiKey without a touch). Groups 4 to 7 depend on them.

**Known limits to state honestly** (not test failures): no trusted display, so a swapped transaction the person never sees is possible; no knowledge factor (PIN); a rooted Linux side can piggyback on a click; the HMAC-SHA1 fallback gives the verifier a secret it could use to fake the YubiKey proof. All are in [CRYPTO.md](CRYPTO.md#remaining-weak-spots).
