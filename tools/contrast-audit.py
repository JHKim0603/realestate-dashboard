# 밝은·어두운 화면 글자·그림 대비 점검: python tools/contrast-audit.py <dashboard.html> <결과 폴더> [화면 폭]. 크롬으로 두 화면을 열어 3:1 미만 글자를 보여 준다.
import json, os, re, shutil, subprocess, sys, pathlib, collections
page, outdir = pathlib.Path(sys.argv[1]).resolve(), pathlib.Path(sys.argv[2]).resolve()
outdir.mkdir(parents=True, exist_ok=True)
html = page.read_text(encoding='utf-8').replace('</body>', '<script>' + (pathlib.Path(__file__).parent / 'contrast-audit.js').read_text(encoding='utf-8') + '</script></body>')
tgt = outdir / 'audit.html'; tgt.write_text(html, encoding='utf-8')
# 크롬 위치는 PC마다 다르다(Program Files 와 Program Files (x86)). 처음 판은 (x86) 만 봐서 다른 PC에서 돌지 않았다.
CH = next((p for p in (shutil.which('chrome'), shutil.which('google-chrome'), r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                       r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe') if p and os.path.exists(p)), None)
if not CH: sys.exit('크롬을 찾지 못했습니다')
# 크롬 프로필을 결과 폴더 안에 둔다. 회사 PC에서는 임시 폴더(TEMP)에 프로필을 만들면 크롬이 화면을 그리지 못하고 멈춘 적이 있다(2026-11-20).
prof = outdir / 'chrome-profile'
res = {}
for th in ('light', 'dark'):
    dom = subprocess.run([CH, '--headless=new', '--disable-gpu', '--no-sandbox', '--hide-scrollbars', '--virtual-time-budget=10000', f'--user-data-dir={prof}',
                          f'--window-size={sys.argv[3] if len(sys.argv) > 3 else 1280},16000', '--dump-dom', tgt.as_uri() + f'#audit-{th}'], capture_output=True, timeout=180).stdout.decode('utf-8', 'replace')
    m = re.search(r'<pre id="auditOut" hidden="">(.*?)</pre>', dom, re.S)
    import html as H
    res[th] = json.loads(H.unescape(m.group(1))) if m else None
json.dump(res, open(outdir / 'audit.json', 'w', encoding='utf-8'), ensure_ascii=False)
for th, d in res.items():
    if not d: print(th, 'NO RESULT'); continue
    T = d['texts']; bad = [t for t in T if t['r'] < 3]; weak = [t for t in T if 3 <= t['r'] < 4.5 and not (t['fs'] >= 18.6 or (t['bold'] and t['fs'] >= 14))]
    print(f'== {th}: 글자 {len(T)}개 · 3:1 미만 {len(bad)} · 4.5:1 미만(작은 글자) {len(weak)}')
    g = collections.defaultdict(list)
    for t in bad: g[(t['sec'], t['tag'], t['cls'], t['fg'], t['bg'])].append(t)
    for k, v in sorted(g.items(), key=lambda kv: min(x['r'] for x in kv[1])):
        print(f"  [{min(x['r'] for x in v):.2f}] x{len(v)} {k[0]} <{k[1]} .{k[2]}> {k[3]} on {k[4]} :: {v[0]['t']}")
    gw = collections.defaultdict(list)
    for t in weak: gw[(t['sec'], t['cls'], t['fg'], t['bg'])].append(t)
    print('  -- 약함(3~4.5) 묶음 상위:')
    for k, v in sorted(gw.items(), key=lambda kv: min(x['r'] for x in kv[1]))[:14]:
        print(f"   ({min(x['r'] for x in v):.2f}) x{len(v)} {k[0]} .{k[1]} {k[2]} on {k[3]} :: {v[0]['t']}")
    M = d['marks']; gm = collections.defaultdict(list)
    for x in M: gm[x['q']].append(x)
    print('  -- 그림 요소(바탕 대비 최저/중간, 1.3 미만 수):')
    for q, v in gm.items():
        rs = sorted(x['r'] for x in v); low = [x for x in v if x['r'] < 1.3]
        print(f"   {q:22s} n={len(v):4d} min={rs[0]:.2f} med={rs[len(rs)//2]:.2f} <1.3:{len(low)}" + (f"  e.g. {low[0]['c']} on {low[0]['bg']}" if low else ''))
