# 지도 경계 만들기: 통계청 2018 행정구역(southkorea-maps 의 TopoJSON)을 화면용 SVG 좌표로 줄여 geo/maps.json 에 쓴다.
#
#   python tools/build-geo.py [원자료 폴더]        (폴더를 주지 않으면 GitHub 에서 받는다)
#
# - 원자료: https://github.com/southkorea/southkorea-maps (kostat/2018/json). 통계청 통계지리정보서비스(SGIS)가
#   공공누리 제1유형(출처 표시)으로 제공한 경계를 2018-12-24 에 모은 것. 서울 25개 구, 부산 16개 구·군은 그 뒤 바뀌지 않았다.
#   시·도 경계는 2023년 군위군의 대구 편입이 반영되어 있지 않다(전국 지도의 색칠에는 영향 없음).
# - TopoJSON 은 이웃한 구가 경계선(arc)을 함께 쓰므로 경계선마다 한 번씩 줄이면(Douglas-Peucker) 이웃끼리 틈이 생기지 않는다.
# - 좌표는 위도 가운데의 cos 로 경도를 줄인 평면(작은 지역이라 충분), 너비 600(시·도 지도는 높이 기준)으로 맞춘다.
# - 이름표 자리는 구 안에서 경계와 가장 먼 점(polylabel 근사)이다. 좁은 구는 아래 LABEL_AT 으로 바다·강 쪽에 빼고 선으로 잇는다.
# - 강: 한강은 강북 구와 강남 구가 맞닿은 경계(강 한가운데)를, 낙동강은 부산 강서구와 사하·사상·북구의 경계를 따라 그린다.
import json, math, os, sys, urllib.request

BASE = "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/kostat/2018/json/"
FILES = {"muni": "skorea-municipalities-2018-topo.json", "prov": "skorea-provinces-2018-topo.json"}
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "geo", "maps.json")


def load(kind):
    name = FILES[kind]
    if len(sys.argv) > 1:
        return json.load(open(os.path.join(sys.argv[1], name), encoding="utf-8"))
    with urllib.request.urlopen(BASE + name, timeout=60) as r:
        return json.load(r)


def decode_arcs(topo):
    sx, sy = topo["transform"]["scale"]; tx, ty = topo["transform"]["translate"]
    out = []
    for arc in topo["arcs"]:
        x = y = 0; pts = []
        for dx, dy in arc:
            x += dx; y += dy; pts.append((x * sx + tx, y * sy + ty))
        out.append(pts)
    return out


def dp(pts, tol):
    """Douglas-Peucker. 양 끝점은 남긴다(이웃 경계와 이어지는 점)."""
    if len(pts) < 3: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]; dx, dy = x2 - x1, y2 - y1; L = math.hypot(dx, dy)
        best, bi = -1, -1
        for i in range(a + 1, b):
            x, y = pts[i]
            d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / L if L else math.hypot(x - x1, y - y1)
            if d > best: best, bi = d, i
        if best > tol:
            keep[bi] = True; stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def ring_area(r):
    return 0.5 * sum(r[i][0] * r[i - 1][1] - r[i - 1][0] * r[i][1] for i in range(len(r)))


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay; L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def inside(px, py, ring):
    c = False; j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]; xj, yj = ring[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi: c = not c
        j = i
    return c


def polylabel(ring):
    """링 안에서 경계와 가장 먼 점(격자로 찾고 두 번 좁혀 다시 찾는다)."""
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    best = (-1, (x0 + x1) / 2, (y0 + y1) / 2)
    span = max(x1 - x0, y1 - y0); cx, cy = best[1], best[2]
    for it in range(3):
        n = 36; step = span / n
        for i in range(-n // 2, n // 2 + 1):
            for j in range(-n // 2, n // 2 + 1):
                px, py = cx + i * step, cy + j * step
                if not inside(px, py, ring): continue
                d = min(seg_dist(px, py, *ring[k - 1], *ring[k]) for k in range(len(ring)))
                if d > best[0]: best = (d, px, py)
        cx, cy = best[1], best[2]; span = step * 4
    return best


def build(topo, arcs, geoms, width=None, height=None, tol=0.6, min_area=6.0, keep_ring=None):
    """geoms 를 한 평면에 올려 path 문자열과 이름표 자리를 만든다."""
    used = sorted({abs(a) if a >= 0 else ~a for g in geoms for poly in polys(g) for ring in poly for a in ring})
    lons = [p[0] for i in used for p in arcs[i]]; lats = [p[1] for i in used for p in arcs[i]]
    lat0 = (min(lats) + max(lats)) / 2; k = math.cos(math.radians(lat0))
    w0, h0 = (max(lons) - min(lons)) * k, max(lats) - min(lats)
    s = width / w0 if width else height / h0
    W, H = round(w0 * s, 1), round(h0 * s, 1)
    lon0, lat1 = min(lons), max(lats)
    proj = lambda p: ((p[0] - lon0) * k * s, (lat1 - p[1]) * s)
    simp = {i: dp([proj(p) for p in arcs[i]], tol) for i in used}
    full = {i: [proj(p) for p in arcs[i]] for i in used}

    def ring_pts(ring, src):
        pts = []
        for a in ring:
            seg = src[a] if a >= 0 else src[~a][::-1]
            pts += seg if not pts else seg[1:]
        return pts

    areas = []
    for g in geoms:
        d, rings_kept, big = "", 0, None
        for poly in polys(g):
            for ri, ring in enumerate(poly):
                pts = ring_pts(ring, simp)
                if len(pts) < 4: continue
                a = abs(ring_area(pts))
                if a < min_area and not (keep_ring and keep_ring(g, [p for p in ring_pts(ring, full)])): continue
                d += "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts[:-1]) + "Z"; rings_kept += 1
                if ri == 0 and (big is None or a > big[0]): big = (a, pts)
        r, lx, ly = polylabel(big[1])
        areas.append({"code": g["properties"]["code"], "name": g["properties"]["name"], "d": d,
                      "lx": round(lx, 1), "ly": round(ly, 1), "r": round(r, 1)})
    return {"w": W, "h": H, "areas": areas}, (proj, simp, full)


def polys(g):
    return g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]


def shared_arcs(geoms_a, geoms_b):
    ids = lambda gs: {abs(a) if a >= 0 else ~a for g in gs for poly in polys(g) for ring in poly for a in ring}
    return sorted(ids(geoms_a) & ids(geoms_b))


def river_paths(arc_ids, simp):
    """맞닿은 경계선 조각들을 이어 붙여 강 선으로 만든다."""
    segs = [list(simp[i]) for i in arc_ids]
    lines = []
    while segs:
        cur = segs.pop(0); grown = True
        while grown:
            grown = False
            for i, s in enumerate(segs):
                if math.dist(cur[-1], s[0]) < 0.5: cur += s[1:]
                elif math.dist(cur[-1], s[-1]) < 0.5: cur += s[::-1][1:]
                elif math.dist(cur[0], s[-1]) < 0.5: cur = s + cur[1:]
                elif math.dist(cur[0], s[0]) < 0.5: cur = s[::-1] + cur[1:]
                else: continue
                segs.pop(i); grown = True; break
        lines.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in cur))
    return lines


