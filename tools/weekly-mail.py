"""부동산 시장 주간 요약 메일을 만든다: 본문(email-summary.html), 제목(email-subject.txt), 그림(mail-charts/*.png).

    python3 tools/weekly-mail.py [dashboard.html] [출력 폴더]

- 자료는 Update-RealEstateDashboard.ps1 이 만든 dashboard.html 안의 JSON 두 개(id="data", id="geo")를 그대로 읽는다.
  계산 방식은 template.html 의 화면과 같다(3개월 변동으로 정하는 큰 글자, 연속 주, 시장 온도, 신호 5개 등).
- 메일 프로그램은 화면의 그래프(SVG, 자바스크립트)를 보여 주지 않는다. 그래서 같은 자료로 SVG 를 그리고 크롬으로 2배 해상도
  PNG 를 찍는다(work-dashboard·stockdashboard 의 mail_charts.py 와 같은 방식). 발송 도구(dawidd6/action-send-mail)는
  첨부 파일 이름을 cid 로 붙이므로 본문에서 <img src="cid:파일이름"> 으로 부른다. 그림을 못 만들면 그 자리는 글만 나간다.
- 표준 라이브러리만 쓴다. 실행 환경에는 한글 글꼴(우분투는 fonts-nanum)과 크롬만 있으면 된다.
"""
import datetime as dt
import html
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dashboard.html"
OUTDIR = (pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT).resolve()
CHARTS = OUTDIR / "mail-charts"
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
URL = CFG.get("dashboardUrl", "")

INK, INK2, INK3, GRID, BG, SURF, RAISED = "#15171c", "#464a53", "#7c808a", "#ece9e2", "#f3f2ee", "#ffffff", "#f8f7f4"
RISE, FALL, FLAT = "#d0352a", "#1d62d3", "#8a8e97"
RISE_B, FALL_B, ZERO, NA = ["#fbe2dc", "#f2aa9a", "#e06651"], ["#dee8fb", "#a7c1f2", "#5e8ce0"], "#ecebe6", "#f1f0ec"
CITY_COL = {"seoul": "#6a45d0", "busan": "#08877a"}
RIVER = "#b5d4f0"
FONT = "'Malgun Gothic','NanumGothic','Noto Sans KR',sans-serif"
MFONT = "'Malgun Gothic','Apple SD Gothic Neo','Noto Sans KR',sans-serif"

page = SRC.read_text(encoding="utf-8")


def block(id_):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % id_, page, re.S)
    return json.loads(m.group(1)) if m else None


D, G = block("data"), block("geo")
if not D:
    sys.exit("dashboard.html 에서 자료를 찾지 못했습니다")
WKD = D["weekly"]
esc = lambda s: html.escape(str(s), quote=True)
has = lambda v: isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v))


def W(k):
    a = WKD["series"].get(k) or []
    return [(d, v) for d, v in zip(WKD["dates"], a) if v is not None]


M = lambda k: D["monthly"].get(k) or []
E = lambda k: D["ecos"].get(k) or []
last = lambda a: a[-1][1] if a else None
last_key = lambda a: a[-1][0] if a else None
chg = lambda a, n: (a[-1][1] / a[-1 - n][1] - 1) * 100 if len(a) > n else None
wk_chg = lambda a: [(a[i][1] / a[i - 1][1] - 1) * 100 for i in range(1, len(a))]
avg = lambda a: (sum(x for x in a if has(x)) / len([x for x in a if has(x)])) if [x for x in a if has(x)] else None


def streak(arr, up):
    n = 0
    for x in reversed(arr):
        r = round(x, 2)
        if (r > 0) if up else (r < 0):
            n += 1
        else:
            break
    return n


def pct(x, d=2):
    if not has(x):
        return "–"
    r = round(x, d)
    return ("+" if r > 0 else "−" if r < 0 else "") + f"{abs(r):.{d}f}%"


def cls(x, d=2):
    if not has(x):
        return "flat"
    r = round(x, d)
    return "up" if r > 0 else "down" if r < 0 else "flat"


COLOR = {"up": RISE, "down": FALL, "flat": FLAT}
num = lambda v, d=0: f"{v:,.{d}f}" if has(v) else "–"
ym = lambda t: f"{t[:4]}.{int(t[5:7])}"


def mshift(t, k):
    y, m = int(t[:4]), int(t[5:7]) + k
    while m < 1:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y}-{m:02d}"


