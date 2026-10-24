#!/usr/bin/env python3
"""A0 call-trace 观察器：把官方入口 CLI 在本进程内跑一遍，用 sys.setprofile 记录
所有 cangjie_fos 模块函数的真实调用（module + func + file:def_line + caller + 深度）。

性质：纯观察。不打补丁、不包装、不修改任何 cangjie_fos / tools 代码；
只挂 C 级 profile 回调，按 co_filename 过滤写入 JSONL。与 CLI 子进程跑法语义一致
（同一 main()、同一 argv、同一 env），差别仅在旁路记录调用事件。

用法：
  a0-trace-runner.py --trace-out <jsonl路径> [--append] -- <入口脚本> [入口参数...]

分段语义（attempt-3 修复，独立 Reviewer M1）：
  - 默认每次调用**覆盖**写 trace（mode="w"）：一个文件 = 一次运行 = 一个分段；
    meta 事件携带 run_id（UTC 时间戳+pid）与完整 argv，done 事件携带真实退出码。
  - 需要多轮追加时显式传 --append；此时每段仍以 meta 开头、done 结尾，
    靠 run_id 区分段落（禁止把不同 run 混在无标记的同一文件里）。

退出码语义（attempt-3 修复，独立 Reviewer M1）：
  - SystemExit.code：int 原样；None→0；其他（字符串等）→1（与 sys.exit 语义一致）；
  - **非 SystemExit 异常（含未捕获崩溃）一律记录真实失败**：done.exit_code=1，
    done.error 携带异常类型与消息，且 runner 进程自身以该真实码退出——
    绝不允许异常路径默认 0 把崩溃记成成功。
"""
import json
import os
import runpy
import sys
import time
from pathlib import Path

REPO = Path("/Users/mac/cangjie-fos-wt-a0")
SRC = REPO / "backend" / "src"
_SCOPE = str(SRC / "cangjie_fos")


def main() -> int:
    args = sys.argv[1:]
    trace_out = None
    append = False
    while args and args[0].startswith("--trace-out") or (args and args[0] == "--append"):
        if args[0] == "--append":
            append = True
            args = args[1:]
        elif args[0] == "--trace-out":
            trace_out = Path(args[1])
            args = args[2:]
        else:  # --trace-out=<path>
            trace_out = Path(args[0].split("=", 1)[1])
            args = args[1:]
    if args and args[0] == "--":
        args = args[1:]
    if not args or trace_out is None:
        print("usage: a0-trace-runner.py --trace-out <jsonl> [--append] -- <script> [args...]",
              file=sys.stderr)
        return 2
    script, script_args = args[0], args[1:]
    sys.argv = [script] + script_args
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    mode = "a" if append else "w"
    run_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"-p{os.getpid()}"
    fh = trace_out.open(mode, encoding="utf-8", buffering=1)

    def rel(p: str) -> str:
        try:
            return os.path.relpath(p, REPO)
        except ValueError:
            return p

    def emit(rec: dict) -> None:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    emit({"seq": 0, "event": "meta", "run_id": run_id,
          "trace_mode": "append-multi" if append else "single-run",
          "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
          "script": rel(os.path.abspath(script)), "args": script_args,
          "head_sha": os.popen("git -C %s rev-parse HEAD" % REPO).read().strip()})

    def prof(frame, event, arg):
        code = frame.f_code
        fn = code.co_filename
        if not (event == "call" and fn.startswith(_SCOPE)):
            return
        parent = frame.f_back
        caller = None
        depth = 0
        w = parent
        while w is not None:
            if w.f_code.co_filename.startswith(_SCOPE):
                depth += 1
            if caller is None and w is parent:
                prel = rel(w.f_code.co_filename)
                caller = f"{prel}:{w.f_lineno}"
            w = w.f_back
        mrel = rel(fn)
        emit({"seq": None, "event": "call", "depth": depth,
              "module": mrel[: -len(".py")].replace("/", ".") if mrel.endswith(".py") else mrel,
              "func": code.co_name,
              "file_line": f"{mrel}:{code.co_firstlineno}",
              "caller": caller})

    rc = 0
    err = None
    sys.setprofile(prof)
    try:
        runpy.run_path(os.path.abspath(script), run_name="__main__")
    except SystemExit as e:
        rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        if isinstance(rc, bool):
            rc = int(rc)
    except BaseException as e:  # 未捕获崩溃：真实退出码必须是 1，不许默认 0
        rc = 1
        err = f"{type(e).__name__}: {e}"
    finally:
        sys.setprofile(None)
        done = {"seq": None, "event": "done", "run_id": run_id, "exit_code": rc}
        if err is not None:
            done["error"] = err
        emit(done)
        fh.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
