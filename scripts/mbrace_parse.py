"""mbrace 日次ファイル(Shift_JIS)のパーサ。
K=競走成績, B=番組表。出力は素のdict。表記ゆれ・欠場・失格は捨てずに区別して返す。
"""
import re
import unicodedata

VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川", "06": "浜名湖",
    "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島", "17": "宮島", "18": "徳山",
    "19": "下関", "20": "若松", "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}

def decode(path):
    return open(path, "rb").read().decode("cp932", errors="replace")

def _blocks(text, tag):
    """`NNtagBGN` 〜 `NNtagEND` を (場コード, 行リスト) で返す。"""
    cur, lines = None, []
    for ln in text.splitlines():
        m = re.match(r"^(\d\d)%sBGN" % tag, ln)
        if m:
            cur, lines = m.group(1), []
        elif re.match(r"^\d\d%sEND" % tag, ln):
            if cur:
                yield cur, lines
            cur = None
        elif cur:
            lines.append(ln)

# 着順コード: 01-06=着順 / それ以外(F=フライング L=出遅れ S=失格 K=欠場 など)=不着
ENTRANT_K = re.compile(
    r"^\s+(\d\d|[A-Z]\d?)\s+([1-6])\s+(\d{4})\s+(.+?)\s+(\d{1,2})\s+(\d{1,3})\s+(.*)$")
RACE_HEAD = re.compile(r"^\s+(\d{1,2})R\s+(\S.*?)\s+H\d{3,4}m")

def parse_k(text):
    """戻り値: [{venue, race, boat, racer_no, finish(int|None), code, motor, boat_no, exhibition, course, start}]"""
    out = []
    for venue, lines in _blocks(text, "K"):
        race = None
        for ln in lines:
            h = RACE_HEAD.match(ln)
            if h:
                race = int(h.group(1)); continue
            if race is None:
                continue
            m = ENTRANT_K.match(ln)
            if not m:
                continue
            code, boat, racer_no, _name, motor, boat_no, rest = m.groups()
            # 欠場(K0等)は rest に "K ." が入る。展示/進入/ST を取れる範囲で取る
            toks = rest.split()
            expo = course = st = None
            if toks and re.fullmatch(r"\d\.\d\d", toks[0]):
                expo = float(toks[0]); toks = toks[1:]
                if toks and re.fullmatch(r"[1-6]", toks[0]):
                    course = int(toks[0]); toks = toks[1:]
                    if toks and re.fullmatch(r"-?\d?\.\d\d", toks[0]):
                        st = float(toks[0])
            out.append({
                "venue": venue, "race": race, "boat": int(boat), "racer_no": int(racer_no),
                "code": code, "finish": int(code) if code.isdigit() else None,
                "motor": int(motor), "boat_no": int(boat_no),
                "exhibition": expo, "course": course, "start": st,
            })
    return out

# 番組表: "1 5104山田　丈27福岡52A2 6.02 45.45 5.69 40.82 29 34.42112 30.99 1 324312    10"
ENTRANT_B = re.compile(
    r"^([1-6])\s(\d{4})(.{4})(\d\d)(.{2})(\d\d)([AB][12])\s*"
    r"(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+"
    r"(\d{1,2})\s+(\d+\.\d\d)\s*(\d{1,3})\s+(\d+\.\d\d)")

def parse_b(text):
    """戻り値: [{venue, race, boat, racer_no, name, klass, motor, motor_two_rate, boat_no}]"""
    out = []
    for venue, lines in _blocks(text, "B"):
        race = None
        for ln in lines:
            norm = unicodedata.normalize("NFKC", ln)
            h = re.match(r"^\s*(\d{1,2})R\s", norm)
            if h:
                race = int(h.group(1)); continue
            if race is None:
                continue
            # 全角を含む氏名欄があるので、NFKCで揃えたうえで固定幅でなく正規表現で読む
            m = re.match(
                r"^([1-6])\s(\d{4})(.+?)(\d\d)(\S{2})(\d\d)([AB][12])\s+"
                r"(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+(\d+\.\d\d)\s+"
                r"(\d{1,2})\s+(\d+\.\d\d)\s*(\d{1,3})\s+(\d+\.\d\d)", norm)
            if not m:
                continue
            boat, racer_no, name, age, branch, weight, klass, _, _, _, _, motor, mrate, boat_no, _ = m.groups()
            out.append({"venue": venue, "race": race, "boat": int(boat), "racer_no": int(racer_no),
                        "name": name.strip(), "klass": klass, "motor": int(motor),
                        "motor_two_rate": float(mrate), "boat_no": int(boat_no)})
    return out

def racer_names_from_k(text):
    """K の選手名(全角スペース混じり)を {登番: 氏名} で返す。"""
    names = {}
    for venue, lines in _blocks(text, "K"):
        for ln in lines:
            m = ENTRANT_K.match(ln)
            if m:
                names[int(m.group(3))] = re.sub(r"[\s　]+", "", m.group(4))
    return names
