"""`ui-audit ui`: a local app for starting audits and working through their findings.

It serves one page and a small JSON API on 127.0.0.1. The page opens only from the address
printed at start, whose key buys a session cookie; every API call carries the token that is
written into the page, and every request must name this server in its Host header, so
another website open in the same browser can neither read reports nor start runs. Audits
run one at a time, each in its own process (`python -m ui_audit.runner`), always into a new
folder next to the earlier runs.
"""

from __future__ import annotations

import copy
import hmac
import json
import os
import queue
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
from collections import deque
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__, report as report_mod, verify
from .config import CONFIG_FILENAME, Config, ConfigError, load, parse_browsers

RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
STAMP = re.compile(r"-\d{8}-\d{6}(-\d+)?$")
LOCALE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8})*$")
GIT_REF = re.compile(r"^[A-Za-z0-9_./~^@{}][A-Za-z0-9_./~^@{}-]{0,199}$")
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
DEFAULT_PORT = 8484
COMMON_PORTS = (3000, 5173, 8080, 4200)  # React and Next, Vite, many others, Angular
PAGE_POLICY = ("default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
               "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
MAX_BODY = 1_000_000
ENTER_PAGE = (b'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=/">'
              b'<title>ui-audit</title><p><a href="/">ui-audit</a></p>')
FORBIDDEN_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>ui-audit: open the address from the terminal</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:36rem;margin:3rem auto;padding:0 16px}</style>
<h1>Open the address printed in the terminal</h1>
<p>This app only opens from the address that <code>ui-audit ui</code> printed when it started. It ends in
<code>?k=</code> and a key, so other users on this computer cannot use your app.</p>
<div lang="de"><h2>Öffne die Adresse aus dem Terminal</h2>
<p>Diese App öffnet sich nur über die Adresse, die <code>ui-audit ui</code> beim Start ausgegeben hat. Sie endet auf
<code>?k=</code> und einen Schlüssel, damit andere Benutzer dieses Rechners deine App nicht verwenden können.</p></div>
</html>""".encode()


class ApiError(Exception):
    """An error for the page: the English message, and a code (err.<code> in ui/i18n.js) with
    values the page fills into its own language."""

    def __init__(self, status: int, message: str, code: str = "internal", **params) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.params = params

    def body(self) -> dict:
        return {"error": self.message, "code": self.code, "params": self.params}


def recheck_widths(issues: list[dict], low: int, high: int, limit: int = 14) -> list[int]:
    """Where to look again for these findings: both edges of every width range they were
    seen in, the widths just outside those edges (a fix must not move the edge by a pixel),
    and one width from the middle."""
    edges: set[int] = set()
    middles: set[int] = set()
    for issue in issues:
        seen = sorted(issue.get("widths") or [])
        if not seen:
            continue
        edges |= {seen[0], seen[-1], seen[0] - 1, seen[-1] + 1}
        middles.add(seen[len(seen) // 2])
    widths = sorted(w for w in edges | middles if low <= w <= high)
    if len(widths) <= limit:
        return widths
    kept = sorted(w for w in edges if low <= w <= high)
    if len(kept) > limit:  # many routes, many ranges: an even spread across them
        step = len(kept) / limit
        kept = [kept[int(n * step)] for n in range(limit)]
    return kept


def _strings(value, label: str, limit: int, pattern: re.Pattern | None = None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part for part in re.split(r"[\s,]+", value) if part]
    if not isinstance(value, list) or len(value) > limit or not all(isinstance(v, str) and 0 < len(v) <= 300 for v in value):
        raise ApiError(400, f"{label} must be a list of at most {limit} short strings", "badList", label=label, limit=limit)
    if pattern and not all(pattern.match(v) for v in value):
        raise ApiError(400, f"{label} contains an invalid value", "badValue", label=label)
    return value


class Workspace:
    """The project folder the app was started in and the folder its runs live in."""

    def __init__(self, root: Path, config_path: Path | None = None, runs_dir: Path | None = None) -> None:
        self.root = root.resolve()
        self.config_path = config_path.resolve() if config_path else None
        cfg = self.config()
        output = Path(cfg.output)
        self.runs_dir = (runs_dir or (output if output.is_absolute() else self.root / output).parent).resolve()
        self._summaries: dict[str, tuple[tuple, dict]] = {}
        self._run_data: dict[str, tuple[tuple, dict]] = {}
        self._json_files: dict[Path, tuple[tuple, list[str] | None]] = {}  # file -> (stamp, origins if a session)
        self._lock = threading.Lock()

    def rel(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(path.resolve())

    def config(self, path: Path | None = None) -> Config:
        path = path or self.config_path
        return load(path)[0] if path else Config()

    def config_files(self) -> list[dict]:
        """ui-audit settings files: in the project folder and next to the runs."""
        found: dict[Path, dict] = {}
        candidates = [*sorted(self.root.glob("*.toml")), *sorted(self.runs_dir.glob("*.toml"))]
        if self.config_path:
            candidates.insert(0, self.config_path)
        for path in candidates:
            path = path.resolve()
            if path in found or path.name == "pyproject.toml":
                continue
            try:
                cfg = load(path)[0]
            except (ConfigError, OSError, ValueError) as exc:
                if path == self.config_path:
                    found[path] = {"path": self.rel(path), "error": str(exc), "default": True}
                continue  # some other tool's .toml
            found[path] = {"path": self.rel(path), "base_url": cfg.base_url, "default": path == self.config_path,
                           "storage_state": cfg.storage_state, "locale": cfg.locale, "sweep": cfg.states.sweep,
                           "browsers": cfg.browsers}
        return list(found.values())

    def config_file(self, name: str) -> Path:
        for entry in self.config_files():
            if entry["path"] == name and "error" not in entry:
                path = Path(name)
                return path if path.is_absolute() else self.root / path
        raise ApiError(400, f"unknown settings file: {name}", "unknownSettings", name=name)

    def sessions(self) -> list[dict]:
        """Signed-in browser sessions saved by `ui-audit login` (Playwright storage states)."""
        found = []
        for folder in dict.fromkeys([self.runs_dir, self.root / ".ui-audit", self.root]):
            for path in sorted(folder.glob("*.json")):
                try:
                    stat = path.stat()
                except OSError:
                    continue
                origins = self._session_origins(path, (stat.st_mtime_ns, stat.st_size))
                if origins is not None:
                    found.append({"path": self.rel(path), "modified": _iso(stat.st_mtime), "origins": origins})
        return found

    def _session_origins(self, path: Path, stamp: tuple) -> list[str] | None:
        """The origins of a saved session, None for any other JSON file. The state is asked for
        every few seconds and a project's package-lock.json can be megabytes: each file is read
        again only when its time or size changed."""
        with self._lock:
            cached = self._json_files.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
        origins = None
        if stamp[1] <= 5_000_000:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            if isinstance(data, dict) and "cookies" in data and "origins" in data:
                origins = [o.get("origin") for o in data.get("origins", []) if isinstance(o, dict)][:5]
        with self._lock:
            self._json_files[path] = (stamp, origins)
        return origins

    def session_file(self, name: str) -> str:
        if not name:
            return ""
        for entry in self.sessions():
            if entry["path"] == name:
                return str(self.root / name) if not Path(name).is_absolute() else name
        raise ApiError(400, f"unknown session file: {name}", "unknownSession", name=name)

    def run_dir(self, name: str) -> Path:
        if not isinstance(name, str) or not RUN_NAME.match(name):
            raise ApiError(400, "invalid run name", "badRunName")
        path = self.runs_dir / name
        if not (path / report_mod.REPORT_JSON).is_file():
            raise ApiError(404, f"no run called {name}", "noRun", name=name)
        return path

    def _stamp(self, path: Path) -> tuple:
        verify_file = path / "verify.json"
        report_file = path / report_mod.REPORT_JSON
        return (report_file.stat().st_mtime_ns, report_file.stat().st_size,
                verify_file.stat().st_mtime_ns if verify_file.exists() else 0)

    def report(self, name: str) -> dict:
        return report_mod.read_json(self.run_dir(name))

    def runs(self) -> list[dict]:
        if not self.runs_dir.is_dir():
            return []
        found = []
        for folder in self.runs_dir.iterdir():
            if folder.is_dir() and RUN_NAME.match(folder.name) and (folder / report_mod.REPORT_JSON).is_file():
                try:
                    found.append(self.summary(folder))
                except (OSError, ValueError, KeyError, TypeError):
                    continue  # a half-written or foreign report.json
        return sorted(found, key=lambda r: r.get("created") or "", reverse=True)

    def summary(self, folder: Path) -> dict:
        stamp = self._stamp(folder)
        with self._lock:
            cached = self._summaries.get(folder.name)
            if cached and cached[0] == stamp:
                return cached[1]
        summary = summarize(folder.name, report_mod.read_json(folder), folder)
        with self._lock:
            self._summaries[folder.name] = (stamp, summary)
        return summary

    def run_data(self, name: str) -> dict:
        folder = self.run_dir(name)
        stamp = self._stamp(folder)
        with self._lock:
            cached = self._run_data.get(name)
            if cached and cached[0] == stamp:
                return cached[1]
        report = report_mod.read_json(folder)
        data = report_mod.viewer_data(report, str(folder))
        data["name"] = name
        data["dir"] = str(folder)
        data["summary"] = summarize(name, report, folder)
        if (folder / "verify.json").is_file():
            try:
                data["verify"] = json.loads((folder / "verify.json").read_text(encoding="utf-8"))
            except ValueError:
                pass
        with self._lock:
            self._run_data = {k: v for k, v in list(self._run_data.items())[-5:]}  # a few, they can be large
            self._run_data[name] = (stamp, data)
        return data


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


def summarize(name: str, report: dict, folder: Path) -> dict:
    """What the run list shows about one run."""
    config = report.get("config") or {}
    viewports = config.get("viewports") or {}
    issues = report.get("issues", [])
    routes = report.get("routes", [])
    audited = report_mod.audited_routes(report)
    stats = report.get("stats") or {}
    only = report.get("only_routes") or []
    summary = {
        "name": name,
        "created": report.get("created", ""),
        "base_url": report.get("base_url", ""),
        "locale": report.get("locale") or config.get("locale") or "",
        "version": report.get("version", ""),
        "counts": report_mod.summary_counts(issues),
        "accepted": sum(1 for i in issues if i.get("accepted")),
        "agent": sum(1 for i in issues if i.get("origin") == "agent"),
        "causes": len({i.get("group") or i["id"] for i in issues if not i.get("accepted")}),
        "pages": len(audited),
        "skipped": len(routes) - len(audited),
        "states": len(report.get("states", [])),
        "screenshots": len(report.get("captures", [])),
        "bytes": stats.get("screenshot_bytes", 0),
        "seconds": stats.get("seconds", 0),
        "fast": (config.get("states") or {}).get("sweep") == "key",
        "targeted": bool(only or viewports.get("widths")),
        "routes": only or ([r["path"] for r in audited] if viewports.get("widths") else []),
        "paths": [r["path"] for r in audited],
        "widths": viewports.get("widths") or [],
        "signed_in": bool(config.get("storage_state")),
        "doubtful": sum(1 for r in audited if (r.get("content") or {}).get("state", "ok") != "ok"),
        "errors": len(report.get("errors", [])),
    }
    verify_file = folder / "verify.json"
    if verify_file.is_file():
        try:
            result = json.loads(verify_file.read_text(encoding="utf-8"))
            summary["verify"] = {"baseline": Path(result.get("baseline") or "").name,
                                 **{key: len(result.get(key) or []) for key in ("fixed", "introduced", "persistent")}}
        except (ValueError, TypeError, AttributeError):
            pass
    return summary


class Job:
    """One audit, re-check or sign-in started from the app."""

    def __init__(self, kind: str, name: str, spec: dict, title: str = "", source: str | None = None,
                 issue_ids: list[str] | None = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind  # audit | recheck | login
        self.name = name  # the run folder it writes; for a sign-in, the session file
        self.spec = spec
        self.title = title
        self.source = source
        self.issue_ids = issue_ids or []
        self.status = "queued"  # queued | running | waiting | done | failed | cancelled
        self.created = time.time()
        self.started: float | None = None
        self.ended: float | None = None
        self.progress: dict = {}
        self.result: dict | None = None
        self.error: str | None = None
        self.error_code: str | None = None  # err.<code> in ui/i18n.js
        self.error_params: dict = {}
        self.proc: subprocess.Popen | None = None
        self.cancel_requested = False
        self._log: deque[str] = deque(maxlen=400)
        self._logged = 0  # lines ever logged, so the page can append the new ones
        self._lock = threading.Lock()

    def log(self, line: str) -> None:
        with self._lock:
            self._log.append(line[:2000])
            self._logged += 1

    def fail(self, message: str, code: str, **params) -> None:
        self.error, self.error_code, self.error_params = message, code, params

    def public(self) -> dict:
        with self._lock:
            tail, logged = list(self._log)[-60:], self._logged
        return {"id": self.id, "kind": self.kind, "name": self.name, "title": self.title, "source": self.source,
                "issue_ids": self.issue_ids, "status": self.status, "created": self.created, "started": self.started,
                "ended": self.ended, "progress": self.progress, "result": self.result, "error": self.error,
                "error_code": self.error_code, "error_params": self.error_params, "log": tail, "log_count": logged}


def _stop(proc: subprocess.Popen) -> None:
    """Interrupt a run and everything it started (the browser too); kill it if it does not stop."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
        else:
            os.killpg(proc.pid, signal.SIGINT)
    except (OSError, ValueError):
        pass

    def escalate() -> None:
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "nt":
                    proc.kill()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass

    threading.Thread(target=escalate, daemon=True).start()


