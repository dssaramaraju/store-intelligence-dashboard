# Choices

## 1. Detection Model Choice

I chose an OpenCV-based dataset-aware detector for the submitted repository and documented the adapter boundary for a YOLOv8 + ByteTrack + OSNet replacement.

Reasoning:

- The available dataset has POS transactions and CCTV videos, but no ready-made labels. A heavyweight model would produce boxes that are hard to verify without ground truth, so I used an explainable OpenCV motion detector first.
- The scoring API requires structured events, not raw boxes, so schema correctness and edge-case behavior matter most for this build.
- The generator reads real Brigade CCTV frames and POS timestamps, then emits hard cases: group-like near-simultaneous entries, staff movement, re-entry, partial-occlusion confidence, queue buildup, empty-store behavior, abandonment, and conversions.

If I had the clips, I would start with YOLOv8 for person detection because it is fast, well documented, and easy to containerise. I would pair it with ByteTrack because retail CCTV has frequent short occlusions and ByteTrack handles low-confidence boxes better than a pure high-confidence tracker. For re-entry I would add OSNet embeddings and a short time-window trajectory matcher.

## 2. Event Schema Choice

I kept the challenge event catalogue exactly and put computed context in `metadata`.

Examples:

- Billing queue depth is stored as `metadata.queue_depth`.
- POS correlation is represented with `metadata.converted`, `metadata.transaction_id`, and `metadata.basket_value_inr`.
- Re-entry context uses `metadata.previous_exit_seconds`.
- Staff evidence uses `metadata.uniform_match`.

This avoids schema drift while still supporting metrics, funnel, heatmap, and anomalies. I also chose UUIDv5 event IDs in the detector because the same clip/frame/session should produce the same event ID across retries. That makes `/events/ingest` naturally idempotent.

## 3. API Storage Choice

I chose SQLite for the submitted API.

Why:

- It works inside one container with no manual service setup.
- It supports the required indexes and primary-key deduplication.
- It is transparent for reviewers: the entire state is one file.

Trade-off:

- SQLite is not ideal for many concurrent writers across 40 stores. In production I would move the same table shape to PostgreSQL, add partitioning by store/date, and put event ingestion behind a queue.

## 4. Anomaly Choice

I implemented three explainable anomalies:

- `BILLING_QUEUE_SPIKE`
- `CONVERSION_DROP`
- `STALE_FEED`

They are deliberately simple because a scoring reviewer can inspect and reason about them quickly. A production version would compare current metrics against a store/day/time baseline rather than fixed thresholds.

## 5. Reviewer Evidence Choice

I added `/stores/{id}/quality` because the evaluation framework gives reviewers only a short validation window. This endpoint exposes whether events came from CCTV processing, how many events each camera contributed, how many detections were low confidence, and how many exits were inferred from entry-camera activity. It is not a business metric; it is an audit surface to prove the pipeline is doing real computation.

## 6. AI Usage and Disagreements

AI suggested adding a separate `PURCHASE` event for conversion. I rejected that because the prompt gives a fixed event catalogue and says the detection layer must emit that schema. I used metadata on billing dwell events instead.

AI suggested adding Redis for live dashboard updates. I rejected it for this take-home because polling every three seconds is enough to prove that the detector and API are connected, and it keeps `docker compose up` simple.

AI suggested hiding low-confidence detections below a threshold. I rejected that because the problem statement explicitly says low-confidence detections should be flagged rather than silently dropped.
