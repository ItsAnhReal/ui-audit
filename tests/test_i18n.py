"""Every text the app shows exists in English and German, with the same placeholders."""

import re
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "src" / "ui_audit" / "ui"
README = Path(__file__).resolve().parent.parent / "README.md"

# Keys app.js builds from data instead of spelling them out.
BUILT = {f"sev.{s}{suffix}" for s in ("P1", "P2", "P3") for suffix in ("", ".long")} | {
    *(f"theme.{t}" for t in ("system", "light", "dark")),
    *(f"editor.{e}" for e in ("vscode", "cursor", "windsurf", "zed", "copy")),
    *(f"na.mode.{m}{suffix}" for m in ("quick", "complete", "pages") for suffix in ("", ".help")),
    *(f"list.by.{m}{suffix}" for m in ("cause", "page") for suffix in ("", ".title")),
}


def dictionaries() -> dict[str, dict[str, str]]:
    source = (UI / "i18n.js").read_text(encoding="utf-8")
    blocks = re.split(r"\n  const (en|de) = \{\n", source)
    found = {}
    for lang, block in zip(blocks[1::2], blocks[2::2]):
        body = block.split("\n  };", 1)[0]
        found[lang] = dict(re.findall(r'^\s+"([^"]+)": "((?:[^"\\]|\\.)*)",$', body, re.M))
    return found


def used_keys() -> set[str]:
    app = (UI / "app.js").read_text(encoding="utf-8")
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


def test_scripts_cannot_end_the_inline_script_block():
    for name in ("app.js", "i18n.js"):
        assert "</script" not in (UI / name).read_text(encoding="utf-8").lower()