def _new_group() -> dict:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


class Jobs:
    """Runs audits one after another; a sign-in runs on its own because it waits for a person."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.items: dict[str, Job] = {}
        self.lock = threading.Lock()
        self.pending: queue.Queue[Job] = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def submit(self, job: Job) -> Job:
        with self.lock:
            self.items[job.id] = job
            finished = [j for j in self.items.values() if j.status in ("done", "failed", "cancelled")]
            for old in sorted(finished, key=lambda j: j.created)[:-12]:
                del self.items[old.id]
        if job.kind == "login":
            threading.Thread(target=self._run_login, args=(job,), daemon=True).start()
        else:
            self.pending.put(job)
        return job

    def get(self, job_id: str) -> Job:
        with self.lock:
            job = self.items.get(job_id)
        if job is None:
            raise ApiError(404, "no such job", "noJob")
        return job

    def list(self) -> list[dict]:
        with self.lock:
            jobs = list(self.items.values())
        return [job.public() for job in sorted(jobs, key=lambda j: j.created, reverse=True)]

    def busy_names(self) -> set[str]:
        with self.lock:
            return {j.name for j in self.items.values() if j.status in ("queued", "running", "waiting")}

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
            job.ended = time.time()
        elif job.proc is not None:
            _stop(job.proc)
        return job

    def stop_all(self) -> None:
        with self.lock:
            jobs = list(self.items.values())
        for job in jobs:
            if job.status in ("queued", "running", "waiting"):
                self.cancel(job.id)

    def _worker(self) -> None:
        while True:
            job = self.pending.get()
            if job.status != "queued":
                continue
            try:
                self._run_audit(job)
            except Exception as exc:  # noqa: BLE001 - one broken job must not stop the queue
                job.fail(f"{exc.__class__.__name__}: {exc}", "jobCrashed", detail=f"{exc.__class__.__name__}: {exc}")
                job.status, job.ended = "failed", time.time()

    def _run_audit(self, job: Job) -> None:
        out = Path(job.spec["config"]["output"])
        fresh = not out.exists()
        job.status, job.started = "running", time.time()
        job.proc = subprocess.Popen(
            [sys.executable, "-m", "ui_audit.runner"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", cwd=self.workspace.root,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}, **_new_group())
        try:
            job.proc.stdin.write(json.dumps(job.spec))
            job.proc.stdin.close()
        except OSError:
            pass
        if job.cancel_requested:  # cancelled while it was starting
            _stop(job.proc)
        for line in job.proc.stdout:
            self._line(job, line.rstrip("\n"))
        code = job.proc.wait()
        job.ended = time.time()
        if job.cancel_requested:
            job.status = "cancelled"
        elif code == 0 and job.result is not None:
            job.status = "done"
        else:
            job.status = "failed"
            if not job.error:
                job.fail(f"the audit stopped (exit code {code}); see the log", "auditStopped", exit=code)
        if job.status != "done" and fresh and not (out / report_mod.REPORT_JSON).exists():
            shutil.rmtree(out, ignore_errors=True)  # screenshots without a report are of no use
        if job.status == "done" and job.kind == "recheck" and not job.result.get("empty"):
            try:
                job.result = {**job.result, "recheck": self._recheck_outcome(job)}
            except Exception as exc:  # noqa: BLE001 - the run itself is still there
                job.fail(f"could not compare with {job.source}: {exc}", "compareFailed", source=job.source, detail=str(exc))

    def _line(self, job: Job, line: str) -> None:
        if line.startswith("{"):
            try:
                event = json.loads(line)
            except ValueError:
                event = None
            if isinstance(event, dict) and "event" in event:
                self._event(job, event)
                return
        if line.strip():
            job.log(line)

    def _event(self, job: Job, event: dict) -> None:
        kind = event.pop("event")
        progress = dict(job.progress)  # replaced, not changed, while requests may be reading it
        if kind == "log":
            job.log(str(event.get("message", "")))
        elif kind == "routes":
            progress.update(paths=len(event.get("paths") or []), limit=event.get("limit"), measured=0, skipped=0,
                            states=0, states_done=0, route=None, state=None)
        elif kind == "route":
            if event.get("status") == "measuring":
                progress.update(measured=progress.get("measured", 0) + 1, route=event.get("path"),
                                states=event.get("states", 0), states_done=0, state=None)
            else:
                progress["skipped"] = progress.get("skipped", 0) + 1
                job.log(f"{event.get('path')}: {event.get('status')} ({event.get('detail', '')})")
        elif kind == "state":
            progress.update(states_done=progress.get("states_done", 0) + 1, state=event.get("state"))
        elif kind == "scope":
            progress["scope"] = event.get("message")
            job.log(str(event.get("message", "")))
        elif kind == "done":
            job.result = event
        elif kind == "error":
            params = event.get("params") if isinstance(event.get("params"), dict) else {}
            job.fail(str(event.get("message", "the audit failed")), str(event.get("code") or "auditFailed"), **params)
            job.log(job.error or "")
        elif kind == "cancelled":
            job.cancel_requested = True
        if "paths" in progress:
            expected = max(1, min(progress["limit"] or 10**9, progress["paths"] - progress["skipped"]))
            done = max(0, progress["measured"] - 1) + (progress["states_done"] / progress["states"] if progress["states"] else 0)
            progress["fraction"] = round(min(0.99, done / expected), 4)
            progress["expected"] = expected
        job.progress = progress

    def _recheck_outcome(self, job: Job) -> dict:
        baseline = self.workspace.report(job.source)
        current = report_mod.read_json(self.workspace.runs_dir / job.name)
        result = verify.compare(baseline, current)
        verify.write(result, self.workspace.runs_dir / job.name)
        wanted = set(job.issue_ids)
        outcome = {issue_id: "not_checked" for issue_id in wanted}
        for key in ("fixed", "persistent"):
            for issue in result[key]:
                if issue["id"] in wanted:
                    outcome[issue["id"]] = key
        return {"issues": outcome, "introduced": result["introduced"][:20]}

    def _run_login(self, job: Job) -> None:
        job.status, job.started = "waiting", time.time()
        job.proc = subprocess.Popen(
            [sys.executable, "-m", "ui_audit", *job.spec["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", cwd=self.workspace.root,
            env={**os.environ, "PYTHONUNBUFFERED": "1"}, **_new_group())
        for line in job.proc.stdout:
            if line.strip():
                job.log(line.rstrip("\n"))
        code = job.proc.wait()
        job.ended = time.time()
        if job.cancel_requested:
            job.status = "cancelled"
        elif code == 0:
            job.status, job.result = "done", {"session": job.name}
        else:
            job.status = "failed"
            job.fail("the browser window closed before the session was saved", "loginClosed")

    def finish_login(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.kind != "login" or job.status != "waiting" or job.proc is None:
            raise ApiError(409, "this sign-in is not waiting", "loginNotWaiting")
        try:
            job.proc.stdin.write("\n")
            job.proc.stdin.flush()
        except OSError as exc:
            raise ApiError(409, f"the sign-in window is gone ({exc})", "loginGone") from exc
        job.status = "running"
        return job


class Api:
    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self.jobs = Jobs(workspace)
        self._browser: dict | None = None

    def handle(self, method: str, path: str, query: dict, body: dict):
        parts = [unquote(part) for part in path.strip("/").split("/")]
        match method, parts:
            case "GET", ["state"]:
                return self.state()
            case "GET", ["runs", name]:
                return self.workspace.run_data(name)
            case "GET", ["check"]:
                return self.check_url((query.get("url") or [""])[0])
            case "GET", ["discover"]:
                return self.discover()
            case "POST", ["command"]:
                return self.audit_command(body)
            case "POST", ["runs"]:
                return self.start_audit(body)
            case "POST", ["runs", name, "again"]:
                return self.run_again(name)
            case "POST", ["runs", name, "recheck"]:
                return self.recheck(name, body)
            case "POST", ["runs", name, "accept"]:
                ids = _strings(body.get("ids"), "ids", 500)
                reason = str(body.get("reason") or "").strip()
                if not ids or not reason or len(reason) > 500:
                    raise ApiError(400, "give the findings and a reason (at most 500 characters)", "acceptNeeds")
                try:
                    added, already, file = report_mod.accept(self.workspace.run_dir(name), ids, reason)
                except LookupError as exc:
                    raise ApiError(404, str(exc), "unknownIds") from exc
                return {"added": added, "already": already, "file": self.workspace.rel(file)}
            case "POST", ["runs", name, "unaccept"]:
                try:
                    removed, file = report_mod.unaccept(self.workspace.run_dir(name), _strings(body.get("ids"), "ids", 500))
                except LookupError as exc:
                    raise ApiError(404, str(exc), "unknownIds") from exc
                return {"removed": removed, "file": self.workspace.rel(file)}
            case "POST", ["runs", name, "delete"]:
                return self.delete(name)
            case "POST", ["runs", name, "reveal"]:
                return self.reveal(name)
            case "POST", ["compare"]:
                base, current = str(body.get("baseline", "")), str(body.get("current", ""))
                result = verify.compare(self.workspace.report(base), self.workspace.report(current))
                return {**result, "baseline": base, "current": current}
            case "POST", ["login"]:
                return self.login(body)
            case "POST", ["jobs", job_id, "cancel"]:
                return self.jobs.cancel(job_id).public()
            case "POST", ["jobs", job_id, "continue"]:
                return self.jobs.finish_login(job_id).public()
        raise ApiError(404, f"no such endpoint: {method} /api/{path}", "notFound")

    def state(self) -> dict:
        ws = self.workspace
        default = None
        try:
            cfg = ws.config()
            default = {"path": ws.rel(ws.config_path) if ws.config_path else None, "base_url": cfg.base_url,
                       "storage_state": cfg.storage_state, "locale": cfg.locale, "sweep": cfg.states.sweep,
                           "browsers": cfg.browsers}
        except (ConfigError, OSError, ValueError) as exc:
            default = {"path": ws.rel(ws.config_path) if ws.config_path else None, "error": str(exc)}
        return {"version": __version__, "project": ws.root.name, "root": str(ws.root), "runs_dir": ws.rel(ws.runs_dir),
                "config": default, "configs": ws.config_files(), "sessions": ws.sessions(), "runs": ws.runs(),
                "jobs": self.jobs.list(), "browser": self.browser()}

    def browser(self) -> dict:
        """Whether Chromium is there, looked up once in the background."""
        if self._browser is None:
            self._browser = {"ok": None}

            def look() -> None:
                from .browser import _fallback_executables

                try:
                    from playwright.sync_api import sync_playwright

                    with sync_playwright() as playwright:
                        pinned = playwright.chromium.executable_path
                    ok = bool(os.environ.get("UI_AUDIT_BROWSER_PATH")) or Path(pinned).exists() or bool(_fallback_executables())
                    self._browser = {"ok": ok, "detail": "" if ok else "run `playwright install chromium`"}
                except Exception as exc:  # noqa: BLE001 - shown to the person as is
                    self._browser = {"ok": False, "detail": str(exc).splitlines()[0][:200]}

            threading.Thread(target=look, daemon=True).start()
        return self._browser

    def check_url(self, url: str, timeout: float = 4) -> dict:
        if not re.match(r"^https?://[^\s/]+", url or ""):
            return {"ok": False, "detail": "not an http(s) address"}
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - the person's own dev server
                return {"ok": True, "status": response.status}
        except urllib.error.HTTPError as exc:
            return {"ok": exc.code < 500, "status": exc.code}
        except Exception as exc:  # noqa: BLE001 - any network error means "not reachable"
            reason = getattr(exc, "reason", exc)
            return {"ok": False, "detail": str(reason)[:160]}

    def discover(self) -> dict:
        """Dev servers that answer on the usual ports, for a first start without a settings
        file. Only this computer's loopback address is tried, never another host."""
        found: dict[int, bool] = {}

        def look(port: int) -> None:
            found[port] = self.check_url(f"http://127.0.0.1:{port}/", timeout=1.5)["ok"]

        threads = [threading.Thread(target=look, args=(port,), daemon=True) for port in COMMON_PORTS]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(2)
        return {"found": [f"http://127.0.0.1:{port}" for port in COMMON_PORTS if found.get(port)], "ports": list(COMMON_PORTS)}

    def audit_command(self, body: dict) -> dict:
        """The command line that starts the audit this body would start (POST /api/runs),
        quoted for a POSIX shell like every command ui-audit prints."""
        ws, q = self.workspace, shlex.quote
        parts = ["ui-audit audit"]
        config, settings_url = str(body.get("config") or ""), None
        if config:
            parts.append(f"--config {q(config)}")
            try:
                settings_url = ws.config(ws.config_file(config)).base_url
            except (ApiError, ConfigError, OSError, ValueError):
                pass
        base_url = str(body.get("base_url") or "").strip()
        if base_url and base_url != settings_url:
            parts.append(f"--base-url {q(base_url)}")
        mode = body.get("mode")
        if mode == "quick":
            parts.append("--fast")
        if mode == "pages":
            parts += [f"--route {q(route)}" for route in _strings(body.get("routes"), "routes", 60)]
            widths = _strings(body.get("widths"), "widths", 40)
            if widths:
                parts.append(f"--width {q(','.join(widths))}")
        for flag, key in (("--storage-state", "storage_state"), ("--locale", "locale")):
            if body.get(key):
                parts.append(f"{flag} {q(str(body[key]))}")
        if body.get("states") is False:
            parts.append("--no-states")
        if not body.get("annotate"):
            parts.append("--no-annotate")
        if body.get("changed_since") and mode != "pages":
            parts.append(f"--changed-since {q(str(body['changed_since']))}")
        if body.get("name"):
            parts.append(f"--output {q(ws.rel(ws.runs_dir) + '/' + str(body['name']))}")
        return {"command": " \\\n  ".join(parts)}

    def _name(self, base: str) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-.")[:70] or "audit"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        busy = self.jobs.busy_names()
        name, n = f"{base}-{stamp}", 2
        while (self.workspace.runs_dir / name).exists() or name in busy:
            name, n = f"{base}-{stamp}-{n}", n + 1
        return name

    def _submit(self, kind: str, config: dict, routes: list[str], title: str, base: str, extra: dict | None = None,
                **job_args) -> dict:
        name = self._name(base)
        config = {**config, "output": str(self.workspace.runs_dir / name)}
        spec = {"config": config, "routes": routes, **(extra or {})}
        return self.jobs.submit(Job(kind, name, spec, title=title, **job_args)).public()

    def _settings(self, body: dict) -> tuple[Path | None, Config]:
        """The settings file a request names; without "config" the app's own, with "" the built-in defaults."""
        ws = self.workspace
        if "config" in body:
            name = str(body.get("config") or "")
            config_file = ws.config_file(name) if name else None
        else:
            config_file = ws.config_path
        return config_file, (ws.config(config_file) if config_file else Config())

    def start_audit(self, body: dict) -> dict:
        ws = self.workspace
        config_file, cfg = self._settings(body)
        base_url = str(body.get("base_url") or cfg.base_url).strip()
        if not re.match(r"^https?://[^\s]+$", base_url):
            raise ApiError(400, "the app address must start with http:// or https://", "badUrl")
        cfg.base_url = base_url
        mode = body.get("mode", "quick")
        if mode not in ("quick", "complete", "pages"):
            raise ApiError(400, "mode must be quick, complete or pages", "badMode")
        if mode in ("quick", "complete"):
            cfg.states.sweep = "key" if mode == "quick" else "full"
        routes = _strings(body.get("routes"), "routes", 60) if mode == "pages" else []
        if any(not route.startswith("/") for route in routes):
            raise ApiError(400, "every page must start with /, like /pricing", "pageSlash")
        if mode == "pages" and not routes:
            raise ApiError(400, "list at least one page, like /pricing", "noPages")
        widths = _strings(body.get("widths"), "widths", 40, re.compile(r"^\d{3,4}$")) if mode == "pages" else []
        cfg.viewports.widths = sorted({int(w) for w in widths})
        if "locale" in body:
            locale = str(body.get("locale") or "")
            if locale and not LOCALE.match(locale):
                raise ApiError(400, "language must look like de or fr-FR", "badLocale")
            cfg.locale = locale
        if "browsers" in body:
            try:
                cfg.browsers = parse_browsers(body.get("browsers") or [])
            except ConfigError as exc:
                raise ApiError(400, str(exc), "config", detail=str(exc)) from exc
        if "storage_state" in body:
            cfg.storage_state = ws.session_file(str(body.get("storage_state") or ""))
        if body.get("states") is False:
            cfg.states.auto = False
        if "annotate" in body:
            cfg.annotate = bool(body["annotate"])
        extra = {}
        if body.get("changed_since"):
            ref = str(body["changed_since"])
            if not GIT_REF.match(ref):
                raise ApiError(400, "not a git branch, tag or commit", "badRef")
            baseline = str(body.get("baseline") or "")
            if not baseline:
                complete = [r for r in ws.runs() if not r["targeted"]]
                if not complete:
                    raise ApiError(400, "only-changed runs need an earlier complete audit to compare with", "noBaseline")
                baseline = complete[0]["name"]
            extra = {"changed_since": ref, "baseline": str(ws.run_dir(baseline))}
        # "menusmarter" from .ui-audit/menusmarter.toml; for the default settings file, the project folder's name
        if config_file and config_file.name != CONFIG_FILENAME:
            default_base = config_file.stem
        else:
            default_base = (Path(cfg.project_root).name if config_file else ws.root.name) or "audit"
        base = str(body.get("name") or default_base)
        return self._submit("audit", cfg.to_dict(), routes, title=base, base=base, extra=extra)

    def run_again(self, name: str) -> dict:
        report = self.workspace.report(name)
        base = STAMP.sub("", name)
        return self._submit("audit", copy.deepcopy(report["config"]), report.get("only_routes") or [], title=base, base=base)

    def recheck(self, name: str, body: dict) -> dict:
        report = self.workspace.report(name)
        wanted = set(_strings(body.get("ids"), "ids", 500))
        issues = [i for i in report["issues"] if i["id"] in wanted]
        if not issues:
            raise ApiError(404, "none of these findings are in this run", "notInRun")
        config = copy.deepcopy(report["config"])
        viewports = config.setdefault("viewports", {})
        widths = recheck_widths(issues, viewports.get("min_width", 320), viewports.get("max_width", 1920))
        if not widths:
            raise ApiError(400, "these findings have no widths to look at again", "noWidths")
        viewports["widths"] = widths
        if all(i["state"] == "default" for i in issues):
            config.setdefault("states", {})["auto"] = False  # nothing to open: skip looking for menus and dialogs
        routes = sorted({i["route"] for i in issues})
        base = f"{STAMP.sub('', name)}-recheck"
        title = issues[0]["check"] if len(issues) == 1 else f"{len(issues)} findings"
        return self._submit("recheck", config, routes, title=title, base=base, source=name,
                            issue_ids=[i["id"] for i in issues])

    def login(self, body: dict) -> dict:
        ws = self.workspace
        config_file, cfg = self._settings(body)
        base_url = str(body.get("base_url") or cfg.base_url).strip()
        path = str(body.get("path") or "/").strip()
        if not re.match(r"^https?://[^\s]+$", base_url) or not path.startswith("/"):
            raise ApiError(400, "give the app address and a page that starts with /", "loginNeeds")
        name = str(body.get("save") or "auth.json")
        if not RUN_NAME.match(name) or not name.endswith(".json"):  # a plain file name: never package.json one folder up
            raise ApiError(400, "sessions are saved as a plain .json file name next to the runs", "badSessionName")
        save = ws.runs_dir / name
        args = ["login", "--base-url", base_url, "--path", path, "--save", str(save)]
        if config_file:
            args += ["--config", str(config_file)]
        return self.jobs.submit(Job("login", ws.rel(save), {"args": args}, title=path)).public()

    def delete(self, name: str) -> dict:
        folder = self.workspace.run_dir(name)
        if name in self.jobs.busy_names():
            raise ApiError(409, "this run is still being written", "runBusy")
        if folder.is_symlink() or folder.resolve().parent != self.workspace.runs_dir:
            raise ApiError(400, "only run folders directly in the runs folder can be deleted", "notDeletable")
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        shutil.rmtree(folder)
        return {"deleted": name, "bytes": size}

    def reveal(self, name: str) -> dict:
        folder = self.workspace.run_dir(name)
        command = {"darwin": ["open"], "win32": ["explorer"]}.get(sys.platform, ["xdg-open"])
        try:
            subprocess.Popen([*command, str(folder)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise ApiError(501, f"cannot open folders here: {exc}", "cannotReveal", detail=str(exc)) from exc
        return {"opened": str(folder)}


class Handler(BaseHTTPRequestHandler):
    server: "AppServer"
    protocol_version = "HTTP/1.1"
    server_version = f"ui-audit/{__version__}"

    def log_message(self, format, *args) -> None:  # noqa: A002 - quiet; errors are reported in the page
        pass

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        url = urlparse(self.path)
        try:
            if self.headers.get("Host", "") not in self.server.hosts:
                raise ApiError(403, "unexpected Host header", "badHost")
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._page(parse_qs(url.query).get("k", [""])[0])
            if method == "GET" and url.path.startswith("/files/"):
                if not self._has_session():
                    raise ApiError(403, "open the app first", "openFirst")
                return self._send_file(url.path[len("/files/"):])
            if url.path.startswith("/api/"):
                if not hmac.compare_digest(self.headers.get("X-UI-Audit-Token", ""), self.server.token):
                    raise ApiError(403, "missing or wrong token", "badToken")
                body = self._body() if method == "POST" else {}
                result = self.server.api.handle(method, url.path[len("/api/"):], parse_qs(url.query), body)
                return self._json(200, result)
            raise ApiError(404, "not found", "notFound")
        except ApiError as exc:
            self._json(exc.status, exc.body())
        except ConfigError as exc:
            self._json(400, ApiError(400, f"config error: {exc}", "config", detail=str(exc)).body())
        except Exception as exc:  # noqa: BLE001 - show it in the page instead of dropping the connection
            traceback.print_exc()
            detail = f"{exc.__class__.__name__}: {exc}"
            self._json(500, ApiError(500, detail, "internal", detail=detail).body())

    def _page(self, key: str) -> None:
        """The page, only for a browser that opened the address printed in the terminal: its
        key (`?k=`) buys a strict same-site cookie, and the cookie buys the page with the token
        in it. Another user on this machine knows the port but not the key."""
        if key:
            if not hmac.compare_digest(key, self.server.key):
                return self._send(403, FORBIDDEN_PAGE, "text/html; charset=utf-8", {"Content-Security-Policy": PAGE_POLICY})
            # Screenshots load through <img>, which cannot send the token header, so the cookie
            # carries the token too. The page then reloads itself without the key: a same-origin
            # navigation, so the strict cookie is sent even when the link was opened from elsewhere.
            cookie = f"{self.server.cookie}={self.server.token}; Path=/; HttpOnly; SameSite=Strict"
            return self._send(200, ENTER_PAGE, "text/html; charset=utf-8",
                              {"Content-Security-Policy": PAGE_POLICY, "Set-Cookie": cookie})
        if not self._has_session():
            return self._send(403, FORBIDDEN_PAGE, "text/html; charset=utf-8", {"Content-Security-Policy": PAGE_POLICY})
        return self._send(200, report_mod.page(app={"token": self.server.token, "version": __version__}).encode(),
                          "text/html; charset=utf-8", {"Content-Security-Policy": PAGE_POLICY})

    def _has_session(self) -> bool:
        jar = SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except CookieError:
            pass
        sent = jar[self.server.cookie].value if self.server.cookie in jar else ""
        return hmac.compare_digest(sent, self.server.token)

    def _body(self) -> dict:
        try:
            length = max(0, int(self.headers.get("Content-Length") or 0))
        except ValueError:
            length = 0
            self.close_connection = True  # unknown body length: do not read the rest as the next request
        if length > MAX_BODY:
            self.close_connection = True
            raise ApiError(413, "request too large", "tooLarge")
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError as exc:
            raise ApiError(400, "the request body is not JSON", "notJson") from exc
        if not isinstance(body, dict):
            raise ApiError(400, "the request body must be a JSON object", "notObject")
        return body

    def _send_file(self, rest: str) -> None:
        name, _, inner = rest.partition("/")
        folder = self.server.api.workspace.run_dir(unquote(name)).resolve()
        target = (folder / unquote(inner)).resolve()
        if not target.is_relative_to(folder) or target.suffix.lower() not in IMAGE_TYPES or not target.is_file():
            raise ApiError(404, "not found", "notFound")
        modified = target.stat().st_mtime
        since = self.headers.get("If-Modified-Since")
        if since:
            try:
                if parsedate_to_datetime(since).timestamp() >= int(modified):
                    return self._send(304, b"", None, {"Last-Modified": formatdate(modified, usegmt=True)})
            except (TypeError, ValueError):
                pass
        self._send(200, target.read_bytes(), IMAGE_TYPES[target.suffix.lower()],
                   {"Last-Modified": formatdate(modified, usegmt=True), "Cache-Control": "private, no-cache"})

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _send(self, status: int, body: bytes, content_type: str | None, headers: dict | None = None) -> None:
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if not (headers and "Cache-Control" in headers):
            self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, workspace: Workspace, port: int = DEFAULT_PORT) -> None:
        try:
            super().__init__(("127.0.0.1", port), Handler)
        except OSError:
            super().__init__(("127.0.0.1", 0), Handler)  # the port is taken: any free one
        self.port = self.server_address[1]
        self.hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        self.token = secrets.token_urlsafe(24)
        self.key = secrets.token_urlsafe(24)  # in the printed address; valid while the server runs
        self.cookie = f"ui-audit-{self.port}"
        self.api = Api(workspace)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def launch_url(self) -> str:
        """The address to open: it carries the key that lets this browser in."""
        return f"{self.url}?k={self.key}"


def serve(workspace: Workspace, port: int = DEFAULT_PORT, open_browser: bool = True) -> None:
    server = AppServer(workspace, port)
    print(f"ui-audit is running at {server.launch_url}")
    print("open this address (with its key) to use the app; without the key the page is refused")
    print(f"runs: {workspace.runs_dir}")
    print("press Ctrl+C to stop")
    if open_browser:
        import webbrowser

        threading.Timer(0.4, webbrowser.open, (server.launch_url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.api.jobs.stop_all()
        server.server_close()
