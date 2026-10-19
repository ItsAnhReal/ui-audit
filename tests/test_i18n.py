"""Every text the app shows exists in English and German, with the same placeholders."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "src" / "ui_audit" / "ui"
README = Path(__file__).resolve().parent.parent / "README.md"

# Keys the app builds from data instead of spelling them out.
BUILT = {f"sev.{s}{suffix}" for s in ("P1", "P2", "P3") for suffix in ("", ".long")} | {
    *(f"theme.{t}" for t in ("system", "light", "dark")),
    *(f"editor.{e}" for e in ("vscode", "cursor", "windsurf", "zed", "copy")),
    *(f"na.mode.{m}{suffix}" for m in ("quick", "complete", "pages") for suffix in ("", ".help")),
    *(f"list.by.{m}{suffix}" for m in ("cause", "page") for suffix in ("", ".title")),
}


def app_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((UI / "app").glob("*.js")))


def dictionaries() -> dict[str, dict[str, str]]:
    source = (UI / "i18n.js").read_text(encoding="utf-8")
    blocks = re.split(r"\n  const (en|de) = \{\n", source)
    found = {}
    for lang, block in zip(blocks[1::2], blocks[2::2]):
        body = block.split("\n  };", 1)[0]
        found[lang] = dict(re.findall(r'^\s+"([^"]+)": "((?:[^"\\]|\\.)*)",$', body, re.M))
    return found


def used_keys() -> set[str]:
    app = app_source()
    keys = set(re.findall(r'\bt\("([^"]+)"', app))
    for one, many in re.findall(r'plural\([^,]+, "([^"]+)", "([^"]+)"', app):
        keys |= {one, many}
    return keys | BUILT


def test_both_languages_have_the_same_keys_and_placeholders():
    found = dictionaries()
    assert set(found) == {"en", "de"} and len(found["en"]) > 300
    assert found["en"].keys() == found["de"].keys()
    for key, text in found["en"].items():
        assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", found["de"][key])), key


def test_every_key_the_app_asks_for_exists():
    missing = used_keys() - dictionaries()["en"].keys()
    assert not missing


def test_every_documented_check_has_a_title_and_a_tip():
    table = README.read_text(encoding="utf-8").split("## Checks", 1)[1].split("\n## ", 1)[0]
    first_cells = re.findall(r"^\| ([^|]+) \|", table, re.M)
    checks = {name for cell in first_cells for name in re.findall(r"`([a-z]+(?:-[a-z]+)+)`", cell)}
    texts = dictionaries()["de"]
    assert {"horizontal-overflow", "offscreen-content", "small-target", "failed-resource"} <= checks
    for check in checks:
        assert f"check.{check}" in texts and f"tip.{check}" in texts, check


PACKAGE = UI.parent


def probe_messages() -> dict[str, str]:
    source = (PACKAGE / "probe.js").read_text(encoding="utf-8")
    block = source.split("const MESSAGES = {", 1)[1].split("\n  };", 1)[0]
    return dict(re.findall(r'^\s+(\w+): "((?:[^"\\]|\\.)*)",$', block, re.M))


def test_every_probe_message_has_a_text_with_its_values():
    """Keys the app builds from report data: msg.<key> for each of the probe's messages."""
    messages = probe_messages()
    assert len(messages) > 20 and "pageWide" in messages
    for lang, texts in dictionaries().items():
        for key, english in messages.items():
            assert f"msg.{key}" in texts, (lang, key)
            assert set(re.findall(r"\{(\w+)\}", texts[f"msg.{key}"])) == set(re.findall(r"\{(\w+)\}", english)), (lang, key)
        assert {"msg.edge.left", "msg.edge.right"} <= texts.keys()


def test_every_content_detail_the_probe_names_has_a_text():
    source = (PACKAGE / "probe.js").read_text(encoding="utf-8")
    keys = set(re.findall(r'detail_key: "(\w+)"', source))
    states = set(re.findall(r'state: "([\w-]+)"', source)) - {"ok"}
    assert keys and states
    for texts in dictionaries().values():
        assert {f"content.{k}" for k in keys} <= texts.keys()
        assert {f"content.{s}" for s in states} <= texts.keys()


def test_every_error_code_of_the_server_and_runner_has_a_text():
    codes = set()
    for name in ("server.py", "runner.py"):
        source = (PACKAGE / name).read_text(encoding="utf-8")
        codes |= set(re.findall(r'ApiError\(\d+, [^\n]*?, "(\w+)"', source))
        codes |= set(re.findall(r'(?:fail\([^\n]*?, |code=)"(\w+)"', source))
    assert {"badMode", "noRun", "auditStopped", "loginClosed", "config", "changes", "auditFailed"} <= codes
    for lang, texts in dictionaries().items():
        missing = {c for c in codes if f"err.{c}" not in texts}
        assert not missing, (lang, missing)


def test_the_page_joins_every_script_file():
    from ui_audit.report import APP_SCRIPTS

    assert sorted(APP_SCRIPTS) == sorted(p.name for p in (UI / "app").glob("*.js"))
    assert APP_SCRIPTS[0] == "core.js" and APP_SCRIPTS[-1] == "main.js"


def test_scripts_cannot_end_the_inline_script_block():
    for path in [UI / "i18n.js", *(UI / "app").glob("*.js")]:
        assert "</script" not in path.read_text(encoding="utf-8").lower(), path.name
