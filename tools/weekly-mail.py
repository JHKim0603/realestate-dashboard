"""부동산 시장 Dashboard 주간 메일을 만든다: 본문(email-summary.html), 제목(email-subject.txt), 그림(mail-charts/*.png).

    python3 tools/weekly-mail.py [dashboard.html] [출력 폴더]

- 자료는 Update-RealEstateDashboard.ps1 이 만든 dashboard.html 안의 JSON 두 개(id="data", id="geo")를 그대로 읽는다.
  계산 방식은 template.html 의 화면과 같다(연속 주, 시장 온도, 신호 5개 등). 큰 글자(국면)와 근거 문장, 제목의 판정은
  화면이 계산해 페이지에 남긴 요약(<script id="summary">)을 그대로 쓴다.
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

# 윈도 콘솔(CP949)은 제목의 '−' 같은 글자를 못 찍어 미리보기가 끝에서 멈췄다. 화면 출력만 대체 문자로 바꾼다(파일은 UTF-8 그대로).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
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


# 기간 변동률(3개월·1년): 10% 이상이면 정수, 그 밖은 소수 첫째 자리(화면의 pctL 과 같음). 주간 변동률은 pct(x) 로 둘째 자리.
dg_l = lambda x: 0 if has(x) and abs(x) >= 9.95 else 1
pct_l = lambda x: pct(x, dg_l(x))
cls_l = lambda x: cls(x, dg_l(x))
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
        return f"{a / 1e8:.1f}".removesuffix(".0") + "억 원"
    if a >= 1e4:
        unit = 100 if a >= 1e7 else 10
        return f"{round(a / 1e4 / unit) * unit:,.0f}만 원"
    return f"{a:,.0f}원"


def tw(s, f=12):
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
        return "거의 제자리", ("소폭 상승" if up else "소폭 하락"), ("up" if up else "down")
    if a < 1:
        return ("조금씩 오르는 중" if up else "조금씩 내리는 중"), "", ("up" if up else "down")
    if a < 3:
        return ("오르는 중" if up else "내리는 중"), "", ("up" if up else "down")
    return ("빠르게 오르는 중" if up else "빠르게 내리는 중"), "", ("up" if up else "down")


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
        ("집값 " + ("상승" if has(s12) and s12 > 0.1 else "하락" if has(s12) and s12 < -0.1 else "보합"), lvl(s12, 0.1), lvl(s12, 0.1)),
        ("전세 " + ("상승" if has(j12) and j12 > 0.1 else "하락" if has(j12) and j12 < -0.1 else "보합"), lvl(j12, 0.1), lvl(j12, 0.1)),
        ("거래 " + ("증가" if has(trch) and trch > 5 else "감소" if has(trch) and trch < -5 else "비슷"), lvl(trch, 5), lvl(trch, 5)),
        ("미분양 " + ("증가" if has(uch) and uch > 5 else "감소" if has(uch) and uch < -5 else "비슷"), -lvl(uch, 5), lvl(uch, 5)),
        (("매수 우위" if buy >= 100 else "매도 우위") if has(buy) else "매수심리 –", (1 if buy >= 100 else -1) if has(buy) else 0, (1 if buy >= 100 else -1) if has(buy) else 0)]}


# ---- 그림(SVG → 크롬 → PNG) ---------------------------------------------------------------------
def text(x, y, s, size=12, color=INK2, weight=500, anchor="start", extra=""):
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}"{extra}>{esc(s)}</text>'


def hero_range():
    """두 도시 1년 흐름 그림의 같은 눈금(화면 heroChart 와 같음)."""
    lo = hi = 0.0
    for c in CITY:
        s = W(f"sale:{CITY[c]['code']}")
        if len(s) >= 53:
            base = s[-53][1]
            for _, v in s[-53:]:
                x = (v / base - 1) * 100
                lo, hi = min(lo, x), max(hi, x)
    return lo, hi


def nice_step(raw, n):
    pw = 10 ** math.floor(math.log10(raw / n))
    x = raw / n / pw
    return (1 if x <= 1 else 2 if x <= 2 else 2.5 if x <= 2.5 else 5 if x <= 5 else 10) * pw


def sgn_p(v):
    return "0%" if v == 0 else ("+" if v > 0 else "−") + f"{abs(round(v, 2)):g}%"


def hero_svg(city):
    s = W(f"sale:{CITY[city]['code']}")
    if len(s) < 53:
        return None
    base = s[-53][1]
    pts = [(i, (v / base - 1) * 100) for i, (_, v) in enumerate(s[-53:])]
    vs = [v for _, v in pts]
    Wd, H, PL, PR, PT, PB = 600, 176, 46, 92, 16, 24
    rlo, rhi = hero_range()
    step = nice_step((rhi - rlo) or 1, 3)
    lo, hi = math.floor(rlo / step + 1e-9) * step, math.ceil(rhi / step - 1e-9) * step
    if hi == lo:
        hi = lo + step
    X = lambda i: PL + i / 52 * (Wd - PL - PR)
    Y = lambda v: PT + (hi - v) / (hi - lo) * (H - PT - PB)
    end, s12, i3, col = vs[-1], chg(s, 12), 40, CITY_COL[city]
    path = lambda a: "M" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in a)
    y0 = Y(0)
    g = (f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
         f'<stop offset="0" stop-color="{col}" stop-opacity=".18"/><stop offset="1" stop-color="{col}" stop-opacity=".02"/></linearGradient></defs>')
    g += f'<rect width="{Wd}" height="{H}" fill="{SURF}"/>'
    v = lo
    while v <= hi + step / 1e6:
        vv = 0 if abs(v) < step / 1e6 else v
        g += (f'<line x1="{PL}" x2="{Wd - PR}" y1="{Y(vv):.1f}" y2="{Y(vv):.1f}" stroke="{INK3 if vv == 0 else GRID}"'
              + (' stroke-dasharray="4 4"' if vv == 0 else "") + "/>")
        g += text(PL - 6, Y(vv) + 4, sgn_p(vv), 12, INK3, 500, "end")
        v += step
    g += f'<line x1="{X(i3):.1f}" x2="{X(i3):.1f}" y1="{PT - 6}" y2="{H - PB}" stroke="{GRID}"/>'
    g += text(X(i3), H - 7, "3개월 전", 12, INK3, 500, "middle") + text(PL, H - 7, "1년 전", 12, INK3) + text(X(52), H - 7, "지금", 12, INK3, 500, "end")
    g += f'<path d="{path(pts)} L{X(52):.1f},{y0:.1f} L{X(0):.1f},{y0:.1f} Z" fill="url(#g)"/>'
    g += f'<path d="{path(pts[:i3 + 1])}" fill="none" stroke="{col}" stroke-width="2.2" stroke-opacity=".55" stroke-linejoin="round"/>'
    g += f'<path d="{path(pts[i3:])}" fill="none" stroke="{col}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>'
    ly = max(PT + 2, min(Y(v) for _, v in pts[i3:]) - 9)
    g += text((X(i3) + X(52)) / 2, ly, f"최근 3개월 {pct_l(s12)}", 12, INK2, 750, "middle",
              f' paint-order="stroke" stroke="{SURF}" stroke-width="3"')
    g += f'<circle cx="{X(52):.1f}" cy="{Y(end):.1f}" r="5.5" fill="{col}" stroke="{SURF}" stroke-width="2.5"/>'
    g += (f'<text x="{X(52) + 9:.1f}" y="{Y(end) + 6:.1f}" font-size="17" font-weight="800" fill="{INK}">'
          f'<tspan font-size="12" font-weight="600" fill="{INK3}">1년 </tspan>{esc(pct_l(end))}</text>')
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
        w = tw(nm, 12) + tw(vt, 12) + 18
        x0 = a["call"][0] * k - (w / 2 if a["call"][2] == "middle" else w if a["call"][2] == "end" else 0)
        x0, y = max(1, min(Wd - w - 1, x0)), max(11, min(H - 11, a["call"][1] * k))
        if not put(x0, y - 11, x0 + w, y + 11):
            continue
        ex, ey = max(x0, min(x0 + w, cx)), max(y - 10, min(y + 10, cy))
        big = hi.get(a["code"])
        labs += f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{INK3}"/><circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.3" fill="{INK}"/>'
        labs += f'<rect x="{x0:.1f}" y="{y - 10:.1f}" width="{w:.1f}" height="20" rx="10" fill="#fff" stroke="{big or "#e3e0d8"}" stroke-width="{1.6 if big else 1}"/>'
        labs += (f'<text x="{x0 + 8:.1f}" y="{y + 4:.1f}" font-size="12" font-weight="800" fill="{big or INK}">{esc(nm)}'
                 f'<tspan dx="5" font-weight="750" fill="{COLOR[cls(r["v"], 1)] if cls(r["v"], 1) != "flat" else INK3}">{esc(vt)}</tspan></text>')
    for r in sorted([r for r in rows if not r["a"].get("call")], key=lambda r: -r["a"]["r"]):
        a, nm, vt = r["a"], short(r["nm"]), pct(r["v"], 1)
        cx, cy, rho = a["lx"] * k, a["ly"] * k, a["r"] * k
        bw, w1 = max(tw(nm, 12), tw(vt, 12)), tw(nm, 12)
        done = False
        if rho >= 11 and bw / 2 <= rho * 1.75:
            for ox, oy in ((0, 0), (0.45, 0), (-0.45, 0), (0, 0.4), (0, -0.4)):
                x, y = cx + ox * rho, cy + oy * rho
                if put(x - bw / 2, y - 10, x + bw / 2, y + 13):
                    labs += text(x, y - 1, nm, 12, INK, 750, "middle") + text(x, y + 12, vt, 12, INK2, 650, "middle")
                    done = True
                    break
        if not done and rho >= 6 and w1 / 2 <= rho * 2.1:
            for ox, oy in ((0, 0), (0.45, 0), (-0.45, 0), (0, 0.4), (0, -0.4)):
                x, y = cx + ox * rho, cy + oy * rho
                if put(x - w1 / 2, y - 6, x + w1 / 2, y + 6):
                    labs += text(x, y + 4, nm, 12, INK, 750, "middle")
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
CHROME_ARGS = ["--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars", "--virtual-time-budget=8000"]


def dump_dom(url, width=1280):
    r = subprocess.run([chrome, *CHROME_ARGS, f"--window-size={width},1600", "--dump-dom", url],
                       capture_output=True, timeout=120)
    return r.stdout.decode("utf-8", "replace")


def page_shot(name):
    """대시보드를 #mailshot-이름 으로 열면 그 그림만 폭 600 으로 그려지고, 제목에 높이(H=)를 적는다. 그 높이로 찍는다."""
    url = SRC.resolve().as_uri() + "#mailshot-" + name
    m = re.search(r"<title>H=(\d+)</title>", dump_dom(url, 600))
    if not m:
        return False
    out = CHARTS / f"{name}.png"
    if out.exists():
        out.unlink()
    subprocess.run([chrome, *CHROME_ARGS, "--force-device-scale-factor=2", f"--window-size=600,{int(m.group(1))}", f"--screenshot={out}", url],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
    return out.exists() and out.stat().st_size > 2000


SUM = {}
if chrome:
    CHARTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for ch in charts:
            try:
                if shoot(chrome, ch, tmp):
                    made.add(ch["file"])
            except Exception as e:  # 그림 하나가 실패해도 메일은 나간다
                print("그림 실패", ch["file"], e)
    try:
        m = re.search(r'<script type="application/json" id="summary">(.*?)</script>', dump_dom(SRC.resolve().as_uri()), re.S)
        SUM = json.loads(m.group(1)) if m else {}
    except Exception as e:
        print("요약 읽기 실패", e)
    for name in ("cycle", "timeline-seoul", "timeline-busan"):
        try:
            if page_shot(name):
                made.add(f"{name}.png")
        except Exception as e:
            print("화면 그림 실패", name, e)
print("그림", sorted(made), "크롬", bool(chrome), "요약", sorted(SUM))


def img(file, w, alt):
    if file not in made:
        return ""
    return f'<img src="cid:{file}" width="{w}" alt="{esc(alt)}" style="display:block;width:100%;max-width:{w}px;height:auto;border:0;margin:6px 0 2px">'


P = f"font-family:{MFONT};"
# 공통 규칙 7: 상자는 흰 바탕, 1px #e1e0d9 테두리, 둥근 모서리 8px, 안쪽 여백 13px 15px. 상태는 왼쪽 4px 띠의 색으로만.
BOX = "background:#ffffff;border:1px solid #e1e0d9;border-radius:8px"
span = lambda s, c, w=700: f'<span style="color:{c};font-weight:{w}">{s}</span>'
colored = lambda x, d=2: span(esc(pct(x, d)), COLOR[cls(x, d)] if cls(x, d) != "flat" else INK3)
colored_l = lambda x: colored(x, dg_l(x))
DIR_BAR = {"up": RISE, "down": FALL, "flat": "#e1e0d9"}
WARN = "#c07812"


def sec(title):
    """구역 제목: 상자 밖에 12px 굵게, 회색, 글자 간격 0.6px, 위 여백 22px(공통 규칙 7)."""
    return f'<tr><td style="padding:22px 2px 7px;font-size:12px;font-weight:700;color:#6e6c66;letter-spacing:0.6px;{P}">{esc(title)}</td></tr>'


def card(inner, bar=None):
    left = f";border-left:4px solid {bar}" if bar else ""
    return (f'<tr><td style="padding:0 0 10px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="{BOX}{left}"><tr><td style="padding:13px 15px;{P}">{inner}</td></tr></table></td></tr>')


def city_block(c):
    code, nm = CITY[c]["code"], CITY[c]["nm"]
    s = W(f"sale:{code}")
    wk = wk_chg(s)
    s1, s12, s52 = chg(s, 1), chg(s, 12), chg(s, 52)
    # 국면(큰 글자)과 문장은 '흐름 정리'에 있어 여기서는 되풀이하지 않는다. 상자 왼쪽 띠 색만 국면의 방향을 따른다.
    d = ((SUM.get("cities") or {}).get(c) or {}).get("dir") or trend_word(s12)[2]
    med, medm = last(M(f"median:{c}")), last_key(M(f"median:{c}"))
    money = ""
    if has(med) and has(s52):
        P_ = med * 1000
        delta = P_ * (s52 / 100) / (1 + s52 / 100)
        dd = cls_l(s52)
        money = (f"중위 가격 아파트({int(medm[5:7])}월 약 {won(P_)})로 환산하면 "
                 + ("<b>1년 동안 가격 변화가 거의 없습니다</b>." if dd == "flat" else f"<b>1년 동안 약 {won(delta)} {'오른' if dd == 'up' else '내린'} 셈</b>입니다."))
    sg = signals(c)
    n_up, n_dn = sum(1 for x in sg["list"] if x[1] > 0), sum(1 for x in sg["list"] if x[1] < 0)
    sig = ", ".join(span(f"{'▲' if x[2] > 0 else '▼' if x[2] < 0 else '–'} {esc(x[0])}", RISE if x[1] > 0 else FALL if x[1] < 0 else INK3, 650) for x in sg["list"])
    hn = heat_now(c)
    rows = [(n, chg(W(f"sale:{cd}"), 4)) for n, cd, _ in DIST[c]]
    rows = sorted([r for r in rows if has(r[1])], key=lambda r: -r[1])
    top3 = ", ".join(f"{esc(n)} {colored(v, 1)}" for n, v in rows[:3] if round(v, 1) > 0) or "없음"
    bot3 = ", ".join(f"{esc(n)} {colored(v, 1)}" for n, v in rows[::-1][:3] if round(v, 1) < 0) or "없음"
    n_r, n_d = sum(1 for _, v in rows if round(v, 1) > 0), sum(1 for _, v in rows if round(v, 1) < 0)
    unit = "구·군" if c == "busan" else "구"
    cell = lambda k, v, dg: (f'<td style="padding:8px 10px;background:{RAISED};border:1px solid #e1e0d9;border-radius:8px;{P}">'
                             f'<div style="font-size:12px;color:{INK3}">{k}</div><div style="font-size:19px;font-weight:800">{colored(v, dg)}</div></td>')
    heat = f' <span style="color:{INK3};font-weight:600">(시장 온도 {hn}, {heat_label(hn)})</span>' if has(hn) else ""
    inner = f"""
  <div style="font-size:13px;font-weight:800;color:{CITY_COL[c]}">{nm} 아파트{heat}</div>
  {img(f"hero-{c}.png", 600, f"{nm} 집값 1년 흐름")}
  <table role="presentation" width="100%" cellpadding="0" cellspacing="6" style="margin-top:2px"><tr>{cell("이번 주", s1, 2)}{cell("3개월", s12, dg_l(s12))}{cell("1년", s52, dg_l(s52))}</tr></table>
  <div style="font-size:14px;color:{INK2};line-height:1.6;margin-top:4px">{money}</div>
  <div style="font-size:13px;line-height:1.7;margin-top:6px">{sig}<br><span style="color:{INK3};font-size:12px">빨강은 집값을 올리는 요인, 파랑은 내리는 요인입니다(▲▼는 지표의 방향). 상승 요인 {n_up}개, 하락 요인 {n_dn}개입니다.</span></div>
  <div style="border-top:1px dashed {GRID};margin-top:10px;padding-top:8px;font-size:13.5px;color:{INK2};line-height:1.65">
    <b style="color:{INK}">최근 4주 변동률로 보면</b> 상승 {n_r}곳, 보합 {len(rows) - n_r - n_d}곳, 하락 {n_d}곳입니다.<br>많이 오른 {unit}: {top3}<br>많이 내린 {unit}: {bot3}
    {img(f"map-{c}.png", 600, f"{nm} 구별 최근 4주 변동 지도")}
    <div style="font-size:12px;color:{INK3};margin-top:2px">지도 색은 진할수록 변동이 큽니다(빨강은 상승, 파랑은 하락, 4주 변동률 ±0.2%, ±0.4%, ±0.8% 구간).</div>
  </div>"""
    return card(inner, DIR_BAR[d])


def korea_block():
    rows = sorted([(p["name"], p["cls"], chg(W(f"sale:{p['cls']}"), 4)) for p in PROV.values()], key=lambda r: -(r[2] if has(r[2]) else -99))
    rows = [r for r in rows if has(r[2])]
    if not rows:
        return ""
    up, dn = sum(1 for r in rows if round(r[2], 1) > 0), sum(1 for r in rows if round(r[2], 1) < 0)
    fl = len(rows) - up - dn
    pos = lambda code: next((i + 1 for i, r in enumerate(rows) if r[1] == code), "–")
    sv = next((r[2] for r in rows if r[1] == CITY["seoul"]["code"]), None)
    bv = next((r[2] for r in rows if r[1] == CITY["busan"]["code"]), None)
    rank = ", ".join(f"{i + 1} {esc(n)} {colored(v, 1)}" for i, (n, _, v) in enumerate(rows))
    inner = (f'<div style="font-size:14px;color:{INK2};line-height:1.65">17개 시·도 중 <b style="color:{INK}">{up}곳이 오르고 {dn}곳이 내렸습니다</b>{f"(보합 {fl}곳)" if fl else ""}. '
             f'{span("서울", CITY_COL["seoul"], 800)} {colored(sv, 1)}({pos(CITY["seoul"]["code"])}위), {span("부산", CITY_COL["busan"], 800)} {colored(bv, 1)}({pos(CITY["busan"]["code"])}위), '
             f'전국 {colored(chg(W(f"sale:{NAT}"), 4), 1)}입니다.</div>'
             f'{img("map-korea.png", 520, "전국 시·도 최근 4주 변동 지도")}'
             f'<div style="font-size:12.5px;color:{INK2};line-height:1.8;margin-top:6px">순위: {rank}</div>')
    return sec("전국에서 보면(최근 4주)") + card(inner)


def bullets(L):
    return '<table role="presentation" cellpadding="0" cellspacing="0" width="100%">' + "".join(
        f'<tr><td style="padding:5px 10px 5px 0;vertical-align:top;white-space:nowrap;width:66px;{P}">' + (f'<span style="display:inline-block;font-size:12px;font-weight:800;'
        f'color:{INK3};background:#efede8;border-radius:5px;padding:1px 6px">{esc(k)}</span>' if k else "") + '</td>'
        f'<td style="padding:5px 0;font-size:13.5px;color:{INK2};line-height:1.6;{P}">{v}</td></tr>' for k, v in L) + "</table>"


def mail_b(L):
    """화면 글의 <b class="up|down">을 메일 앱이 읽는 인라인 색으로 바꾼다(메일에는 화면의 CSS 가 없다)."""
    cmap = {"up": RISE, "down": FALL}
    return [(k, re.sub(r'<b class="(\w*)">', lambda m: f'<b style="color:{cmap[m.group(1)]}">' if m.group(1) in cmap else "<b>", v)) for k, v in L]


def brief_block():
    """대시보드 맨 위 카드의 국면·문장과 '판단 근거'의 문장(화면이 계산해 페이지에 남긴 요약)."""
    if not SUM.get("cities"):
        return ""
    out = sec("흐름 정리")
    for c in ("seoul", "busan"):
        x = SUM["cities"].get(c)
        if not x:
            continue
        d = x.get("dir")
        col = COLOR.get(d, INK) if d != "flat" else INK
        # 화면 맨 위 카드와 같은 순서: 국면 → 결론 문장 → 근거 한 줄 → 지난주와 비교 → 눈여겨볼 점 → 판단 근거(2026-11-28).
        # 결론 문장이 없는 예전 요약이면 예전처럼 run·long 문장을 쓴다.
        con = x.get("con") or ""
        ev = x.get("ev") or f'{esc(x.get("run", ""))} {x.get("long", "")}'
        # 같은 묶음의 둘째 줄부터는 꼬리표를 비운다(줄마다 '지난주'가 되풀이되면 기계적으로 읽힘).
        notes = [("지난주" if i == 0 else "", v) for i, v in enumerate(x.get("wow") or [])] + [("눈여겨볼" if i == 0 else "", v) for i, v in enumerate(x.get("watch") or [])]
        out += card(f'<div style="font-size:13px;font-weight:800;color:{CITY_COL[c]}">{esc(x["name"])} 아파트</div>'
                    f'<div style="font-size:22px;font-weight:800;color:{col};letter-spacing:-0.4px;margin-top:2px">{esc(x["word"])}</div>'
                    + (f'<div style="font-size:14.5px;font-weight:700;color:{INK};line-height:1.55;margin-top:4px">{con}</div>' if con else "")
                    + f'<div style="font-size:13px;color:{INK3 if con else INK2};line-height:1.6;margin:2px 0 6px">{ev}</div>{bullets(mail_b(notes + x["bullets"]))}', DIR_BAR.get(d))
    if SUM.get("common"):
        out += sec("전국과 금리") + card(bullets(SUM["common"]))
    return out


def trend_block():
    turns = SUM.get("turns") or []
    if "cycle.png" not in made and not turns:
        return ""
    stc = {"상승": RISE, "하락": FALL, "보합": INK3}
    fresh = f' <span style="color:{WARN}">확인 중</span>'
    # 날짜는 화면 요약에 이미 '11/2주' 꼴로 들어 있다(예전에는 여기서 ' 주'를 또 붙여 '11/2주 주'가 됐음).
    rows = "".join(f'<tr><td style="padding:3px 8px 3px 0;font-size:12px;color:{INK3};white-space:nowrap;{P}">{esc(t["date"])}</td>'
                   f'<td style="padding:3px 8px 3px 0;font-size:12px;font-weight:800;color:{CITY_COL.get(t["sc"], INK2)};white-space:nowrap;{P}">{ {"seoul": "서울", "busan": "부산"}.get(t["sc"], "시·도") }</td>'
                   f'<td style="padding:3px 8px 3px 0;font-size:13px;color:{INK};{P}">{esc(t["names"])}</td>'
                   f'<td style="padding:3px 0;font-size:12.5px;font-weight:750;white-space:nowrap;{P}"><span style="color:{stc.get(t["from"], INK3)}">{esc(t["from"])}</span> → '
                   f'<span style="color:{stc.get(t["to"], INK3)}">{esc(t["to"])}</span>{fresh if t.get("fresh") else ""}</td></tr>' for t in turns)
    # 시계 읽는 법은 그림 아래에 짧게 적는다. 그림을 못 만든 날은 도시별 국면 문장을 글로 적는다.
    cap = (f'<div style="font-size:12px;color:{INK3};line-height:1.6;margin-top:2px">시계는 위가 상승, 아래가 하락입니다. 왼쪽은 그 폭이 커지는 중, '
           f'오른쪽은 줄어드는 중입니다. 큰 점이 지금 위치이고, 흐린 점은 4주 간격으로 6개월 전까지의 위치입니다. 아래 그래프는 최근 1년 주간 변동률의 4주 평균입니다.</div>')
    inner = (img("cycle.png", 600, "서울·부산 시장 시계와 주간 변동률 4주 평균") + cap) if "cycle.png" in made else "".join(
        f'<div style="font-size:13.5px;color:{INK2};line-height:1.6;margin-bottom:4px">{esc(x["name"])} {esc(x.get("word", ""))}: {esc(re.sub("<[^>]+>", "", x.get("long", "")))}</div>'
        for x in (SUM.get("cities") or {}).values())
    if turns:
        inner += (f'<div style="font-size:14px;font-weight:800;color:{INK};margin:10px 0 4px">최근 3개월 추세 전환</div><table role="presentation" cellpadding="0" cellspacing="0">{rows}</table>'
                  f'<div style="font-size:12px;color:{INK3};margin-top:4px">4주 평균 주간 변동률로 본 상승·보합·하락 상태가 바뀌어 3주 이상 이어진 곳입니다. 보합은 ±0.01% 이내이고, 확인 중은 아직 2주째인 곳입니다.</div>')
    return sec("국면과 흐름") + card(inner)


def issue_news_block():
    iss = SUM.get("issues") or {}
    items = ((D.get("news") or {}).get("items")) or {}
    if not iss and not items:
        return ""
    body = ""
    for i_g, (g, title) in enumerate((("seoul", "서울"), ("busan", "부산"), ("nation", "전국·정책"))):
        x = iss.get(g)
        col = CITY_COL.get(g, INK)
        body += f'<div style="font-size:14px;font-weight:800;color:{col};margin:{0 if i_g == 0 else 14}px 0 2px">{title}</div>'
        if x:
            body += f'<div style="font-size:13.5px;color:{INK2};line-height:1.6">{esc(x["line"])}</div>'
        if g in ("seoul", "busan"):
            body += img(f"timeline-{g}.png", 600, f"{title} 주간 변동률과 주별 이슈")
        for i in (items.get(g) or [])[:3]:
            t_ = i["t"]
            while i.get("s") and t_.endswith(" - " + i["s"]):
                t_ = t_[: -len(i["s"]) - 3].strip()
            body += (f'<div style="font-size:13.5px;line-height:1.5;margin:4px 0"><a href="{esc(i["u"])}" style="color:{INK};text-decoration:none">{esc(t_)}</a> '
                     f'<span style="color:{INK3};font-size:12px">{esc(i.get("s", ""))} · {esc(i.get("d", ""))}</span></div>')
    body += (f'<div style="font-size:12px;color:{INK3};margin-top:8px;line-height:1.6">구글 뉴스에서 서울, 부산, 전국 정책 기사를 검색했고 사건·사고 기사는 뺐습니다. '
             f'주제와 논조는 제목의 단어로 센 대략값입니다. 그림의 위 칸은 주간 변동률이고, 아래 칸은 그 주에 직전 4주 평균보다 가장 많이 늘어난 주제입니다. '
             f'검색어에 \'전세\'가 들어 있어 전세·월세 기사는 어느 주에나 많이 잡힙니다.</div>')
    return sec("요즘 이슈") + card(body)


def schedule_block():
    now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)
    dn = "월화수목금토일"
    d = now.date() + dt.timedelta(days=(3 - now.weekday()) % 7 or 7)
    items = [("주간 가격동향 발표(한국부동산원)", f"{d.month}/{d.day}({dn[d.weekday()]}) 14시")]
    ahead, seen = [], set()
    for e in sorted(D["meta"].get("events") or [], key=lambda e: e["date"]):
        if e["date"] >= now.date().isoformat() and e["name"] not in seen:   # 화면 흐름 정리와 같이 같은 이름은 한 번만
            seen.add(e["name"]); ahead.append(e)
    for e in ahead[:2]:   # 화면과 같이 다가오는 2개만
        ed = dt.date.fromisoformat(e["date"])
        items.append((e["name"], f"{ed.month}/{ed.day}({dn[ed.weekday()]})"))
    return "<br>".join(f"{esc(n)} <b>{w}</b>" for n, w in items)


