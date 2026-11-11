#!/usr/bin/env python3
"""mbrace 日次ファイル(競走成績K・番組表B)を取得して展開する。再開可能。
使い方: fetch_mbrace.py START END WORKDIR   (日付は YYYY-MM-DD)
- WORKDIR/lzh/ に取得、WORKDIR/txt/ に展開(Shift_JISのまま)。リポジトリには保存しない。
- 負荷配慮: 1リクエスト/秒、失敗時は最大3回再試行、404は欠番として記録。
"""
import sys, os, time, subprocess
from datetime import date, timedelta

UA = "BoatMotorLab-research/1.0 (personal analysis; contact via App Store page)"

def fetch(kind, d, work):
    yymmdd = d.strftime("%y%m%d")
    name = f"{kind.lower()}{yymmdd}"
    lzh = os.path.join(work, "lzh", f"{name}.lzh")
    txt = os.path.join(work, "txt", f"{kind.upper()}{yymmdd}.TXT")
    if os.path.exists(txt):
        return "cached"
    url = f"https://www1.mbrace.or.jp/od2/{kind.upper()}/{d.strftime('%Y%m')}/{name}.lzh"
    # Python.org版PythonはCA証明書が無いことがあるため、検証を無効化せず curl で取得する
    for attempt in range(3):
        r = subprocess.run(["curl", "-sS", "-A", UA, "--max-time", "30", "-o", lzh, "-w", "%{http_code}", url],
                           capture_output=True, text=True)
        code = r.stdout.strip()
        if code == "200":
            break
        if code == "404":
            open(txt + ".missing", "w").close()
            return "missing"
        time.sleep(3)
    else:
        return "failed"
    r = subprocess.run(["bsdtar", "-xf", lzh, "-C", os.path.join(work, "txt")], capture_output=True)
    if r.returncode != 0 or not os.path.exists(txt):
        return "badarchive"
    return "ok"

def main():
    start, end, work = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]), sys.argv[3]
    os.makedirs(os.path.join(work, "lzh"), exist_ok=True)
    os.makedirs(os.path.join(work, "txt"), exist_ok=True)
    d, stats = start, {}
    while d <= end:
        for kind in ("K", "B"):
            if os.path.exists(os.path.join(work, "txt", f"{kind}{d.strftime('%y%m%d')}.TXT.missing")):
                continue
            s = fetch(kind, d, work)
            stats[s] = stats.get(s, 0) + 1
            if s in ("ok", "missing", "failed", "badarchive"):
                time.sleep(1.0)
        d += timedelta(days=1)
    print(stats)

if __name__ == "__main__":
    main()
