# Store Intelligence API

A containerised offline retail analytics pipeline for the Purplle Engineering Hiring Challenge.

## Quick Start

1. Build and start the API:
   ```bash
   docker compose up --build
   ```
2. Check health:
   ```bash
   curl http://localhost:8000/health
   ```
3. Generate detector events from the updated challenge inputs:
   ```bash
   docker compose run --rm api python -m pipeline.run --input /app/updated_docs --output /tmp/events.jsonl
   ```
4. Ingest generated events:
   ```bash
   curl -X POST http://localhost:8000/events/ingest \
     -H "Content-Type: application/json" \
     --data-binary @events.jsonl
   ```
5. Query store intelligence:
   ```bash
   curl http://localhost:8000/metrics
   curl http://localhost:8000/stores/STORE_BLR_002/metrics
   curl http://localhost:8000/stores/STORE_BLR_002/funnel
   curl http://localhost:8000/stores/STORE_BLR_002/heatmap
   curl http://localhost:8000/stores/STORE_BLR_002/anomalies
   curl http://localhost:8000/stores/STORE_BLR_002/quality
   ```

This repository is configured for the new `updated_docs` challenge dataset. If no challenge dataset is mounted, the pipeline still generates a deterministic demo stream.

## What Is Included

- Detection pipeline that emits the required structured event schema.
- FastAPI intelligence service with idempotent ingest.
- `/metrics`, store metrics, funnel, heatmap, anomaly, and health endpoints.
- Event quality endpoint showing CCTV-derived ratio, camera counts, inferred exits, and low-confidence detections.
- SQLite-backed persistence with graceful database error handling.
- Structured request logging with trace ID, store ID, endpoint, latency, and event count.
- Live terminal dashboard at `/dashboard`.
- Tests covering ingestion idempotency, metrics, funnel/session deduplication, anomalies, health, and edge cases.

## Running Tests

```bash
docker compose run --rm api pytest --cov=app --cov=pipeline --cov-report=term-missing
```

## Evaluation Checklist Mapping

- System execution: `docker compose up --build` starts the API.
- API availability: `GET /metrics` and `GET /health` return valid JSON.
- Event generation: `python -m pipeline.run --input ./data --output ./events.jsonl` emits structured JSONL events.
- CCTV proof: `GET /stores/ST1008/quality` shows `cctv_detected_events`, camera-level counts, and inferred exit events.
- Documentation: `DESIGN.md` and `CHOICES.md` explain architecture, trade-offs, and AI-assisted decisions.
- Stability: empty stores return zero metrics and an informational anomaly instead of crashing.

## Detection Pipeline

The command below reads optional challenge files from a directory:

```bash
python -m pipeline.run --input ./data --output ./events.jsonl
```

While processing CCTV, the command prints progress per video:

```text
[cctv] opening CAM 1.mp4
[cctv] CAM 1.mp4: sampled 30/180 frames
[cctv] CAM 1.mp4: activity_samples=...
```

Expected optional files:

- `store_layout.json` or layout PNG files
- POS CSV files with names containing `pos`
- sample event JSONL files with names containing `sample` and `events`
- CCTV MP4 files anywhere under the input directory

The current implementation uses OpenCV to read the CCTV videos, sample frames, detect moving person-sized regions, and emit structured events. POS transactions are then used to mark billing-zone conversions. The video stage remains an adapter boundary: a YOLO/ByteTrack/ReID implementation can replace `pipeline/detect.py` without changing the event schema or API.

For this dataset:

- Default store: `STORE_BLR_002`
- Source event example store: `ST1076`, normalized from `store_1076` and `ST1076` rows in `updated_docs/sample_eventsbe42122.jsonl`
- Layout source: Store 1 and Store 2 layout PNG files in `updated_docs`
- POS source: `updated_docs/POS - sample transactionsb1e826f.csv`
- CCTV source: Store 1 and Store 2 MP4 clips nested under `updated_docs`
- Sample event source: `updated_docs/sample_eventsbe42122.jsonl`, translated from source names such as `entry`, `zone_entered`, and `queue_completed` into the required event catalogue

## Live Dashboard

Open:

```text
http://localhost:8000/dashboard
```

The page polls live API endpoints and shows unique visitors, conversion rate, average dwell, queue depth, abandonment, funnel counts, heatmap zones, anomalies, and feed health.

## Hosted Demo

The app can run as a hosted demo without private dataset files. On an empty database it seeds a small demo event stream automatically unless `AUTO_SEED_DEMO=false` is set.

Recommended Render settings:

- Build command: `pip install -r requirements.txt`
- Start command: `python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment:
  - `AUTO_SEED_DEMO=true`
  - `DEFAULT_STORE_ID=STORE_BLR_002`

The live dashboard path is `/dashboard`.