def won(w):
    a = abs(w)
    if a >= 1e8:
        return (f"{a / 1e8:.1f}" if a >= 1e9 else f"{a / 1e8:.2f}").rstrip("0").rstrip(".") + "억 원"
    if a >= 1e4:
        unit = 100 if a >= 1e7 else 10
        return f"{round(a / 1e4 / unit) * unit:,.0f}만 원"
    return f"{a:,.0f}원"


def tw(s, f=11):
    return sum(f * 1.04 if "ㄱ" <= ch <= "힝" else f * 0.6 for ch in str(s))


# ---- 계산(화면과 같은 방식) ---------------------------------------------------------------------
REG = {r["key"]: r for r in D["meta"]["regions"]}
CITY = {"seoul": {"nm": "서울", "code": REG["seoul"]["cls"]}, "busan": {"nm": "부산", "code": REG["busan"]["cls"]}}
NAT = REG["national"]["cls"]
DIST = {k: [(n, c, g["name"]) for g in REG[k].get("groups") or [] if g.get("districts") for n, c in g["districts"]] for k in CITY}
grp_cls = lambda city, name: next((g["cls"] for g in REG[city].get("groups") or [] if g["name"] == name), None)


def month_end(k):
    o = {}
    for d, v in W(k):
        o[d[:7]] = v
    return o


def yoy(a, b):
    return (a / b - 1) * 100 if has(a) and has(b) and b else None


clp = lambda v: max(0.0, min(100.0, v))


def comps(buy, rent, p3, tr, un):
    return [clp(buy - 50) if has(buy) else None, clp(rent - 50) if has(rent) else None, clp(50 + p3 / 3 * 50) if has(p3) else None,
            clp(50 + tr / 50 * 50) if has(tr) else None, clp(50 - un / 50 * 50) if has(un) else None]


heat_label = lambda s: "강한 매도자 우위" if s >= 70 else "매도자 우위" if s >= 55 else "중립" if s >= 40 else "매수자 우위"


def heat_now(city):
    code = CITY[city]["code"]
    tr, un = dict(M(f"trade:{city}")), dict(E(f"unsold.{city}"))

    def ma3(m):
        vs = [tr.get(mshift(m, -i)) for i in range(3)]
        return sum(vs) / 3 if all(has(v) for v in vs) else None

    lm, lu = (max(tr) if tr else None), (max(un) if un else None)
    parts = comps(last(W(f"buy:{code}")), last(W(f"rent:{code}")), chg(W(f"sale:{code}"), 12),
                  yoy(ma3(lm), ma3(mshift(lm, -12))) if lm else None, yoy(un.get(lu), un.get(mshift(lu, -12))) if lu else None)
    a = avg(parts)
    return round(a) if has(a) else None


def trend_word(x):
    a, up = abs(x), x > 0
    if a < 0.1:
        return "제자리", "", "flat"
    if a < 0.3:
        return "거의 제자리", ("살짝 오름" if up else "살짝 내림"), ("up" if up else "down")
    if a < 1:
        return ("조금씩 오르는 중" if up else "조금씩 내리는 중"), "", ("up" if up else "down")
    if a < 3:
        return ("오르는 중" if up else "내리는 중"), "", ("up" if up else "down")
    return ("가파르게 오르는 중" if up else "가파르게 내리는 중"), "", ("up" if up else "down")


def signals(city):
    code = CITY[city]["code"]
    s12, j12 = chg(W(f"sale:{code}"), 12), chg(W(f"jeonse:{code}"), 12)
    tr = [v for _, v in M(f"trade:{city}")]
    ma = [(tr[i] + tr[i - 1] + tr[i - 2]) / 3 for i in range(2, len(tr))]
    trch = (ma[-1] / ma[-13] - 1) * 100 if len(ma) > 12 else None
    un = E(f"unsold.{city}")
    uch = (un[-1][1] / un[-13][1] - 1) * 100 if len(un) > 12 else None
    buy = last(W(f"buy:{code}"))
    lvl = lambda x, t: 0 if not has(x) else 1 if x > t else -1 if x < -t else 0
    return {"trch": trch, "uch": uch, "list": [
        ("집값", lvl(s12, 0.1), "오름" if has(s12) and s12 > 0.1 else "내림" if has(s12) and s12 < -0.1 else "보합"),
        ("전세", lvl(j12, 0.1), "오름" if has(j12) and j12 > 0.1 else "내림" if has(j12) and j12 < -0.1 else "보합"),
        ("거래", lvl(trch, 5), "늘어남" if has(trch) and trch > 5 else "줄어듦" if has(trch) and trch < -5 else "비슷"),
        ("미분양", -lvl(uch, 5), "늘어남" if has(uch) and uch > 5 else "줄어듦" if has(uch) and uch < -5 else "비슷"),
        ("살 사람", (1 if buy >= 100 else -1) if has(buy) else 0, ("더 많음" if buy >= 100 else "더 적음") if has(buy) else "–")]}