# 좁은 구의 이름표 자리(지도 좌표). 화면이 좁으면 이 자리에 이름을 두고 구 안쪽 점과 선으로 잇는다.
LABEL_AT = {}

muni = load("muni"); prov = load("prov")
ma = decode_arcs(muni); pa = decode_arcs(prov)
mg = muni["objects"][next(iter(muni["objects"]))]["geometries"]
pg = prov["objects"][next(iter(prov["objects"]))]["geometries"]
by = lambda pref: [g for g in mg if g["properties"]["code"].startswith(pref)]
named = lambda gs, names: [g for g in gs if g["properties"]["name"] in names]

out = {"src": "통계청 SGIS 행정구역 경계(2018, 공공누리 제1유형) · southkorea-maps"}

# 서울 25개 구 + 한강
seoul = by("11")
out["seoul"], (proj, simp, full) = build(muni, ma, seoul, width=600, tol=0.55, min_area=4)
north = named(seoul, {"마포구", "용산구", "성동구", "광진구"})
south = named(seoul, {"강서구", "영등포구", "동작구", "서초구", "강남구", "송파구", "강동구"})
outside_n = [g for g in mg if g["properties"]["name"] in ("덕양구", "구리시", "남양주시") or g["properties"]["name"].endswith("덕양구")]
gangseo = named(seoul, {"강서구"}); gangdong = named(seoul, {"강동구"})
han = shared_arcs(north, south) + shared_arcs(gangseo, outside_n) + shared_arcs(gangdong, outside_n)
# 바깥 구와 맞닿은 경계선은 서울 평면에 없을 수 있으니 새로 투영한다
for i in han:
    if i not in simp: simp[i] = dp([proj(p) for p in ma[i]], 0.55)
out["seoul"]["rivers"] = [{"name": "한강", "d": d} for d in river_paths(han, simp)]

# 부산 16개 구·군 + 낙동강
busan = by("21")
out["busan"], (proj, simp, full) = build(muni, ma, busan, width=600, tol=0.55, min_area=6)
nak = shared_arcs(named(busan, {"강서구"}), named(busan, {"사하구", "사상구", "북구"}))
out["busan"]["rivers"] = [{"name": "낙동강", "d": d} for d in river_paths(nak, simp)]

# 전국 17개 시·도. 작은 섬은 빼되 울릉도는 남고(면적이 충분), 독도는 너무 작아 점으로 따로 둔다.
korea, (proj, simp, full) = build(prov, pa, pg, height=560, tol=0.7, min_area=5)
dok = [proj(p) for i, arc in enumerate(pa) for p in arc if p[0] > 131.8]
if dok:
    korea["dokdo"] = [round(sum(p[0] for p in dok) / len(dok), 1), round(sum(p[1] for p in dok) / len(dok), 1)]
out["korea"] = korea

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print("geo/maps.json", os.path.getsize(OUT), "bytes",
      {k: (v["w"], v["h"], len(v["areas"])) for k, v in out.items() if isinstance(v, dict)},
      "rivers", len(out["seoul"]["rivers"]), len(out["busan"]["rivers"]), "ulleung" in korea, korea.get("dokdo"))
