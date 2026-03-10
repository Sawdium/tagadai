#!/usr/bin/env python3
"""
Danger Stats Tool - Display MapDanger operation cost statistics from leek registers.

Reads d_* registers written by MapDanger._flushDangerStats() and displays
aggregated stats per item, grouped by dimension keys.

Usage:
    python -m src.tools.dangerstats                # Display all stats
    python -m src.tools.dangerstats --html          # Open HTML dashboard in browser
    python -m src.tools.dangerstats --clear         # Clear all d_* registers
    python -m src.tools.dangerstats --json          # JSON output
"""

import sys
import json
import argparse
import tempfile
import webbrowser
from collections import defaultdict
from pathlib import Path

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError


# Dimension key labels for display
TURN_LABELS = {"1": "T1", "2": "T2", "3": "T3", "w": "T4+"}
MP_LABELS = {"l": "0-3", "m": "4-6", "h": "7-9", "x": "10+"}

# Items to exclude from display (no longer monitored)
EXCLUDED_ITEMS = {"burning", "repotting"}


def parse_dims(dims: str) -> dict:
    """Parse a dims key like '2mj' into structured components."""
    turn = dims[0]
    mp = dims[1]
    flags = dims[2:]
    return {
        "turn": TURN_LABELS.get(turn, turn),
        "mp": MP_LABELS.get(mp, mp),
        "jump": "j" in flags,
        "teleport": "t" in flags,
    }


def parse_register_value(value: str) -> list:
    """Parse pipe-separated entries like '1l:2345,3|2m:456,5' into list of dicts."""
    entries = []
    for part in value.split("|"):
        if not part or ":" not in part:
            continue
        dims, rest = part.split(":", 1)
        if "," not in rest:
            continue
        kops_str, count_str = rest.split(",", 1)
        try:
            entries.append({
                "dims": dims,
                "kops": float(kops_str),
                "count": int(float(count_str)),
            })
        except ValueError:
            continue
    return entries


def aggregate_entries(entries: list) -> dict:
    """Group entries by dims and compute totals."""
    grouped = defaultdict(lambda: {"total_kops": 0.0, "total_count": 0})
    for e in entries:
        g = grouped[e["dims"]]
        g["total_kops"] += e["kops"]
        g["total_count"] += e["count"]
    # Compute averages
    result = {}
    for dims, g in grouped.items():
        avg = g["total_kops"] / g["total_count"] if g["total_count"] > 0 else 0
        result[dims] = {
            "avg_kops": round(avg),
            "total_count": g["total_count"],
            "total_kops": round(g["total_kops"]),
        }
    return result


def display_stats(registers: dict):
    """Display formatted danger stats."""
    # Filter d_* keys and parse
    items = {}
    for key, value in sorted(registers.items()):
        if not key.startswith("d_"):
            continue
        item_name = key[2:]
        if item_name in EXCLUDED_ITEMS:
            continue
        entries = parse_register_value(value)
        if entries:
            items[item_name] = aggregate_entries(entries)

    if not items:
        print("No danger stats found in registers.")
        return

    print(f"{'ITEM':<20} {'DIMS':<10} {'AVG kOps':>10} {'SAMPLES':>8}")
    print("=" * 52)

    for item_name in sorted(items.keys()):
        dims_data = items[item_name]
        first = True
        # Sort dims by avg cost descending
        for dims in sorted(dims_data.keys(), key=lambda d: -dims_data[d]["avg_kops"]):
            d = dims_data[dims]
            parsed = parse_dims(dims)
            flags = ""
            if parsed["jump"]:
                flags += "+J"
            if parsed["teleport"]:
                flags += "+T"
            dims_label = f"{parsed['turn']} MP{parsed['mp']}{flags}"
            name_col = item_name if first else ""
            print(f"{name_col:<20} {dims_label:<10} {d['avg_kops']:>10,} {d['total_count']:>8}")
            first = False
        # Item total
        total_kops = sum(d["total_kops"] for d in dims_data.values())
        total_count = sum(d["total_count"] for d in dims_data.values())
        avg_total = round(total_kops / total_count) if total_count > 0 else 0
        print(f"{'':>20} {'TOTAL':<10} {avg_total:>10,} {total_count:>8}")
        print("-" * 52)


