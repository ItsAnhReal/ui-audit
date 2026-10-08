"""Report files: report.json (the source of truth) and index.html (the contact sheet)."""

from __future__ import annotations

import html
import json
from pathlib import Path

from .issues import SEVERITY_ORDER

REPORT_JSON = "report.json"
REPORT_HTML = "index.html"


def write_json(report: dict, out_dir: Path) -> Path:
    path = out_dir / REPORT_JSON
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_json(path: Path) -> dict:
    if path.is_dir():
        path = path / REPORT_JSON
    return json.loads(path.read_text(encoding="utf-8"))


def summary_counts(issues: list[dict]) -> dict[str, int]:
    counts = {"P1": 0, "P2": 0, "P3": 0}
    for issue in issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1
    return counts


def _e(value) -> str:
    return html.escape(str(value), quote=True)


STYLE = """
:root { color-scheme: light dark; --bg:#fff; --fg:#1d2433; --muted:#667085; --line:#e4e7ec; --card:#f9fafb;
  --p1:#d92d20; --p2:#dc6803; --p3:#7a5af8; }
@media (prefers-color-scheme: dark) { :root { --bg:#111418; --fg:#e6e9ee; --muted:#98a2b3; --line:#2b313a; --card:#181c22; } }
* { box-sizing: border-box; }
body { margin:0; font:14px/1.5 system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--fg); }
main { max-width:1200px; margin:0 auto; padding:24px 16px 64px; }
h1 { font-size:22px; margin:0 0 4px; } h2 { font-size:17px; margin:32px 0 8px; } h3 { font-size:15px; margin:20px 0 8px; }
.meta { color:var(--muted); margin:0 0 16px; }
.pills { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }
.pill { padding:2px 10px; border-radius:999px; border:1px solid var(--line); background:var(--card); }
.sev { display:inline-block; min-width:28px; text-align:center; font-weight:700; color:#fff; border-radius:4px; padding:0 4px; font-size:12px; }
.P1 { background:var(--p1); } .P2 { background:var(--p2); } .P3 { background:var(--p3); }
table { width:100%; border-collapse:collapse; font-size:13px; }
th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
td code { font-size:12px; word-break:break-all; }
.wrap { overflow-x:auto; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
figure { margin:0; background:var(--card); border:1px solid var(--line); border-radius:6px; padding:6px; }
figure img { width:100%; height:220px; object-fit:cover; object-position:top; display:block; border-radius:3px; }
figcaption { font-size:12px; color:var(--muted); margin-top:4px; }
.agent { font-size:11px; padding:0 6px; border-radius:4px; border:1px dashed var(--muted); color:var(--muted); }
"""


def write_html(report: dict, out_dir: Path) -> Path:
    issues = report["issues"]
    counts = summary_counts(issues)
    rows = []
    for index, issue in enumerate(sorted(issues, key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), i["route"])), 1):
        widths = issue.get("widths") or []
        width_text = f"{widths[0]}–{widths[-1]}px" if len(widths) > 1 else (f"{widths[0]}px" if widths else "—")
        candidates = "<br>".join(f"<code>{_e(c['file'])}</code>" for c in issue.get("source_candidates", [])[:2])
        evidence = " ".join(f'<a href="{_e(f)}">{n + 1}</a>' for n, f in enumerate(issue.get("evidence", [])[:4]))
        origin = ' <span class="agent">agent</span>' if issue.get("origin") == "agent" else ""
        rows.append(
            f"<tr><td><span class='sev {_e(issue['severity'])}'>{_e(issue['severity'])}</span></td>"
            f"<td>{_e(issue['check'])}{origin}</td><td>{_e(issue['route'])}<br><small>{_e(issue['state'])}</small></td>"
            f"<td>{_e(width_text)}</td><td>{_e(issue['message'])}<br><code>{_e(issue.get('selector', ''))}</code></td>"
            f"<td>{candidates}</td><td>{evidence}</td></tr>"
        )

    sections = []
    groups: dict[tuple[str, str], list[dict]] = {}
    for capture in report["captures"]:
        groups.setdefault((capture["route"], capture["state"]), []).append(capture)
    for (route, state), captures in groups.items():
        figures = []
        for capture in sorted(captures, key=lambda c: c["width"]):
            image = capture.get("annotated") or capture["file"]
            figures.append(
                f'<figure><a href="{_e(image)}"><img loading="lazy" src="{_e(image)}" alt="{_e(route)} at {capture["width"]}px"></a>'
                f'<figcaption>{capture["width"]}×{capture["height"]} · {_e(", ".join(capture["reasons"]))} · '
                f'{capture["issue_count"]} issue(s)</figcaption></figure>'
            )
        sections.append(f"<h3>{_e(route)} — {_e(state)}</h3><div class='grid'>{''.join(figures)}</div>")

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UI Audit Report</title><style>{STYLE}</style></head>
<body><main>
<h1>UI audit</h1>
<p class="meta">{_e(report['base_url'])} · {_e(report['created'])} · ui-audit {_e(report['version'])}</p>
<div class="pills">
<span class="pill"><span class="sev P1">P1</span> {counts['P1']}</span>
<span class="pill"><span class="sev P2">P2</span> {counts['P2']}</span>
<span class="pill"><span class="sev P3">P3</span> {counts['P3']}</span>
<span class="pill">{len(report['routes'])} routes</span>
<span class="pill">{len(report['states'])} states</span>
<span class="pill">{len(report['captures'])} screenshots</span>
<span class="pill">{report['stats']['probes']} probes</span>
</div>
<h2>Issues</h2>
<div class="wrap"><table><thead><tr><th>Sev</th><th>Check</th><th>Route / state</th><th>Widths</th><th>Finding</th><th>Likely source</th><th>Evidence</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="7">No issues found.</td></tr>'}</tbody></table></div>
<h2>Screenshots</h2>
{''.join(sections)}
</main></body></html>
"""
    path = out_dir / REPORT_HTML
    path.write_text(page, encoding="utf-8")
    return path
