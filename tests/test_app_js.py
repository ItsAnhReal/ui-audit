"""The app's pure functions (ui/app/core.js, text.js, model.js), run in Node.

The files are joined the way report.py joins them for the page; a test script at the end of
that function calls them and prints the results as JSON. Skipped where Node is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ui_audit.report import app_script

UI = Path(__file__).resolve().parent.parent / "src" / "ui_audit" / "ui"
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def run_js(body: str, lang: str = "en"):
    """Run `body` inside the app's scope (without the DOM files) and return what it returns."""
    tail = f"const IS_APP = false;\nI18N.use({json.dumps(lang)});\nprocess.stdout.write(JSON.stringify((() => {{ {body} }})()));"
    script = ("globalThis.window = globalThis;\n"
              + (UI / "i18n.js").read_text(encoding="utf-8") + "\n"
              + app_script(("core.js", "text.js", "model.js"), tail=tail))
    # on stdin: the script is longer than a Windows command line may be
    done = subprocess.run([NODE, "-"], input=script, capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_messages_are_translated_from_their_key_and_values():
    issue = {"check": "horizontal-overflow", "message": "Extends to 900px in a 390px viewport (page scrolls sideways by 510px).",
             "message_key": "extends", "message_params": {"right": 900, "vw": 390, "scroll": {"key": "scrolls", "params": {"by": 510}}}}
    cut = {"check": "offscreen-control", "message": "Control is cut off at the left edge of a 390px viewport.",
           "message_key": "controlCut", "message_params": {"edge": "left", "vw": 390}}
    result = run_js(f"""
      const issue = {json.dumps(issue)}, cut = {json.dumps(cut)};
      return {{
        extends: messageText(issue), cut: messageText(cut),
        unknown: messageText({{ ...issue, message_key: "fromTheFuture" }}),
        nestedUnknown: messageText({{ ...issue, message_params: {{ ...issue.message_params, scroll: {{ key: "nope", params: {{}} }} }} }}),
        old: messageText({{ ...issue, message_key: undefined }}),
        agent: messageText({{ ...issue, origin: "agent" }}),
      }};""", lang="de")
    assert result["extends"] == "Reicht bis 900 px bei 390 px Fensterbreite, die Seite scrollt dadurch 510 px seitlich."
    assert result["cut"] == "Bedienelement wird bei 390 px Fensterbreite am linken Rand abgeschnitten."
    # anything the app cannot translate whole keeps the English the probe wrote
    assert result["unknown"] == result["nestedUnknown"] == result["old"] == result["agent"] == issue["message"]


def test_content_details_and_errors_use_their_codes():
    result = run_js("""
      return {
        thin: contentDetail({ state: "thin", detail: "12 characters of text, 1 control", detail_key: "thinDetail", detail_params: { chars: 1234, controls: 1 } }),
        old: contentDetail({ state: "thin", detail: "12 characters of text, 1 control" }),
        known: errorText(Object.assign(new Error("no run called x"), { code: "noRun", params: { name: "x" } })),
        unknown: errorText(Object.assign(new Error("something new"), { code: "fromTheFuture", params: {} })),
        missing: errorText(Object.assign(new Error("raw text"), { code: "noRun", params: {} })),
        job: jobError({ error: "the audit stopped (exit code 3); see the log", error_code: "auditStopped", error_params: { exit: 3 } }, "?"),
      };""", lang="de")
    assert result["thin"] == "1.234 Zeichen Text, 1 Bedienelemente"
    assert result["old"] == "12 characters of text, 1 control"
    assert result["known"] == "Es gibt keinen Lauf namens x. Vielleicht wurde er gelöscht."
    assert result["unknown"] == "something new" and result["missing"] == "raw text"
    assert result["job"] == "Die Prüfung wurde beendet (Exit-Code 3). Das Log nennt den Grund."


def test_plurals_follow_the_language_rules():
    result = run_js("""return [0, 1, 2].map((n) => plural(n, "unit.pages.one", "unit.pages.many"));""")
    assert result == ["0 pages", "1 page", "2 pages"]


def test_filters_survive_a_round_trip_through_the_url():
    result = run_js("""
      const vs = { sev: new Set(["P2", "P1"]), route: "/a b", check: "text-spill", text: "hero", width: 390, accepted: true, mode: "page" };
      const query = filterQuery(vs);
      const back = readFilters(query);
      const none = filterQuery({ sev: new Set(), route: "", check: "", text: "", width: null, accepted: false, mode: "cause" });
      const junk = readFilters({ sev: "P9,P1", w: "wide", by: "x" });
      return { query, back: { ...back, sev: [...back.sev] }, none, junk: { ...junk, sev: [...junk.sev] } };""")
    assert result["query"] == {"sev": "P1,P2", "page": "/a b", "check": "text-spill", "q": "hero", "w": "390", "accepted": "1", "by": "page"}
    assert result["back"] == {"sev": ["P1", "P2"], "route": "/a b", "check": "text-spill", "text": "hero", "width": 390,
                              "accepted": True, "mode": "page"}
    assert result["none"] == {}
    assert result["junk"]["sev"] == ["P1"] and result["junk"]["width"] is None and result["junk"]["mode"] == "cause"


def test_exports_quote_what_needs_quoting():
    issues = [
        {"id": "a1", "severity": "P1", "check": "text-spill", "route": "/x", "state": "default", "selector": "p.a|b",
         "message": 'Text spills 4px outside its box: "a, b"', "widths": [390, 400],
         "source_candidates": [{"file": "src/A.tsx", "line": 3}]},
        {"id": "b2", "severity": "P2", "check": "console-error", "route": "/y", "state": "menu", "selector": "x",
         "message": "=HYPERLINK(1)\nsecond line", "widths": [1280], "accepted": {"reason": "known"}},
    ]
    result = run_js(f"""
      const issues = {json.dumps(issues)};
      return {{ csv: findingsCsv(issues), md: findingsMarkdown({{ data: {{ base_url: "http://localhost:3000" }} }}, issues) }};""")
    rows = result["csv"].split("\r\n")
    assert rows[0] == "id,severity,check,page,state,widths,element,message,source,accepted,origin"
    assert rows[1] == 'a1,P1,text-spill,/x,default,390-400,p.a|b,"Text spills 4px outside its box: ""a, b""",src/A.tsx:3,,deterministic'
    assert rows[2].startswith("b2,P2,console-error,/y,menu,,,\"'=HYPERLINK(1)\nsecond line\",,known,")
    md = result["md"].splitlines()
    assert md[0] == "# ui-audit findings for http://localhost:3000"
    assert "| P1 | text-spill | `/x` | default | 390-400 | `p.a\\|b` | Text spills 4px outside its box: \"a, b\" |" in md
    assert "| P2 | console-error | `/y` | menu |  |  | =HYPERLINK(1) second line |" in md


def test_the_log_box_appends_only_new_lines():
    result = run_js("""
      return [
        logLines(null, { log: ["a", "b"], log_count: 2 }),
        logLines(2, { log: ["a", "b"], log_count: 2 }),
        logLines(2, { log: ["b", "c", "d"], log_count: 4 }),
        logLines(2, { log: ["x", "y"], log_count: 90 }),
        logLines(0, { log: ["a"], log_count: 1 }),
      ];""")
    assert result[0] == {"reset": True, "lines": ["a", "b"], "total": 2}
    assert result[1] == {"reset": False, "lines": [], "total": 2}
    assert result[2] == {"reset": False, "lines": ["c", "d"], "total": 4}
    assert result[3]["reset"] and result[4]["reset"]  # fell behind the tail; nothing drawn yet


def test_recheck_commands_come_from_the_report():
    data = {"issues": [{"id": "i1", "group": "g1", "route": "/", "check": "a", "severity": "P2", "recheck": "one"},
                       {"id": "i2", "group": "g1", "route": "/b", "check": "a", "severity": "P2", "recheck": "two"},
                       {"id": "i3", "group": "g2", "route": "/", "check": "b", "severity": "P3"}],
            "groups": [{"id": "g1", "recheck": "both"}, {"id": "g2", "recheck": "alone"}],
            "accept_command": "ui-audit accept 'my run' {id} --reason \"why this is fine\""}
    result = run_js(f"""
      const model = buildModel({json.dumps(data)});
      const by = (id) => model.byId.get(id);
      return [recheckCommand(model, [by("i1")]), recheckCommand(model, [by("i1"), by("i2")]), recheckCommand(model, [by("i3")]),
              recheckCommand(model, [by("i1"), by("i3")]), acceptCommand(model, "g1")];""")
    assert result == ["one", "both", "alone", None, "ui-audit accept 'my run' g1 --reason \"why this is fine\""]