# ---- 그림(SVG → 크롬 → PNG) ---------------------------------------------------------------------
def text(x, y, s, size=12, color=INK2, weight=500, anchor="start", extra=""):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}"{extra}>{esc(s)}</text>'


def hero_svg(city):
    s = W(f"sale:{CITY[city]['code']}")
    if len(s) < 53:
        return None
    base = s[-53][1]
    pts = [(i, (v / base - 1) * 100) for i, (_, v) in enumerate(s[-53:])]
    vs = [v for _, v in pts]
    Wd, H, PL, PR, PT, PB = 600, 176, 6, 92, 22, 24
    lo, hi = min(0, *vs), max(0, *vs)
    pad = max((hi - lo) * 0.14, 0.4)
    lo, hi = lo - pad, hi + pad
    X = lambda i: PL + i / 52 * (Wd - PL - PR)
    Y = lambda v: PT + (hi - v) / (hi - lo) * (H - PT - PB)
    end = vs[-1]
    col, s12 = COLOR[cls(end, 1)], chg(s, 12)
    col3, i3 = COLOR[cls(s12)], 40
    path = lambda a: "M" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in a)
    y0 = Y(0)
    down = cls(end, 1) == "down"
    g = (f'<defs><linearGradient id="g" x1="0" y1="{1 if down else 0}" x2="0" y2="{0 if down else 1}">'
         f'<stop offset="0" stop-color="{col}" stop-opacity=".26"/><stop offset="1" stop-color="{col}" stop-opacity=".03"/></linearGradient></defs>')
    g += f'<rect width="{Wd}" height="{H}" fill="{SURF}"/>'
    g += f'<line x1="{X(i3):.1f}" x2="{X(i3):.1f}" y1="{PT - 6}" y2="{H - PB}" stroke="{GRID}"/>'
    g += text(X(i3), H - 7, "3개월 전", 11, INK3, 500, "middle") + text(PL, H - 7, "1년 전", 11, INK3) + text(X(52), H - 7, "지금", 11, INK3, 500, "end")
    g += f'<path d="{path(pts)} L{X(52):.1f},{y0:.1f} L{X(0):.1f},{y0:.1f} Z" fill="url(#g)"/>'
    g += f'<line x1="{PL}" x2="{Wd - PR}" y1="{y0:.1f}" y2="{y0:.1f}" stroke="{INK3}" stroke-dasharray="4 4"/>'
    if abs(Y(end) - y0) > 18:
        g += text(Wd - PR + 8, y0 + 4, "1년 전 값", 11, INK3)
    g += f'<path d="{path(pts[:i3 + 1])}" fill="none" stroke="{col}" stroke-width="2.2" stroke-opacity=".55" stroke-linejoin="round"/>'
    g += f'<path d="{path(pts[i3:])}" fill="none" stroke="{col3}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
    ly = max(PT + 2, min(Y(v) for _, v in pts[i3:]) - 9)
    g += text((X(i3) + X(52)) / 2, ly, f"최근 3개월 {pct(s12)}", 11.5, col3, 750, "middle")
    g += f'<circle cx="{X(52):.1f}" cy="{Y(end):.1f}" r="5.5" fill="{col3}" stroke="{SURF}" stroke-width="2.5"/>'
    g += (f'<text x="{X(52) + 9:.1f}" y="{Y(end) + 6:.1f}" font-size="17" font-weight="800" fill="{col}">'
          f'<tspan font-size="11" font-weight="600" fill="{INK3}">1년 </tspan>{esc(pct(end, 1))}</text>')
    return {"file": f"hero-{city}.png", "w": Wd, "h": H, "svg": g}


BIN = [0.2, 0.4, 0.8]   # 4주 변동의 색 경계(화면과 같음)


def fill_of(v):
    if not has(v):
        return NA
    a = abs(v)
    lv = 0 if a < BIN[0] else 1 if a < BIN[1] else 2 if a < BIN[2] else 3
    return ZERO if lv == 0 else (RISE_B if v > 0 else FALL_B)[lv - 1]


