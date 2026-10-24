#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FOS #71 落盘器（GitHub Git Data API）——带「重入即中止」幂等闸。

定位：把一个本地文件以「单父快进、非 force」的方式落到远端分支的一个路径上。

本脚本针对两处已登记的自曝设计：

  自曝 A：收尾核验时用 import 读本脚本的常量，import 执行了模块顶层代码，
          于是落盘流程被完整重跑一遍（blob → tree → commit → PATCH）。
          处置：模块顶层 0 副作用（全部写动作都在 main() 内），并提供 constants
          子命令供子进程读常量（另一条受控读法是 runpy 读文件）。
  自曝 4：回读命中了本地磁盘上的 GET 响应缓存，读到落盘前的旧 tip。
          处置：本脚本不落任何本地读数缓存，每次读都是一次新的 HTTP GET。

闸（fail-closed；任一红 ⇒ 0 远端写）：

  Gate A  重入闸：落盘前独立重读目标 ref tip，取该 tip 的 commit message；
                  若其中含本笔落盘的 LAND-ID ⇒ 判「已落过」⇒ 零写动作退出。
  Gate B  基座闸：落盘前再验一次 ref；tip 与基座不一致 ⇒ 零写动作退出，
                  调用方须以新基座重跑全流程（禁重推旧载荷）。
  Gate C  补丁前复验：PATCH 之前再读一次 ref；tip 已等于本席目标 commit ⇒
                  不 PATCH（0 新对象、0 ref 写）；tip 已漂 ⇒ 零 ref 写退出。
  禁形闸  可选调用仓内 shape_probe.py（硬闸、退出码驱动、作用域＝本轮增量字节）。

退出码：

  0   落盘成功
  20  已落过、中止（零写动作）
  21  基座漂移（零写动作）；调用方须以新基座重跑全流程
  22  非快进（422）；不重试同一份载荷，须以新基座重跑全流程
  23  前置闸失败（禁形闸等），零写动作
  2   用法错误

读本脚本的常量：优先用子命令 `constants`（无副作用）；禁在本进程里 import 后
再调用其落地路径（本脚本已把顶层做成 0 副作用，但子进程读法更稳）。
"""

from __future__ import annotations

import argparse
import ast
import base64
import datetime
import hashlib
import json
import os
import subprocess
import sys
import tempfile

EXIT_LANDED = 0
EXIT_ALREADY_LANDED = 20
EXIT_BASE_DRIFT = 21
EXIT_NOT_FAST_FORWARD = 22
EXIT_GATE = 23
EXIT_USAGE = 2

DEFAULTS = {
    "repo": "bog5d/cangjie-fos",
    "branch": "feat/71-player2-p0-fix-20261023",
    "author_name": "Player2 Executor",
    "author_email": "player2-executor@local",
    "ca_bundle": "/etc/ssl/certs/agent-identity/sandbox-gateway-ca.crt",
    "api_root": "https://api.github.com",
}

AUTO_SLOT = "@LANDID@"
LAND_ID_PREFIX = "F71-"


# ── 基础工具 ────────────────────────────────────────────────────────────────

def now_iso():
    """现读 UTC 时刻（禁手写时刻标签）。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def git_object_id(kind, payload):
    """git 对象 id ＝ sha1(类型串 + 字节长度 + NUL + 对象内容)。"""
    head = ("%s %d\0" % (kind, len(payload))).encode("utf-8")
    return hashlib.sha1(head + payload).hexdigest()


def compute_landing_id(path, content):
    """LAND-ID ＝ 路径 ＋ 内容 sha256 的摘要（与 message 无关 ⇒ 同内容重跑必同 id）。"""
    h = hashlib.sha256()
    h.update(path.encode("utf-8"))
    h.update(b"\n")
    h.update(sha256_hex(content).encode("ascii"))
    raw = base64.b32encode(h.digest()).decode("ascii").rstrip("=")
    return LAND_ID_PREFIX + raw[:16]