def status_block():
    """수집에 실패한 자료가 있으면 메일 맨 위에 적는다(공통 규칙 5: 실패를 말없이 빼지 않음)."""
    NM = {"rone.weekly": "한국부동산원 주간", "rone.monthly": "한국부동산원 월간", "ecos": "한국은행", "news": "뉴스"}
    bad = [(k, s) for k, s in (D.get("status") or {}).items() if isinstance(s, dict) and not s.get("ok")]
    if not bad:
        return ""
    lines = "<br>".join(f"{esc(NM.get(k, k))}: {esc(s.get('note') or '이번 실행에서 받지 못했습니다')}" for k, s in bad)
    return card(f'<div style="font-size:13.5px;color:{INK2};line-height:1.6"><b style="color:{INK}">자료 상태</b><br>{lines}</div>', WARN)


NAME = CFG.get("title") or "부동산 시장 Dashboard"
s, b = W(f"sale:{CITY['seoul']['code']}"), W(f"sale:{CITY['busan']['code']}")


def head_of(c, ser):
    """제목의 도시 판정: 화면 요약의 국면과 4주 평균 주간 변동률. 요약을 못 읽은 날만 3개월 변동으로 대신한다."""
    x = (SUM.get("cities") or {}).get(c) or {}
    if x.get("word"):
        return x["word"] + (f"(4주 평균 {x['pace']})" if x.get("pace") else "")
    return f"{trend_word(chg(ser, 12))[0]}(이번 주 {pct(chg(ser, 1))})"


