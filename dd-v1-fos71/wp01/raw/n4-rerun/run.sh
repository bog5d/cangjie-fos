#!/bin/bash
# N4 rerun: each probe -> <name>.events / <name>.stderr / <name>.timing.json
cd "$(dirname "$0")"
t(){ python3 -c 'import time;print(f"{time.time():.3f}")'; }
run(){ name=$1; shift; s=$(t); "$@" </dev/null >"$name.events" 2>"$name.stderr"; rc=$?; e=$(t)
  python3 - "$name" "$s" "$e" "$rc" "$*" <<'PY'
import json,sys,datetime as d
n,s,e,rc,cmd=sys.argv[1:];s=float(s);e=float(e)
z=lambda x:d.datetime.fromtimestamp(x,d.timezone(d.timedelta(hours=8))).isoformat(timespec="seconds")
json.dump({"probe":n,"command":cmd,"exit_code":int(rc),"start":z(s),"end":z(e),"elapsed_s":round(e-s,1),"stdin":"/dev/null"},open(n+".timing.json","w"),ensure_ascii=False,indent=1)
PY
}
D=$(pwd)
run codex perl -e 'alarm 300; exec @ARGV' codex exec --ephemeral --skip-git-repo-check -C "$D" -s read-only --output-schema schema.json -o codex-out.json --json "$(cat prompt.txt)"
run pi perl -e 'alarm 180; exec @ARGV' pi -p --provider minimax-cn --no-session --no-tools --mode json "$(cat mm-prompt.txt)"
run hermes perl -e 'alarm 180; exec @ARGV' hermes chat -Q --provider minimax-cn -m MiniMax-M3 --ignore-rules --max-turns 1 -q "$(cat mm-prompt.txt)"
