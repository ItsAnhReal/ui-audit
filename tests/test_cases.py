"""Every page in tests/cases must be reported exactly as its first line says."""

import shutil
from collections import Counter
from pathlib import Path

import pytest

from ui_audit import audit
from ui_audit.config import from_dict

CASES = sorted((Path(__file__).parent / "cases").glob("*.html"))

pytestmark = [pytest.mark.e2e, pytest.mark.usefixtures("chromium_available")]


def expected(path: Path) -> dict[str, int]:
    spec = path.read_text().splitlines()[0].removeprefix("<!-- expect:").removesuffix("-->").strip()
    if spec == "clean":
        return {}
    return {check: int(count) for check, count in (part.split("=") for part in spec.split())}


def test_every_case_reports_what_it_says(demo_site, tmp_path):
    url, site = demo_site
    for case in CASES:
        shutil.copy(case, site / case.name)
    cfg = from_dict({
        "base_url": url, "project_root": str(site), "output": str(tmp_path / "run"), "settle_ms": 50,
        # The cases look alike on purpose; none of them is a copy to skip.
        "routes": {"include": [f"/{case.name}" for case in CASES], "discover": ["config"], "dedupe": False,
                   "max_routes": len(CASES)},
        "states": {"auto": False}, "viewports": {"widths": [390, 1366]},
    })
    report = audit.run(cfg, log=lambda _: None)
    got = {case.name: dict(Counter(i["check"] for i in report["issues"] if i["route"] == f"/{case.name}")) for case in CASES}
    assert got == {case.name: expected(case) for case in CASES}
