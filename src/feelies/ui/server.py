"""Dependency-free web server for the Feelies trading workbench."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from feelies.ui.workbench import BacktestRunRequest, WorkbenchError, load_workbench_bootstrap, run_workbench


@dataclass(slots=True)
class _WorkbenchState:
    config_path: str
    latest_snapshot: dict[str, object] | None = None


class WorkbenchServer(ThreadingHTTPServer):
    """HTTP server carrying UI state between requests."""

    def __init__(self, server_address: tuple[str, int], config_path: str) -> None:
        super().__init__(server_address, WorkbenchRequestHandler)
        self.state = _WorkbenchState(config_path=config_path)


class WorkbenchRequestHandler(BaseHTTPRequestHandler):
    """Serves the dashboard shell and its JSON endpoints."""

    server: WorkbenchServer

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route == "/":
            self._send_html(_INDEX_HTML)
            return
        if route == "/api/bootstrap":
            payload = load_workbench_bootstrap(self.server.state.config_path)
            self._send_json(HTTPStatus.OK, payload)
            return
        if route == "/api/runs/latest":
            self._send_json(HTTPStatus.OK, {"snapshot": self.server.state.latest_snapshot})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {route}"})

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route != "/api/backtests/run":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown route: {route}"})
            return

        try:
            body = self._read_json_body()
            request = BacktestRunRequest.from_payload(body)
            if not request.config_path:
                request = BacktestRunRequest(
                    demo=request.demo,
                    config_path=self.server.state.config_path,
                    symbols=request.symbols,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    cache_dir=request.cache_dir,
                    no_cache=request.no_cache,
                    api_key=request.api_key,
                )
            snapshot = run_workbench(request)
        except WorkbenchError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        except json.JSONDecodeError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Request body must be valid JSON."})
            return
        except Exception as exc:  # pragma: no cover - defensive server boundary
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return

        self.server.state.latest_snapshot = snapshot
        self._send_json(HTTPStatus.OK, {"snapshot": snapshot})

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def _read_json_body(self) -> dict[str, object]:
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict):
            raise WorkbenchError("Request body must be a JSON object.")
        return body

    def _send_html(self, html: str) -> None:
        encoded = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def serve_workbench(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    config_path: str = "platform.yaml",
) -> None:
    """Start the workbench server and block until interrupted."""
    server = WorkbenchServer((host, port), config_path=config_path)
    print(f"Feelies workbench available at http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Feelies Control Room</title>
  <style>
    :root {
      --canvas: #f4efe6;
      --panel: rgba(255, 250, 242, 0.78);
      --panel-strong: rgba(255, 248, 237, 0.94);
      --line: rgba(19, 34, 53, 0.12);
      --ink: #14253a;
      --muted: #5c6a79;
      --accent: #b66d2d;
      --accent-soft: rgba(182, 109, 45, 0.14);
      --success: #0f766e;
      --warning: #a45b1e;
      --danger: #a0352d;
      --shadow: 0 20px 60px rgba(18, 27, 43, 0.12);
      --radius: 22px;
      --mono: "IBM Plex Mono", "Consolas", monospace;
      --sans: "IBM Plex Sans", "Segoe UI Variable Text", "Segoe UI", sans-serif;
      --serif: "Iowan Old Style", "Palatino Linotype", serif;
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: var(--sans);
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(182, 109, 45, 0.20), transparent 28%),
        radial-gradient(circle at top right, rgba(20, 37, 58, 0.12), transparent 24%),
        linear-gradient(180deg, #f8f3ea 0%, var(--canvas) 45%, #efe7da 100%);
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(19, 34, 53, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(19, 34, 53, 0.04) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.4), transparent 75%);
    }

    .shell {
      width: min(1440px, calc(100vw - 40px));
      margin: 24px auto 48px;
      position: relative;
      z-index: 1;
    }

    .hero {
      padding: 28px 30px;
      border: 1px solid var(--line);
      border-radius: calc(var(--radius) + 6px);
      background: linear-gradient(135deg, rgba(255, 252, 247, 0.94), rgba(244, 235, 221, 0.78));
      backdrop-filter: blur(16px);
      box-shadow: var(--shadow);
      display: grid;
      grid-template-columns: 2.2fr 1fr;
      gap: 24px;
      animation: rise 500ms ease;
    }

    .hero h1 {
      margin: 0 0 12px;
      font-family: var(--serif);
      font-size: clamp(2rem, 4vw, 3.2rem);
      font-weight: 600;
      letter-spacing: -0.03em;
    }

    .hero p {
      margin: 0;
      max-width: 68ch;
      color: var(--muted);
      line-height: 1.55;
      font-size: 1rem;
    }

    .hero-side {
      display: grid;
      gap: 12px;
      align-content: start;
    }

    .hero-chip,
    .topology-pill,
    .status-pill,
    .mode-pill,
    .verification-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(20, 37, 58, 0.10);
      background: rgba(255, 255, 255, 0.65);
      font-size: 0.84rem;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }

    .hero-chip strong,
    .status-pill strong,
    .mode-pill strong,
    .verification-pill strong {
      font-family: var(--mono);
      font-size: 0.82rem;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(320px, 360px) 1fr;
      gap: 22px;
      margin-top: 22px;
    }

    .stack {
      display: grid;
      gap: 22px;
      align-content: start;
    }

    .panel {
      padding: 22px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--panel);
      backdrop-filter: blur(14px);
      box-shadow: var(--shadow);
      animation: rise 620ms ease;
    }

    .panel h2,
    .panel h3 {
      margin: 0 0 12px;
      font-size: 1rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }

    .panel h3 {
      font-size: 0.88rem;
      color: var(--muted);
    }

    .muted {
      color: var(--muted);
    }

    .form-grid {
      display: grid;
      gap: 14px;
    }

    .field {
      display: grid;
      gap: 6px;
    }

    .field label {
      font-size: 0.82rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }

    input,
    textarea,
    select,
    button {
      font: inherit;
    }

    input,
    textarea,
    select {
      width: 100%;
      border-radius: 16px;
      border: 1px solid rgba(20, 37, 58, 0.14);
      background: rgba(255, 255, 255, 0.88);
      padding: 12px 14px;
      color: var(--ink);
      transition: border-color 160ms ease, transform 160ms ease;
    }

    input:focus,
    textarea:focus,
    select:focus {
      outline: none;
      border-color: rgba(182, 109, 45, 0.65);
      transform: translateY(-1px);
    }

    textarea {
      min-height: 84px;
      resize: vertical;
    }

    .toggle {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid rgba(20, 37, 58, 0.10);
      background: rgba(255, 255, 255, 0.7);
    }

    .toggle input {
      width: 20px;
      height: 20px;
      margin: 0;
    }

    .actions {
      display: flex;
      gap: 12px;
      align-items: center;
      flex-wrap: wrap;
    }

    button {
      border: none;
      border-radius: 999px;
      padding: 12px 18px;
      font-weight: 600;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      cursor: pointer;
      transition: transform 180ms ease, box-shadow 180ms ease, opacity 180ms ease;
    }

    button:hover { transform: translateY(-1px); }
    button:disabled { opacity: 0.6; cursor: wait; }

    .primary {
      background: linear-gradient(135deg, var(--accent), #d08f4f);
      color: white;
      box-shadow: 0 14px 28px rgba(182, 109, 45, 0.22);
    }

    .secondary {
      background: rgba(20, 37, 58, 0.08);
      color: var(--ink);
    }

    .message {
      min-height: 24px;
      font-size: 0.95rem;
      color: var(--muted);
    }

    .message.error { color: var(--danger); }
    .message.success { color: var(--success); }

    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }

    .metric-card {
      padding: 18px;
      border-radius: 18px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      display: grid;
      gap: 8px;
      min-height: 120px;
      animation: rise 700ms ease;
    }

    .metric-card span {
      color: var(--muted);
      font-size: 0.82rem;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .metric-card strong {
      font-size: 2rem;
      letter-spacing: -0.04em;
      line-height: 1;
      font-variant-numeric: tabular-nums;
    }

    .metric-card small {
      color: var(--muted);
      font-size: 0.9rem;
    }

    .section-grid {
      display: grid;
      gap: 22px;
      margin-top: 22px;
    }

    .dual {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 22px;
    }

    .triple {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 22px;
    }

    .badge-row,
    .topology,
    .verification,
    .modes {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .status-pill.good,
    .verification-pill.pass,
    .mode-pill.available {
      background: rgba(15, 118, 110, 0.12);
      color: var(--success);
    }

    .status-pill.warn,
    .mode-pill.unavailable {
      background: rgba(164, 91, 30, 0.12);
      color: var(--warning);
    }

    .status-pill.bad,
    .verification-pill.fail {
      background: rgba(160, 53, 45, 0.12);
      color: var(--danger);
    }

    .chart {
      min-height: 260px;
      display: grid;
      align-items: center;
      justify-items: stretch;
    }

    .chart svg {
      width: 100%;
      height: 260px;
      overflow: visible;
    }

    .chart .empty {
      text-align: center;
      color: var(--muted);
    }

    .bars {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
      align-items: end;
      gap: 12px;
      min-height: 240px;
    }

    .bar {
      display: grid;
      gap: 8px;
      align-items: end;
      justify-items: center;
    }

    .bar-visual {
      width: 100%;
      border-radius: 18px 18px 6px 6px;
      background: linear-gradient(180deg, rgba(182, 109, 45, 0.78), rgba(20, 37, 58, 0.75));
      min-height: 8px;
    }

    .bar-label {
      font-size: 0.8rem;
      color: var(--muted);
      text-align: center;
      word-break: break-word;
    }

    .bar-value {
      font-family: var(--mono);
      font-size: 0.86rem;
    }

    .table-wrap {
      overflow: auto;
      border-radius: 18px;
      border: 1px solid rgba(20, 37, 58, 0.08);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.94rem;
      background: rgba(255, 255, 255, 0.72);
    }

    thead th {
      position: sticky;
      top: 0;
      background: rgba(245, 238, 228, 0.95);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-size: 0.74rem;
      color: var(--muted);
      z-index: 1;
    }

    th,
    td {
      padding: 12px 14px;
      border-bottom: 1px solid rgba(20, 37, 58, 0.08);
      text-align: left;
      vertical-align: top;
      font-variant-numeric: tabular-nums;
    }

    tbody tr:hover {
      background: rgba(182, 109, 45, 0.07);
    }

    .list {
      display: grid;
      gap: 12px;
      padding: 0;
      margin: 0;
      list-style: none;
    }

    .list-item {
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(20, 37, 58, 0.08);
      background: rgba(255, 255, 255, 0.66);
    }

    .list-item strong {
      display: block;
      margin-bottom: 6px;
      font-size: 0.95rem;
    }

    .timeline {
      display: grid;
      gap: 14px;
    }

    .timeline-item {
      display: grid;
      grid-template-columns: 160px 1fr;
      gap: 14px;
      align-items: start;
      padding-top: 14px;
      border-top: 1px solid rgba(20, 37, 58, 0.08);
    }

    .timeline-item:first-child { border-top: none; padding-top: 0; }

    .timeline-time {
      font-family: var(--mono);
      color: var(--muted);
      font-size: 0.86rem;
    }

    .empty-state {
      display: grid;
      gap: 10px;
      place-items: center;
      min-height: 300px;
      text-align: center;
      color: var(--muted);
      border-radius: var(--radius);
      border: 1px dashed rgba(20, 37, 58, 0.16);
      background: rgba(255, 255, 255, 0.42);
    }

    .footnote {
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.5;
    }

    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @media (max-width: 1120px) {
      .hero,
      .grid,
      .dual,
      .triple,
      .metrics-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 780px) {
      .shell {
        width: min(100vw - 20px, 100%);
        margin-top: 10px;
      }

      .hero,
      .panel {
        padding: 18px;
      }

      .timeline-item {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <div class="hero-chip">Feelies operator surface</div>
        <h1>Institutional control room for a deterministic trading stack</h1>
        <p>
          This workbench is bound to the platform's real event bus, macro and micro state machines,
          risk escalation path, in-memory journals, and metrics. It is intentionally opinionated:
          backtest is actionable today, while paper and live are shown as governed posture rather than fake controls.
        </p>
      </div>
      <div class="hero-side" id="heroMeta"></div>
    </section>

    <div class="grid">
      <aside class="stack">
        <section class="panel">
          <h2>Control Deck</h2>
          <form id="runForm" class="form-grid">
            <div class="field">
              <label for="configPath">Config Path</label>
              <input id="configPath" name="configPath" value="platform.yaml" />
            </div>

            <div class="field">
              <label for="modeSelect">Execution Posture</label>
              <select id="modeSelect" disabled>
                <option>BACKTEST</option>
                <option>PAPER</option>
                <option>LIVE</option>
              </select>
            </div>

            <div class="toggle">
              <div>
                <strong>Demo replay</strong>
                <div class="muted">Synthetic 8-tick path with no external dependencies.</div>
              </div>
              <input id="demoToggle" name="demo" type="checkbox" checked />
            </div>

            <div class="field">
              <label for="symbols">Symbols</label>
              <textarea id="symbols" name="symbols" placeholder="AAPL, MSFT, NVDA"></textarea>
            </div>

            <div class="dual">
              <div class="field">
                <label for="startDate">Start Date</label>
                <input id="startDate" name="startDate" type="date" />
              </div>
              <div class="field">
                <label for="endDate">End Date</label>
                <input id="endDate" name="endDate" type="date" />
              </div>
            </div>

            <div class="toggle">
              <div>
                <strong>Bypass cache</strong>
                <div class="muted">Force fresh historical ingestion.</div>
              </div>
              <input id="noCache" name="noCache" type="checkbox" />
            </div>

            <div class="actions">
              <button class="primary" id="runButton" type="submit">Run Backtest</button>
              <button class="secondary" id="loadLatestButton" type="button">Load Latest Snapshot</button>
            </div>
            <div id="runMessage" class="message"></div>
          </form>
        </section>

        <section class="panel">
          <h2>Mode Posture</h2>
          <div class="modes" id="modePills"></div>
          <p class="footnote" id="modeNarrative"></p>
        </section>

        <section class="panel">
          <h2>Topology</h2>
          <h3>Macro states</h3>
          <div class="topology" id="macroTopology"></div>
          <h3>Micro pipeline</h3>
          <div class="topology" id="microTopology"></div>
        </section>

        <section class="panel">
          <h2>Platform Notes</h2>
          <ul class="list" id="bootstrapNotes"></ul>
        </section>
      </aside>

      <main>
        <section class="panel">
          <h2>Run Posture</h2>
          <div class="badge-row" id="statusPills"></div>
          <p class="footnote" id="runNarrative">Run a demo or historical backtest to populate the dashboard.</p>
        </section>

        <section id="resultsRoot" class="section-grid">
          <div class="empty-state" id="emptyState">
            <strong>No run snapshot loaded</strong>
            <div>Use the control deck to execute the deterministic backtest path and inspect the resulting operator telemetry.</div>
          </div>
        </section>
      </main>
    </div>
  </div>

  <script>
    const state = {
      bootstrap: null,
      snapshot: null,
    };

    const els = {
      heroMeta: document.getElementById('heroMeta'),
      configPath: document.getElementById('configPath'),
      demoToggle: document.getElementById('demoToggle'),
      symbols: document.getElementById('symbols'),
      startDate: document.getElementById('startDate'),
      endDate: document.getElementById('endDate'),
      noCache: document.getElementById('noCache'),
      runForm: document.getElementById('runForm'),
      runButton: document.getElementById('runButton'),
      runMessage: document.getElementById('runMessage'),
      loadLatestButton: document.getElementById('loadLatestButton'),
      modePills: document.getElementById('modePills'),
      modeNarrative: document.getElementById('modeNarrative'),
      macroTopology: document.getElementById('macroTopology'),
      microTopology: document.getElementById('microTopology'),
      bootstrapNotes: document.getElementById('bootstrapNotes'),
      statusPills: document.getElementById('statusPills'),
      runNarrative: document.getElementById('runNarrative'),
      resultsRoot: document.getElementById('resultsRoot'),
      emptyState: document.getElementById('emptyState'),
    };

    function fmtNumber(value, digits = 0) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return 'n/a';
      return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(Number(value));
    }

    function fmtMoney(value) {
      if (value === null || value === undefined) return 'n/a';
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(Number(value));
    }

    function fmtPct(value) {
      if (value === null || value === undefined) return 'n/a';
      return `${fmtNumber(value, 2)}%`;
    }

    function fmtTs(value) {
      if (!value) return 'n/a';
      if (value < 1_000_000_000_000) {
        return `${fmtNumber(value / 1_000_000_000, 3)}s`;
      }
      return `${fmtNumber(value / 1_000_000_000, 3)}s`;
    }

    function parseSymbols(text) {
      return text
        .split(/[\\s,]+/)
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean);
    }

    function setMessage(text, tone = 'muted') {
      els.runMessage.className = `message ${tone}`;
      els.runMessage.textContent = text;
    }

    async function fetchJson(url, options) {
      const response = await fetch(url, options);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || 'Request failed');
      }
      return payload;
    }

    function renderBootstrap() {
      if (!state.bootstrap) return;
      const bootstrap = state.bootstrap;
      const defaults = bootstrap.config.defaults || {};
      els.configPath.value = bootstrap.config.path || 'platform.yaml';
      els.symbols.value = (defaults.symbols || []).join(', ');
      els.demoToggle.checked = defaults.demo !== false;
      els.noCache.checked = Boolean(defaults.noCache);

      els.heroMeta.innerHTML = [
        chip('Active executable path', 'BACKTEST'),
        chip('Config source', bootstrap.config.exists ? 'FOUND' : 'MISSING'),
        chip('Alpha specs', String((bootstrap.alphaSpecs || []).length)),
      ].join('');

      els.modePills.innerHTML = Object.entries(bootstrap.capabilities || {})
        .map(([name, meta]) => modePill(name, meta.available, meta.reason))
        .join('');
      els.modeNarrative.textContent = 'The UI exposes platform posture honestly: backtest is operable, while paper and live remain governed placeholders until concrete execution backends are wired.';

      els.macroTopology.innerHTML = (bootstrap.topology.macro || []).map((step) => topologyPill(step)).join('');
      els.microTopology.innerHTML = (bootstrap.topology.micro || []).map((step) => topologyPill(step)).join('');
      els.bootstrapNotes.innerHTML = (bootstrap.notes || []).map((note) => `<li class="list-item">${escapeHtml(note)}</li>`).join('');
    }

    function chip(label, value) {
      return `<div class="hero-chip"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
    }

    function topologyPill(text) {
      return `<span class="topology-pill">${escapeHtml(text)}</span>`;
    }

    function modePill(name, available, reason) {
      const klass = available ? 'available' : 'unavailable';
      return `<span class="mode-pill ${klass}" title="${escapeHtml(reason || '')}"><strong>${escapeHtml(name)}</strong>${available ? 'enabled' : 'future'}</span>`;
    }

    function statusPill(label, value, tone = 'good') {
      return `<span class="status-pill ${tone}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></span>`;
    }

    function verificationPill(item) {
      return `<span class="verification-pill ${item.passed ? 'pass' : 'fail'}"><strong>${item.passed ? 'PASS' : 'FAIL'}</strong>${escapeHtml(item.name)}</span>`;
    }

    function escapeHtml(text) {
      return String(text)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
    }

    function renderSnapshot() {
      const snapshot = state.snapshot;
      if (!snapshot) {
        els.emptyState.hidden = false;
        return;
      }
      els.emptyState.hidden = true;
      const summary = snapshot.summary;
      const system = snapshot.system;
      const runMeta = snapshot.runMeta;
      const config = snapshot.config;
      const verification = snapshot.verification || [];

      els.statusPills.innerHTML = [
        statusPill('Macro', system.macroState, system.macroState === 'READY' ? 'good' : 'warn'),
        statusPill('Micro', system.microState, 'good'),
        statusPill('Risk', system.riskLevel, system.riskLevel === 'NORMAL' ? 'good' : 'warn'),
        statusPill('Kill switch', system.killSwitchActive ? 'ACTIVE' : 'INACTIVE', system.killSwitchActive ? 'bad' : 'good'),
        statusPill('Active alerts', String(system.activeAlerts), system.activeAlerts ? 'warn' : 'good'),
      ].join('');

      els.runNarrative.textContent = `${runMeta.modeNote} Scope: ${runMeta.symbolScope}. Date range: ${runMeta.dateRange}. Config checksum: ${runMeta.configChecksum.slice(0, 12)}.`;

      els.resultsRoot.innerHTML = `
        <section class="metrics-grid">
          ${metricCard('Net P&L', fmtMoney(summary.netPnl), `${fmtPct(summary.returnPct)} return`)}
          ${metricCard('Orders filled', fmtNumber(summary.ordersFilled), `${fmtNumber(summary.ordersRejected)} rejected`)}
          ${metricCard('Signals emitted', fmtNumber(summary.signalsEmitted), `${fmtNumber(summary.longSignals)} long / ${fmtNumber(summary.shortSignals)} short`)}
          ${metricCard('Avg tick latency', `${fmtNumber(summary.avgTickLatencyMs, 3)} ms`, `max ${fmtNumber(summary.maxTickLatencyMs, 3)} ms`)}
        </section>

        <section class="dual">
          <div class="panel">
            <h2>Operator Summary</h2>
            <div class="triple">
              ${summaryList('Run envelope', [
                ['Symbols', runMeta.symbolScope],
                ['Date range', runMeta.dateRange],
                ['Alpha count', String(runMeta.alphaCount)],
              ])}
              ${summaryList('Risk posture', [
                ['Max exposure', `${fmtMoney(summary.maxExposure)} (${fmtPct(summary.maxExposurePct)})`],
                ['Max drawdown', `${fmtMoney(summary.maxDrawdown)} (${fmtPct(summary.maxDrawdownPct)})`],
                ['Open positions', fmtNumber(summary.openPositions)],
              ])}
              ${summaryList('Trading quality', [
                ['Win rate', fmtPct(summary.winRate)],
                ['Avg winner', fmtMoney(summary.avgWin)],
                ['Avg loser', fmtMoney(summary.avgLoss)],
              ])}
            </div>
          </div>
          <div class="panel">
            <h2>Verification</h2>
            <div class="verification">${verification.map(verificationPill).join('')}</div>
            <div class="timeline" style="margin-top: 16px;">
              ${verification.map((item) => timelineItem(item.name, item.detail, item.passed ? 'Passed' : 'Failed')).join('')}
            </div>
          </div>
        </section>

        <section class="dual">
          <div class="panel">
            <h2>Equity Curve</h2>
            <div class="chart" id="equityChart">${lineChart(snapshot.charts.equityCurve, 'equity', fmtMoney)}</div>
          </div>
          <div class="panel">
            <h2>Event Mix</h2>
            <div class="bars">${barChart(snapshot.charts.eventMix, 'eventType', 'count')}</div>
          </div>
        </section>

        <section class="dual">
          <div class="panel">
            <h2>Positions</h2>
            ${tableFor(snapshot.tables.positions || [], ['symbol', 'quantity', 'avgEntryPrice', 'realizedPnl', 'unrealizedPnl'])}
          </div>
          <div class="panel">
            <h2>Orders</h2>
            ${tableFor(snapshot.tables.orders || [], ['timestampNs', 'orderId', 'symbol', 'side', 'quantity', 'status', 'filledQuantity', 'fillPrice', 'fees'])}
          </div>
        </section>

        <section class="dual">
          <div class="panel">
            <h2>Trades</h2>
            ${tableFor(snapshot.tables.trades || [], ['orderId', 'symbol', 'side', 'requestedQuantity', 'filledQuantity', 'fillPrice', 'realizedPnl', 'fees', 'slippageBps'])}
          </div>
          <div class="panel">
            <h2>Alerts</h2>
            ${tableFor(snapshot.tables.alerts || [], ['timestampNs', 'severity', 'layer', 'alertName', 'message', 'active'])}
          </div>
        </section>

        <section class="dual">
          <div class="panel">
            <h2>State Transitions</h2>
            ${tableFor(snapshot.tables.stateTransitions || [], ['timestampNs', 'machine', 'from', 'to', 'trigger'])}
          </div>
          <div class="panel">
            <h2>Configuration Surface</h2>
            <div class="triple">
              ${summaryList('Config', [
                ['Author', config.author],
                ['Version', config.version],
                ['Mode', config.mode],
              ])}
              ${summaryList('Universe', [
                ['Symbols', (config.symbols || []).join(', ') || 'n/a'],
                ['Regime engine', config.regimeEngine || 'none'],
                ['Account equity', fmtMoney(config.risk.accountEquity)],
              ])}
              ${summaryList('Risk limits', [
                ['Max position', fmtNumber(config.risk.maxPositionPerSymbol)],
                ['Max gross', fmtPct(config.risk.maxGrossExposurePct)],
                ['Max drawdown', fmtPct(config.risk.maxDrawdownPct)],
              ])}
            </div>
            <p class="footnote" style="margin-top: 14px;">Parameter overrides are executed through alpha discovery and bootstrap before the orchestrator enters READY. The control surface intentionally reflects that provenance instead of mutating state in-browser.</p>
          </div>
        </section>

        <section class="panel">
          <h2>Operator Notes</h2>
          <ul class="list">
            ${(snapshot.notes || []).map((note) => `<li class="list-item">${escapeHtml(note)}</li>`).join('')}
          </ul>
        </section>
      `;
    }

    function metricCard(label, value, detail) {
      return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(detail)}</small></article>`;
    }

    function summaryList(title, rows) {
      return `
        <div class="list-item">
          <strong>${escapeHtml(title)}</strong>
          ${rows.map(([label, value]) => `<div class="timeline-item"><div class="timeline-time">${escapeHtml(label)}</div><div>${escapeHtml(value)}</div></div>`).join('')}
        </div>
      `;
    }

    function timelineItem(time, detail, status) {
      return `<div class="timeline-item"><div class="timeline-time">${escapeHtml(status)}</div><div><strong>${escapeHtml(time)}</strong><div class="muted">${escapeHtml(detail)}</div></div></div>`;
    }

    function lineChart(rows, key, formatter) {
      if (!rows || !rows.length) {
        return '<div class="empty">No series available.</div>';
      }
      const width = 820;
      const height = 240;
      const padding = 18;
      const values = rows.map((row) => Number(row[key]));
      const min = Math.min(...values);
      const max = Math.max(...values);
      const span = max - min || 1;
      const points = rows.map((row, index) => {
        const x = padding + (index / Math.max(rows.length - 1, 1)) * (width - padding * 2);
        const y = height - padding - ((Number(row[key]) - min) / span) * (height - padding * 2);
        return `${x},${y}`;
      }).join(' ');
      const last = values[values.length - 1];
      return `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Line chart">
          <defs>
            <linearGradient id="lineFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="rgba(182, 109, 45, 0.26)"></stop>
              <stop offset="100%" stop-color="rgba(182, 109, 45, 0.02)"></stop>
            </linearGradient>
          </defs>
          <rect x="0" y="0" width="${width}" height="${height}" rx="20" fill="rgba(255,255,255,0.36)"></rect>
          <polyline fill="none" stroke="rgba(20, 37, 58, 0.16)" stroke-width="1" points="${padding},${height - padding} ${width - padding},${height - padding}"></polyline>
          <polyline fill="none" stroke="rgba(182, 109, 45, 0.95)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" points="${points}"></polyline>
          <circle cx="${padding + (width - padding * 2)}" cy="${height - padding - ((last - min) / span) * (height - padding * 2)}" r="6" fill="rgba(20, 37, 58, 0.92)"></circle>
          <text x="${padding}" y="26" fill="rgba(20, 37, 58, 0.72)" font-size="14">Start: ${formatter(values[0])}</text>
          <text x="${width - padding}" y="26" text-anchor="end" fill="rgba(20, 37, 58, 0.72)" font-size="14">End: ${formatter(last)}</text>
        </svg>
      `;
    }

    function barChart(rows, labelKey, valueKey) {
      if (!rows || !rows.length) {
        return '<div class="empty">No event distribution available.</div>';
      }
      const max = Math.max(...rows.map((row) => Number(row[valueKey]))) || 1;
      return rows.map((row) => {
        const height = Math.max(8, Math.round((Number(row[valueKey]) / max) * 180));
        return `
          <div class="bar">
            <div class="bar-value">${fmtNumber(row[valueKey])}</div>
            <div class="bar-visual" style="height:${height}px"></div>
            <div class="bar-label">${escapeHtml(row[labelKey])}</div>
          </div>
        `;
      }).join('');
    }

    function tableFor(rows, columns) {
      if (!rows || !rows.length) {
        return '<div class="empty-state" style="min-height: 180px;">No rows for this section.</div>';
      }
      return `
        <div class="table-wrap">
          <table>
            <thead><tr>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('')}</tr></thead>
            <tbody>
              ${rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(renderCell(row[column], column))}</td>`).join('')}</tr>`).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    function renderCell(value, column) {
      if (value === null || value === undefined || value === '') return 'n/a';
      if (column.toLowerCase().includes('pnl') || column === 'fees' || column.toLowerCase().includes('equity') || column === 'fillPrice' || column === 'avgEntryPrice') {
        return fmtMoney(value);
      }
      if (column.toLowerCase().includes('pct')) {
        return fmtPct(value);
      }
      if (column.toLowerCase().includes('timestamp')) {
        return fmtTs(Number(value));
      }
      if (typeof value === 'boolean') {
        return value ? 'true' : 'false';
      }
      if (typeof value === 'number') {
        return fmtNumber(value, Number.isInteger(value) ? 0 : 3);
      }
      return String(value);
    }

    async function loadBootstrap() {
      const payload = await fetchJson('/api/bootstrap');
      state.bootstrap = payload;
      renderBootstrap();
    }

    async function loadLatest() {
      const payload = await fetchJson('/api/runs/latest');
      state.snapshot = payload.snapshot;
      renderSnapshot();
      if (state.snapshot) {
        setMessage('Loaded latest snapshot from the current server session.', 'success');
      }
    }

    async function submitRun(event) {
      event.preventDefault();
      els.runButton.disabled = true;
      setMessage('Running backtest through the deterministic pipeline...', 'muted');

      const payload = {
        demo: els.demoToggle.checked,
        configPath: els.configPath.value.trim(),
        symbols: parseSymbols(els.symbols.value),
        startDate: els.startDate.value || null,
        endDate: els.endDate.value || null,
        noCache: els.noCache.checked,
      };

      try {
        const response = await fetchJson('/api/backtests/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        state.snapshot = response.snapshot;
        renderSnapshot();
        setMessage('Run completed and snapshot refreshed.', 'success');
      } catch (error) {
        setMessage(error.message || 'Run failed.', 'error');
      } finally {
        els.runButton.disabled = false;
      }
    }

    els.runForm.addEventListener('submit', submitRun);
    els.loadLatestButton.addEventListener('click', () => {
      loadLatest().catch((error) => setMessage(error.message || 'Failed to load latest snapshot.', 'error'));
    });

    loadBootstrap()
      .then(loadLatest)
      .catch((error) => setMessage(error.message || 'Failed to load bootstrap data.', 'error'));
  </script>
</body>
</html>
"""