def map_svg(key, val, name, short, width, hi=None, file=None):
    m = G[key]
    k = width / m["w"]
    Wd, H = width, round(m["h"] * k)
    rows = [{"a": a, "v": val(a), "nm": name(a)} for a in m["areas"]]
    hi = hi or {}
    land = "".join(f'<path d="{r["a"]["d"]}" fill="{fill_of(r["v"])}" stroke="#fff" stroke-width="{1 / k:.2f}"/>' for r in rows)
    for rv in m.get("rivers", []):
        land += f'<path d="{rv["d"]}" fill="none" stroke="{RIVER}" stroke-width="{9 if key == "seoul" else 7}" stroke-linecap="round" stroke-linejoin="round"/>'
    top = "".join(f'<path d="{r["a"]["d"]}" fill="none" stroke="{hi[r["a"]["code"]]}" stroke-width="{2.6 / k:.2f}"/>' for r in rows if r["a"]["code"] in hi)
    placed, labs = [], ""

    def put(x0, y0, x1, y1):
        if x0 < 0 or x1 > Wd or any(x0 < p[2] and x1 > p[0] and y0 < p[3] and y1 > p[1] for p in placed):
            return False
        placed.append((x0, y0, x1, y1))
        return True

    for r in sorted([r for r in rows if r["a"].get("call")], key=lambda r: r["a"]["code"] not in hi):
        a, nm, vt = r["a"], short(r["nm"]), pct(r["v"], 1)
        cx, cy = a["lx"] * k, a["ly"] * k
        w = tw(nm, 11.5) + tw(vt, 11.5) + 18
        x0 = a["call"][0] * k - (w / 2 if a["call"][2] == "middle" else w if a["call"][2] == "end" else 0)
        x0, y = max(1, min(Wd - w - 1, x0)), max(11, min(H - 11, a["call"][1] * k))
        if not put(x0, y - 11, x0 + w, y + 11):
            continue
        ex, ey = max(x0, min(x0 + w, cx)), max(y - 10, min(y + 10, cy))
        big = hi.get(a["code"])
        labs += f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{INK3}"/><circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.3" fill="{INK}"/>'
        labs += f'<rect x="{x0:.1f}" y="{y - 10:.1f}" width="{w:.1f}" height="20" rx="10" fill="#fff" stroke="{big or "#e3e0d8"}" stroke-width="{1.6 if big else 1}"/>'
        labs += (f'<text x="{x0 + 8:.1f}" y="{y + 4:.1f}" font-size="11.5" font-weight="800" fill="{big or INK}">{esc(nm)}'
                 f'<tspan dx="5" font-weight="750" fill="{COLOR[cls(r["v"], 1)] if cls(r["v"], 1) != "flat" else INK3}">{esc(vt)}</tspan></text>')
    for r in sorted([r for r in rows if not r["a"].get("call")], key=lambda r: -r["a"]["r"]):
        a, nm, vt = r["a"], short(r["nm"]), pct(r["v"], 1)
        cx, cy, rho = a["lx"] * k, a["ly"] * k, a["r"] * k
        bw, w1 = max(tw(nm, 11.5), tw(vt, 11)), tw(nm, 11.5)
        done = False
        if rho >= 11 and bw / 2 <= rho * 1.75:
            for ox, oy in ((0, 0), (0.45, 0), (-0.45, 0), (0, 0.4), (0, -0.4)):
                x, y = cx + ox * rho, cy + oy * rho
                if put(x - bw / 2, y - 10, x + bw / 2, y + 13):
                    labs += text(x, y - 1, nm, 11.5, INK, 750, "middle") + text(x, y + 12, vt, 11, INK2, 650, "middle")
                    done = True
                    break
        if not done and rho >= 6 and w1 / 2 <= rho * 2.1:
            for ox, oy in ((0, 0), (0.45, 0), (-0.45, 0), (0, 0.4), (0, -0.4)):
                x, y = cx + ox * rho, cy + oy * rho
                if put(x - w1 / 2, y - 6, x + w1 / 2, y + 6):
                    labs += text(x, y + 4, nm, 11.5, INK, 750, "middle")
                    break
    g = (f'<defs><filter id="sh" x="-5%" y="-5%" width="110%" height="115%"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#1e222d" flood-opacity=".16"/></filter></defs>'
         f'<rect width="{Wd}" height="{H}" fill="{SURF}"/><g filter="url(#sh)" transform="scale({k:.5f})">{land}</g><g transform="scale({k:.5f})">{top}</g>{labs}')
    return {"file": file or f"map-{key}.png", "w": Wd, "h": H, "svg": g}


