"""뉴스 이슈 흐름의 지난 주들을 채운다(내 PC 에서 한 번 실행). news-history.json 을 새로 쓴다.

    python tools/news-backfill.py [주 수, 기본 config 의 news.weeks]

- 구글 뉴스 RSS 의 지난 주 검색(after:/before:)은 GitHub 실행 환경에서 503 으로 막힌다(2026-11-16 확인). 그래서 처음 몇 주는
  이 스크립트로 채우고, 그 뒤로는 Update-RealEstateDashboard.ps1 이 최근 7일 기사(when:7d)를 하루 두 번 받아 주마다 더한다.
- 세는 방식은 PS1 과 같다: 시장 낱말(keep)이 있는 제목만, 사건·사고(drop)는 빼고, 앞 14글자가 같은 제목은 한 번, 주제 낱말로 주제별 수.
  제목 지문(ids)은 PS1 이 이어서 더할 이번 주·지난주에만 남긴다(같은 계산: 앞 14글자 → SHA-1 앞 4바이트).
- 지난 주 검색은 주마다 검색어당 30~100건을 준다. 최근 주(실행 중 더해지는 주)와 세는 표본이 조금 다르니 비율만 비교한다.
"""
import datetime as dt
import email.utils
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))["news"]
WEEKS = int(sys.argv[1]) if len(sys.argv) > 1 else int(CFG["weeks"])
KST = dt.timezone(dt.timedelta(hours=9))
KEEP, DROP = re.compile(CFG["keep"]), re.compile(CFG["drop"])
TOPICS = [(t["key"], re.compile(t["kw"])) for t in CFG["topics"]]
ISSUE = [t["key"] for t in CFG["topics"] if not t.get("mood")]
GROUPS = list(CFG["groups"])


def tid(t):
    k = re.sub(r"\W", "", t)[:14]
    return hashlib.sha1(k.encode("utf-8")).hexdigest()[:8]


def fetch(q):
    u = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
    for attempt in range(3):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "realestate-dashboard/1.0 (+https://github.com/JHKim0603/realestate-dashboard)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                root = ET.fromstring(r.read())
            break
        except Exception as e:
            if attempt == 2:
                print("실패", q, e)
                return []
            time.sleep(3 * (attempt + 1))
    out = []
    for it in root.findall("./channel/item"):
        t, src = (it.findtext("title") or "").strip(), (it.findtext("source") or "").strip()
        while src and t.endswith(" - " + src):   # 언론사 이름이 두 번 붙은 제목도 있다
            t = t[: -len(src) - 3].strip()
        if not t or not KEEP.search(t) or DROP.search(t):
            continue
        try:
            when = email.utils.parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception:
            continue
        out.append({"t": t, "s": src, "u": it.findtext("link") or "", "when": when, "id": tid(t), "tp": [k for k, rx in TOPICS if rx.search(t)]})
    return out


now = dt.datetime.now(KST)
monday = (now - dt.timedelta(days=now.weekday())).date()
cur, prev = monday.isoformat(), (monday - dt.timedelta(days=7)).isoformat()
weeks = {}
for i in range(WEEKS - 1, -1, -1):
    a = monday - dt.timedelta(days=7 * i)
    b = a + dt.timedelta(days=7)
    rec = {}
    for g in GROUPS:
        seen, lst = set(), []
        for q in CFG["groups"][g]["queries"]:
            for x in fetch(f"{q} after:{a} before:{b}"):
                if x["id"] not in seen:
                    seen.add(x["id"]); lst.append(x)
            time.sleep(0.6)
        top = [x for x in lst if any(k in ISSUE for k in x["tp"])][:3] or lst[:3]
        r = {"n": len(lst), "tp": {k: sum(1 for x in lst if k in x["tp"]) for k, _ in TOPICS},
             "top": [{"t": x["t"], "s": x["s"], "u": x["u"], "d": f"{x['when'].month}/{x['when'].day}"} for x in top]}
        if a.isoformat() in (cur, prev):
            r["ids"] = sorted(seen)
        rec[g] = r
    weeks[a.isoformat()] = rec
    print(a, {g: rec[g]["n"] for g in GROUPS})

items = {}
for g in GROUPS:
    seen, lst = set(), []
    for q in CFG["groups"][g]["queries"]:
        for x in fetch(f"{q} when:7d"):
            if x["id"] not in seen:
                seen.add(x["id"]); lst.append(x)
        time.sleep(0.6)
    lst.sort(key=lambda x: x["when"], reverse=True)
    items[g] = [{"t": x["t"], "s": x["s"], "d": f"{x['when'].month}/{x['when'].day}", "u": x["u"], "tp": x["tp"]} for x in lst[: int(CFG["perGroup"])]]

dump = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":"))
text = ('{\n  "items": {\n' + ",\n".join(f'    {dump(g)}: {dump(items[g])}' for g in GROUPS) + '\n  },\n  "weeks": {\n'
        + ",\n".join(f'    {dump(k)}: {dump(weeks[k])}' for k in sorted(weeks)) + "\n  }\n}\n")
(ROOT / "news-history.json").write_text(text, encoding="utf-8", newline="\n")
print("news-history.json", len(text), "bytes")