def parse_iso_to_git(iso):
    """ISO 8601（UTC）→ (epoch 秒, 时区串)。"""
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    epoch = int(dt.timestamp())
    off = dt.utcoffset() or datetime.timedelta(0)
    total = int(off.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return epoch, "%s%02d%02d" % (sign, total // 3600, (total % 3600) // 60)


# ── HTTP 层：凭证走 stdin 的 curl 配置，不进 argv、不落盘、不缓存 ──────────

class Api:
    def __init__(self, repo, ca, auth, api_root):
        self.repo = repo
        self.ca = ca
        self.auth = auth
        self.api_root = api_root
        self.reads = 0
        self.writes = 0
        self.trace = []

    def _curl_config(self):
        lines = [
            'header = "Authorization: Bearer %s"' % self.auth,
            'header = "Accept: application/vnd.github+json"',
            'cacert = "%s"' % self.ca,
        ]
        return "\n".join(lines) + "\n"

    def request(self, method, path, payload=None):
        url = "%s/repos/%s%s" % (self.api_root, self.repo, path)
        cmd = ["curl", "-sS", "-o", "-", "-w", "\n%{http_code}", "-K", "-", "-X", method, url]
        if payload is not None:
            cmd += ["-H", "Content-Type: application/json", "--data-binary", payload]
        proc = subprocess.run(
            cmd, input=self._curl_config(), capture_output=True, text=True
        )
        out = proc.stdout
        body, _, code = out.rpartition("\n")
        try:
            code = int(code.strip())
        except ValueError:
            code = 0
        if method == "GET":
            self.reads += 1
        else:
            self.writes += 1
        self.trace.append({"method": method, "path": path, "status": code})
        try:
            obj = json.loads(body) if body.strip() else {}
        except ValueError:
            obj = {"_raw": body}
        if code == 0:
            obj = {"_curl_rc": proc.returncode, "_stderr": proc.stderr[:400], "_raw": body[:400]}
        return code, obj

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, obj):
        return self.request("POST", path, json.dumps(obj))

    def patch(self, path, obj):
        return self.request("PATCH", path, json.dumps(obj))

    def head_tip(self, branch):
        code, obj = self.get("/git/ref/heads/" + branch)
        if code != 200:
            raise RuntimeError("读 ref 失败 HTTP %d: %s" % (code, json.dumps(obj)[:200]))
        return obj["object"]["sha"]

    def commit_message(self, sha):
        code, obj = self.get("/git/commits/" + sha)
        if code != 200:
            raise RuntimeError("读 commit 失败 HTTP %d" % code)
        return obj.get("message", "")


# ── 前置闸 ──────────────────────────────────────────────────────────────────

def run_shape_probe(probe_path, targets):
    """仓内禁形硬闸：子进程调用、退出码驱动、fail-closed。"""
    cmd = [sys.executable, probe_path] + list(targets)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def assert_top_level_inert(module_path):
    """静态证：模块顶层没有可执行副作用（AST 口径）。"""
    with open(module_path, "rb") as fh:
        tree = ast.parse(fh.read().decode("utf-8"), filename=module_path)
    allowed = (
        ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef,
        ast.ClassDef, ast.Assign, ast.AnnAssign, ast.If, ast.Expr,
    )
    offenders = []
    for node in tree.body:
        if not isinstance(node, allowed):
            offenders.append(type(node).__name__)
        elif isinstance(node, ast.Expr):
            # 顶层只允许模块 docstring（常量字符串）
            if not isinstance(node.value, ast.Constant):
                offenders.append("Expr(非字面量)")
        elif isinstance(node, ast.If):
            # 顶层 if 只允许 __name__ == "__main__" 形态
            test = node.test
            ok = (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "__name__"
            )
            if not ok:
                offenders.append("If(非 __name__ 守卫)")
    return offenders


# ── 落地流程 ────────────────────────────────────────────────────────────────

def land(args, api=None):
    own_api = api is None
    if own_api:
        api = Api(args.repo, args.ca, args.token, args.api_root)
    out = {"reads": 0, "writes": 0}

    with open(args.file, "rb") as fh:
        content = fh.read()
    with open(args.message_file, "rb") as fh:
        message_raw = fh.read().decode("utf-8")
    if AUTO_SLOT not in message_raw:
        raise RuntimeError("message 文件缺自动槽 %s（ LAND-ID 无法落位）" % AUTO_SLOT)

    landing_id = compute_landing_id(args.path, content)
    message = message_raw.replace(AUTO_SLOT, landing_id)
    if AUTO_SLOT in message:
        raise RuntimeError("自动槽替换后仍有残留")

    # STEP1 基座现读
    base = api.head_tip(args.branch)
    code, base_commit = api.get("/git/commits/" + base)
    if code != 200:
        raise RuntimeError("读基座 commit 失败 HTTP %d" % code)
    base_tree = base_commit["tree"]["sha"]

    # Gate A：独立重读目标 ref tip（零写动作）
    tip_a = api.head_tip(args.branch)
    if tip_a != base:
        out["verdict"] = "BASE_DRIFT_ABORT"
        out["base"] = base
        out["tip"] = tip_a
        out["writes"] = api.writes
        out["reads"] = api.reads
        return EXIT_BASE_DRIFT, out
    msg_a = api.commit_message(tip_a)
    if landing_id in msg_a:
        out["verdict"] = "IDEMPOTENT_ABORT"
        out["land_id"] = landing_id
        out["tip"] = tip_a
        out["writes"] = api.writes
        out["reads"] = api.reads
        return EXIT_ALREADY_LANDED, out

    # 禁形闸（可选；作用域＝本轮增量字节 ＋ 最终 message）
    if args.shape_probe:
        tmpdir = tempfile.mkdtemp(prefix="fos71land-gate-")
        try:
            msg_path = os.path.join(tmpdir, "message.txt")
            with open(msg_path, "w", encoding="utf-8") as fh:
                fh.write(message)
            rc, stdout, stderr = run_shape_probe(args.shape_probe, [args.file, msg_path])
        finally:
            for name in os.listdir(tmpdir):
                os.unlink(os.path.join(tmpdir, name))
            os.rmdir(tmpdir)
        if rc != 0:
            out["verdict"] = "SHAPE_GATE_ABORT"
            out["probe_rc"] = rc
            out["probe_tail"] = stdout[-2000:]
            out["writes"] = api.writes
            out["reads"] = api.reads
            return EXIT_GATE, out

    if args.dry_run:
        out["verdict"] = "DRY_RUN_PLAN"
        out["land_id"] = landing_id
        out["base"] = base
        out["base_tree"] = base_tree
        out["writes"] = api.writes
        out["reads"] = api.reads
        return EXIT_LANDED, out

    # STEP2 blob → tree（内容寻址；同内容复用同一 sha）
    b64 = base64.b64encode(content).decode("ascii")
    code, blob = api.post("/git/blobs", {"content": b64, "encoding": "base64"})
    if code not in (200, 201):
        raise RuntimeError("建 blob 失败 HTTP %d: %s" % (code, json.dumps(blob)[:200]))
    blob_sha = blob["sha"]

    code, tree = api.post("/git/trees", {
        "base_tree": base_tree,
        "tree": [{"path": args.path, "mode": "100644", "type": "blob", "sha": blob_sha}],
    })
    if code not in (200, 201):
        raise RuntimeError("建 tree 失败 HTTP %d: %s" % (code, json.dumps(tree)[:200]))
    tree_sha = tree["sha"]

    # STEP3 commit（author/committer 的时刻在本轮现读）
    stamp = args.date if args.date else now_iso()
    epoch, tz = parse_iso_to_git(stamp)
    ident = "%s <%s> %d %s" % (args.author_name, args.author_email, epoch, tz)
    commit_payload = {
        "message": message,
        "tree": tree_sha,
        "parents": [base],
        "author": {"name": args.author_name, "email": args.author_email, "date": stamp},
        "committer": {"name": args.author_name, "email": args.author_email, "date": stamp},
    }
    code, commit = api.post("/git/commits", commit_payload)
    if code not in (200, 201):
        raise RuntimeError("建 commit 失败 HTTP %d: %s" % (code, json.dumps(commit)[:200]))
    commit_sha = commit["sha"]

    # 本地按内容寻址复算（自证；两种 message 尾换行形态都试，报告命中哪一形态）
    head_txt = "tree %s\nparent %s\nauthor %s\ncommitter %s\n\n" % (
        tree_sha, base, ident, ident)
    variants = {}
    for tag, tail in (("尾换行", "\n"), ("无尾换行", "")):
        body = head_txt.encode("utf-8") + (message + tail).encode("utf-8")
        variants[tag] = git_object_id("commit", body)
    recompute_hit = [k for k, v in variants.items() if v == commit_sha]

    # Gate C：PATCH 之前再验一次 ref
    tip_c = api.head_tip(args.branch)
    if tip_c == commit_sha:
        out["verdict"] = "IDEMPOTENT_ABORT"
        out["land_id"] = landing_id
        out["tip"] = tip_c
        out["commit"] = commit_sha
        out["blob"] = blob_sha
        out["tree"] = tree_sha
        out["writes"] = api.writes
        out["reads"] = api.reads
        return EXIT_ALREADY_LANDED, out
    if tip_c != base:
        out["verdict"] = "BASE_DRIFT_ABORT"
        out["base"] = base
        out["tip"] = tip_c
        out["writes"] = api.writes
        out["reads"] = api.reads
        return EXIT_BASE_DRIFT, out

    # STEP4 PATCH ref（单父快进、非 force）
    code, ref_resp = api.patch(
        "/git/refs/heads/" + args.branch, {"sha": commit_sha, "force": False})
    if code == 422:
        out["verdict"] = "NOT_FAST_FORWARD"
        out["tip"] = api.head_tip(args.branch)
        out["commit"] = commit_sha
        out["blob"] = blob_sha
        out["tree"] = tree_sha
        out["note"] = "禁重推旧 commit 对象：以新基座重跑全流程"
        out["writes"] = api.writes
        out["reads"] = api.reads
        return EXIT_NOT_FAST_FORWARD, out
    if code not in (200, 201):
        raise RuntimeError("PATCH ref 失败 HTTP %d: %s" % (code, json.dumps(ref_resp)[:200]))

    out["verdict"] = "LANDED"
    out["commit"] = commit_sha
    out["blob"] = blob_sha
    out["tree"] = tree_sha
    out["base"] = base
    out["base_tree"] = base_tree
    out["land_id"] = landing_id
    out["date"] = stamp
    out["recompute_variants"] = variants
    out["recompute_hit"] = recompute_hit
    out["writes"] = api.writes
    out["reads"] = api.reads
    return EXIT_LANDED, out


# ── 自测（只读；不发任何写请求，除被测的落盘器自身闸门） ──────────────────

def self_test(args, api):
    result = {"checks": []}

    def check(name, ok, detail=None):
        result["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    module_path = os.path.abspath(__file__)
    offenders = assert_top_level_inert(module_path)
    check("顶层无副作用(AST)", not offenders, offenders)

    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.dirname(module_path)
    env["CA_BUNDLE"] = "/nonexistent/ca-for-import-safety-check.pem"
    env["GITHUB_TOKEN"] = ""
    proc = subprocess.run(
        [sys.executable, "-c", "import %s" % os.path.splitext(os.path.basename(module_path))[0]],
        env=env, capture_output=True, text=True, cwd=os.path.dirname(module_path))
    check("import 无副作用(rc=0 且无输出)", proc.returncode == 0 and proc.stdout.strip() == "",
          {"rc": proc.returncode, "stdout": proc.stdout[:200], "stderr": proc.stderr[:200]})

    tip_before = api.head_tip(args.branch)

    # 阳性对照：同内容重跑 ⇒ 重入闸命中、零写动作
    rc, out = land(args, api=api)
    check("阳性对照：同内容重跑被重入闸拦下",
          rc == EXIT_ALREADY_LANDED and out.get("verdict") == "IDEMPOTENT_ABORT"
          and out.get("writes") == 0,
          {"rc": rc, "verdict": out.get("verdict"), "writes": out.get("writes")})

    # 阴性对照：内容不同的载荷 ⇒ 重入闸不得命中（只干跑，0 写）
    tmpdir = tempfile.mkdtemp(prefix="fos71land-selftest-")
    try:
        alt_file = os.path.join(tmpdir, "alt.bin")
        with open(args.file, "rb") as fh:
            base_bytes = fh.read()
        with open(alt_file, "wb") as fh:
            fh.write(base_bytes + "\n# 阴性对照用的不同载荷\n".encode("utf-8"))
        alt_args = argparse.Namespace(**vars(args))
        alt_args.file = alt_file
        alt_args.dry_run = True
        rc2, out2 = land(alt_args, api=api)
        check("阴性对照：不同载荷不被重入闸拦下",
              rc2 == EXIT_LANDED and out2.get("verdict") == "DRY_RUN_PLAN"
              and out2.get("writes") == 0,
              {"rc": rc2, "verdict": out2.get("verdict"), "writes": out2.get("writes")})
    finally:
        for name in os.listdir(tmpdir):
            os.unlink(os.path.join(tmpdir, name))
        os.rmdir(tmpdir)

    tip_after = api.head_tip(args.branch)
    check("自测全程远端 tip 未变", tip_before == tip_after,
          {"before": tip_before, "after": tip_after})
    result["tip_before"] = tip_before
    result["tip_after"] = tip_after
    result["reads"] = api.reads
    result["writes"] = api.writes
    result["passed"] = all(c["ok"] for c in result["checks"])
    return result


# ── CLI ─────────────────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(description="FOS #71 落盘器（带重入即中止幂等闸）")
    p.add_argument("--repo", default=DEFAULTS["repo"])
    p.add_argument("--branch", default=DEFAULTS["branch"])
    p.add_argument("--ca", default=DEFAULTS["ca_bundle"])
    p.add_argument("--api-root", default=DEFAULTS["api_root"])
    p.add_argument("--author-name", default=DEFAULTS["author_name"])
    p.add_argument("--author-email", default=DEFAULTS["author_email"])
    p.add_argument("--date", default="", help="ISO8601 UTC；不给则本轮现读")
    p.add_argument("--shape-probe", default="", help="仓内 shape_probe.py 路径（禁形硬闸）")
    sub = p.add_subparsers(dest="mode", required=True)

    land_p = sub.add_parser("land", help="落盘一个文件到分支")
    land_p.add_argument("--path", required=True)
    land_p.add_argument("--file", required=True)
    land_p.add_argument("--message-file", required=True)
    land_p.add_argument("--dry-run", action="store_true")

    sub.add_parser("constants", help="打印本脚本常量（无副作用）")

    st_p = sub.add_parser("self-test", help="幂等闸自测（只读）")
    st_p.add_argument("--path", required=True)
    st_p.add_argument("--file", required=True)
    st_p.add_argument("--message-file", required=True)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    auth = os.environ.get("GITHUB_TOKEN", "")
    if args.mode == "constants":
        print(json.dumps(DEFAULTS, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if not auth:
        sys.stderr.write("缺 GITHUB_TOKEN 环境变量\n")
        return EXIT_USAGE
    api = Api(args.repo, args.ca, auth, args.api_root)
    if args.mode == "land":
        rc, out = land(args, api=api)
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
        return rc
    if args.mode == "self-test":
        res = self_test(args, api)
        print(json.dumps(res, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if res["passed"] else 1
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