def find_chrome():
    for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(c)
        if p:
            return p
    for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.exists(p):
            return p
    return None


def shoot(chrome, chart, tmp):
    src = pathlib.Path(tmp) / (chart["file"] + ".html")
    src.write_text(f'<!doctype html><html><head><meta charset="utf-8"><style>html,body{{margin:0;background:#fff;overflow:hidden}}'
                   f'svg{{display:block;font-family:{FONT}}}</style></head><body><svg width="{chart["w"]}" height="{chart["h"]}" '
                   f'viewBox="0 0 {chart["w"]} {chart["h"]}" xmlns="http://www.w3.org/2000/svg">{chart["svg"]}</svg></body></html>', encoding="utf-8")
    out = CHARTS / chart["file"]
    if out.exists():
        out.unlink()
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--force-device-scale-factor=2",
                    f"--window-size={chart['w']},{chart['h']}", f"--screenshot={out}", src.as_uri()],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    return out.exists() and out.stat().st_size > 2000


# ---- 본문 ------------------------------------------------------------------------------------
wk_date = WKD["latestDate"]
wk_lab = f"{int(wk_date[5:7])}/{int(wk_date[8:10])} 조사"
by_name = {k: {n: c for n, c, _ in DIST[k]} for k in DIST}
PROV = {p["geo"]: p for p in D["meta"].get("provinces") or []}
short = lambda n: n[:-1] if len(n) >= 3 and n[-1] in "구군" else n

charts = []
for c in CITY:
    h = hero_svg(c)
    if h:
        charts.append(h)
if G:
    for c in CITY:
        charts.append(map_svg(c, lambda a, c=c: chg(W(f"sale:{by_name[c][a['name']]}"), 4) if a["name"] in by_name[c] else None,
                              lambda a: a["name"], short, 600))
    charts.append(map_svg("korea", lambda a: chg(W(f"sale:{PROV[a['code']]['cls']}"), 4) if a["code"] in PROV else None,
                          lambda a: PROV[a["code"]]["name"] if a["code"] in PROV else a["name"], lambda n: n, 520,
                          hi={"11": CITY_COL["seoul"], "21": CITY_COL["busan"]}))
made = set()
chrome = find_chrome()
if chrome:
    CHARTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for ch in charts:
            try:
                if shoot(chrome, ch, tmp):
                    made.add(ch["file"])
            except Exception as e:  # 그림 하나가 실패해도 메일은 나간다
                print("그림 실패", ch["file"], e)
print("그림", sorted(made), "크롬", bool(chrome))


def img(file, w, alt):
    if file not in made:
        return ""
    return f'<img src="cid:{file}" width="{w}" alt="{esc(alt)}" style="display:block;width:100%;max-width:{w}px;height:auto;border:0;margin:6px 0 2px">'


P = f"font-family:{MFONT};"
span = lambda s, c, w=700: f'<span style="color:{c};font-weight:{w}">{s}</span>'
colored = lambda x, d=2: span(esc(pct(x, d)), COLOR[cls(x, d)] if cls(x, d) != "flat" else INK3)


