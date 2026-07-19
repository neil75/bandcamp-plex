"""Approval-mode review: generate HTML for user confirmation before downloading."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

log = logging.getLogger(__name__)


@dataclass
class PendingItem:
    key: str
    artist: str
    title: str
    item_type: str


def load_decisions(decisions_file: Path) -> dict[str, list[str]] | None:
    if not decisions_file.exists():
        return None
    try:
        data = json.loads(decisions_file.read_text())
        return {
            "download": data.get("download", []),
            "skip": data.get("skip", []),
        }
    except Exception:
        log.exception("Could not read decisions file %s", decisions_file)
        return None


def clear_decisions(decisions_file: Path) -> None:
    try:
        decisions_file.unlink()
    except FileNotFoundError:
        pass


def write_pending(items: Sequence[PendingItem], pending_file: Path) -> None:
    pending_file.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(item) for item in items]
    pending_file.write_text(json.dumps(data, indent=2))
    log.info("Wrote %d pending item(s) to %s", len(items), pending_file)


def generate_review_html(items: Sequence[PendingItem], html_file: Path) -> None:
    html_file.parent.mkdir(parents=True, exist_ok=True)
    items_json = json.dumps([asdict(i) for i in items])
    html = _REVIEW_TEMPLATE.replace("/* ITEMS_DATA */", items_json)
    html_file.write_text(html)
    log.info("Review HTML generated at %s", html_file)


_REVIEW_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bandcamp-Plex Review</title>
<style>
:root {
  --bg: #fff; --fg: #1a1a1a; --card: #f5f5f5; --border: #ddd;
  --accent: #1db954; --accent-hover: #1ed760; --skip: #e74c3c;
  --muted: #666;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #1a1a1a; --fg: #eee; --card: #2a2a2a; --border: #444;
    --accent: #1db954; --accent-hover: #1ed760; --skip: #e74c3c;
    --muted: #999;
  }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg);
  padding: 1rem; max-width: 900px; margin: 0 auto;
  line-height: 1.5;
}
h1 { margin-bottom: 0.5rem; font-size: 1.5rem; }
.info { color: var(--muted); margin-bottom: 1rem; font-size: 0.9rem; }
.controls { display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 1rem; }
.controls button, .save-btn {
  padding: 0.5rem 1rem; border: none; border-radius: 4px;
  cursor: pointer; font-size: 0.9rem; font-weight: 500;
}
.controls button { background: var(--card); color: var(--fg); border: 1px solid var(--border); }
.controls button:hover { background: var(--border); }
.save-btn {
  background: var(--accent); color: #fff; font-size: 1rem;
  padding: 0.75rem 1.5rem; margin-top: 1rem;
}
.save-btn:hover { background: var(--accent-hover); }
.counter { color: var(--muted); font-size: 0.85rem; margin-bottom: 0.5rem; }
.item {
  display: flex; align-items: center; gap: 0.75rem;
  padding: 0.75rem; margin-bottom: 0.5rem;
  background: var(--card); border-radius: 6px;
  border: 1px solid var(--border);
}
.item.skipped { opacity: 0.5; }
.item label { flex: 1; cursor: pointer; display: flex; flex-direction: column; }
.item .artist { font-weight: 600; }
.item .title { color: var(--muted); font-size: 0.9rem; }
.item .type-badge {
  font-size: 0.7rem; text-transform: uppercase; padding: 0.15rem 0.4rem;
  border-radius: 3px; background: var(--border); color: var(--muted);
  align-self: flex-start; margin-top: 0.2rem;
}
input[type="checkbox"] { width: 1.2rem; height: 1.2rem; cursor: pointer; }
.search { width: 100%; padding: 0.5rem; margin-bottom: 1rem;
  border: 1px solid var(--border); border-radius: 4px;
  background: var(--card); color: var(--fg); font-size: 0.9rem;
}
.hidden { display: none; }
</style>
</head>
<body>
<h1>Bandcamp-Plex Review</h1>
<p class="info">
  These items were found on Bandcamp but not matched in your Plex library.
  Check items to download, uncheck to skip permanently.
  Click "Save Decisions" when done and place the downloaded file in your
  bandcamp-plex state directory.
</p>
<input type="text" class="search" id="search" placeholder="Filter by artist or title...">
<div class="controls">
  <button onclick="selectAll()">Select All</button>
  <button onclick="selectNone()">Select None</button>
  <button onclick="invertSelection()">Invert</button>
</div>
<div class="counter" id="counter"></div>
<div id="items"></div>
<button class="save-btn" onclick="saveDecisions()">Save Decisions</button>

<script>
const items = /* ITEMS_DATA */;
const container = document.getElementById('items');
const counter = document.getElementById('counter');
const search = document.getElementById('search');

function render() {
  const filter = search.value.toLowerCase();
  container.innerHTML = '';
  items.forEach((item, i) => {
    const text = (item.artist + ' ' + item.title).toLowerCase();
    if (filter && !text.includes(filter)) return;
    const div = document.createElement('div');
    div.className = 'item' + (item._skip ? ' skipped' : '');
    div.innerHTML = `
      <input type="checkbox" id="cb${i}" ${item._skip ? '' : 'checked'}
             onchange="toggle(${i}, this.checked)">
      <label for="cb${i}">
        <span class="artist">${esc(item.artist)}</span>
        <span class="title">${esc(item.title)}</span>
      </label>
      <span class="type-badge">${item.item_type}</span>
    `;
    container.appendChild(div);
  });
  updateCounter();
}

function toggle(i, checked) {
  items[i]._skip = !checked;
  const el = document.querySelector(`#cb${i}`).closest('.item');
  el.className = 'item' + (items[i]._skip ? ' skipped' : '');
  updateCounter();
}

function selectAll() { items.forEach(it => it._skip = false); render(); }
function selectNone() { items.forEach(it => it._skip = true); render(); }
function invertSelection() { items.forEach(it => it._skip = !it._skip); render(); }

function updateCounter() {
  const dl = items.filter(it => !it._skip).length;
  const sk = items.filter(it => it._skip).length;
  counter.textContent = `${dl} to download, ${sk} to skip (${items.length} total)`;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function saveDecisions() {
  const decisions = { download: [], skip: [] };
  items.forEach(item => {
    if (item._skip) decisions.skip.push(item.key);
    else decisions.download.push(item.key);
  });
  const blob = new Blob([JSON.stringify(decisions, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'decisions.json';
  a.click();
  URL.revokeObjectURL(url);
}

search.addEventListener('input', render);
items.forEach(it => it._skip = false);
render();
</script>
</body>
</html>
"""
