"""文字稿脱敏（身份/商密/涉军）测试。全确定性，无 LLM。"""
from __future__ import annotations

from cangjie_fos.services import desensitize_service as svc


# ── 身份类正则 ────────────────────────────────────────────────────────────────

def test_identity_regex_masks_structured():
    text = "联系张总手机13800138000，邮箱boss@zeta.com，身份证110101199003074512。"
    r = svc.desensitize(text, tenant_id="t1")
    m = r["masked_text"]
    assert "13800138000" not in m and "[手机]" in m
    assert "boss@zeta.com" not in m and "[邮箱]" in m
    assert "110101199003074512" not in m and "[身份证]" in m


def test_business_numbers_not_masked():
    """红线：金额/产品数/技术口径等业务数字绝不脱（否则 BP口径比对会失效）。"""
    text = "创业启动资金800万元，产品240余款，毛利率60%。"
    r = svc.desensitize(text, tenant_id="t1")
    assert "800万" in r["masked_text"]
    assert "240" in r["masked_text"]
    assert "60%" in r["masked_text"]


# ── 词典：人名 / 商密 / 涉军 ──────────────────────────────────────────────────

def test_name_dictionary_masking():
    svc.add_term("t1", "identity", "波总", "[高管A]")
    r = svc.desensitize("今天波总说到估值问题。", tenant_id="t1")
    assert "波总" not in r["masked_text"]
    assert "[高管A]" in r["masked_text"]


def test_secret_dictionary_masking():
    svc.add_term("t1", "secret", "ZenixOS", "[商密]")
    r = svc.desensitize("我们的核心是 ZenixOS 操作系统。", tenant_id="t1")
    assert "ZenixOS" not in r["masked_text"]
    assert "[商密]" in r["masked_text"]


def test_builtin_military_masking():
    r = svc.desensitize("该项目有军方背景，涉及部队采购。", tenant_id="t1")
    assert "军方" not in r["masked_text"]
    assert "部队" not in r["masked_text"]
    assert "[涉军]" in r["masked_text"]


def test_categories_can_be_limited():
    """只选 identity 时，涉军内置词不脱。"""
    svc.add_term("t1", "secret", "绝密项目X", "[商密]")
    r = svc.desensitize("军方 绝密项目X", tenant_id="t1", categories=("identity",))
    assert "军方" in r["masked_text"]      # 未选 military
    assert "绝密项目X" in r["masked_text"]  # 未选 secret


def test_hits_reported_for_review():
    svc.add_term("t1", "identity", "李四", "[人名]")
    r = svc.desensitize("李四的手机是13900139000", tenant_id="t1")
    cats = {h["category"] for h in r["hits"]}
    assert "identity" in cats
    assert r["count"] >= 2


def test_longer_terms_first():
    """长词优先：'关联公司' 不应被 '公司' 抢先切断。"""
    svc.add_term("t1", "secret", "泽天智航", "[公司A]")
    r = svc.desensitize("泽天智航的BP", tenant_id="t1")
    assert "[公司A]" in r["masked_text"]
    assert "泽天" not in r["masked_text"]


def test_term_crud():
    tid = svc.add_term("t2", "military", "某型号", "[涉军]")
    assert any(t["id"] == tid for t in svc.list_terms("t2"))
    svc.delete_term(tid)
    assert not any(t["id"] == tid for t in svc.list_terms("t2"))


# ── API ───────────────────────────────────────────────────────────────────────

def test_api_preview_and_terms():
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    with TestClient(create_app()) as c:
        # 加一条商密词
        r1 = c.post("/api/v1/desensitize/terms",
                    json={"tenant_id": "t3", "category": "secret", "term": "代号Falcon", "replacement": "[商密]"})
        assert r1.status_code == 200
        # 预览脱敏
        r2 = c.post("/api/v1/desensitize/preview",
                    json={"text": "代号Falcon 手机13711112222，金额500万", "tenant_id": "t3"})
        assert r2.status_code == 200
        body = r2.json()
        assert "代号Falcon" not in body["masked_text"]
        assert "13711112222" not in body["masked_text"]
        assert "500万" in body["masked_text"]  # 业务数字保留


def test_api_unknown_category_400():
    from fastapi.testclient import TestClient
    from cangjie_fos.main import create_app

    with TestClient(create_app()) as c:
        r = c.post("/api/v1/desensitize/terms",
                   json={"tenant_id": "t3", "category": "bogus", "term": "x"})
        assert r.status_code == 400