def city_block(c):
    code, nm = CITY[c]["code"], CITY[c]["nm"]
    s = W(f"sale:{code}")
    wk = wk_chg(s)
    s1, s12, s52 = chg(s, 1), chg(s, 12), chg(s, 52)
    word, sub, d = trend_word(s12)
    up, dn = streak(wk, True), streak(wk, False)
    run = f"{up}주 연속 상승" if up >= 2 else f"{dn}주 연속 하락" if dn >= 2 else f"이번 주 {pct(s1)}"
    r4, r8 = avg(wk[-4:]), avg(wk[-12:-4])
    speed = ""
    if has(r4) and has(r8) and d != "flat":
        diff = r4 - r8
        speed = "비슷한 속도" if abs(diff) < 0.01 else (("오름 폭이 커지는 중" if diff > 0 else "오름 폭이 줄어드는 중") if d == "up" else ("내림 폭이 커지는 중" if diff < 0 else "내림 폭이 줄어드는 중"))
    arrow = "▲" if d == "up" else "▼" if d == "down" else "■"
    col = COLOR[d] if d != "flat" else INK
    med, medm = last(M(f"median:{c}")), last_key(M(f"median:{c}"))
    money = ""
    if has(med) and has(s52):
        P_ = med * 1000
        delta = P_ * (s52 / 100) / (1 + s52 / 100)
        dd = cls(s52, 1)
        money = f"중간 가격 아파트(약 {won(P_)}, {ym(medm)})로 치면 <b>1년 새 약 {won(delta)} {'올랐습니다' if dd == 'up' else '내렸습니다' if dd == 'down' else '그대로입니다'}</b>."
    sg = signals(c)
    n_up, n_dn = sum(1 for x in sg["list"] if x[1] > 0), sum(1 for x in sg["list"] if x[1] < 0)
    sig = " · ".join(span(f"{'↑' if x[1] > 0 else '↓' if x[1] < 0 else '·'} {esc(x[0])} {esc(x[2])}", RISE if x[1] > 0 else FALL if x[1] < 0 else INK3, 650) for x in sg["list"])
    hn = heat_now(c)
    rows = [(n, chg(W(f"sale:{cd}"), 4)) for n, cd, _ in DIST[c]]
    rows = sorted([r for r in rows if has(r[1])], key=lambda r: -r[1])
    top3 = ", ".join(f"{esc(n)} {colored(v, 1)}" for n, v in rows[:3] if round(v, 1) > 0) or "없음"
    bot3 = ", ".join(f"{esc(n)} {colored(v, 1)}" for n, v in rows[::-1][:3] if round(v, 1) < 0) or "없음"
    n_r = sum(1 for _, v in rows if round(v, 2) > 0)
    cell = lambda k, v: (f'<td style="padding:8px 10px;background:{RAISED};border:1px solid #e3e0d8;border-radius:10px;{P}">'
                         f'<div style="font-size:12px;color:{INK3}">{k}</div><div style="font-size:19px;font-weight:800">{colored(v, 1 if k == "1년" else 2)}</div></td>')
    return f"""
<tr><td style="padding:0 0 14px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SURF};border:1px solid #e3e0d8;border-top:4px solid {CITY_COL[c]};border-radius:14px">
<tr><td style="padding:16px 18px 6px;{P}">
  <div style="font-size:14px;font-weight:800;color:{CITY_COL[c]}">{nm} 아파트 · 최근 3개월{f' <span style="color:{INK3};font-weight:600">· 시장 온도 {hn} {heat_label(hn)}</span>' if has(hn) else ''}</div>
  <div style="font-size:28px;font-weight:800;color:{col};letter-spacing:-0.5px;margin-top:4px">{arrow} {esc(word)}{f' <span style="font-size:15px;color:{INK2};font-weight:700">{esc(sub)}</span>' if sub else ''}</div>
  <div style="font-size:13.5px;color:{INK2};margin-top:2px"><b style="color:{INK}">{run}</b>{f' · 최근 4주 {speed}' if speed else ''}</div>
  {img(f"hero-{c}.png", 600, f"{nm} 집값 1년 흐름")}
</td></tr>
<tr><td style="padding:2px 18px 4px"><table role="presentation" width="100%" cellpadding="0" cellspacing="6"><tr>{cell("이번 주", s1)}{cell("3개월", s12)}{cell("1년", s52)}</tr></table></td></tr>
<tr><td style="padding:4px 18px 4px;font-size:14px;color:{INK2};line-height:1.6;{P}">{money}</td></tr>
<tr><td style="padding:2px 18px 8px;font-size:13px;line-height:1.7;{P}">{sig}<br><span style="color:{INK3};font-size:12px">빨강 = 집값을 올리는 쪽, 파랑 = 내리는 쪽 · 올리는 신호 {n_up} · 내리는 신호 {n_dn}</span></td></tr>
<tr><td style="padding:8px 18px 4px;border-top:1px dashed {GRID};font-size:13.5px;color:{INK2};line-height:1.65;{P}">
  <b style="color:{INK}">최근 4주 구별</b> · 오른 곳 {n_r} · 내린 곳 {len(rows) - n_r}<br>많이 오른 곳: {top3}<br>많이 내린 곳: {bot3}
  {img(f"map-{c}.png", 600, f"{nm} 구별 최근 4주 변동 지도")}
</td></tr>
<tr><td style="padding:0 18px 14px;font-size:11.5px;color:{INK3};{P}">지도 색: 진한 빨강일수록 많이 오름, 진한 파랑일수록 많이 내림(4주 ±0.2% / ±0.4% / ±0.8% 경계)</td></tr>
</table></td></tr>"""


