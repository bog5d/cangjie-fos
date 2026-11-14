"""DD-V1 **凭证活性探针** 的回归测试（BLOCKED-7：凭证腐烂没有主动告警）。

★ 全程**不联网**：用本机 ``http.server`` 假扮供应商端点，逐个状态码造响应。
★ 判据钉的是**性质**：
  ① 「配了但坏了」必须与「**没配**」分得开（后者不阻塞规则基线考试）；
  ② **服务端错误 / 网络故障**不得被误判成「凭证坏了」（那是另一种病）；
  ③ **任何路径都不得输出密钥原文**（★ 这是本工具存在的底线）。
"""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools"))
import dd_v1_credential_probe as probe  # noqa: E402

FAKE_SECRET = "sk-FAKE-ONLY-THIS-IS-NOT-A-REAL-KEY-0123456789"


class _Handler(BaseHTTPRequestHandler):
    status_code = 200
    seen_auth: list[str] = []

    def do_GET(self):  # noqa: N802
        _Handler.seen_auth.append(self.headers.get("Authorization", ""))
        body = b'{"data":[]}'
        self.send_response(_Handler.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: D401, ANN002
        """★ 不打访问日志（避免把请求头写进日志）。"""


@pytest.fixture()
def server():
    _Handler.seen_auth = []
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _probe(server, status: int, monkeypatch, secret: str | None = FAKE_SECRET):
    _Handler.status_code = status
    if secret is None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    else:
        monkeypatch.setenv("DEEPSEEK_API_KEY", secret)
    return probe.probe_env_source(
        "DEEPSEEK_API_KEY",
        probe.SOURCES["DEEPSEEK_API_KEY"],
        base_url_override=f"http://127.0.0.1:{server.server_address[1]}",
        timeout=5.0,
    )


# ── 状态码判定 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("status,expected", [
    (200, probe.STATUS_OK),
    (401, probe.STATUS_EXPIRED),
    (402, probe.STATUS_QUOTA),
    (403, probe.STATUS_INVALID),
    (429, probe.STATUS_QUOTA),
])
def test_status_mapping(server, monkeypatch, status, expected):
    res = _probe(server, status, monkeypatch)
    assert res["status"] == expected, res


def test_server_error_is_unknown_not_expired(server, monkeypatch):
    """★ 5xx **不得**被判定成「凭证坏了」—— 那是另一种病，误判会误导人去换 key。"""
    res = _probe(server, 500, monkeypatch)
    assert res["status"] == probe.STATUS_UNKNOWN
    assert res["status"] not in probe.BAD_STATUSES


def test_connection_failure_is_unknown(server, monkeypatch):
    """连不上 ⇒ UNKNOWN（不是 EXPIRED）。"""
    _Handler.status_code = 200
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_SECRET)
    res = probe.probe_env_source(
        "DEEPSEEK_API_KEY",
        probe.SOURCES["DEEPSEEK_API_KEY"],
        base_url_override="http://127.0.0.1:1",   # 必然连不上
        timeout=2.0,
    )
    assert res["status"] == probe.STATUS_UNKNOWN


# ── 「没配」与「配了但坏了」必须分开 ────────────────────────────────────

def test_not_configured_is_distinct_from_expired(server, monkeypatch):
    res = _probe(server, 200, monkeypatch, secret=None)
    assert res["status"] == probe.STATUS_NOT_CONFIGURED
    assert res["status"] not in probe.BAD_STATUSES, "「没配」不该被当成「坏了」"
    assert res.get("fingerprint") is None


def test_verdict_problem_only_when_something_is_bad(server, monkeypatch):
    """只有「配了且坏了」⇒ PROBLEM；「没配」⇒ 仍然 OK（规则基线能跑）。"""
    _Handler.status_code = 200
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    rep = probe.probe_all(base_url_override=f"http://127.0.0.1:{server.server_address[1]}")
    assert rep["verdict"] == "OK", rep
    assert rep["counts"]["not_configured"] >= 1

    _Handler.status_code = 401
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_SECRET)
    rep2 = probe.probe_all(base_url_override=f"http://127.0.0.1:{server.server_address[1]}")
    assert rep2["verdict"] == "PROBLEM", rep2
    assert rep2["bad_sources"], rep2


# ── ★ 安全底线：凭证原文绝不出现在任何输出里 ────────────────────────────

def test_secret_never_appears_in_report(server, monkeypatch):
    res = _probe(server, 401, monkeypatch)
    blob = json.dumps(res, ensure_ascii=False)
    assert FAKE_SECRET not in blob, "★ 报告里出现了密钥原文"
    assert "sk-FAKE" not in blob, "★ 报告里出现了密钥前缀"
    # 只允许出现指纹
    assert res["fingerprint"] and FAKE_SECRET not in res["fingerprint"]
    assert len(res["fingerprint"]) == 12


def test_fingerprint_is_stable_and_distinguishes(server, monkeypatch):
    a = _probe(server, 200, monkeypatch, secret=FAKE_SECRET)
    b = _probe(server, 200, monkeypatch, secret=FAKE_SECRET)
    c = _probe(server, 200, monkeypatch, secret=FAKE_SECRET + "X")
    assert a["fingerprint"] == b["fingerprint"], "同一把 key 的指纹应当稳定"
    assert a["fingerprint"] != c["fingerprint"], "换了一把 key，指纹应当不同"


def test_probe_sends_authorization_header(server, monkeypatch):
    """探针**确实**带上了凭证去鉴权（否则「OK」是假的）。"""
    _probe(server, 200, monkeypatch)
    assert _Handler.seen_auth, "探针没有发出任何请求"
    assert _Handler.seen_auth[0] == "Bearer " + FAKE_SECRET


def test_cli_sources_never_touch_credentials():
    """CLI 型考生：只报「装没装」，**不跑 CLI、不读它的凭证**。"""
    rows = probe.probe_cli_sources()
    assert rows
    for r in rows:
        assert r["kind"] == "cli"
        assert r["fingerprint"] is None
        assert r["status"] in (probe.STATUS_OK, probe.STATUS_CLI_MISSING)
