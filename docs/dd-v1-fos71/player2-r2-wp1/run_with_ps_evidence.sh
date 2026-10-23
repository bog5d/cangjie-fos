#!/usr/bin/env bash
# 测试读数三件套采集器（**仓内落盘版，跨轮可复现**）。
#
# 职责：
#   ① 记录 UTC 起止时刻；
#   ② 采样 ps ⇒ 证明**同一 checkout 内 pytest 主进程恒为 1**（并发跑两套全量会互相踩
#      真实 pitch_jobs.sqlite，仓内已有该隔离缺口）；
#   ③ **退出码取自 pytest 自身**（不接管道、不塞进命令替换）⇒ 免得下游 grep/awk 的退出码
#      把失败掩盖成成功；
#   ④ 同时落 junit XML ⇒ 与 --collect-only 求和、退出码凑成三件套。
#
# 用法：
#   PYTHON_BIN=<解释器> JUNIT_OUT=<xml> LOG_OUT=<log> PS_LOG=<ps采样> \
#     bash docs/dd-v1-fos71/player2-r2-wp1/run_with_ps_evidence.sh <pytest 参数> [更多参数]
set -u

PYTHON_BIN="${PYTHON_BIN:-python3}"
JUNIT_OUT="${JUNIT_OUT:-/tmp/pytest-junit.xml}"
LOG_OUT="${LOG_OUT:-/tmp/pytest-run.log}"
PS_LOG="${PS_LOG:-/tmp/pytest-ps.log}"
PS_SNAP="${PS_SNAP:-/tmp/pytest-ps.snap}"

START="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
: > "$PS_LOG"

"$PYTHON_BIN" -m pytest "$@" --junitxml="$JUNIT_OUT" > "$LOG_OUT" 2>&1 &
PID=$!

while kill -0 "$PID" 2>/dev/null; do
  ps -eo pid,args > "$PS_SNAP"
  N=$(awk '/-m pytest/ && !/awk/ {c++} END {print c+0}' "$PS_SNAP")
  printf '%s pytest_main_procs=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$N" >> "$PS_LOG"
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
  printf 'PS_SAMPLES=%s\n' "$(wc -l < "$PS_LOG" | tr -d ' ')"
  printf 'PS_MAX_PROCS=%s\n' "$(awk -F= '{if ($2+0 > m) m=$2+0} END {print m+0}' "$PS_LOG")"
} >> "$LOG_OUT"

exit "$RC"
