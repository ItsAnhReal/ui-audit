import base64
import json
import subprocess
import sys

import pytest
from agent_fixtures import make_run, tiny_png


class Client:
    """Talks JSON-RPC to `ui-audit mcp` in its own process, one line per message."""

    def __init__(self, cwd):
        self.proc = subprocess.Popen([sys.executable, "-m", "ui_audit", "mcp"], cwd=cwd, text=True,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0

    def notify(self, method, params=None):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()

    def send_raw(self, line):
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def request(self, method, params=None):
        self.next_id += 1
        answer = self.send_raw(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}}))
        assert answer["id"] == self.next_id
        return answer

    def call(self, name, **arguments):
        return self.request("tools/call", {"name": name, "arguments": arguments})["result"]

    def close(self):
        self.proc.stdin.close()
        assert self.proc.wait(timeout=10) == 0
        return self.proc.stderr.read()


@pytest.fixture
def client(tmp_path):
    c = Client(tmp_path)
    yield c
    if c.proc.poll() is None:
        c.proc.kill()


def test_handshake_and_tool_list(client):
    answer = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "test", "version": "1"}})
    result = answer["result"]
    assert result["protocolVersion"] == "2025-06-18" and "tools" in result["capabilities"]
    assert result["serverInfo"]["name"] == "ui-audit"
    client.notify("notifications/initialized")  # no answer: the next line belongs to the next request
    tools = {t["name"]: t for t in client.request("tools/list")["result"]["tools"]}
    assert set(tools) == {"audit", "verify", "list_findings", "get_screenshot", "accept"}
    assert tools["audit"]["inputSchema"]["required"] == ["base_url"]
    assert client.request("ping")["result"] == {}
    assert client.request("nope")["error"]["code"] == -32601
    assert client.send_raw("{not json")["error"]["code"] == -32700
    log = client.close()
    assert "ready" in log  # logs go to stderr, never stdout


def test_older_protocol_versions_are_accepted(client):
    assert client.request("initialize", {"protocolVersion": "2024-11-05"})["result"]["protocolVersion"] == "2024-11-05"
    assert client.request("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] == "2025-06-18"


def test_list_findings_pages_through_causes_and_one_cause(client, tmp_path):
    run, _ = make_run(tmp_path, extra_groups=5)
    client.request("initialize", {"protocolVersion": "2025-06-18"})
    result = client.call("list_findings", run_dir=str(run), limit=3)
    assert result["isError"] is False
    page = json.loads(result["content"][0]["text"])
    assert len(page["groups"]) == 3 and page["total"] == 8 and page["more"] == 5 and page["page"] == 1
    last = json.loads(client.call("list_findings", run_dir=str(run), limit=3, page=3)["content"][0]["text"])
    assert len(last["groups"]) == 2 and last["more"] == 0
    only = json.loads(client.call("list_findings", run_dir=str(run), severity="P1")["content"][0]["text"])
    assert [g["severity"] for g in only["groups"]] == ["P1"]
    cause = json.loads(client.call("list_findings", run_dir=str(run), group=only["groups"][0]["id"], limit=1)["content"][0]["text"])
    assert cause["total"] == 2 and len(cause["issues"]) == 1 and cause["more"] == 1 and "ui-audit verify" in cause["recheck"]
    missing = client.call("list_findings", run_dir=str(tmp_path / "nothing"))
    assert missing["isError"] is True and "no report.json" in missing["content"][0]["text"]
    assert client.call("list_findings")["isError"] is True  # run_dir is required


def test_get_screenshot_returns_the_png(client, tmp_path):
    run, data = make_run(tmp_path)
    overflow = next(i for i in data["issues"] if i["check"] == "horizontal-overflow")
    result = client.call("get_screenshot", run_dir=str(run), id=overflow["group"])
    assert result["isError"] is False
    text, image = result["content"]
    assert image["type"] == "image" and image["mimeType"] == "image/png"
    assert base64.b64decode(image["data"]) == tiny_png()
    assert "390px" in text["text"] and "annotated" in text["text"]
    near = client.call("get_screenshot", run_dir=str(run), id=overflow["id"], width=900)
    assert "800px" in near["content"][0]["text"]
    runtime = next(i for i in data["issues"] if i["check"] == "console-error")
    assert client.call("get_screenshot", run_dir=str(run), id=runtime["id"])["isError"] is True


def test_accept_and_verify(client, tmp_path):
    run, data = make_run(tmp_path)
    clipped = next(i for i in data["issues"] if i["check"] == "clipped-content")
    result = json.loads(client.call("accept", run_dir=str(run), id=clipped["id"], reason="decorative")["content"][0]["text"])
    assert result["accepted"] == 1 and (tmp_path / "ui-audit.accepted.json").is_file()
    verified = json.loads(client.call("verify", baseline=str(run), current=str(run))["content"][0]["text"])
    assert len(verified["persistent"]) == 3 and verified["fixed"] == [] and verified["introduced"] == []


@pytest.mark.e2e
def test_audit_tool_runs_an_audit_and_returns_the_summary(client, demo_site, tmp_path):
    url, site = demo_site
    result = client.call("audit", base_url=url, routes=["/"], widths=[390], project_root=str(site), output=str(tmp_path / "out"))
    assert result["isError"] is False, result
    data = json.loads(result["content"][0]["text"])
    assert data["report"] == str(tmp_path / "out" / "report.json") and data["routes"]["audited"] == 1
    assert {g["check"] for g in data["groups"]} >= {"small-target", "unnamed-control"}
    assert "exit_code" in data
