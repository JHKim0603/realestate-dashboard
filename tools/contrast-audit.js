// 글자·그림 대비 점검: #audit-light / #audit-dark 로 열면 그 화면 모드에서 모든 글자(HTML·SVG)와 주요 그림 요소의
// 색을 실제로 그 아래에 깔린 색과 비교해 대비(WCAG)를 재고, 결과를 <pre id="auditOut"> 에 JSON 으로 남긴다.
(function () {
  const m = location.hash.match(/^#audit-(light|dark)$/); if (!m) return;
  document.documentElement.setAttribute("data-theme", m[1]);
  document.querySelectorAll("details").forEach(d => { d.open = true; });
  // 스크롤 목록은 펼쳐서 잰다(가려진 줄이 엉뚱한 바탕과 비교되지 않게)
  const st = document.createElement("style"); st.textContent = ".turns,.weeks{max-height:none!important;overflow:visible!important}"; document.head.appendChild(st);
  const parse = s => {
    if (!s) return null; s = s.trim();
    let r = s.match(/^rgba?\(([^)]+)\)/);
    if (r) { const p = r[1].split(/[\s,\/]+/).filter(Boolean).map(parseFloat); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    r = s.match(/^color\(srgb\s+([^)]+)\)/);
    if (r) { const [c, a] = r[1].split("/"); const v = c.trim().split(/\s+/).map(parseFloat); return [v[0] * 255, v[1] * 255, v[2] * 255, a ? parseFloat(a) : 1]; }
    if (s === "transparent") return [0, 0, 0, 0];
    return null;
  };
  const over = (t, b) => { const a = t[3]; return [t[0] * a + b[0] * (1 - a), t[1] * a + b[1] * (1 - a), t[2] * a + b[2] * (1 - a), 1]; };
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const opac = el => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement || e.parentNode) { const cs = getComputedStyle(e); o *= parseFloat(cs.opacity); if (e === document.documentElement) break; } return o; };
  const hex = c => "#" + c.slice(0, 3).map(v => Math.round(v).toString(16).padStart(2, "0")).join("");
  const bodyBg = parse(getComputedStyle(document.body).backgroundColor);
  const colorOf = el => {   // 요소가 칠하는 색(배경으로 쓰일 때)
    const cs = getComputedStyle(el);
    if (el instanceof SVGElement) {
      if (!(el instanceof SVGGeometryElement) || el.tagName === "line" || el.tagName === "polyline") return null;
      if (!cs.fill || cs.fill === "none" || cs.fill.startsWith("url")) return null;
      const c = parse(cs.fill); if (!c) return null; c[3] *= parseFloat(cs.fillOpacity) * opac(el); return c;
    }
    const c = parse(cs.backgroundColor); if (!c) return null; c[3] *= opac(el); return c;
  };
  // (x, y) 아래에 실제로 깔린 색: 위에서부터 쌓인 층을 아래부터 합성한다. skip 은 재려는 요소 자신.
  const bgAt = (x, y, skip) => {
    const layers = [];
    if (!(skip instanceof SVGElement)) { const own = colorOf(skip); if (own && own[3] > 0) layers.push(own); }
    for (const el of document.elementsFromPoint(x, y)) {
      if (el === skip || skip.contains(el)) continue;
      const c = colorOf(el); if (c && c[3] > 0.001) { layers.push(c); if (c[3] >= 0.999) break; }
    }
    let base = bodyBg; for (let i = layers.length - 1; i >= 0; i--) base = over(layers[i], base); return base;
  };
  const sec = el => { const s = el.closest("section,header,nav,.foot"); return s ? (s.id || s.className || s.tagName) : ""; };
  const visible = el => { const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) return null; const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none" || el.closest("[hidden]")) return null; return r; };
  const texts = [];
  const all = document.querySelectorAll("body *");
  all.forEach(el => {
    if (["SCRIPT", "STYLE", "TITLE"].includes(el.tagName.toUpperCase()) || el.closest("#auditOut")) return;
    const own = [...el.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim()).map(n => n.textContent.trim()).join(" ");
    if (!own) return;
    const r = visible(el); if (!r) return;
    const cs = getComputedStyle(el), svg = el instanceof SVGElement;
    let fg = parse(svg ? cs.fill : cs.color); if (!fg) return;
    fg = [...fg]; fg[3] *= (svg ? parseFloat(cs.fillOpacity) : 1) * opac(el);
    const bg = bgAt(r.left + r.width / 2, r.top + r.height / 2, el), shown = over(fg, bg);
    const fs = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    texts.push({ t: own.slice(0, 40), r: +ratio(shown, bg).toFixed(2), fg: hex(shown), bg: hex(bg), fs, bold, sec: sec(el), tag: el.tagName.toLowerCase(), cls: (el.getAttribute("class") || "").slice(0, 30) });
  });
  // 그림 요소: 선(stroke)과 칠(fill)이 바탕과 구별되는지
  const MARKS = [".ch .ln", ".spd .ma", ".tline .ma", ".h-chart .h-line", ".quad .trail", ".ch .bar", ".spd .bar-u", ".spd .bar-d", ".tline .bar-u", ".tline .bar-d", ".tline .mu", ".tline .md",
    ".ybar .yb", ".ch .area", ".hs-strip i", ".hmx .hr i", ".strip i", ".brd rect", ".geo .ar", ".tr2 svg rect", ".sc-c svg path", ".rk .bar i", ".tl i", ".scale i", ".gauge .arc-l", ".gauge .arc-r", ".legend i", ".h-arrow path", ".ybar .dem", ".ybar .avg", ".spd .mk", ".ch .mk"];
  const marks = [];
  MARKS.forEach(q => document.querySelectorAll(q).forEach(el => {
    const r = visible(el); if (!r) return; const cs = getComputedStyle(el);
    let c = null, kind = "fill";
    if (el instanceof SVGElement) {
      if (cs.stroke && cs.stroke !== "none" && (el.tagName === "path" && (cs.fill === "none" || el.classList.contains("ma") || el.classList.contains("h-line")) || el.tagName === "polyline" || el.tagName === "line")) { c = parse(cs.stroke); kind = "stroke"; if (c) c[3] *= parseFloat(cs.strokeOpacity); }
      else if (cs.fill && cs.fill !== "none" && !cs.fill.startsWith("url")) { c = parse(cs.fill); if (c) c[3] *= parseFloat(cs.fillOpacity); }
    } else { c = parse(cs.backgroundColor); kind = "bg"; if (c && c[3] === 0) { c = parse(cs.borderTopColor); kind = "border"; } }
    if (!c) return; c = [...c]; c[3] *= opac(el);
    // 바탕: 요소 자신을 빼고 그 자리 아래 색. 선은 가장자리가 아니라 중심 근처가 바탕과 겹치므로 중심을 쓴다.
    // 그림 요소의 바탕 = 그것을 담은 카드(또는 페이지) 색
    let bg = bodyBg; for (let e = el.parentElement; e; e = e.parentElement) { const b = parse(getComputedStyle(e).backgroundColor); if (b && b[3] > 0.99) { bg = b; break; } }
    const shown = over(c, bg);
    marks.push({ q, kind, r: +ratio(shown, bg).toFixed(2), c: hex(shown), bg: hex(bg), sec: sec(el) });
  }));
  const out = document.createElement("pre"); out.id = "auditOut"; out.hidden = true;
  out.textContent = JSON.stringify({ theme: m[1], texts, marks });
  document.body.appendChild(out);
})();
