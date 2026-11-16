"""template.html 을 고친 뒤, 배포하기 전에 내 PC 에서 미리 볼 파일을 만든다(인증키·수집 없이).

사용: python tools/preview.py [출력.html] [--data 자료.json] [--news]

- 자료: --data 를 주지 않으면 배포된 페이지(GitHub Pages)에 들어 있는 최신 자료(<script id="data">)를 그대로 쓴다.
- 지도: geo/maps.json. 지역·인구·정책 발표일·일정은 지금 config.json 의 것으로 바꿔 넣는다.
- --news: 자료의 뉴스 부분을 news-history.json 과 config.json 으로 다시 만든다(뉴스 주제·검색어 설정을 고쳤을 때).
  모양은 Update-RealEstateDashboard.ps1 이 만드는 D.news 와 같다.

만든 파일 확인: 밝은·어두운 화면 대비는 tools/contrast-audit.py, 메일은 tools/weekly-mail.py <이 파일> <폴더>.
"""
import argparse
import json
import pathlib
import re
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE = "https://jhkim0603.github.io/realestate-dashboard/"


def live_data():
    with urllib.request.urlopen(LIVE, timeout=30) as r:
        page = r.read().decode("utf-8")
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    if not m:
        raise SystemExit("배포된 페이지에서 자료를 찾지 못했습니다")
    return json.loads(m.group(1))


def news_from_history(d):
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))["news"]
    nh = json.loads((ROOT / "news-history.json").read_text(encoding="utf-8"))
    ks = sorted(nh["weeks"])[-int(cfg["weeks"]):]
    d["news"] = {
        "topics": [{"key": t["key"], "name": t["name"], "short": t.get("short", t["name"]), "mood": t.get("mood", 0)} for t in cfg["topics"]],
        "groups": {g: cfg["groups"][g]["name"] for g in cfg["groups"]},
        "queries": {g: cfg["groups"][g]["queries"] for g in cfg["groups"]},
        "weeks": [{"w": k, "g": {g: {kk: vv for kk, vv in r.items() if kk != "ids"} for g, r in nh["weeks"][k].items()}} for k in ks],
        "items": nh["items"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(ROOT / "preview.html"))
    ap.add_argument("--data")
    ap.add_argument("--news", action="store_true")
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.data).read_text(encoding="utf-8")) if a.data else live_data()
    # 설명용 설정(지역·인구·정책·일정)은 수집 스크립트처럼 지금 config.json 의 것을 쓴다(설정만 고쳤을 때도 바로 보이게)
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    for k, v in (("regions", cfg.get("regions")), ("provinces", cfg.get("provinces")), ("population", cfg.get("population")),
                 ("policies", cfg.get("policies")), ("events", cfg.get("events"))):
        if v is not None:
            d.setdefault("meta", {})[k] = v
    if a.news:
        news_from_history(d)
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    geo = (ROOT / "geo" / "maps.json").read_text(encoding="utf-8").strip()
    assert "__DATA_JSON__" in tpl and "__GEO_JSON__" in tpl
    data = json.dumps(d, ensure_ascii=False).replace("</", "<\\/")
    out = pathlib.Path(a.out).resolve()
    out.write_text(tpl.replace("__GEO_JSON__", geo).replace("__DATA_JSON__", data), encoding="utf-8")
    print(f"만듦: {out} (자료 {'파일' if a.data else '배포된 페이지'}{', 뉴스 다시 계산' if a.news else ''})")


if __name__ == "__main__":
    main()
