#!/usr/bin/env python3
"""mbrace の競走成績(K)・番組表(B)から、アプリ用の実データJSONを組み立てる。
使い方:
  build_real_data.py analyze WORKDIR          # モーター入れ替え検出の診断(場ごとの2連率の変化量)
  build_real_data.py build   WORKDIR OUT.json # アプリ用JSON

方針(docs/DATA_SOURCE_RULES.md「実データ版」節):
- モーター個体 = (場, 番号, 入替日)。番組表のモーター2連率は「その個体の通算」なので、
  前回出現値から整合しない急変(全数入替=場全体の分布の崩れ / 個別入替=1機の急変)を入替とみなす。
- 検出の限界(取り込み期間の頭は“入替日不明”)は meta に残し、画面で「観測開始」と表示する。
"""
import json
import os
import sys
import statistics
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mbrace_parse as P



def load(work, start=None, end=None):
    days = {}
    txt = os.path.join(work, "txt")
    for f in sorted(os.listdir(txt)):
        if not f.endswith(".TXT") or not f.startswith("K"):
            continue
        d = date(2000 + int(f[1:3]), int(f[3:5]), int(f[5:7]))
        if (start and d < start) or (end and d > end):
            continue
        k = P.parse_k(P.decode(os.path.join(txt, f)))
        bp = os.path.join(txt, "B" + f[1:])
        b = P.parse_b(P.decode(bp)) if os.path.exists(bp) else []
        names = P.racer_names_from_k(P.decode(os.path.join(txt, f)))
        days[d] = {"k": k, "b": b, "names": names}
    return days


def rate_series(days):
    """{(場,機): [(日付, 2連率)]}(1日1値)"""
    s = defaultdict(dict)
    for d, x in days.items():
        for e in x["b"]:
            s[(e["venue"], e["motor"])][d] = e["motor_two_rate"]
    return {k: sorted(v.items()) for k, v in s.items()}


def runs_on(days):
    """{(場,機): {日付: (出走数, 2連対数)}}  欠場は数えない"""
    r = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for d, x in days.items():
        for e in x["k"]:
            if e["code"] in NOT_A_RUN:
                continue
            c = r[(e["venue"], e["motor"])][d]
            c[0] += 1
            if e["finish"] in (1, 2):
                c[1] += 1
    return r


# 公式のモーター2連率と突合して決めた『出走に数えない』コード: K0=欠場, S0=失格(出走前)。K1(事故)・F・L・S1/S2は出走に数える
NOT_A_RUN = {"K0", "S0"}
RESET_FROM_MIN = 10.0   # 「0.00へ戻る」直前の2連率がこの値以上なら入替とみなす(自然に0.00になることはない)


def detect_epochs(days):
    """{(場,機): [入替日,...]}  先頭の観測開始は含めない。
    番組表のモーター2連率は個体の通算で、節の切れ目ごとにしか変わらない。入替後は 0.00 から始まる
    (実データで確認: 常滑 2026-10-06 に全機 0.00 → 以後 22.22 等の小母数から積み上がる)。
    よって『前回が RESET_FROM_MIN 以上 → 今回が 0.00』を入替日とする。全数入替も個別入替も同じ規則で検出できる。"""
    swaps = defaultdict(list)
    for (v, m), pts in rate_series(days).items():
        for (d0, r0), (d1, r1) in zip(pts, pts[1:]):
            if r1 == 0.0 and r0 >= RESET_FROM_MIN:
                swaps[(v, m)].append(d1)
    return dict(swaps)


def epoch_start(swaps, key, d):
    """日付 d が属する個体の開始日(入替日。無ければ None=観測開始より前)"""
    prior = [x for x in swaps.get(key, []) if x <= d]
    return max(prior) if prior else None


def verify_against_official(days, swaps):
    """Kから自前集計した個体通算2連率を、次の節頭のBの公式値と突き合わせる(入替検出と集計定義の検証)。"""
    series = rate_series(days)
    res = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # (v,m,epoch) -> date -> [runs, two]
    for d, x in days.items():
        for e in x["k"]:
            if e["code"] in NOT_A_RUN:
                continue
            key = (e["venue"], e["motor"])
            c = res[(key, epoch_start(swaps, key, d))][d]
            c[0] += 1
            c[1] += 1 if e["finish"] in (1, 2) else 0
    ok = bad = 0
    diffs = []
    for key, pts in series.items():
        ep0 = None
        for (d0, r0), (d1, r1) in zip(pts, pts[1:]):
            if r1 == 0.0 and r0 >= RESET_FROM_MIN:
                ep0 = d1
            # 入替直後の節(0.00)の後から検証できる: 起点=その個体の最初の0.00日(観測内で入替が見えた個体のみ)
        starts = swaps.get(key, [])
        for st in starts:
            later = [(d, r) for d, r in pts if d > st and r > 0]
            if not later:
                continue
            d, r = later[0]
            runs = sum(c[0] for dd, c in res[(key, st)].items() if st <= dd < d)
            two = sum(c[1] for dd, c in res[(key, st)].items() if st <= dd < d)
            if runs == 0:
                continue
            mine = 100.0 * two / runs
            diffs.append(abs(mine - r))
            if abs(mine - r) <= 0.06:
                ok += 1
            else:
                bad += 1
    return ok, bad, diffs


