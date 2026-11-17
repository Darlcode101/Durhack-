# The duress model

Back to the [README](../README.md) or [how it works](HOW-IT-WORKS.md).

The duress score comes from an Edge Impulse model running on the UNO Q's Linux side. No reading or camera frame leaves the board.

## How it fits together

We started with Gemini and Tiger Data and dropped both, because sending someone's body readings to a cloud LLM is a bad idea for a security device. Now it's classical ML on the board.

Edge Impulse trains one generic K-means anomaly model, on synthetic calm data only, never on a real person. Each mouse makes it personal without retraining: most of the inputs are your reading as a z-score against your own mean and spread for that hour, z = (x − μ) / σ, using the STM32's per-hour baseline. So the same model ends up meaning "unusual for you".

The model runs once per transaction, on the last minute of readings plus the ones taken right after the click. A minute is short enough that a sudden change doesn't get averaged away. The score goes to the STM32 as a whole number from 0 to 100, and the STM32 makes the decision (see [HOW-IT-WORKS.md](HOW-IT-WORKS.md#one-approval-step-by-step)).

If there's no model, a model fault or a bad output, there's no verdict, and that counts as duress. The dashboard's own body score is used when no model is installed.

## The encrypted profile

Each user's baseline copy, their one-row-a-minute training data and their installed model are kept in one profile on the board, encrypted with AES-256-GCM. The key is derived on the STM32 (`HMAC(K_MCU, "YS3/profile-key")`) and never stored on Linux, so a stolen SD card or a copied folder is unreadable. The model is only decrypted into RAM to run. Code: [`app/python/userprofile.py`](../app/python/userprofile.py).

## The inputs

17 features, in this order (`FEATURE_NAMES` in [`app/python/edge_model.py`](../app/python/edge_model.py)):

`temp_c_mean`, `humidity_mean`, `humidity_delta`, `shake_rms_mean`, `shake_rms_max`, `moisture_mean`, `moisture_delta`, `grip_fraction`, `click_hold_ms`, `faces`, `others_close`, `sweat_z`, `move_z`, `hour_z_humidity`, `hour_z_moisture`, `hour_z_shake`, `hour_z_temp`

`faces` and `others_close` come from the camera's over-the-shoulder rule. The `hour_z_*` values need at least 20 samples in that hour before they count.

The output is an anomaly score. It maps to a duress score of 0.5 at `EI_ANOMALY_LIMIT` and 1.0 at twice that.

## Training the generic model

1. `python3 tools/gen_generic_training.py generic.csv 2000` makes the synthetic calm set.
2. In Edge Impulse Studio, make a project, upload the CSV, and create an impulse with a raw-data input of the 17 features (same order) and a K-means anomaly detection block. Train it. Ours used 2000 calm rows.
3. Note the anomaly score for calm and for a staged hold, and set `EI_ANOMALY_LIMIT` in `.env` to the "unusual" level.
4. Deploy as Linux (AARCH64) `.eim`, then `python3 app/python/main.py import-model <user> generic.eim`. That encrypts it into the user's profile, so delete the plain copy afterwards.
5. Test calm against a staged duress on the real mouse.

To build up a baseline, run `python3 app/python/main.py learn <user>` all day, or `seed <user> 15` for a quick 15 minute demo.
