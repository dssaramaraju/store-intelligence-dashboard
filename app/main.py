import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.database import has_events, init_db, insert_events
from app.health import service_health
from app.ingestion import ingest_events, parse_events_payload
from app.metrics import compute_funnel, compute_heatmap, compute_metrics, detect_anomalies, event_quality_report


logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("store-intelligence")

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    if os.getenv("AUTO_SEED_DEMO", "true").lower() in {"1", "true", "yes"} and not has_events():
        from pipeline.detect import generate_demo_events

        insert_events(generate_demo_events(os.getenv("DEFAULT_STORE_ID", "STORE_BLR_002")))
    yield


app = FastAPI(title="Store Intelligence API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def structured_logging(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id", str(uuid4()))
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        return response
    finally:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        store_id = request.path_params.get("store_id", "-")
        event_count = getattr(request.state, "event_count", 0)
        logger.info(
            "trace_id=%s store_id=%s endpoint=%s method=%s status=%s latency_ms=%s event_count=%s",
            trace_id,
            store_id,
            request.url.path,
            request.method,
            getattr(response, "status_code", 500),
            latency_ms,
            event_count,
        )


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    if exc.__class__.__module__.startswith("sqlite3"):
        return JSONResponse(
            status_code=503,
            content={"error": "DATABASE_UNAVAILABLE", "message": "Store intelligence database is unavailable."},
        )
    raise exc


@app.post("/events/ingest")
async def ingest(request: Request):
    try:
        events, malformed = parse_events_payload(await request.body(), request.headers.get("content-type"))
        request.state.event_count = len(events)
        return ingest_events(events, malformed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if exc.__class__.__module__.startswith("json"):
            raise HTTPException(status_code=400, detail="invalid JSON payload") from exc
        raise


@app.get("/stores/{store_id}/metrics")
def metrics(store_id: str):
    return compute_metrics(store_id)


@app.get("/metrics")
def default_metrics():
    return compute_metrics(os.getenv("DEFAULT_STORE_ID", "STORE_BLR_002"))


@app.get("/stores/{store_id}/funnel")
def funnel(store_id: str):
    return compute_funnel(store_id)


@app.get("/stores/{store_id}/heatmap")
def heatmap(store_id: str):
    return compute_heatmap(store_id)


@app.get("/stores/{store_id}/anomalies")
def anomalies(store_id: str):
    return detect_anomalies(store_id)


@app.get("/stores/{store_id}/quality")
def quality(store_id: str):
    return event_quality_report(store_id)


@app.get("/health")
def health():
    return service_health()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Store Intelligence Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; background: #f6f8fb; color: #172033; }
    header { background: #4338ca; color: white; padding: 20px 28px; }
    main { padding: 24px; display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }
    section { background: white; border: 1px solid #dde3ef; border-radius: 8px; padding: 16px; }
    h1 { margin: 0; font-size: 24px; }
    h2 { margin: 0 0 12px; font-size: 16px; }
    .subhead { margin-top: 6px; opacity: 0.9; }
    .toolbar { padding: 16px 24px 0; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
    .toolbar button { border: 1px solid #c8d1e3; background: white; border-radius: 6px; padding: 8px 10px; cursor: pointer; }
    .toolbar button.active { background: #172033; color: white; border-color: #172033; }
    .note { color: #506078; font-size: 13px; }
    .metric { font-size: 32px; font-weight: 700; }
    pre { white-space: pre-wrap; font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <h1>Store Intelligence Dashboard</h1>
    <div id="status" class="subhead">updated_docs dataset | Live metrics ready</div>
  </header>
  <div class="toolbar">
    <strong>Store</strong>
    <div id="stores"></div>
    <span class="note">ST1076 = normalized sample events. STORE_BLR_002 = CCTV/POS generated stream.</span>
  </div>
  <main>
    <section><h2>Total Events</h2><div class="metric" id="totalEvents">0</div></section>
    <section><h2>Visitors</h2><div class="metric" id="visitors">0</div></section>
    <section><h2>Conversion</h2><div class="metric" id="conversion">0%</div></section>
    <section><h2>Queue Depth</h2><div class="metric" id="queue">0</div></section>
    <section><h2>CCTV Events</h2><div class="metric" id="cctv">0</div></section>
    <section><h2>Funnel</h2><pre id="funnel"></pre></section>
    <section><h2>Heatmap</h2><pre id="heatmap"></pre></section>
    <section><h2>Event Quality</h2><pre id="quality"></pre></section>
    <section><h2>Anomalies</h2><pre id="anomalies"></pre></section>
  </main>
  <script>
    let store = new URLSearchParams(location.search).get('store') || 'STORE_BLR_002';
    function setStore(nextStore) {
      store = nextStore;
      const url = new URL(location.href);
      url.searchParams.set('store', store);
      history.replaceState(null, '', url);
      refresh();
    }
    function renderStoreButtons(health) {
      const knownStores = Object.keys(health.stores || {});
      if (!knownStores.includes('STORE_BLR_002')) knownStores.push('STORE_BLR_002');
      if (!knownStores.includes('ST1076')) knownStores.push('ST1076');
      stores.innerHTML = '';
      knownStores.sort().forEach((item) => {
        const button = document.createElement('button');
        button.textContent = item;
        button.className = item === store ? 'active' : '';
        button.onclick = () => setStore(item);
        stores.appendChild(button);
      });
    }
    async function refresh() {
      try {
        const [m, f, h, a, q, health] = await Promise.all([
          fetch(`/stores/${store}/metrics`).then(r => r.json()),
          fetch(`/stores/${store}/funnel`).then(r => r.json()),
          fetch(`/stores/${store}/heatmap`).then(r => r.json()),
          fetch(`/stores/${store}/anomalies`).then(r => r.json()),
          fetch(`/stores/${store}/quality`).then(r => r.json()),
          fetch('/health').then(r => r.json())
        ]);
        renderStoreButtons(health);
        totalEvents.textContent = q.total_events || 0;
        visitors.textContent = m.unique_visitors;
        conversion.textContent = Math.round(m.conversion_rate * 100) + '%';
        queue.textContent = m.avg_queue_depth;
        cctv.textContent = m.cctv_detected_events || 0;
        funnel.textContent = JSON.stringify(f.stages, null, 2);
        heatmap.textContent = JSON.stringify(h.zones, null, 2);
        quality.textContent = JSON.stringify({
          total_events: q.total_events,
          cctv_ratio: q.cctv_event_ratio,
          low_confidence: q.low_confidence_events,
          inferred_exits: q.inferred_exit_events,
          cameras: q.camera_event_counts
        }, null, 2);
        anomalies.textContent = JSON.stringify(a, null, 2);
        status.textContent = `updated_docs dataset | ${store} | ${health.status} | updated ${new Date().toLocaleTimeString()}`;
      } catch (error) {
        status.textContent = `${store} | API connection issue`;
      }
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""