def analyze(work, start=None):
    days = load(work, start)
    ds = sorted(days)
    print(f"days={len(days)} {ds[0]}..{ds[-1]} entries={sum(len(x['k']) for x in days.values())}")
    swaps = detect_epochs(days)
    by_venue = defaultdict(lambda: defaultdict(int))
    for (v, m), l in swaps.items():
        for d in l:
            by_venue[v][d] += 1
    print("--- 入替イベント(場: 日付×機数) ---")
    for v, dd in sorted(by_venue.items()):
        print(P.VENUES[v], {str(d)[5:]: n for d, n in sorted(dd.items())})
    ok, bad, diffs = verify_against_official(days, swaps)
    print(f"--- 公式2連率との突合: 一致(±0.06) {ok} / 不一致 {bad}")
    if diffs:
        print("   差の中央値", statistics.median(diffs), " 最大", max(diffs))


SESSION_GAP_DAYS = 3        # 同じ選手が同じ個体を使った出走の間隔がこれを超えたら別の節
RECENT_RESULTS_PER_MOTOR = 10


def build(work, out_path, start=None, end=None):
    days = load(work, start, end)
    ds = sorted(days)
    swaps = detect_epochs(days)
    first_seen, last_seen = {}, {}
    for d in ds:
        for e in days[d]["k"]:
            key = (e["venue"], e["motor"])
            first_seen.setdefault(key, d); last_seen[key] = d
    # 選手の級別は期間内の最新の番組表から
    klass, names = {}, {}
    for d in ds:
        for e in days[d]["b"]:
            klass[e["racer_no"]] = e["klass"]
        names.update(days[d]["names"])

    def mid(key, st):
        return f"m-{key[0]}-{key[1]:02d}-" + ("e0" if st is None else "e" + st.strftime("%Y%m%d"))

    # --- 個体 ---
    motors = {}
    for key in sorted(first_seen):
        starts = [None] + sorted(swaps.get(key, []))
        for i, st in enumerate(starts):
            nxt = starts[i + 1] if i + 1 < len(starts) else None
            latest = nxt is None
            active = latest   # 最新の個体は稼働中とみなす(長期未使用でも廃止とは断定しない)
            motors[mid(key, st)] = {
                "motorId": mid(key, st), "venueId": f"v-{key[0]}", "motorNumber": key[1],
                "introductionDate": (st or first_seen[key]).isoformat(),
                "retirementDate": None if latest else (nxt - timedelta(days=1)).isoformat(),
                "activeStatus": "active" if active else "retired",
            }
    # --- 使用履歴(選手×個体×節) ---
    by = defaultdict(list)
    for d in ds:
        for e in days[d]["k"]:
            if e["code"] in NOT_A_RUN:
                continue
            key = (e["venue"], e["motor"])
            by[(mid(key, epoch_start(swaps, key, d)), e["racer_no"])].append((d, e))
    usages, results, racers = [], [], {}
    for (motor_id, racer_no), rows in sorted(by.items()):
        rows.sort(key=lambda x: (x[0], x[1]["race"]))
        groups, cur = [], [rows[0]]
        for prev, nxt in zip(rows, rows[1:]):
            if (nxt[0] - prev[0]).days > SESSION_GAP_DAYS:
                groups.append(cur); cur = []
            cur.append(nxt)
        groups.append(cur)
        for g in groups:
            sd, ed = g[0][0], g[-1][0]
            uid = f"u-{motor_id[2:]}-{racer_no}-{sd.strftime('%Y%m%d')}"
            f = [sum(1 for _, e in g if e["finish"] == n) for n in (1, 2, 3)]
            usages.append({"usageId": uid, "motorId": motor_id, "racerId": f"r-{racer_no}",
                           "eventId": f"ev-{motor_id.split('-')[1]}-{sd.isoformat()}",
                           "startDate": sd.isoformat(), "endDate": ed.isoformat(), "raceCount": len(g),
                           "firstPlaceCount": f[0], "secondPlaceCount": f[1], "thirdPlaceCount": f[2]})
            racers[racer_no] = True
            for d, e in g:
                if e["finish"] and e["exhibition"] and e["start"] is not None and e["course"]:
                    results.append((motor_id, d, e, uid, racer_no))
    # 直近の結果(個体ごと最新N件)だけ詳細を持つ。それ以前は節ごとの集計のみ
    bym = defaultdict(list)
    for r in results:
        bym[r[0]].append(r)
    raceRows = []
    for motor_id, rs in bym.items():
        rs.sort(key=lambda r: (r[1], r[2]["race"]))
        for motor_id_, d, e, uid, racer_no in rs[-RECENT_RESULTS_PER_MOTOR:]:
            raceRows.append({"raceId": f"rc-{e['venue']}-{d.strftime('%Y%m%d')}-{e['race']:02d}-{e['boat']}",
                             "date": d.isoformat(), "venueId": f"v-{e['venue']}", "raceNumber": e["race"],
                             "racerId": f"r-{racer_no}", "motorId": motor_id_, "usageId": uid,
                             "course": e["course"], "finishPosition": e["finish"],
                             "exhibitionTime": e["exhibition"], "startTiming": e["start"]})
    # 収録最終日の出走表(番組表Bの最新日)。アプリは「その日の出走表」として日付付きで表示する
    # 成績(K)より新しい番組表(B)があれば、それを出走表にする(前日夕方に翌日分が公開される)
    b_days = [d for d in ds if days[d]["b"]]
    ahead = {}
    txt = os.path.join(work, "txt")
    for f in sorted(os.listdir(txt)):
        if f.startswith("B") and f.endswith(".TXT"):
            d = date(2000 + int(f[1:3]), int(f[3:5]), int(f[5:7]))
            if d > ds[-1]:
                ahead[d] = P.parse_b(P.decode(os.path.join(txt, f)))
    lineup, lineup_day = [], None
    if ahead:
        lineup_day = max(ahead); lineup_src = ahead[lineup_day]
    elif b_days:
        lineup_day = b_days[-1]; lineup_src = days[lineup_day]["b"]
    if lineup_day:
        for e in lineup_src:
            if (e["venue"], e["motor"]) not in first_seen:
                continue
            racers.setdefault(e["racer_no"], True); names.setdefault(e["racer_no"], e["name"].replace(" ", ""))
            klass[e["racer_no"]] = e["klass"]
            lineup.append({"date": lineup_day.isoformat(), "venueId": f"v-{e['venue']}", "raceNumber": e["race"],
                           "boat": e["boat"], "racerId": f"r-{e['racer_no']}", "motorNumber": e["motor"]})
    runs_by_motor = defaultdict(int)
    for u in usages:
        runs_by_motor[u["motorId"]] += u["raceCount"]
    evals = [{"motorId": m, "evaluationDate": ds[-1].isoformat(), "modelVersion": "none",
              "sampleSize": runs_by_motor[m], "totalScore": None, "performanceScores": None,
              "confidence": "insufficient"} for m in motors]
    src = {"sourceId": "src-mbrace", "sourceName": "BOAT RACE オフィシャルウェブサイト 競走成績・番組表ダウンロード",
           "sourceURL": "https://www1.mbrace.or.jp/od2/", "retrievedAt": date.today().isoformat(),
           "publishedAt": ds[-1].isoformat(), "usagePermissionStatus": "owner-decision-no-permission-required",
           "reliability": "official-raw"}
    data = {
        "meta": {"isSample": False, "resultsPartial": True,
                 "notice": f"{ds[0].isoformat()}〜{ds[-1].isoformat()}の競走成績・番組表から自動集計。整備履歴は含まない。"
                           "個体の使用開始日が『観測開始』と書かれているものは、それより前の入替日は不明。",
                 "generatedFor": ds[-1].isoformat(), "windowStart": ds[0].isoformat()},
        "sources": [src],
        "venues": [{"venueId": f"v-{c}", "venueName": n} for c, n in sorted(P.VENUES.items())],
        "motors": sorted(motors.values(), key=lambda m: m["motorId"]),
        "racers": [{"racerId": f"r-{n}", "registrationNumber": n, "racerName": names.get(n, str(n)),
                    "racerClass": klass.get(n, "－")} for n in sorted(racers)],
        "races": lineup, "usages": usages, "raceResults": raceRows, "maintenance": [], "evaluations": evals,
    }
    with open(out_path, "w") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    import hashlib
    raw = open(out_path, "rb").read()
    manifest = {"version": 1, "generatedFor": ds[-1].isoformat(), "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw), "file": os.path.basename(out_path)}
    json.dump(manifest, open(os.path.join(os.path.dirname(out_path), "manifest.json"), "w"))
    print({k: len(v) for k, v in data.items() if isinstance(v, list)}, "bytes", os.path.getsize(out_path))
    return data


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "analyze":
        analyze(sys.argv[2], date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else None)
    elif len(sys.argv) >= 4 and sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3], date.fromisoformat(sys.argv[4]) if len(sys.argv) > 4 else None)
