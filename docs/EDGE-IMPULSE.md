# The on-device duress model (Edge Impulse)

The duress judgement is made by an **Edge Impulse model that runs on the UNO Q's Linux side**. No camera frame and no reading leaves the board. Back to the **[overview](YuDuino-Overview.md)** · **[crypto design](CRYPTO.md)** · **[baseline](BASELINE.md)** · **[build flow](BUILD-FLOW.md)**

## The design

- **Classical ML, not a cloud LLM.** We started with Gemini and Tiger Data and moved everything onto the device.
- **A generic model, personalised on the device without retraining.** Edge Studio trains one *generic* anomaly model on **synthetic** calm data only, never on a real person's data. Each mouse personalises it locally: the features it scores include the user's own reading against **their own per-hour mean and spread** (the STM32's rolling baseline), so the same model means "unusual for this person". Real user data never leaves the device. Studio is used only for the generic model.
- **Only at a transaction.** The model runs once, on **the last minute of readings** (plus the readings taken right after the click), scored against the user's per-hour baseline. One minute is short enough that a sudden change isn't averaged away. The last minute is kept in RAM only by the learner (`python3 main.py learn <user>`, which runs all day) and overwritten every second; with no learner running, only the short live sample is scored. Everyday use is learned from (the baseline) but never judged.
- **The STM32 still decides.** The score goes to the STM32 as a whole number 0 to 100; the STM32 applies the veto and the decision rule (below 40 normal, 40 to 69 step-up, 70 and over duress) and makes the tag. The model can raise the alarm but never lower it.
- **Fails closed.** No model, a model fault or an out-of-range output means no verdict, which counts as duress.
- **Encrypted at rest.** The baseline copy, the training rows and the installed model are AES-256-GCM encrypted under a key the STM32 derives (`HMAC(K_MCU, "YS3/profile-key")`). The key is never stored on Linux, so a stolen board reveals nothing. The model is decrypted into RAM only to run.

## Edge cases (as presented)

- **Over-the-shoulder rule.** Coworkers and passers-by don't count. The camera only flags someone who is close and facing the screen for 3 seconds or more (`SHOULDER_DWELL_S` in `app/dashboard/server.py`).
- **Hand on the mouse.** Readings only register while a palm is on the grip (the touch sensor), so a mouse left on the desk teaches the baseline nothing.
- **Just back from a run.** After 5+ minutes away from the mouse, if sweat or shake is high but falling, that is treated as recovery from exercise: the body score is capped below the duress threshold, so the body sensors alone can't signal duress (`ABSENCE_S`, `RECOVERY_CAP` in `app/dashboard/baseline_model.py`).

## How the data becomes a baseline

1. While the palm is on the grip, the STM32 reads the sensors itself and folds each reading into a **per-sensor, per-hour running mean and variance** (24 hours × humidity, moisture, shake, temperature). The count is capped at 1000 so old habits fade slowly. Linux only supplies the hour.
2. Linux condenses each minute into **one feature row** (the `FEATURE_NAMES` vector) and discards the raw samples. Rows are kept encrypted on the board.
3. At a transaction, the last minute's features are normalised against that hour's baseline (`hour_z_*`) and passed to the model with the camera's face count. The score combines the model's output and the z-scores.
4. A baseline needs 20 samples in an hour before its z-scores count.

Seed a demo quickly: `python3 main.py seed <user> 15` (15 minutes with a hand on the mouse). Learn all day with `python3 main.py learn <user>`.

## Training the generic model (one time, no real data)

1. `python3 tools/gen_generic_training.py generic.csv 2000` makes the synthetic calm set.
2. In Edge Studio: new project, upload the CSV (one row per sample, header = `FEATURE_NAMES`), create an impulse with a raw-data input of the 17 features in that order and a **K-means anomaly detection** block, train. (Our trained model: 2000 calm rows, 17 input columns.)
3. Note the anomaly scores for calm and for a staged hold; set `EI_ANOMALY_LIMIT` to the "unusual" level.
4. Deploy: Linux (AARCH64) `.eim`. `python3 main.py import-model <user> generic.eim` encrypts it into that user's profile; delete the plaintext afterwards.
5. Test calm against a staged duress on the real mouse.

If real data was ever uploaded to Studio, delete that project's data.

## Where it plugs in

| What | Where |
|---|---|
| The model wrapper | `app/python/edge_model.py` (`EdgeModel`, `edge_score`) |
| The input vector | `FEATURE_NAMES` in `edge_model.py`: `temp_c_mean`, `humidity_mean`, `humidity_delta`, `shake_rms_mean`, `shake_rms_max`, `moisture_mean`, `moisture_delta`, `grip_fraction`, `click_hold_ms`, `faces`, `others_close`, `sweat_z`, `move_z`, `hour_z_humidity`, `hour_z_moisture`, `hour_z_shake`, `hour_z_temp` |
| The output | a classifier's `duress` class (`EI_DURESS_LABEL`), or an anomaly score mapped as 0.5 at `EI_ANOMALY_LIMIT` and 1.0 at twice it |
| Profile folder | `PROFILE_DIR` (default `app/python/profile/`) |
| The call | `model_fn` in `app/python/main.py`; the live dashboard runs the same model when the body sensors are unsure |

## If there is no model

The dashboard's body score (the learned baselines and the camera) decides. With neither, there is no verdict and the approval fails closed to duress.