def korea_block():
    rows = sorted([(p["name"], p["cls"], chg(W(f"sale:{p['cls']}"), 4)) for p in PROV.values()], key=lambda r: -(r[2] if has(r[2]) else -99))
    rows = [r for r in rows if has(r[2])]
    if not rows:
        return ""
    up = sum(1 for r in rows if round(r[2], 1) > 0)
    pos = lambda code: next((i + 1 for i, r in enumerate(rows) if r[1] == code), "–")
    sv = next((r[2] for r in rows if r[1] == CITY["seoul"]["code"]), None)
    bv = next((r[2] for r in rows if r[1] == CITY["busan"]["code"]), None)
    rank = " · ".join(f"{i + 1} {esc(n)} {colored(v, 1)}" for i, (n, _, v) in enumerate(rows))
    return f"""
<tr><td style="padding:0 0 14px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SURF};border:1px solid #e3e0d8;border-radius:14px">
<tr><td style="padding:16px 18px;font-size:14px;color:{INK2};line-height:1.65;{P}">
  <div style="font-size:16px;font-weight:800;color:{INK}">전국에서 보면(최근 4주)</div>
  17개 시·도 중 <b style="color:{INK}">{up}곳이 오르고 {len(rows) - up}곳이 내렸습니다.</b>
  {span("서울", CITY_COL["seoul"], 800)} {colored(sv, 1)}({pos(CITY["seoul"]["code"])}위) · {span("부산", CITY_COL["busan"], 800)} {colored(bv, 1)}({pos(CITY["busan"]["code"])}위) · 전국 {colored(chg(W(f"sale:{NAT}"), 4), 1)}
  {img("map-korea.png", 520, "전국 시·도 최근 4주 변동 지도")}
  <div style="font-size:12.5px;line-height:1.8;margin-top:6px">{rank}</div>
</td></tr></table></td></tr>"""


def issues_block():
    s, b = W(f"sale:{CITY['seoul']['code']}"), W(f"sale:{CITY['busan']['code']}")
    kb, gn = grp_cls("seoul", "강북지역"), grp_cls("seoul", "강남지역")
    kb12, gn12 = chg(W(f"sale:{kb}"), 12), chg(W(f"sale:{gn}"), 12)
    gang = by_name["seoul"].get("강남구")
    gw = wk_chg(W(f"sale:{gang}")) if gang else []
    rs = M("rentIdx:seoul")
    rs_y = yoy(last(rs), dict(rs).get(mshift(rs[-1][0], -12))) if rs else None
    mt = E("mortgage")
    mch = mt[-1][1] - mt[-13][1] if len(mt) > 12 else None
    L = []
    L.append(("서울", f"강북·강남 3개월: 강북 {pct(kb12, 1)} · 강남 {pct(gn12, 1)}" + (f". 강남구는 {streak(gw, False)}주 연속 하락" if streak(gw, False) >= 2 else f". 강남구는 {streak(gw, True)}주 연속 상승" if streak(gw, True) >= 2 else "") + "."))
    if has(rs_y):
        jy = chg(W(f"jeonse:{CITY['seoul']['code']}"), 52)
        rm = last(M("rentMed:seoul"))
        L.append(("서울", f"월세 1년 {pct(rs_y, 1)}" + (f", 중위 월세 {num(rm / 10)}만 원" if has(rm) else "") + f". 전세 1년 {pct(jy, 1)}."))
    ub, us = last(E("unsold.busan")), last(E("unsold.seoul"))
    hb, hs = last(E("houses.busan")), last(E("houses.seoul"))
    if has(ub) and has(hb):
        L.append(("부산", f"미분양 {num(ub)}호, 주택의 {ub / (hb * 1000) * 100:.2f}%" + (f"(서울 {us / (hs * 1000) * 100:.2f}%)" if has(us) and has(hs) else "") + f". 1년 전보다 {pct(signals('busan')['uch'], 1)}."))
    if mt:
        L.append(("공통", f"주담대 금리 {mt[-1][1]:.2f}%" + (f", 1년 {'+' if mch >= 0 else '−'}{abs(mch):.2f}%p" if has(mch) else "") + f" ({ym(mt[-1][0])})."))
    items = "".join(f'<tr><td style="padding:5px 8px 5px 0;vertical-align:top;white-space:nowrap;font-size:12px;font-weight:800;color:{CITY_COL.get({"서울": "seoul", "부산": "busan"}.get(t, ""), INK2)};{P}">{t}</td>'
                    f'<td style="padding:5px 0;font-size:13.5px;color:{INK2};line-height:1.55;{P}">{esc(x)}</td></tr>' for t, x in L)
    news = ""
    for k, title in (("seoul", "서울 뉴스"), ("busan", "부산 뉴스"), ("policy", "정책 뉴스")):
        it = (D.get("news") or {}).get(k) or []
        if it:
            news += f'<div style="font-size:13px;font-weight:800;color:{INK};margin:10px 0 2px">{title}</div>' + "".join(
                f'<div style="font-size:13.5px;line-height:1.5;margin:3px 0"><a href="{esc(i["u"])}" style="color:{INK};text-decoration:none">{esc(i["t"])}</a> '
                f'<span style="color:{INK3};font-size:12px">{esc(i.get("s", ""))} · {esc(i.get("d", ""))}</span></div>' for i in it[:3])
    return f"""
<tr><td style="padding:0 0 14px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SURF};border:1px solid #e3e0d8;border-radius:14px">
<tr><td style="padding:16px 18px;{P}"><div style="font-size:16px;font-weight:800;color:{INK};margin-bottom:4px">이번 주 이슈</div>
<table role="presentation" cellpadding="0" cellspacing="0">{items}</table>{news}
<div style="font-size:11.5px;color:{INK3};margin-top:8px">뉴스는 구글 뉴스 최근 7일, 사건·사고 기사는 거름.</div></td></tr></table></td></tr>"""


