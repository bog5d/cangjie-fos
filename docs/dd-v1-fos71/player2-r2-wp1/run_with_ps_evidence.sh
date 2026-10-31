#!/usr/bin/env bash
# 测试读数三件套采集器（**仓内落盘版，跨轮可复现**）。
#
# 职责：
#   ① 记录 UTC 起止时刻；
#   ② 采样 ps ⇒ 证明**同一 checkout 内 pytest 主进程恒为 1**（并发跑两套全量会互相踩
#      真实 pitch_jobs.sqlite，仓内已有该隔离缺口）。
#      ★ 计数**按进程的工作目录**（/proc/<pid>/cwd）落在本 checkout ⇒ 其他 checkout 上
#        并行跑的 pytest（例如独立复核席）**不计入**本 checkout 的读数，但仍逐条登记
#        在明细里（不隐藏、不冒充）。
#   ③ **退出码取自 pytest 自身**（不接管道、不塞进命令替换）⇒ 免得下游 grep/awk 的退出码
#      把失败掩盖成成功；
#   ④ 同时落 junit XML ⇒ 与 --collect-only 求和、退出码凑成三件套。
#
# 用法：
#   PYTHON_BIN=<解释器> JUNIT_OUT=<xml> LOG_OUT=<log> PS_LOG=<ps采样> PS_CWD=<checkout绝对路径> \
#     bash docs/dd-v1-fos71/player2-r2-wp1/run_with_ps_evidence.sh <pytest 参数> [更多参数]
set -u

PYTHON_BIN="${PYTHON_BIN:-python3}"
JUNIT_OUT="${JUNIT_OUT:-/tmp/pytest-junit.xml}"
LOG_OUT="${LOG_OUT:-/tmp/pytest-run.log}"
PS_LOG="${PS_LOG:-/tmp/pytest-ps.log}"
PS_SNAP="${PS_SNAP:-/tmp/pytest-ps.snap}"
# ★ 本 checkout 的**解析后**绝对路径（沙箱里 /workspace 是挂载点的软链 ⇒ 必须 readlink -f）
PS_CWD="$(readlink -f "${PS_CWD:-$(pwd)}")"

START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MAX_N=0
MAX_GLOBAL=0
: > "$PS_LOG"

"$PYTHON_BIN" -m pytest "$@" --junitxml="$JUNIT_OUT" > "$LOG_OUT" 2>&1 &
PID=$!

while kill -0 "$PID" 2>/dev/null; do
  ps -eo pid,args > "$PS_SNAP"
  N=0
  GLOBAL=0
  while read -r p rest; do
    case "$rest" in
      *"-m pytest"*)
        GLOBAL=$((GLOBAL + 1))
        CWD="$(readlink -f "/proc/$p/cwd" 2>/dev/null || true)"
        printf '%s pid=%s cwd=%s args=%s\n' \
          "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$p" "${CWD:-UNKNOWN}" "$rest" >> "$PS_LOG"
        if [ "$CWD" = "$PS_CWD" ]; then
          N=$((N + 1))
        fi
        ;;
    esac
  done < "$PS_SNAP"
  if [ "$N" -gt "$MAX_N" ]; then MAX_N="$N"; fi
  if [ "$GLOBAL" -gt "$MAX_GLOBAL" ]; then MAX_GLOBAL="$GLOBAL"; fi
  printf '%s pytest_main_procs_in_checkout=%s pytest_main_procs_global=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$N" "$GLOBAL" >> "$PS_LOG"
  sleep 2
done

wait "$PID"
RC=$?
END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

{
  printf 'REAL_EXIT=%s\n' "$RC"
  printf 'START_UTC=%s\n' "$START"
  printf 'END_UTC=%s\n' "$END"
  printf 'PYTEST_PID=%s\n' "$PID"
  printf 'JUNIT_OUT=%s\n' "$JUNIT_OUT"
  printf 'PS_LOG=%s\n' "$PS_LOG"
  printf 'PS_CWD=%s\n' "$PS_CWD"
  printf 'PS_SAMPLES=%s\n' "$(grep -c 'in_checkout=' "$PS_LOG" || true)"
  printf 'PS_MAX_PROCS=%s\n' "$MAX_N"
  printf 'PS_MAX_PROCS_GLOBAL=%s\n' "$MAX_GLOBAL"
} >> "$LOG_OUT"

exit "$RC"
