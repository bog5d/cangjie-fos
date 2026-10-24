"""共享服务器部署：账号配置语义。

锁定一个对"数据真实流转"至关重要的事实：
  同一 tenant_id 的多个账号 = 共享同一份数据。
若不同 tenant_id，则各自隔离——这正是部署手册要求"全团队同 tenant"的原因。
"""
from __future__ import annotations

from cangjie_fos.api.routes.auth import _load_accounts


def test_same_tenant_means_shared_workspace(monkeypatch):
    monkeypatch.setenv(
        "FOS_ACCOUNTS",
        "wangbo:pwA:team,tongshi1:pwB:team,tongshi2:pwC:team",
    )
    accts = _load_accounts()
    assert set(accts) == {"wangbo", "tongshi1", "tongshi2"}
    # 三个账号同 tenant → 共享一份数据
    assert {a["tenant_id"] for a in accts.values()} == {"team"}
    assert accts["wangbo"]["password"] == "pwA"


def test_different_tenant_isolated(monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "zt001:p1:zt,gk001:p2:gk")
    accts = _load_accounts()
    assert accts["zt001"]["tenant_id"] == "zt"
    assert accts["gk001"]["tenant_id"] == "gk"  # 不同 tenant = 互相看不见


def test_env_overrides_builtin_defaults(monkeypatch):
    monkeypatch.setenv("FOS_ACCOUNTS", "solo:secret:team")
    accts = _load_accounts()
    assert "zt001" not in accts  # 内置弱密码默认账号被覆盖掉
    assert accts["solo"]["tenant_id"] == "team"


def test_malformed_entries_skipped(monkeypatch):
    """格式不全的条目被跳过，不会导致整体崩溃。"""
    monkeypatch.setenv("FOS_ACCOUNTS", "good:pw:team,broken_no_colons,also:bad")
    accts = _load_accounts()
    assert "good" in accts
    assert len(accts) == 1