def schedule_block():
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    dn = "월화수목금토일"
    d = now.date() + dt.timedelta(days=(3 - now.weekday()) % 7 or 7)
    items = [("다음 주간 가격동향(한국부동산원)", f"{d.month}/{d.day}({dn[d.weekday()]})")]
    for e in sorted(D["meta"].get("events") or [], key=lambda e: e["date"]):
        if e["date"] >= now.date().isoformat():
            ed = dt.date.fromisoformat(e["date"])
            items.append((e["name"], f"{ed.month}/{ed.day}({dn[ed.weekday()]})"))
    return " · ".join(f"{esc(n)} <b>{w}</b>" for n, w in items)


s, b = W(f"sale:{CITY['seoul']['code']}"), W(f"sale:{CITY['busan']['code']}")
ws, wb = trend_word(chg(s, 12))[0], trend_word(chg(b, 12))[0]
subject = f"부동산 주간 요약 {wk_lab} · 서울 {ws}(이번 주 {pct(chg(s, 1))}) · 부산 {wb}(이번 주 {pct(chg(b, 1))})"
body = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(subject)}</title></head>
<body style="margin:0;padding:0;background:{BG}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;color:{INK};{P}">
<tr><td style="padding:0 4px 14px;{P}">
  <div style="font-size:12px;font-weight:700;letter-spacing:1px;color:{INK3}">서울 · 부산 아파트 시장</div>
  <div style="font-size:24px;font-weight:800;letter-spacing:-0.5px">부동산 시장 주간 요약</div>
  <div style="font-size:13px;color:{INK2};margin-top:2px">{wk_lab} 기준(한국부동산원 주간, 목요일 발표) · 큰 글자는 최근 3개월 변동으로 정함
  {f'· <a href="{esc(URL)}" style="color:#2b4a7a">대시보드 열기</a>' if URL else ''}</div>
</td></tr>
{city_block("seoul")}
{city_block("busan")}
{korea_block()}
{issues_block()}
<tr><td style="padding:2px 4px 6px;font-size:13px;color:{INK2};line-height:1.7;{P}">다가오는 일정: {schedule_block()}</td></tr>
<tr><td style="padding:6px 4px 0;font-size:11.5px;color:{INK3};line-height:1.6;{P}">자료: 한국부동산원 R-ONE, 한국은행 ECOS, 구글 뉴스. 지도: {esc((G or {}).get("src", ""))}.
"1년 새 약 얼마"는 중위 매매가에 1년 지수 변동률을 곱한 어림값입니다. 매주 한 번(목요일 발표가 반영된 첫 실행) 보내는 메일입니다.</td></tr>
</table></td></tr></table></body></html>"""
OUTDIR.mkdir(parents=True, exist_ok=True)
(OUTDIR / "email-summary.html").write_text(body, encoding="utf-8")
(OUTDIR / "email-subject.txt").write_text(subject, encoding="utf-8")
print("제목:", subject)
print("본문", len(body), "bytes")