# 공통 규칙 7: 화면 제목, 메일 제목, 메일 머리, 보내는 사람에 같은 이름을 쓴다.
subject = f"{NAME} - {wk_lab}, 서울 {head_of('seoul', s)}, 부산 {head_of('busan', b)}"
link = (f'<a href="{esc(URL)}" style="display:inline-block;margin-top:12px;background:#2b4a7a;color:#ffffff;font-size:13px;font-weight:700;'
        f'text-decoration:none;padding:9px 16px;border-radius:6px">대시보드 열기</a>') if URL else ""
# 메일 앱의 어두운 모드가 색을 멋대로 뒤집지 않게 밝은 화면 전용이라고 알린다(애플 메일 등은 따름. Gmail 앱은 무시할 수 있음).
body = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light only"><meta name="supported-color-schemes" content="light only"><style>:root{{color-scheme:light only;}}</style><title>{esc(subject)}</title></head>
<body style="margin:0;padding:0;background:{BG}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG}"><tr><td align="center" style="padding:20px 10px">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="width:100%;max-width:640px;color:{INK};{P}">
<tr><td style="padding:0 2px 4px;{P}">
  <div style="font-size:22px;font-weight:800;letter-spacing:-0.4px">{esc(NAME)}</div>
  <div style="font-size:12px;color:{INK3};margin-top:3px">{wk_lab} 기준(한국부동산원 주간 통계, 매주 목요일 발표), 서울·부산 아파트 시장</div>
  {link}
</td></tr>
{status_block()}
{brief_block()}
{trend_block()}
{issue_news_block()}
{sec("도시별 상세")}
{city_block("seoul")}
{city_block("busan")}
{korea_block()}
{sec("다가오는 일정")}
{card(f'<div style="font-size:13.5px;color:{INK2};line-height:1.8">{schedule_block()}</div>')}
<tr><td style="padding:10px 2px 0;font-size:12px;color:{INK3};line-height:1.6;{P}">자료: 한국부동산원 R-ONE, 한국은행 ECOS, 구글 뉴스. 지도: {esc((G or {}).get("src", ""))}.
'1년 동안 약 얼마'는 중위 매매가격에 1년 지수 변동률을 적용한 어림값입니다. 매주 목요일 발표가 반영되면 한 번 보내는 메일입니다.</td></tr>
</table></td></tr></table></body></html>"""
OUTDIR.mkdir(parents=True, exist_ok=True)
(OUTDIR / "email-summary.html").write_text(body, encoding="utf-8")
(OUTDIR / "email-subject.txt").write_text(subject, encoding="utf-8")
print("제목:", subject)
print("본문", len(body), "bytes")
