"""`ui-audit ci`: start the app, audit it, compare with the base branch and report.

One command a CI job runs instead of a script of its own: it starts the app (once in
the checkout under test and, with `--compare base`, once in a worktree of the base
commit), audits each, compares them with `verify`, and writes a Markdown summary that
fits a job summary and a pull request comment. On GitHub Actions it writes the summary
to the job page, posts or updates one comment on the pull request and sets step outputs.
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import ipaddress
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import report as report_mod
from . import verify

MARKER = "<!-- ui-audit-ci -->"
LIST_LIMIT = 15


class CIError(Exception):
    """A step failed in a way the summary should explain rather than hide."""


# --- the app under test ------------------------------------------------------

def _loopback(host: str) -> bool:
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


# urllib honours proxy environment variables and, on macOS, the system proxy settings, neither of
# which exempts 127.0.0.1 by default; an app on this machine is asked directly.
_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _answers(url: str) -> bool:
    opener = _DIRECT if _loopback(urlparse(url).hostname or "") else urllib.request.build_opener()
    try:
        with opener.open(url, timeout=3) as response:  # noqa: S310 - the app under test
            return response.status < 500
    except urllib.error.HTTPError as exc:
        return exc.code < 500
    except Exception:  # noqa: BLE001 - not up yet
        return False


class App:
    """The app started by a shell command, in its own process group so all of it stops."""

    def __init__(self, command: str, cwd: Path, log_path: Path):
        self.command, self.cwd, self.log_path = command, cwd, log_path
        self.process: subprocess.Popen | None = None

    def start(self, url: str, timeout: float) -> None:
        if _answers(url):
            raise CIError(f"something already answers at {url} before the app was started; "
                          "stop it or let ui-audit start the app")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("w", encoding="utf-8")
        group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"  # type: ignore[attr-defined]
                 else {"start_new_session": True})
        self.process = subprocess.Popen(self.command, shell=True, cwd=self.cwd, stdout=log, stderr=subprocess.STDOUT,
                                        **group)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if _answers(url):
                return
            if self.process.poll() is not None:
                raise CIError(f"the start command exited with code {self.process.returncode} before {url} answered"
                              f"\n{self.tail()}")
            time.sleep(1)
        self.stop()
        raise CIError(f"{url} did not answer within {timeout:.0f}s of starting the app\n{self.tail()}")

    def stop(self, url: str | None = None) -> None:
        if self.process and self.process.poll() is None and os.name == "nt":
            # cmd.exe passes nothing on to the app it started; end the whole process tree.
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)], capture_output=True)
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                pass
        elif self.process and self.process.poll() is None:
            for sig, wait in ((signal.SIGTERM, 10), (signal.SIGKILL, 5)):
                try:
                    os.killpg(self.process.pid, sig)
                except ProcessLookupError:
                    break
                try:
                    self.process.wait(wait)
                    break
                except subprocess.TimeoutExpired:
                    continue
        # A dev server's children can outlive the group leader for a moment; the next
        # start must not find the old app still answering.
        deadline = time.monotonic() + 10
        while url and time.monotonic() < deadline and _answers(url):
            time.sleep(0.5)

    def tail(self, lines: int = 20) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        return "app output (last lines):\n" + "\n".join(text[-lines:]) if text else ""


def _run(command: str, cwd: Path, label: str) -> None:
    print(f"::group::{label}" if _on_github() else f"== {label}", flush=True)
    done = subprocess.run(command, shell=True, cwd=cwd)
    if _on_github():
        print("::endgroup::", flush=True)
    if done.returncode:
        raise CIError(f"{label} failed with exit code {done.returncode}: {command}")


def _audit(url: str, cwd: Path, output: Path, audit_args: list[str], extra: list[str] | None = None) -> int:
    command = [sys.executable, "-m", "ui_audit", "audit", url, "--no-annotate", "--output", str(output),
               *audit_args, *(extra or [])]
    print(f"::group::ui-audit audit ({cwd})" if _on_github() else f"== ui-audit audit ({cwd})", flush=True)
    done = subprocess.run(command, cwd=cwd)
    if _on_github():
        print("::endgroup::", flush=True)
    return done.returncode


def audit_checkout(*, cwd: Path, url: str, output: Path, audit_args: list[str], install: str | None,
                   start: str | None, timeout: float, label: str, extra: list[str] | None = None) -> None:
    if install:
        _run(install, cwd, f"install ({label})")
    app = App(start, cwd, output.parent / f"app-{label}.log") if start else None
    try:
        if app:
            app.start(url, timeout)
        elif not _answers(url):
            raise CIError(f"nothing answers at {url}; start the app first or pass --start")
        code = _audit(url, cwd, output, audit_args, extra)
        if code not in (0, 2):  # 2 is --fail-on in the audit args; the summary decides here
            raise CIError(f"ui-audit audit exited with code {code} for the {label} checkout")
    finally:
        if app:
            app.stop(url)


# --- the base commit ---------------------------------------------------------

def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def base_worktree(cwd: Path, ref: str, into: Path) -> tuple[Path, str]:
    """A checkout of `ref` next to the current one; returns the matching working directory and the commit."""
    try:
        top = Path(_git("rev-parse", "--show-toplevel", cwd=cwd))
        try:
            _git("cat-file", "-e", f"{ref}^{{commit}}", cwd=top)
        except subprocess.CalledProcessError:  # a shallow checkout: fetch just that commit
            _git("fetch", "--quiet", "--depth=1", "origin", ref, cwd=top)
            ref = "FETCH_HEAD" if not _is_sha(ref) else ref
        sha = _git("rev-parse", f"{ref}^{{commit}}", cwd=top)
        if into.exists():
            _git("worktree", "remove", "--force", str(into), cwd=top)
        _git("worktree", "add", "--quiet", "--detach", str(into), sha, cwd=top)
    except subprocess.CalledProcessError as exc:
        raise CIError(f"could not check out the base commit {ref}: {(exc.stderr or '').strip() or exc}") from exc
    return into / cwd.resolve().relative_to(top.resolve()), sha


def _is_sha(ref: str) -> bool:
    return len(ref) >= 7 and all(c in "0123456789abcdef" for c in ref.lower())


def remove_worktree(cwd: Path, path: Path) -> None:
    try:
        _git("worktree", "remove", "--force", str(path), cwd=cwd)
    except (subprocess.CalledProcessError, OSError):
        pass


# --- the summary -------------------------------------------------------------

def _open(issues: list[dict]) -> list[dict]:
    return [i for i in issues if not i.get("accepted")]


def _where(issue: dict) -> str:
    widths = issue.get("widths") or []
    span = f"{widths[0]}–{widths[-1]}px" if len(widths) > 1 else (f"{widths[0]}px" if widths else "")
    state = "" if issue.get("state") in (None, "default") else f" ({issue['state']})"
    return f"`{issue['route']}`{state}" + (f" at {span}" if span else "")


def _line(issue: dict) -> str:
    return f"- **{issue['severity']}** {issue['check']} on {_where(issue)}: {issue['message']} `{issue['selector']}`"


def _list(issues: list[dict]) -> list[str]:
    lines = [_line(i) for i in issues[:LIST_LIMIT]]
    if len(issues) > LIST_LIMIT:
        lines.append(f"- … and {len(issues) - LIST_LIMIT} more in the report")
    return lines


def _details(title: str, issues: list[dict]) -> list[str]:
    if not issues:
        return []
    return ["", f"<details><summary>{title} ({len(issues)})</summary>", "", *_list(issues), "", "</details>"]


def _counts(issues: list[dict]) -> str:
    counts = report_mod.summary_counts(issues)
    return " · ".join(f"{counts[level]} {level}" for level in ("P1", "P2", "P3"))


def render_summary(current: dict | None, comparison: dict | None = None, *, base: dict | None = None,
                   base_sha: str | None = None, blocking: bool = False, run_url: str | None = None,
                   notes: list[str] | None = None, artifact: str | None = None) -> str:
    lines = [MARKER]
    notes = list(notes or [])
    if current is None:
        lines += ["### ui-audit could not audit this change", ""]
        lines += [f"> {note}" for note in notes] or ["> See the job log."]
        if run_url:
            lines += ["", f"[Job log]({run_url})"]
        return "\n".join(lines) + "\n"

    issues = _open(current["issues"])
    routes = report_mod.audited_routes(current)
    if comparison is not None:
        new, fixed, still = comparison["introduced"], comparison["fixed"], comparison["persistent"]
        mark = "❌" if blocking else ("⚠️" if new else "✅")
        if new:
            head = f"{mark} ui-audit: {len(new)} new responsive problem{'s' if len(new) != 1 else ''} in this change"
        else:
            head = f"{mark} ui-audit: no new responsive problems"
        against = f"the base commit `{base_sha[:7]}`" if base_sha else "the baseline"
        lines += [f"### {head}", "",
                  f"Compared with {against}: **{len(new)} new** · {len(fixed)} fixed · {len(still)} still open "
                  f"across {len(routes)} route{'s' if len(routes) != 1 else ''}."]
        if base is not None:
            lines += ["", "| | P1 | P2 | P3 |", "|---|---|---|---|"]
            for label, report in (("This change", current), ("Base", base)):
                counts = report_mod.summary_counts(report["issues"])
                lines.append(f"| {label} | {counts['P1']} | {counts['P2']} | {counts['P3']} |")
        if new:
            lines += ["", "#### New in this change", "", *_list(new)]
        lines += _details("Fixed", fixed)
        lines += _details("Still open", still)
        if comparison.get("out_of_scope"):
            notes.append(f"{comparison['out_of_scope']} base finding(s) are on routes, states or widths this run did "
                         "not look at, so they are neither fixed nor open here.")
    else:
        groups = [g for g in current.get("groups", []) if any(not i.get("accepted") for i in current["issues"]
                                                               if i.get("group") == g["id"])]
        mark = "❌" if blocking else ("⚠️" if issues else "✅")
        if issues:
            causes = f" from {len(groups)} cause{'s' if len(groups) != 1 else ''}" if groups and len(groups) < len(issues) else ""
            head = f"{mark} ui-audit: {len(issues)} responsive problem{'s' if len(issues) != 1 else ''}{causes}"
        else:
            head = f"{mark} ui-audit: no responsive problems"
        lines += [f"### {head}", "", f"{_counts(issues)} across {len(routes)} route{'s' if len(routes) != 1 else ''}."]
        if issues:
            by_id = {i["id"]: i for i in issues}
            firsts = [by_id[next(x for x in g["issue_ids"] if x in by_id)] for g in groups
                      if any(x in by_id for x in g["issue_ids"])] or issues
            lines += ["", "#### Problems", "", *_list(firsts)]
    for route in routes:
        content = route.get("content") or {}
        if content.get("state", "ok") != "ok":
            notes.append(f"`{route['path']}` may not show its real content ({content['state']}: {content.get('detail', '')}),"
                         " so a clean result there means little.")
    for error in current.get("errors", [])[:5]:
        notes.append(f"warning: {error}")
    if notes:
        lines += ["", *[f"> {note}" for note in notes]]
    if run_url:
        where = f"the `{artifact}` artifact" if artifact else "the artifacts"
        lines += ["", f"Screenshots and the full report: {where} of [this run]({run_url}) (open `head/index.html`)."]
    return "\n".join(lines) + "\n"


# --- GitHub ------------------------------------------------------------------

def _on_github() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _event() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def github_context() -> dict:
    event = _event()
    pr = event.get("pull_request") or {}
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run = os.environ.get("GITHUB_RUN_ID")
    return {
        "repo": repo,
        "pr": pr.get("number"),
        "base_sha": (pr.get("base") or {}).get("sha"),
        "run_url": f"{server}/{repo}/actions/runs/{run}" if repo and run else None,
        "api": os.environ.get("GITHUB_API_URL", "https://api.github.com"),
    }


def _api(method: str, url: str, token: str, body: dict | None = None):
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ui-audit"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - GitHub API
        return json.loads(response.read() or b"null")


def post_comment(body: str, *, api: str, repo: str, pr: int, token: str) -> str:
    """Create the pull request comment, or update the one an earlier run left."""
    existing = None
    page = 1
    while existing is None:
        comments = _api("GET", f"{api}/repos/{repo}/issues/{pr}/comments?per_page=100&page={page}", token)
        existing = next((c for c in comments if MARKER in (c.get("body") or "")), None)
        if len(comments) < 100:
            break
        page += 1
    if existing:
        return _api("PATCH", f"{api}/repos/{repo}/issues/comments/{existing['id']}", token, {"body": body})["html_url"]
    return _api("POST", f"{api}/repos/{repo}/issues/{pr}/comments", token, {"body": body})["html_url"]


def _set_outputs(values: dict) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


# --- the command -------------------------------------------------------------

def is_blocking(fail_on: str, current: dict | None, comparison: dict | None) -> bool:
    if current is None or fail_on == "never":
        return False
    if fail_on == "new":
        return bool(comparison) and any(i["severity"] in ("P1", "P2") for i in comparison["introduced"])
    levels = {"P1": ("P1",), "P2": ("P1", "P2"), "P3": ("P1", "P2", "P3")}[fail_on]
    return any(i["severity"] in levels for i in _open(current["issues"]))


def run(args) -> int:
    # The app's install and start commands run code from the pull request: they must not see the
    # token that posts the comment. GITHUB_TOKEN is read too, for runs outside the action.
    tokens = [os.environ.pop(name, None) for name in ("UI_AUDIT_GITHUB_TOKEN", "GITHUB_TOKEN")]
    token = next((t for t in tokens if t), None)
    cwd = Path(args.working_directory or ".").resolve()
    out = (cwd / args.output).resolve() if not Path(args.output).is_absolute() else Path(args.output)
    head_dir, base_dir = out / "head", out / "base"
    out.mkdir(parents=True, exist_ok=True)
    audit_args = shlex.split(args.args or "")
    gh = github_context()
    notes: list[str] = []
    current = base = comparison = None
    base_sha = None
    failed = False

    compare = args.compare
    if compare == "auto":
        compare = "base" if (args.base_ref or gh["base_sha"]) and args.start else "none"
    try:
        baseline_dir = None
        if compare == "base":
            ref = args.base_ref or gh["base_sha"]
            if not ref:
                raise CIError("--compare base needs --base-ref (on GitHub, the pull request's base commit is used)")
            if not args.start:
                raise CIError("--compare base needs --start: the app has to run once from each commit")
            worktree = Path(os.environ.get("RUNNER_TEMP") or tempfile.gettempdir()) / "ui-audit-base"
            base_cwd, base_sha = base_worktree(cwd, ref, worktree)
            try:
                audit_checkout(cwd=base_cwd, url=args.url, output=base_dir, audit_args=audit_args, install=args.install,
                               start=args.start, timeout=args.wait_timeout, label="base")
                baseline_dir = base_dir
            except CIError as exc:
                # Without the base there is no telling what this change introduced: fail rather
                # than pass a check that could not look.
                notes.append(f"The base commit could not be audited, so nothing is compared: {exc}".splitlines()[0])
                print(f"error: {exc}", file=sys.stderr)
                failed = args.fail_on != "never"
            finally:
                remove_worktree(cwd, worktree)
        elif compare != "none":
            baseline_dir = (cwd / compare).resolve()
            if not (baseline_dir / report_mod.REPORT_JSON).is_file():
                raise CIError(f"no report.json in the baseline {compare}")

        extra = []
        if args.changed_only and baseline_dir is not None and base_sha:
            extra = ["--changed-since", base_sha, "--baseline", str(baseline_dir)]
        audit_checkout(cwd=cwd, url=args.url, output=head_dir, audit_args=audit_args, install=args.install,
                       start=args.start, timeout=args.wait_timeout, label="head", extra=extra)
        if (head_dir / report_mod.REPORT_JSON).is_file():
            current = report_mod.read_json(head_dir)
        elif extra:
            notes.append("No route renders a file this change touched, so nothing was audited.")
            current = {"issues": [], "routes": [], "groups": [], "errors": []}
        else:
            raise CIError("the audit wrote no report")
        if baseline_dir is not None:
            base = report_mod.read_json(baseline_dir)
            comparison = verify.compare(base, current)
            verify.write(comparison, out)
    except CIError as exc:
        failed = True
        notes.append(str(exc).splitlines()[0])
        print(f"error: {exc}", file=sys.stderr)

    blocking = is_blocking(args.fail_on, current, comparison)
    artifact = os.environ.get("UI_AUDIT_ARTIFACT")
    summary = render_summary(current, comparison, base=base, base_sha=base_sha, blocking=blocking,
                             run_url=gh["run_url"] if _on_github() else None, notes=notes, artifact=artifact)
    (out / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)

    if _on_github() and os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary.replace(MARKER + "\n", "") + "\n")
    if args.comment and gh["pr"] and gh["repo"]:
        if not token:
            print("warning: no GITHUB_TOKEN, so no pull request comment", file=sys.stderr)
        else:
            try:
                print(f"comment: {post_comment(summary, api=gh['api'], repo=gh['repo'], pr=gh['pr'], token=token)}")
            except urllib.error.HTTPError as exc:
                # Pull requests from forks get a read-only token; the job summary still has everything.
                print(f"warning: could not comment on the pull request ({exc.code}); "
                      "the job needs `permissions: pull-requests: write`", file=sys.stderr)

    counts = report_mod.summary_counts(current["issues"]) if current else {"P1": 0, "P2": 0, "P3": 0}
    _set_outputs({
        "report-dir": str(head_dir), "summary-file": str(out / "summary.md"),
        "p1": counts["P1"], "p2": counts["P2"], "p3": counts["P3"],
        "introduced": len(comparison["introduced"]) if comparison else "",
        "fixed": len(comparison["fixed"]) if comparison else "",
        "blocking": str(blocking).lower(),
    })
    if failed:
        return 2
    return 1 if blocking else 0


def add_parser(sub) -> None:
    p = sub.add_parser("ci", help="start the app, audit it, compare with the base commit and report (for CI jobs)")
    p.add_argument("url", help="where the app answers once started, e.g. http://localhost:3000")
    p.add_argument("--start", help="shell command that starts the app and keeps running; stopped after each audit")
    p.add_argument("--install", help="shell command run before --start in each checkout, e.g. 'npm ci'")
    p.add_argument("--wait-timeout", type=float, default=180, help="seconds to wait for the app to answer (default 180)")
    p.add_argument("--working-directory", help="where the app lives (default: current directory)")
    p.add_argument("--compare", default="auto",
                   help="'base' audits the base commit too, 'none' skips the comparison, or a folder with a report.json; "
                        "'auto' (default) is 'base' when there is a base commit and a start command")
    p.add_argument("--base-ref", help="commit or branch to compare with (default on GitHub: the pull request's base)")
    p.add_argument("--changed-only", action="store_true",
                   help="audit only routes that render a changed file in this checkout (needs --compare base)")
    p.add_argument("--fail-on", default="new", choices=["new", "P1", "P2", "P3", "never"],
                   help="'new' (default) fails when the change introduces a P1 or P2; P1/P2/P3 fail on any open "
                        "finding at or above that level")
    p.add_argument("--args", help="extra arguments for `ui-audit audit`, e.g. '--fast --route /'")
    p.add_argument("--output", default=".ui-audit/ci", help="folder for both reports and summary.md (default .ui-audit/ci)")
    p.add_argument("--comment", action="store_true",
                   help="on a GitHub pull request, post the summary as a comment (updated on later runs)")
    p.set_defaults(func=run)
