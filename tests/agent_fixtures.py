"""A small synthetic run for the agent-facing views: no browser needed."""

import json
import struct
import zlib

from ui_audit import report
from ui_audit.issues import short_id


def tiny_png() -> bytes:
    """A 1×1 red PNG."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _issue(check, route, selector, widths, severity="P2", state="default", **extra):
    sig = f"{check}|{route}|{state}|{selector}"
    return {"id": short_id(sig), "signature": sig, "check": check, "severity": severity,
            "origin": "deterministic", "route": route, "state": state, "selector": selector,
            "message": f"{check} at {selector}", "widths": widths, "rects": {}, "hints": {},
            "evidence": [], "source_candidates": [], "also_in_states": [], "browsers": ["chromium"],
            "widths_by_browser": {"chromium": widths}, **extra}


def make_run(tmp_path, extra_groups: int = 0):
    """Write a run with two overflowing cards (one cause), a clipped box, a console error and a
    page that did not show its content. Returns (run_dir, report)."""
    run = tmp_path / "run"
    (run / "shots").mkdir(parents=True)
    (run / "shots" / "pricing__default__390.png").write_bytes(tiny_png())
    (run / "shots" / "pricing__default__390__annotated.png").write_bytes(tiny_png())
    (run / "shots" / "pricing__default__800.png").write_bytes(tiny_png())
    card = {"file": "src/Card.tsx", "line": 12, "reasons": ["runtime source"]}
    issues = [
        _issue("horizontal-overflow", "/pricing", "main > div.card", [320, 390, 480], "P1",
               rects={"390": {"x": 0, "y": 0, "width": 10, "height": 10}},
               evidence=["shots/pricing__default__390__annotated.png"], source_candidates=[card]),
        _issue("offscreen-content", "/", "main > div.card", [320, 360], "P1", source_candidates=[card]),
        _issue("clipped-content", "/pricing", "div.plan", [700, 800], source_candidates=[{"file": "src/Plan.tsx", "reasons": []}]),
        _issue("console-error", "/", "boom", [1280], message="TypeError: boom"),
    ]
    issues += [_issue("text-spill", "/", f"p.x{n}", [400], "P3") for n in range(extra_groups)]
    data = {
        "version": "test", "base_url": "http://localhost:3000", "project_root": str(tmp_path), "output_dir": str(run),
        "config": {"viewports": {"min_width": 320, "max_width": 1920}},
        "routes": [{"path": "/", "status": "audited", "loaded": True, "content": {"state": "ok", "detail": ""}},
                   {"path": "/pricing", "status": "audited", "loaded": True, "content": {"state": "ok", "detail": ""}},
                   {"path": "/account", "status": "audited", "loaded": True,
                    "content": {"state": "login", "detail": "looks like a sign-in page"}},
                   {"path": "/gone", "status": "skipped: not found"}],
        "truncated_routes": ["/extra"], "states": [], "breakpoints": [], "coverage": {"/pricing|default": [320, 390, 480, 700, 800]},
        "captures": [
            {"route": "/pricing", "state": "default", "width": 390, "height": 844, "browser": "chromium", "reasons": [],
             "file": "shots/pricing__default__390.png", "annotated": "shots/pricing__default__390__annotated.png", "issue_count": 1},
            {"route": "/pricing", "state": "default", "width": 800, "height": 844, "browser": "chromium", "reasons": [],
             "file": "shots/pricing__default__800.png", "issue_count": 1},
        ],
        "issues": issues, "errors": ["/account: timed out"],
        "stats": {"issues": report.summary_counts(issues)},
    }
    report.write_json(json.loads(json.dumps(data)), run)
    return run, report.read_json(run)