def build_html(items: dict, leek_name: str, raw_registers: dict) -> str:
    """Build self-contained HTML dashboard."""
    # Prepare data for JS
    js_data = json.dumps(items)
    raw_data = {k: v for k, v in raw_registers.items() if k.startswith("d_")}
    js_raw = json.dumps(raw_data)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>MapDanger Stats - {leek_name}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
         background: #1a1a2e; color: #e0e0e0; padding: 20px; max-width: 1400px; margin: 0 auto; }}
  h1 {{ color: #e94560; margin-bottom: 4px; font-size: 22px; }}
  .subtitle {{ color: #777; font-size: 13px; margin-bottom: 20px; }}
  h2 {{ color: #e94560; font-size: 16px; margin: 28px 0 12px 0; }}
  h2:first-of-type {{ margin-top: 0; }}

  /* Summary cards */
  .summary {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .card {{ background: #16213e; border-radius: 8px; padding: 16px 20px; min-width: 140px; }}
  .card .label {{ color: #888; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }}
  .card .value {{ color: #e94560; font-size: 28px; font-weight: bold; margin-top: 4px; }}
  .card .unit {{ color: #666; font-size: 13px; }}

  /* Filter bar */
  .filters {{ background: #16213e; border-radius: 8px; padding: 14px 18px; margin-bottom: 24px;
              display: flex; gap: 24px; flex-wrap: wrap; align-items: center; }}
  .filter-group {{ display: flex; align-items: center; gap: 8px; }}
  .filter-group .filter-label {{ color: #888; font-size: 11px; text-transform: uppercase;
                                  letter-spacing: 1px; margin-right: 4px; }}
  .filter-btn {{ background: #0f3460; color: #aaa; border: 1px solid #1a2744; border-radius: 4px;
                 padding: 4px 10px; font-size: 12px; cursor: pointer; font-family: inherit;
                 transition: all 0.15s; }}
  .filter-btn:hover {{ border-color: #e94560; color: #e0e0e0; }}
  .filter-btn.active {{ background: #e94560; color: #fff; border-color: #e94560; }}
  .filter-reset {{ background: none; border: 1px solid #333; color: #888; border-radius: 4px;
                   padding: 4px 10px; font-size: 12px; cursor: pointer; font-family: inherit; }}
  .filter-reset:hover {{ border-color: #e94560; color: #e94560; }}

  /* Bar chart */
  .barchart {{ background: #16213e; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }}
  .bar-row {{ display: flex; align-items: center; margin-bottom: 4px; }}
  .bar-row .bar-label {{ width: 180px; font-size: 13px; color: #e94560; font-weight: 600;
                         text-align: right; padding-right: 12px; flex-shrink: 0;
                         white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .bar-row .bar-track {{ flex: 1; height: 20px; background: #1a1a2e; border-radius: 3px;
                         position: relative; overflow: hidden; }}
  .bar-row .bar-fill {{ height: 100%; border-radius: 3px; transition: width 0.3s; }}
  .bar-row .bar-value {{ position: absolute; right: 8px; top: 0; line-height: 20px;
                         font-size: 11px; color: #ccc; font-variant-numeric: tabular-nums; }}

  /* Heatmap */
  .heatmap-container {{ background: #16213e; border-radius: 8px; padding: 16px 20px;
                        margin-bottom: 24px; overflow-x: auto; }}
  .heatmap {{ border-collapse: collapse; }}
  .heatmap th {{ background: #16213e; color: #e94560; padding: 6px 14px; font-size: 12px;
                 text-transform: uppercase; letter-spacing: 1px; text-align: center;
                 position: sticky; top: 0; }}
  .heatmap td {{ padding: 4px 14px; text-align: center; font-size: 12px; font-variant-numeric: tabular-nums;
                 border: 1px solid #1a1a2e; min-width: 70px; }}
  .heatmap .hm-item {{ text-align: right; color: #e94560; font-weight: 600; padding-right: 12px;
                       border: none; white-space: nowrap; }}

  /* Jump multiplier table */
  .jump-table {{ background: #16213e; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }}
  .jump-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 6px; }}
  .jump-row {{ display: flex; justify-content: space-between; padding: 4px 8px; border-radius: 4px; }}
  .jump-row:hover {{ background: #1a2744; }}
  .jump-name {{ color: #e94560; font-size: 13px; font-weight: 600; }}
  .jump-mult {{ font-size: 13px; font-variant-numeric: tabular-nums; }}
  .jump-mult.high {{ color: #ff6b6b; }}
  .jump-mult.mid {{ color: #ffa726; }}
  .jump-mult.low {{ color: #66bb6a; }}

  /* Main table */
  table.main {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
  table.main th {{ background: #16213e; color: #e94560; text-align: left; padding: 10px 12px;
       font-size: 12px; text-transform: uppercase; letter-spacing: 1px;
       position: sticky; top: 0; cursor: pointer; user-select: none; z-index: 2; }}
  table.main th:hover {{ background: #1a2744; }}
  table.main th .arrow {{ font-size: 10px; margin-left: 4px; opacity: 0.5; }}
  table.main th.sorted .arrow {{ opacity: 1; }}
  table.main td {{ padding: 8px 12px; border-bottom: 1px solid #222; font-size: 14px; }}
  table.main tr:hover td {{ background: #16213e; }}
  .item-name {{ color: #e94560; font-weight: 600; }}
  .dims {{ color: #aaa; }}
  .flag {{ display: inline-block; background: #0f3460; color: #e94560; border-radius: 3px;
           padding: 1px 5px; font-size: 11px; margin-left: 4px; }}
  .bar-cell {{ position: relative; }}
  .bar {{ position: absolute; left: 0; top: 0; bottom: 0; background: #e9456022; border-radius: 2px; }}
  .bar-val {{ position: relative; z-index: 1; font-variant-numeric: tabular-nums; }}
  .pct {{ color: #888; font-size: 12px; font-variant-numeric: tabular-nums; }}
  tr.group-header {{ cursor: pointer; }}
  tr.group-header td {{ background: #0f1a33; font-weight: 600; border-bottom: 1px solid #333; }}
  tr.group-header:hover td {{ background: #132244; }}
  tr.group-child td {{ padding-left: 28px; font-size: 13px; color: #bbb; }}
  tr.group-child.hidden {{ display: none; }}
  .toggle {{ display: inline-block; width: 16px; color: #888; font-size: 12px; }}

  /* Scatter plot */
  .scatter-container {{ background: #16213e; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; position: relative; }}
  .scatter-canvas {{ display: block; width: 100%; }}
  .scatter-tooltip {{ position: absolute; background: #0f1a33; border: 1px solid #e94560; border-radius: 4px;
                      padding: 6px 10px; font-size: 12px; color: #eee; pointer-events: none; display: none; z-index: 10; }}
  .scatter-legend {{ display: flex; gap: 16px; margin-top: 8px; justify-content: center; }}
  .scatter-legend span {{ font-size: 11px; color: #888; }}

  /* Optimization targets */
  .targets {{ background: #16213e; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }}
  .target-row {{ display: flex; align-items: center; gap: 12px; padding: 6px 8px; border-radius: 4px; }}
  .target-row:hover {{ background: #1a2744; }}
  .target-rank {{ color: #e94560; font-weight: 700; font-size: 18px; width: 28px; text-align: right; }}
  .target-info {{ flex: 1; }}
  .target-name {{ color: #e94560; font-weight: 600; font-size: 14px; }}
  .target-detail {{ color: #888; font-size: 12px; margin-top: 2px; }}
  .target-score {{ color: #ffa726; font-size: 16px; font-weight: 600; font-variant-numeric: tabular-nums; }}
  .target-bar {{ flex: 1; height: 8px; background: #1a1a2e; border-radius: 4px; overflow: hidden; max-width: 200px; }}
  .target-bar-fill {{ height: 100%; background: #e94560; border-radius: 4px; }}

  /* Stacked bars */
  .stacked-container {{ background: #16213e; border-radius: 8px; padding: 16px 20px; margin-bottom: 24px; }}
  .stacked-row {{ display: flex; align-items: center; margin-bottom: 5px; }}
  .stacked-label {{ width: 180px; font-size: 13px; color: #e94560; font-weight: 600;
                    text-align: right; padding-right: 12px; flex-shrink: 0;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .stacked-track {{ flex: 1; height: 20px; display: flex; border-radius: 3px; overflow: hidden; }}
  .stacked-seg {{ height: 100%; position: relative; min-width: 1px; }}
  .stacked-seg span {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
                       font-size: 10px; color: #fff; font-weight: 600; }}
  .stacked-legend {{ display: flex; gap: 16px; margin-bottom: 10px; }}
  .stacked-legend-item {{ display: flex; align-items: center; gap: 4px; font-size: 12px; color: #aaa; }}
  .stacked-legend-swatch {{ width: 12px; height: 12px; border-radius: 2px; }}

  .empty {{ color: #555; text-align: center; padding: 40px; }}
  .raw {{ margin-top: 32px; }}
  .raw summary {{ cursor: pointer; color: #888; font-size: 13px; }}
  .raw pre {{ background: #16213e; padding: 12px; border-radius: 6px; margin-top: 8px;
              font-size: 12px; overflow-x: auto; color: #aaa; white-space: pre-wrap; word-break: break-all; }}
  .section-row {{ display: flex; gap: 24px; margin-bottom: 0; }}
  .section-row > div {{ flex: 1; min-width: 0; }}
  @media (max-width: 900px) {{ .section-row {{ flex-direction: column; }} }}
</style>
</head>
<body>

<h1>MapDanger Operation Cost Stats</h1>
<div class="subtitle">{leek_name} &mdash; generated by dangerstats</div>

<div id="summary" class="summary"></div>

<!-- Filter bar -->
<div class="filters" id="filters">
  <div class="filter-group">
    <span class="filter-label">Turn</span>
    <button class="filter-btn active" data-group="turn" data-val="1">T1</button>
    <button class="filter-btn active" data-group="turn" data-val="2">T2</button>
    <button class="filter-btn active" data-group="turn" data-val="3">T3</button>
    <button class="filter-btn active" data-group="turn" data-val="w">T4+</button>
  </div>
  <div class="filter-group">
    <span class="filter-label">MP</span>
    <button class="filter-btn active" data-group="mp" data-val="l">0-3</button>
    <button class="filter-btn active" data-group="mp" data-val="m">4-6</button>
    <button class="filter-btn active" data-group="mp" data-val="h">7-9</button>
    <button class="filter-btn active" data-group="mp" data-val="x">10+</button>
  </div>
  <div class="filter-group">
    <span class="filter-label">Mobility</span>
    <button class="filter-btn active" data-group="mob" data-val="walk">Walk</button>
    <button class="filter-btn active" data-group="mob" data-val="jump">Jump</button>
    <button class="filter-btn active" data-group="mob" data-val="tp">TP</button>
  </div>
  <button class="filter-reset" id="filterReset">Reset</button>
</div>

<!-- Bar chart + Jump multiplier side by side -->
<div class="section-row">
  <div>
    <h2>Top Items by Avg kOps</h2>
    <div class="barchart" id="barchart"></div>
  </div>
  <div>
    <h2>Jump Cost Multiplier</h2>
    <div class="jump-table" id="jumpTable"></div>
  </div>
</div>

<!-- Scatter + Optimization targets side by side -->
<div class="section-row">
  <div>
    <h2>Avg kOps vs Frequency</h2>
    <div class="scatter-container">
      <canvas class="scatter-canvas" id="scatter" height="320"></canvas>
      <div class="scatter-tooltip" id="scatterTip"></div>
      <div class="scatter-legend">
        <span>X = samples (frequency) &mdash; Y = avg kOps &mdash; size = priority score</span>
      </div>
    </div>
  </div>
  <div>
    <h2>Optimization Targets</h2>
    <div class="targets" id="targets"></div>
  </div>
</div>

<!-- Heatmaps side by side -->
<div class="section-row">
  <div>
    <h2>Avg kOps by Item &times; Turn</h2>
    <div class="heatmap-container">
      <table class="heatmap" id="heatmap"></table>
    </div>
  </div>
  <div>
    <h2>Avg kOps by Item &times; MP</h2>
    <div class="heatmap-container">
      <table class="heatmap" id="heatmapMP"></table>
    </div>
  </div>
</div>

<!-- Mobility cost breakdown -->
<h2>Cost Breakdown: Walk vs Jump vs TP</h2>
<div class="stacked-container" id="stacked"></div>

<!-- Grouped table -->
<h2>Detailed Breakdown</h2>
<table class="main" id="table">
  <thead><tr>
    <th data-col="item">Item <span class="arrow">&#9650;</span></th>
    <th data-col="dims">Dims <span class="arrow">&#9650;</span></th>
    <th data-col="avg" data-type="num">Avg kOps <span class="arrow">&#9660;</span></th>
    <th data-col="samples" data-type="num">Samples <span class="arrow">&#9650;</span></th>
    <th data-col="total" data-type="num">Total kOps <span class="arrow">&#9650;</span></th>
    <th data-col="pct" data-type="num">% Budget <span class="arrow">&#9650;</span></th>
  </tr></thead>
  <tbody id="tbody"></tbody>
</table>

<details class="raw">
  <summary>Raw register data</summary>
  <pre id="rawdata"></pre>
</details>

<script>
const ITEMS = {js_data};
const RAW = {js_raw};
const TURN_LABELS = {{"1":"T1","2":"T2","3":"T3","w":"T4+"}};
const TURN_KEYS = ["1","2","3","w"];
const MP_LABELS = {{"l":"0-3","m":"4-6","h":"7-9","x":"10+"}};

// ─── Parse dims key ───
function parseDimsRaw(d) {{
  return {{ turn: d[0], mp: d[1], flags: d.slice(2) }};
}}
function parseDimsLabel(d) {{
  let p = parseDimsRaw(d);
  let parts = [(TURN_LABELS[p.turn]||p.turn), "MP"+(MP_LABELS[p.mp]||p.mp)];
  if (p.flags.includes("j")) parts.push('<span class="flag">Jump</span>');
  if (p.flags.includes("t")) parts.push('<span class="flag">TP</span>');
  return parts.join(" ");
}}
function getMobility(flags) {{
  if (flags.includes("t")) return "tp";
  if (flags.includes("j")) return "jump";
  return "walk";
}}

// ─── Build all rows ───
let allRows = [];
for (const [item, dims] of Object.entries(ITEMS)) {{
  for (const [dk, v] of Object.entries(dims)) {{
    let p = parseDimsRaw(dk);
    allRows.push({{ item, dims: dk, turn: p.turn, mp: p.mp, mob: getMobility(p.flags),
                    dimsLabel: parseDimsLabel(dk),
                    avg: v.avg_kops, samples: v.total_count, total: v.total_kops }});
  }}
}}
const grandTotal = allRows.reduce((s, r) => s + r.total, 0);
allRows.forEach(r => r.pct = grandTotal > 0 ? (r.total / grandTotal * 100) : 0);

// ─── Filter state ───
let filters = {{ turn: new Set(["1","2","3","w"]), mp: new Set(["l","m","h","x"]), mob: new Set(["walk","jump","tp"]) }};

function getFilteredRows() {{
  return allRows.filter(r => filters.turn.has(r.turn) && filters.mp.has(r.mp) && filters.mob.has(r.mob));
}}

// ─── Filter UI ───
document.querySelectorAll(".filter-btn").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const grp = btn.dataset.group, val = btn.dataset.val;
    if (filters[grp].has(val)) {{
      if (filters[grp].size > 1) {{ filters[grp].delete(val); btn.classList.remove("active"); }}
    }} else {{
      filters[grp].add(val); btn.classList.add("active");
    }}
    renderAll();
  }});
}});
document.getElementById("filterReset").addEventListener("click", () => {{
  filters.turn = new Set(["1","2","3","w"]);
  filters.mp = new Set(["l","m","h","x"]);
  filters.mob = new Set(["walk","jump","tp"]);
  document.querySelectorAll(".filter-btn").forEach(b => b.classList.add("active"));
  renderAll();
}});

// ─── Summary cards ───
function renderSummary(rows) {{
  const totalItems = new Set(rows.map(r => r.item)).size;
  const totalSamples = rows.reduce((s, r) => s + r.samples, 0);
  const filteredTotal = rows.reduce((s, r) => s + r.total, 0);
  const globalAvg = totalSamples > 0 ? Math.round(filteredTotal / totalSamples) : 0;
  const costliest = rows.length > 0 ? rows.reduce((a, b) => a.avg > b.avg ? a : b) : null;
  document.getElementById("summary").innerHTML = [
    {{ label: "Items", value: totalItems, unit: "" }},
    {{ label: "Total samples", value: totalSamples.toLocaleString(), unit: "" }},
    {{ label: "Global avg", value: globalAvg.toLocaleString(), unit: "kOps" }},
    {{ label: "Costliest", value: costliest ? costliest.avg.toLocaleString() : "-", unit: costliest ? costliest.item : "" }},
  ].map(c => `<div class="card"><div class="label">${{c.label}}</div><div class="value">${{c.value}}</div><div class="unit">${{c.unit}}</div></div>`).join("");
}}

// ─── 1. Bar chart: Top 20 items by avg kOps ───
function renderBarChart(rows) {{
  const byItem = {{}};
  rows.forEach(r => {{
    if (!byItem[r.item]) byItem[r.item] = {{ total: 0, count: 0 }};
    byItem[r.item].total += r.total;
    byItem[r.item].count += r.samples;
  }});
  const sorted = Object.entries(byItem)
    .map(([name, v]) => [name, v.count > 0 ? Math.round(v.total / v.count) : 0])
    .sort((a,b) => b[1]-a[1]).slice(0, 20);
  const maxVal = sorted.length > 0 ? sorted[0][1] : 1;
  const colors = ["#e94560","#ff6b6b","#ffa726","#ffca28","#66bb6a","#42a5f5","#ab47bc","#ec407a"];
  document.getElementById("barchart").innerHTML = sorted.map(([name, val], i) => {{
    const pct = (val / maxVal * 100).toFixed(1);
    const clr = colors[i % colors.length];
    return `<div class="bar-row">
      <div class="bar-label">${{name}}</div>
      <div class="bar-track">
        <div class="bar-fill" style="width:${{pct}}%;background:${{clr}}"></div>
        <span class="bar-value">${{val.toLocaleString()}} kOps</span>
      </div>
    </div>`;
  }}).join("") || '<div class="empty">No data</div>';
}}

// ─── 2. Heatmap: Item x Turn ───
function renderHeatmap(rows) {{
  const data = {{}};
  rows.forEach(r => {{
    if (!data[r.item]) data[r.item] = {{}};
    if (!data[r.item][r.turn]) data[r.item][r.turn] = {{ totalKops: 0, count: 0 }};
    data[r.item][r.turn].totalKops += r.total;
    data[r.item][r.turn].count += r.samples;
  }});
  // Sort items by weighted avg kOps desc
  const itemAvgs = {{}};
  rows.forEach(r => {{
    if (!itemAvgs[r.item]) itemAvgs[r.item] = {{ total: 0, count: 0 }};
    itemAvgs[r.item].total += r.total;
    itemAvgs[r.item].count += r.samples;
  }});
  const sortedItems = Object.keys(data).sort((a,b) => {{
    const avgA = itemAvgs[a] && itemAvgs[a].count > 0 ? itemAvgs[a].total / itemAvgs[a].count : 0;
    const avgB = itemAvgs[b] && itemAvgs[b].count > 0 ? itemAvgs[b].total / itemAvgs[b].count : 0;
    return avgB - avgA;
  }}).slice(0, 25);
  // Find global max avg for color scaling
  let maxAvg = 0;
  sortedItems.forEach(item => {{
    TURN_KEYS.forEach(t => {{
      if (data[item][t]) {{
        const avg = data[item][t].count > 0 ? data[item][t].totalKops / data[item][t].count : 0;
        if (avg > maxAvg) maxAvg = avg;
      }}
    }});
  }});
  function heatColor(val) {{
    if (val === 0) return "#1a1a2e";
    const ratio = Math.min(val / maxAvg, 1);
    const r = Math.round(30 + 203 * ratio);
    const g = Math.round(30 + 39 * (1 - ratio));
    const b = Math.round(46 + 50 * (1 - ratio));
    return `rgb(${{r}},${{g}},${{b}})`;
  }}
  let html = '<thead><tr><th></th>';
  TURN_KEYS.forEach(t => {{ html += `<th>${{TURN_LABELS[t]}}</th>`; }});
  html += '<th>Avg</th></tr></thead><tbody>';
  sortedItems.forEach(item => {{
    html += `<tr><td class="hm-item">${{item}}</td>`;
    let rowTotalKops = 0, rowTotalCount = 0;
    TURN_KEYS.forEach(t => {{
      const d = data[item][t];
      if (d && d.count > 0) {{
        const avg = Math.round(d.totalKops / d.count);
        rowTotalKops += d.totalKops;
        rowTotalCount += d.count;
        html += `<td style="background:${{heatColor(avg)}};color:#eee">${{avg.toLocaleString()}}</td>`;
      }} else {{
        html += `<td style="background:#1a1a2e;color:#444">-</td>`;
      }}
    }});
    const rowAvg = rowTotalCount > 0 ? Math.round(rowTotalKops / rowTotalCount) : 0;
    html += `<td style="color:#aaa">${{rowAvg.toLocaleString()}}</td></tr>`;
  }});
  html += '</tbody>';
  document.getElementById("heatmap").innerHTML = html;
}}

// ─── 3. Jump/teleport cost multiplier ───
function renderJumpMultiplier(rows) {{
  // For each item, compare avg kOps with jump/tp vs without
  const byItem = {{}};
  rows.forEach(r => {{
    if (!byItem[r.item]) byItem[r.item] = {{ walkTotal: 0, walkCount: 0, jumpTotal: 0, jumpCount: 0 }};
    if (r.mob === "walk") {{
      byItem[r.item].walkTotal += r.total;
      byItem[r.item].walkCount += r.samples;
    }} else {{
      byItem[r.item].jumpTotal += r.total;
      byItem[r.item].jumpCount += r.samples;
    }}
  }});
  const mults = [];
  for (const [name, v] of Object.entries(byItem)) {{
    if (v.walkCount > 0 && v.jumpCount > 0) {{
      const walkAvg = v.walkTotal / v.walkCount;
      const jumpAvg = v.jumpTotal / v.jumpCount;
      if (walkAvg > 0) mults.push({{ name, mult: jumpAvg / walkAvg, jumpAvg: Math.round(jumpAvg), walkAvg: Math.round(walkAvg) }});
    }}
  }}
  mults.sort((a,b) => b.mult - a.mult);
  document.getElementById("jumpTable").innerHTML = mults.length > 0
    ? '<div class="jump-grid">' + mults.map(m => {{
        const cls = m.mult >= 3 ? "high" : m.mult >= 1.5 ? "mid" : "low";
        return `<div class="jump-row">
          <span class="jump-name">${{m.name}}</span>
          <span class="jump-mult ${{cls}}">${{m.mult.toFixed(1)}}x</span>
        </div>`;
      }}).join("") + '</div>'
    : '<div class="empty">No items with both walk and jump/tp data</div>';
}}

// ─── Scatter plot: Avg kOps vs Frequency ───
function renderScatter(rows) {{
  const canvas = document.getElementById("scatter");
  const ctx = canvas.getContext("2d");
  const tip = document.getElementById("scatterTip");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const W = rect.width - 40;
  const H = 320;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + "px"; canvas.style.height = H + "px";
  ctx.scale(dpr, dpr);

  // Aggregate per item
  const byItem = {{}};
  rows.forEach(r => {{
    if (!byItem[r.item]) byItem[r.item] = {{ total: 0, count: 0 }};
    byItem[r.item].total += r.total;
    byItem[r.item].count += r.samples;
  }});
  const points = Object.entries(byItem).map(([name, v]) => {{
    const avg = v.count > 0 ? v.total / v.count : 0;
    const score = avg * Math.sqrt(v.count);
    return {{ name, freq: v.count, avg, score }};
  }});
  if (points.length === 0) {{ ctx.clearRect(0,0,W,H); return; }}

  const pad = {{ l: 60, r: 20, t: 15, b: 35 }};
  const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
  const maxFreq = Math.max(...points.map(p => p.freq));
  const maxAvg = Math.max(...points.map(p => p.avg));
  const maxScore = Math.max(...points.map(p => p.score));

  function toX(freq) {{ return pad.l + (freq / maxFreq) * pw; }}
  function toY(avg) {{ return pad.t + ph - (avg / maxAvg) * ph; }}
  function radius(score) {{ return 4 + (score / maxScore) * 14; }}

  ctx.clearRect(0, 0, W, H);

  // Grid lines
  ctx.strokeStyle = "#2a2a4a"; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {{
    const y = pad.t + (ph / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    ctx.fillStyle = "#666"; ctx.font = "11px monospace"; ctx.textAlign = "right";
    ctx.fillText(Math.round(maxAvg * (4 - i) / 4).toLocaleString(), pad.l - 8, y + 4);
  }}
  for (let i = 0; i <= 4; i++) {{
    const x = pad.l + (pw / 4) * i;
    ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, pad.t + ph); ctx.stroke();
    ctx.fillStyle = "#666"; ctx.font = "11px monospace"; ctx.textAlign = "center";
    ctx.fillText(Math.round(maxFreq * i / 4), x, H - pad.b + 16);
  }}

  // Axis labels
  ctx.fillStyle = "#888"; ctx.font = "11px monospace";
  ctx.textAlign = "center";
  ctx.fillText("samples", pad.l + pw / 2, H - 2);
  ctx.save(); ctx.translate(12, pad.t + ph / 2); ctx.rotate(-Math.PI/2);
  ctx.fillText("avg kOps", 0, 0); ctx.restore();

  // Draw dots
  points.forEach(p => {{
    const x = toX(p.freq), y = toY(p.avg), r = radius(p.score);
    // Color: red if high score, blue if low
    const ratio = p.score / maxScore;
    const cr = Math.round(66 + 167 * ratio);
    const cg = Math.round(187 - 120 * ratio);
    const cb = Math.round(245 - 149 * ratio);
    ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${{cr}},${{cg}},${{cb}},0.7)`;
    ctx.fill();
    ctx.strokeStyle = `rgba(${{cr}},${{cg}},${{cb}},1)`;
    ctx.lineWidth = 1; ctx.stroke();
    // Label top outliers
    if (ratio > 0.5) {{
      ctx.fillStyle = "#ccc"; ctx.font = "10px monospace"; ctx.textAlign = "left";
      ctx.fillText(p.name, x + r + 3, y + 3);
    }}
  }});

  // Hover tooltip
  canvas.onmousemove = (e) => {{
    const br = canvas.getBoundingClientRect();
    const mx = e.clientX - br.left, my = e.clientY - br.top;
    let hit = null;
    for (const p of points) {{
      const x = toX(p.freq), y = toY(p.avg), r = radius(p.score);
      if (Math.hypot(mx - x, my - y) <= r + 2) {{ hit = p; break; }}
    }}
    if (hit) {{
      tip.style.display = "block";
      tip.style.left = (e.clientX - canvas.parentElement.getBoundingClientRect().left + 12) + "px";
      tip.style.top = (e.clientY - canvas.parentElement.getBoundingClientRect().top - 10) + "px";
      tip.innerHTML = `<b>${{hit.name}}</b><br>avg: ${{Math.round(hit.avg).toLocaleString()}} kOps<br>samples: ${{hit.freq}}<br>score: ${{Math.round(hit.score).toLocaleString()}}`;
    }} else {{ tip.style.display = "none"; }}
  }};
  canvas.onmouseleave = () => {{ tip.style.display = "none"; }};
}}

// ─── Optimization Targets panel ───
function renderTargets(rows) {{
  const byItem = {{}};
  rows.forEach(r => {{
    if (!byItem[r.item]) byItem[r.item] = {{ total: 0, count: 0 }};
    byItem[r.item].total += r.total;
    byItem[r.item].count += r.samples;
  }});
  const targets = Object.entries(byItem).map(([name, v]) => {{
    const avg = v.count > 0 ? Math.round(v.total / v.count) : 0;
    const score = avg * Math.sqrt(v.count);
    return {{ name, avg, freq: v.count, score }};
  }}).sort((a,b) => b.score - a.score).slice(0, 10);
  const maxScore = targets.length > 0 ? targets[0].score : 1;
  document.getElementById("targets").innerHTML = targets.map((t, i) => {{
    const pct = (t.score / maxScore * 100).toFixed(0);
    return `<div class="target-row">
      <span class="target-rank">#${{i+1}}</span>
      <div class="target-info">
        <div class="target-name">${{t.name}}</div>
        <div class="target-detail">${{t.avg.toLocaleString()}} kOps avg &middot; ${{t.freq}} samples</div>
      </div>
      <div class="target-bar"><div class="target-bar-fill" style="width:${{pct}}%"></div></div>
      <span class="target-score">${{Math.round(t.score).toLocaleString()}}</span>
    </div>`;
  }}).join("") || '<div class="empty">No data</div>';
}}

// ─── Item x MP heatmap ───
const MP_KEYS = ["l","m","h","x"];
function renderHeatmapMP(rows) {{
  const data = {{}};
  rows.forEach(r => {{
    if (!data[r.item]) data[r.item] = {{}};
    if (!data[r.item][r.mp]) data[r.item][r.mp] = {{ totalKops: 0, count: 0 }};
    data[r.item][r.mp].totalKops += r.total;
    data[r.item][r.mp].count += r.samples;
  }});
  const itemAvgs = {{}};
  rows.forEach(r => {{
    if (!itemAvgs[r.item]) itemAvgs[r.item] = {{ total: 0, count: 0 }};
    itemAvgs[r.item].total += r.total;
    itemAvgs[r.item].count += r.samples;
  }});
  const sortedItems = Object.keys(data).sort((a,b) => {{
    const avgA = itemAvgs[a] && itemAvgs[a].count > 0 ? itemAvgs[a].total / itemAvgs[a].count : 0;
    const avgB = itemAvgs[b] && itemAvgs[b].count > 0 ? itemAvgs[b].total / itemAvgs[b].count : 0;
    return avgB - avgA;
  }}).slice(0, 25);
  let maxAvg = 0;
  sortedItems.forEach(item => {{
    MP_KEYS.forEach(m => {{
      if (data[item][m]) {{
        const avg = data[item][m].count > 0 ? data[item][m].totalKops / data[item][m].count : 0;
        if (avg > maxAvg) maxAvg = avg;
      }}
    }});
  }});
  function heatColor(val) {{
    if (val === 0) return "#1a1a2e";
    const ratio = Math.min(val / maxAvg, 1);
    const r = Math.round(30 + 203 * ratio);
    const g = Math.round(30 + 39 * (1 - ratio));
    const b = Math.round(46 + 50 * (1 - ratio));
    return `rgb(${{r}},${{g}},${{b}})`;
  }}
  let html = '<thead><tr><th></th>';
  MP_KEYS.forEach(m => {{ html += `<th>MP ${{MP_LABELS[m]}}</th>`; }});
  html += '<th>Avg</th></tr></thead><tbody>';
  sortedItems.forEach(item => {{
    html += `<tr><td class="hm-item">${{item}}</td>`;
    let rowTotal = 0, rowCount = 0;
    MP_KEYS.forEach(m => {{
      const d = data[item][m];
      if (d && d.count > 0) {{
        const avg = Math.round(d.totalKops / d.count);
        rowTotal += d.totalKops; rowCount += d.count;
        html += `<td style="background:${{heatColor(avg)}};color:#eee">${{avg.toLocaleString()}}</td>`;
      }} else {{
        html += `<td style="background:#1a1a2e;color:#444">-</td>`;
      }}
    }});
    const rowAvg = rowCount > 0 ? Math.round(rowTotal / rowCount) : 0;
    html += `<td style="color:#aaa">${{rowAvg.toLocaleString()}}</td></tr>`;
  }});
  html += '</tbody>';
  document.getElementById("heatmapMP").innerHTML = html;
}}

// ─── Stacked bars: Walk vs Jump vs TP ───
const MOB_COLORS = {{ walk: "#42a5f5", jump: "#ffa726", tp: "#e94560" }};
function renderStacked(rows) {{
  const byItem = {{}};
  rows.forEach(r => {{
    if (!byItem[r.item]) byItem[r.item] = {{ walk: {{ total: 0, count: 0 }}, jump: {{ total: 0, count: 0 }}, tp: {{ total: 0, count: 0 }} }};
    byItem[r.item][r.mob].total += r.total;
    byItem[r.item][r.mob].count += r.samples;
  }});
  // Only show items that have at least 2 mobility types
  const items = Object.entries(byItem).filter(([_, v]) => {{
    let types = 0;
    if (v.walk.count > 0) types++;
    if (v.jump.count > 0) types++;
    if (v.tp.count > 0) types++;
    return types >= 2;
  }});
  // Sort by jump+tp share descending
  items.sort((a, b) => {{
    const aTotal = a[1].walk.total + a[1].jump.total + a[1].tp.total;
    const bTotal = b[1].walk.total + b[1].jump.total + b[1].tp.total;
    const aJumpShare = aTotal > 0 ? (a[1].jump.total + a[1].tp.total) / aTotal : 0;
    const bJumpShare = bTotal > 0 ? (b[1].jump.total + b[1].tp.total) / bTotal : 0;
    return bJumpShare - aJumpShare;
  }});
  let html = '<div class="stacked-legend">';
  html += '<div class="stacked-legend-item"><div class="stacked-legend-swatch" style="background:#42a5f5"></div> Walk</div>';
  html += '<div class="stacked-legend-item"><div class="stacked-legend-swatch" style="background:#ffa726"></div> Jump</div>';
  html += '<div class="stacked-legend-item"><div class="stacked-legend-swatch" style="background:#e94560"></div> TP</div>';
  html += '</div>';
  items.forEach(([name, v]) => {{
    const total = v.walk.total + v.jump.total + v.tp.total;
    if (total === 0) return;
    html += `<div class="stacked-row"><div class="stacked-label">${{name}}</div><div class="stacked-track">`;
    ["walk","jump","tp"].forEach(mob => {{
      const pct = (v[mob].total / total * 100);
      if (pct > 0) {{
        const label = pct >= 8 ? Math.round(pct) + "%" : "";
        html += `<div class="stacked-seg" style="width:${{pct.toFixed(1)}}%;background:${{MOB_COLORS[mob]}}"><span>${{label}}</span></div>`;
      }}
    }});
    html += '</div></div>';
  }});
  document.getElementById("stacked").innerHTML = html || '<div class="empty">No data with multiple mobility types</div>';
}}

// ─── 4+5+6. Collapsible grouped table with % budget ───
let expanded = new Set();
let currentSort = "avg";
let currentDir = -1;

function renderTable(rows) {{
  // Group by item
  const groups = {{}};
  rows.forEach(r => {{
    if (!groups[r.item]) groups[r.item] = [];
    groups[r.item].push(r);
  }});
  // Compute group summaries
  const groupSummaries = Object.entries(groups).map(([item, children]) => {{
    const total = children.reduce((s,r) => s+r.total, 0);
    const samples = children.reduce((s,r) => s+r.samples, 0);
    const avg = samples > 0 ? Math.round(total / samples) : 0;
    const pct = grandTotal > 0 ? (total / grandTotal * 100) : 0;
    return {{ item, total, samples, avg, pct, children }};
  }});
  // Sort groups
  groupSummaries.sort((a,b) => {{
    let va = a[currentSort], vb = b[currentSort];
    if (currentSort === "item") return currentDir * String(va).localeCompare(String(vb));
    return currentDir * ((va||0) - (vb||0));
  }});

  const maxAvg = Math.max(...groupSummaries.map(g => g.avg), 1);
  const tbody = document.getElementById("tbody");
  let html = "";
  groupSummaries.forEach(g => {{
    const isOpen = expanded.has(g.item);
    const arrow = isOpen ? "&#9660;" : "&#9654;";
    const pctBar = g.avg / maxAvg * 100;
    html += `<tr class="group-header" data-item="${{g.item}}">
      <td class="item-name"><span class="toggle">${{arrow}}</span> ${{g.item}}</td>
      <td class="dims">${{g.children.length}} dims</td>
      <td class="bar-cell"><div class="bar" style="width:${{pctBar}}%"></div><span class="bar-val">${{g.avg.toLocaleString()}}</span></td>
      <td>${{g.samples.toLocaleString()}}</td>
      <td>${{g.total.toLocaleString()}}</td>
      <td class="pct">${{g.pct.toFixed(1)}}%</td>
    </tr>`;
    if (isOpen) {{
      // Sort children by avg desc
      const sorted = [...g.children].sort((a,b) => b.avg - a.avg);
      sorted.forEach(r => {{
        const childPctBar = maxAvg > 0 ? (r.avg / maxAvg * 100) : 0;
        const childPct = grandTotal > 0 ? (r.total / grandTotal * 100) : 0;
        html += `<tr class="group-child">
          <td></td>
          <td class="dims">${{r.dimsLabel}}</td>
          <td class="bar-cell"><div class="bar" style="width:${{childPctBar}}%"></div><span class="bar-val">${{r.avg.toLocaleString()}}</span></td>
          <td>${{r.samples}}</td>
          <td>${{r.total.toLocaleString()}}</td>
          <td class="pct">${{childPct.toFixed(2)}}%</td>
        </tr>`;
      }});
    }}
  }});
  tbody.innerHTML = html;

  // Attach toggle handlers
  tbody.querySelectorAll(".group-header").forEach(tr => {{
    tr.addEventListener("click", () => {{
      const item = tr.dataset.item;
      if (expanded.has(item)) expanded.delete(item); else expanded.add(item);
      renderTable(getFilteredRows());
    }});
  }});
}}

// Header click sorting
document.querySelectorAll("#table th[data-col]").forEach(th => {{
  th.addEventListener("click", () => {{
    const col = th.dataset.col;
    if (currentSort === col) currentDir *= -1;
    else {{ currentSort = col; currentDir = th.dataset.type === "num" ? -1 : 1; }}
    document.querySelectorAll("#table th").forEach(t => t.classList.remove("sorted"));
    th.classList.add("sorted");
    th.querySelector(".arrow").textContent = currentDir > 0 ? "\\u25B2" : "\\u25BC";
    renderTable(getFilteredRows());
  }});
}});

// ─── Render all ───
function renderAll() {{
  const rows = getFilteredRows();
  renderSummary(rows);
  renderBarChart(rows);
  renderScatter(rows);
  renderTargets(rows);
  renderHeatmap(rows);
  renderHeatmapMP(rows);
  renderStacked(rows);
  renderJumpMultiplier(rows);
  renderTable(rows);
}}

renderAll();

// Raw data
document.getElementById("rawdata").textContent = JSON.stringify(RAW, null, 2);
</script>
</body>
</html>"""


ALL_ACCOUNTS = ["tagadai", "tagadanar", "tagadalton", "tagadalone"]


def fetch_account_registers(login: str, password: str) -> tuple[list[tuple[int, str]], dict]:
    """Fetch d_* registers from all leeks of one account.

    Returns ([(leek_id, leek_name), ...], {register_key: value}).
    """
    import time
    api = LeekWarsAPI()
    farmer = api.login(login, password)
    if farmer is None:
        time.sleep(1)
        api = LeekWarsAPI()
        farmer = api.login(login, password)
    if farmer is None:
        raise RuntimeError(f"Login failed for {login}")
    leeks_info = []
    all_registers = {}

    for lid, leek in farmer.get("leeks", {}).items():
        leek_id = int(lid)
        leek_name = leek["name"]
        leeks_info.append((leek_id, leek_name))

        r = api.session.get(f"{api.BASE_URL}/leek/get-registers/{leek_id}")
        data = r.json()
        reg_list = data.get("registers", data) if isinstance(data, dict) else data
        if isinstance(reg_list, list):
            for entry in reg_list:
                if entry["key"].startswith("d_"):
                    # Append to existing register value with pipe separator
                    key = entry["key"]
                    if key in all_registers:
                        all_registers[key] += "|" + entry["value"]
                    else:
                        all_registers[key] = entry["value"]
        elif isinstance(reg_list, dict):
            for key, value in reg_list.items():
                if key.startswith("d_"):
                    if key in all_registers:
                        all_registers[key] += "|" + value
                    else:
                        all_registers[key] = value

    return leeks_info, all_registers


def merge_items(*item_dicts: dict) -> dict:
    """Merge multiple aggregated item dicts, re-averaging across all."""
    merged: dict = {}
    for items in item_dicts:
        for item_name, dims_data in items.items():
            if item_name not in merged:
                merged[item_name] = {}
            for dims, v in dims_data.items():
                if dims not in merged[item_name]:
                    merged[item_name][dims] = {"total_kops": 0, "total_count": 0, "avg_kops": 0}
                merged[item_name][dims]["total_kops"] += v["total_kops"]
                merged[item_name][dims]["total_count"] += v["total_count"]
    # Recompute averages
    for item_name in merged:
        for dims in merged[item_name]:
            d = merged[item_name][dims]
            d["avg_kops"] = round(d["total_kops"] / d["total_count"]) if d["total_count"] > 0 else 0
    return merged


def main():
    parser = argparse.ArgumentParser(description="Display MapDanger operation cost stats")
    parser.add_argument("--clear", action="store_true", help="Clear all d_* registers (all accounts)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--html", action="store_true", help="Open HTML dashboard in browser")
    args = parser.parse_args()

    _, password = load_credentials()

    # Fetch from all accounts
    all_items_list = []
    all_registers: dict = {}
    all_leek_names = []

    for account in ALL_ACCOUNTS:
        try:
            leeks_info, registers = fetch_account_registers(account, password)
            names = [name for _, name in leeks_info]
            all_leek_names.extend(names)
            print(f"  {account}: {', '.join(names)}", file=sys.stderr)

            # Merge raw registers for --clear and raw display
            for key, value in registers.items():
                if key in all_registers:
                    all_registers[key] += "|" + value
                else:
                    all_registers[key] = value

            # Build aggregated items for this account
            items = {}
            for key, value in registers.items():
                item_name = key[2:]
                if item_name in EXCLUDED_ITEMS:
                    continue
                entries = parse_register_value(value)
                if entries:
                    items[item_name] = aggregate_entries(entries)
            all_items_list.append(items)
        except Exception as e:
            print(f"  {account}: ERROR - {e}", file=sys.stderr)

    if args.clear:
        cleared = 0
        for account in ALL_ACCOUNTS:
            try:
                api = LeekWarsAPI()
                farmer = api.login(account, password)
                for lid in farmer.get("leeks", {}):
                    leek_id = int(lid)
                    r = api.session.get(f"{api.BASE_URL}/leek/get-registers/{leek_id}")
                    data = r.json()
                    reg_list = data.get("registers", data) if isinstance(data, dict) else data
                    keys_to_delete = []
                    if isinstance(reg_list, list):
                        keys_to_delete = [e["key"] for e in reg_list if e["key"].startswith("d_")]
                    elif isinstance(reg_list, dict):
                        keys_to_delete = [k for k in reg_list if k.startswith("d_")]
                    for key in keys_to_delete:
                        api.session.delete(f"{api.BASE_URL}/leek/delete-register/{leek_id}/{key}")
                        cleared += 1
            except Exception as e:
                print(f"  {account}: clear error - {e}", file=sys.stderr)
        print(f"Cleared {cleared} danger stat registers across all accounts.")
        return

    # Merge all accounts
    merged = merge_items(*all_items_list) if all_items_list else {}
    total_samples = sum(v["total_count"] for dims in merged.values() for v in dims.values())
    print(f"  Merged: {len(merged)} items, {total_samples:,} samples", file=sys.stderr)

    label = "All accounts (" + ", ".join(ALL_ACCOUNTS) + ")"

    if args.json:
        print(json.dumps(merged, indent=2))
    elif args.html:
        html = build_html(merged, label, all_registers)
        out = Path(__file__).resolve().parent.parent.parent / "dangerstats.html"
        out.write_text(html)
        print(f"Opened {out}", file=sys.stderr)
        webbrowser.open(out.as_uri())
    else:
        display_stats(all_registers)


if __name__ == "__main__":
    try:
        main()
    except TagadAIError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
