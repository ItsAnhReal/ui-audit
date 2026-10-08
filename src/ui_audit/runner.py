"""One audit for `ui-audit ui`, in its own process: a JSON spec on stdin, JSON events on stdout.

The app starts one of these per run, so a run can be cancelled and a crash in the browser
cannot take the app down. Each stdout line is one event object with an "event" key; the
audit's log lines arrive as "log" events. Anything else (a traceback) is plain text.

Spec: {"config": <Config.to_dict()>, "routes": [...], "changed_since": "<git ref>",
       "baseline": "<report dir>"}; only "config" is required.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def emit(event: str, **data) -> None:
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def main() -> int:
    from . import audit, report as report_mod
    from .cli import _git_changed, routes_for_changes
    from .config import ConfigError, from_dict

    spec = json.load(sys.stdin)
    try:
        cfg = from_dict(spec["config"])
    except (ConfigError, TypeError) as exc:
        emit("error", message=f"config error: {exc}")
        return 2
    only = spec.get("routes") or None
    if spec.get("changed_since"):
        baseline = Path(spec.get("baseline") or "")
        try:
            changed = _git_changed(cfg.project_root, spec["changed_since"])
            only, why = routes_for_changes(report_mod.read_json(baseline), changed)
        except Exception as exc:  # noqa: BLE001 - no baseline, not a git checkout, unknown ref
            emit("error", message=f"could not work out what changed since {spec['changed_since']}: {str(exc).splitlines()[0]}")
            return 2
        emit("scope", message=why, routes=only)
        if not only:
            emit("done", empty=True)
            return 0
    try:
        result = audit.run(cfg, only_routes=only, log=lambda message: emit("log", message=message), on_event=emit)
    except KeyboardInterrupt:
        emit("cancelled")
        return 130
    except Exception as exc:  # noqa: BLE001 - report it to the app, with the traceback for the log
        traceback.print_exc(file=sys.stdout)
        emit("error", message=f"{exc.__class__.__name__}: {str(exc).splitlines()[0] if str(exc) else ''}")
        return 1
    emit("done", counts=result["stats"]["issues"], seconds=result["stats"]["seconds"], errors=result["errors"][:20])
    return 0


if __name__ == "__main__":
    sys.exit(main())
