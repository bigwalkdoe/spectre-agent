from __future__ import annotations

import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Any

from spectre.state import load_state

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Spectre Dashboard</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       background: #0f172a; color: #e2e8f0; padding: 2rem; }
h1 { font-size: 1.5rem; margin-bottom: .5rem; color: #38bdf8; }
p.sub { color: #64748b; margin-bottom: 2rem; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: .75rem .5rem; border-bottom: 1px solid #334155;
     color: #94a3b8; font-size: .75rem; text-transform: uppercase; letter-spacing: .05em; }
td { padding: .75rem .5rem; border-bottom: 1px solid #1e293b; font-size: .875rem; }
.status-healthy { color: #22c55e; }
.status-failed { color: #ef4444; }
.status-rolled_back { color: #f59e0b; }
.status-pending { color: #64748b; }
tr:hover { background: #1e293b; }
.steps { font-size: .75rem; color: #64748b; margin-top: .25rem; }
.step-ok { color: #22c55e; }
.step-fail { color: #ef4444; }
a { color: #38bdf8; cursor: pointer; }
summary { cursor: pointer; color: #94a3b8; padding: .25rem 0; }
</style>
</head>
<body>
<h1>Spectre Dashboard</h1>
<p class="sub">deployment history</p>
<div id="root">loading...</div>
<script>
async function load() {
  const r = await fetch('/api/deployments');
  const data = await r.json();
  const root = document.getElementById('root');
  if (!data.length) { root.innerHTML = '<p>no deployments</p>'; return; }
  let html = '<table><thead><tr><th>Service</th><th>Env</th>';
  html += '<th>Version</th><th>Status</th><th>Started</th><th>Steps</th></tr></thead><tbody>';
  for (const d of data) {
    html += '<tr>';
    html += '<td>' + esc(d.service) + '</td>';
    html += '<td>' + esc(d.environment) + '</td>';
    html += '<td>' + esc(d.version) + '</td>';
    html += '<td class="status-' + d.status + '">' + esc(d.status) + '</td>';
    html += '<td>' + esc(d.started_at || '-') + '</td>';
    html += '<td>';
    if (d.steps && d.steps.length) {
      html += '<details><summary>' + d.steps.length + ' step(s)</summary>';
      for (const s of d.steps) {
        const cls = s.status === 'healthy' ? 'step-ok' : 'step-fail';
        html += '<div class="steps"><span class="' + cls + '">' + esc(s.stage)
            + '</span>: ' + esc(s.message) + ' (' + s.duration_ms + 'ms)</div>';
      }
      html += '</details>';
    } else {
      html += '-';
    }
    html += '</td></tr>';
  }
  html += '</tbody></table>';
  root.innerHTML = html;
}
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
load();
setInterval(load, 5000);
</script>
</body>
</html>"""


class _Handler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/api/deployments":
            self._serve_json()
        elif self.path in ("/", "/index.html"):
            self._serve_html()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

    def _serve_json(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        deployments = load_state()
        data = json.dumps([d.to_dict() for d in deployments], indent=2)
        self.wfile.write(data.encode())

    def _serve_html(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_PAGE.encode())

    def log_message(self, format: str, *args: Any) -> None:
        pass


def serve(host: str = "127.0.0.1", port: int = 8080) -> None:
    server = HTTPServer((host, port), _Handler)
    print(f"Spectre dashboard at http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
        server.server_close()
