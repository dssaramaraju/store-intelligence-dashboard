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
3. Generate detector events from sample inputs:
   ```bash
   docker compose run --rm api python -m pipeline.run --input /data --output /tmp/events.jsonl
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
   curl http://localhost:8000/stores/ST1008/metrics
   curl http://localhost:8000/stores/ST1008/funnel
   curl http://localhost:8000/stores/ST1008/heatmap
   curl http://localhost:8000/stores/ST1008/anomalies
   curl http://localhost:8000/stores/ST1008/quality
   ```

This repository is configured for the provided Brigade Bangalore dataset. If no challenge dataset is mounted, the pipeline still generates a deterministic demo stream.

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

- `store_layout.json`
- `store_layout.xlsx`
- `pos_transactions.csv`
- `sample_events.jsonl`
- `cctv/*.mp4`

The current implementation uses OpenCV to read the CCTV videos, sample frames, detect moving person-sized regions, and emit structured events. POS transactions are then used to mark billing-zone conversions. The video stage remains an adapter boundary: a YOLO/ByteTrack/ReID implementation can replace `pipeline/detect.py` without changing the event schema or API.

For this dataset:

- Store: `ST1008` / `Brigade_Bangalore`
- Layout source: `data/store_layout.xlsx`, converted into `data/store_layout.json`
- POS source: `data/pos_transactions.csv`
- CCTV source: `data/cctv/CAM 1.mp4` through `CAM 5.mp4`

## Live Dashboard

Open:

```text
http://localhost:8000/dashboard
```

The page polls live API endpoints and shows unique visitors, conversion rate, average dwell, queue depth, abandonment, funnel counts, heatmap zones, anomalies, and feed health.
