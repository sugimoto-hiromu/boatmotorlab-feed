#!/usr/bin/env python3
"""日次更新: 直近N日の競走成績・番組表を取得(取得済みは再取得しない)→ real_data.json と manifest.json を出力する。
使い方: daily_update.py WORKDIR OUTDIR [日数=183]
cron(GitHub Actions)から毎日1回。WORKDIRはキャッシュして使い回す。"""
import os, sys, glob, subprocess
from datetime import datetime, timedelta, timezone

here = os.path.dirname(os.path.abspath(__file__))
work, out = sys.argv[1], sys.argv[2]
days = int(sys.argv[3]) if len(sys.argv) > 3 else 183
jst = datetime.now(timezone(timedelta(hours=9))).date()
end = jst + timedelta(days=1)          # 翌日の番組表まで
start = jst - timedelta(days=days)
os.makedirs(os.path.join(work, "txt"), exist_ok=True); os.makedirs(out, exist_ok=True)
# 直近は公開前に404になっている可能性があるので、欠番マークを消して取り直す
for m in glob.glob(os.path.join(work, "txt", "*.missing")):
    name = os.path.basename(m)
    d = datetime.strptime(name[1:7], "%y%m%d").date()
    if d >= jst - timedelta(days=3):
        os.remove(m)
subprocess.run([sys.executable, "-I", os.path.join(here, "fetch_mbrace.py"), start.isoformat(), end.isoformat(), work], check=True)
subprocess.run([sys.executable, "-I", os.path.join(here, "build_real_data.py"), "build", work,
                os.path.join(out, "real_data.json"), start.isoformat()], check=True)
