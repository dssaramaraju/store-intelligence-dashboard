# Design

## Architecture Overview

The system is split into two contracts:

1. `pipeline/` produces structured behavioral events from CCTV inputs.
2. `app/` ingests those events and exposes store intelligence through HTTP.

This keeps the computer-vision layer replaceable. The scoring API should not care whether events came from YOLOv8 + ByteTrack, RT-DETR, MediaPipe, a VLM-assisted classifier, or the deterministic simulator included here. The boundary is the event schema in `app/models.py`.

Flow:

```text
CCTV clips / sample_events*.jsonl / POS CSV
  -> pipeline.detect
  -> pipeline.emit JSONL
  -> POST /events/ingest
  -> SQLite event store
  -> metrics / funnel / heatmap / anomalies / dashboard
```

## Detection Layer

The included detector is dataset-aware and reads the provided CCTV MP4 files from the nested `updated_docs` store folders. It samples frames with OpenCV, applies background subtraction, extracts moving person-sized regions, estimates activity per camera, maps cameras to entry/floor/billing zones from filename roles, and emits structured events with `metadata.cctv_detected=true`. It also uses POS transactions for conversion correlation and normalizes challenge-provided source events from `sample_eventsbe42122.jsonl` into the required API schema.

The updated layout files are PNG floor plans rather than structured zone rows. I keep a conservative `store_layout.json` contract with explicit business zones and attach discovered layout PNG paths as metadata when the pipeline creates a layout file.

In a production implementation I would improve `pipeline/detect.py` with:

- Person detection: YOLOv8 or RT-DETR on sampled frames from `data/cctv`.
- Tracking: ByteTrack for frame-to-frame IDs.
- Re-identification: OSNet embeddings plus short-time trajectory matching for exit/re-entry.
- Zone classification: point-in-polygon mapping from `store_layout.json`.
- Staff detection: uniform-color classifier plus manually defined staff-only trajectories.

The event generator uses stable UUIDv5 event IDs so repeated pipeline runs are idempotent when ingested. The current OpenCV detector is intentionally simple and explainable; it proves that the pipeline reads video frames, while keeping the model choice replaceable. The sample-event normalizer preserves original fields such as age bucket, group ID, queue wait, and source event type in metadata so reviewers can audit the translation.

## API Layer

FastAPI exposes:

- `POST /events/ingest`
- `GET /stores/{id}/metrics`
- `GET /stores/{id}/funnel`
- `GET /stores/{id}/heatmap`
- `GET /stores/{id}/anomalies`
- `GET /stores/{id}/quality`
- `GET /health`
- `GET /dashboard`

SQLite is used because the challenge asks for a containerised system that can run on a clean machine without external services. The ingestion table is append-only with `event_id` as the primary key, which makes retries safe. The service returns zero metrics for empty windows and never divides by zero.

## Metrics

The north-star metric is offline store conversion rate:

```text
converted visitor sessions / unique visitor sessions
```

Staff events are excluded from all customer metrics. Funnel counts are session-based rather than raw-event-based so re-entry and camera overlap do not double-count a visitor. Heatmap output includes a `data_confidence` flag when the underlying detections are weak, which is better than silently dropping hard frames.

## Production Readiness

The service is built for `docker compose up`. Request logs include trace ID, store ID, endpoint, method, status, latency, and event count placeholder. Ingest accepts JSONL, a single event, a list of events, or `{"events": [...]}` batches up to 500 events. Database failures are converted into structured HTTP 503 responses.

Tests cover the acceptance gate: ingestion idempotency, staff exclusion, re-entry/session deduplication, zero-event behavior, heatmap confidence, anomaly detection, detector schema behavior, and reviewer-facing event quality.

The `/quality` endpoint exists specifically for reviewer verification. It reports CCTV-derived event count, camera-level event counts, low-confidence detections, staff events excluded from metrics, and inferred exits. This makes it easy to see that the pipeline is not just hardcoded dashboard output.

## AI-Assisted Decisions

1. I used AI to pressure-test the event schema against the scoring endpoints. The useful suggestion was to keep conversion as metadata on billing-zone events instead of inventing an extra event type outside the catalogue. I accepted that because it preserves schema compliance.
2. I used AI to compare SQLite vs PostgreSQL for a take-home container. The recommendation was SQLite for the default submission because it removes setup friction while preserving idempotency and queryability. I agreed, with the note that PostgreSQL would be the production upgrade.
3. I used AI to evaluate whether low-confidence detections should be suppressed. The answer was to emit them with confidence and heatmap confidence flags. I accepted this because the prompt explicitly rewards confidence calibration over hiding hard cases.
4. I used AI to identify the mismatch between the supplied `updated_docs` sample event rows and the required event schema. I accepted the suggestion to build a source normalizer instead of changing the API schema, because the challenge requires the final emitted stream to follow the fixed catalogue.
