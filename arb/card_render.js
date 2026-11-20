// Обложка карточки товара 1200×900 (4:3, как требует Playerok).
// Один и тот же код рисует обложки в панели (предпросмотр) и на странице Playerok при выставлении.
// Логотипы брендов не рисуем — только свои иллюстрации: карта, алмаз, гем, монета, звезда.
(function (root) {
  const W = 1200, H = 900;
  const THEMES = {
    apple:          { bg: ['#120c2e', '#3b1d8f', '#c2389b'], glow: '#ff7ad9', accent: '#ffd6f3', title: 'App Store & iTunes', icon: 'card' },
    google_play:    { bg: ['#03213a', '#0a6b8f', '#0fb38a'], glow: '#5cf2c2', accent: '#d6fff1', title: 'Google Play', icon: 'card' },
    psn:            { bg: ['#020b2e', '#0a3aa8', '#1677ff'], glow: '#5aa8ff', accent: '#d9e8ff', title: 'PlayStation Store', icon: 'card' },
    xbox:           { bg: ['#03140a', '#0b5d1e', '#25b04b'], glow: '#7dff9c', accent: '#dcffe5', title: 'Xbox', icon: 'card' },
    steam:          { bg: ['#060c18', '#13294b', '#2a6fb0'], glow: '#66c0f4', accent: '#d8ecff', title: 'Steam', icon: 'card' },
    nintendo:       { bg: ['#2a0306', '#a3101c', '#ff4155'], glow: '#ff8a96', accent: '#ffe0e4', title: 'Nintendo eShop', icon: 'card' },
    battlenet:      { bg: ['#03101f', '#0b4a8a', '#148eff'], glow: '#6fc3ff', accent: '#dcefff', title: 'Battle.net', icon: 'card' },
    mobile_legends: { bg: ['#0b0a2a', '#28208f', '#d39b18'], glow: '#ffd25c', accent: '#fff2c9', title: 'Mobile Legends', icon: 'diamond' },
    free_fire:      { bg: ['#1f0500', '#a12a08', '#ff7a18'], glow: '#ffb35c', accent: '#ffe7cc', title: 'Free Fire', icon: 'diamond' },
    brawl_stars:    { bg: ['#1a0533', '#6b16c9', '#ffb800'], glow: '#ffe066', accent: '#fff4c2', title: 'Brawl Stars', icon: 'gem' },
    clash_royale:   { bg: ['#06122e', '#1b4fd1', '#f2b705'], glow: '#ffe066', accent: '#fff4c2', title: 'Clash Royale', icon: 'gem' },
    clash_of_clans: { bg: ['#0e1a05', '#3f7a12', '#f2b705'], glow: '#ffe066', accent: '#fff4c2', title: 'Clash of Clans', icon: 'gem' },
    pubg:           { bg: ['#0d0d0b', '#3d3420', '#f2a900'], glow: '#ffd36b', accent: '#fff0c8', title: 'PUBG Mobile', icon: 'coin', coin: 'UC' },
    telegram:       { bg: ['#03182b', '#0d6fb8', '#2aabee'], glow: '#ffd75e', accent: '#e0f3ff', title: 'Telegram Stars', icon: 'star' },
    roblox:         { bg: ['#0c0c0c', '#3a0d0d', '#e2231a'], glow: '#ff6b62', accent: '#ffe1df', title: 'Roblox', icon: 'coin', coin: 'R$' },
    genshin:        { bg: ['#0a1030', '#3a3f9a', '#c9a8ff'], glow: '#e7d8ff', accent: '#f3ecff', title: 'Genshin Impact', icon: 'diamond' },
    fortnite:       { bg: ['#0a0630', '#3b1fb0', '#18c6ff'], glow: '#8fe8ff', accent: '#e2f8ff', title: 'Fortnite', icon: 'coin', coin: 'V' },
    valorant:       { bg: ['#140507', '#7a0f1c', '#ff4655'], glow: '#ff8c95', accent: '#ffe1e4', title: 'Valorant', icon: 'coin', coin: 'VP' },
    standoff2:      { bg: ['#0b0b10', '#3a2c06', '#f2b705'], glow: '#ffd76b', accent: '#fff1c6', title: 'Standoff 2', icon: 'coin', coin: 'G' },
  };
  const DEFAULT = { bg: ['#0d0a26', '#3d2bb3', '#22c1ee'], glow: '#9ad9ff', accent: '#e5f4ff', title: '', icon: 'card' };
  const FONT = '"Inter", "Segoe UI", Arial, sans-serif';

  function rr(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }

  function background(g, t) {
    const lin = g.createLinearGradient(0, 0, W, H);
    lin.addColorStop(0, t.bg[0]); lin.addColorStop(.55, t.bg[1]); lin.addColorStop(1, t.bg[2]);
    g.fillStyle = lin; g.fillRect(0, 0, W, H);
    // мягкие световые пятна
    [[W * .82, H * .28, 420, t.glow, .45], [W * .1, H * .95, 380, t.bg[2], .35], [W * .55, H * .55, 520, '#ffffff', .06]].forEach(([x, y, r, c, a]) => {
      const rad = g.createRadialGradient(x, y, 0, x, y, r); rad.addColorStop(0, hexA(c, a)); rad.addColorStop(1, hexA(c, 0));
      g.fillStyle = rad; g.fillRect(0, 0, W, H);
    });
    // диагональные лучи
    g.save(); g.globalCompositeOperation = 'lighter';
    for (let i = 0; i < 5; i++) {
      const x = 380 + i * 170; g.beginPath(); g.moveTo(x, -50); g.lineTo(x + 70, -50); g.lineTo(x - 260, H + 50); g.lineTo(x - 330, H + 50); g.closePath();
      g.fillStyle = `rgba(255,255,255,${0.025 + (i % 2) * 0.02})`; g.fill();
    }
    g.restore();
    // искры
    let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    for (let i = 0; i < 70; i++) { const x = rnd() * W, y = rnd() * H, s = rnd() * 2.6 + .4; g.fillStyle = `rgba(255,255,255,${.15 + rnd() * .5})`; g.beginPath(); g.arc(x, y, s, 0, Math.PI * 2); g.fill(); }
  }

  function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; }

  function glowShape(g, color, blur, fn) { g.save(); g.shadowColor = color; g.shadowBlur = blur; fn(); g.restore(); }

  function iconCard(g, t, cx, cy) {
    g.save(); g.translate(cx, cy); g.rotate(-0.16);
    const w = 360, h = 234;
    glowShape(g, hexA(t.glow, .8), 70, () => { rr(g, -w / 2, -h / 2, w, h, 30); g.fillStyle = '#fff'; g.fill(); });
    const lg = g.createLinearGradient(-w / 2, -h / 2, w / 2, h / 2); lg.addColorStop(0, '#ffffff'); lg.addColorStop(1, t.accent);
    rr(g, -w / 2, -h / 2, w, h, 30); g.fillStyle = lg; g.fill();
    const band = g.createLinearGradient(-w / 2, 0, w / 2, 0); band.addColorStop(0, t.bg[1]); band.addColorStop(1, t.bg[2]);
    rr(g, -w / 2, -h / 2, w, 92, 30); g.fillStyle = band; g.fill(); g.fillRect(-w / 2, -h / 2 + 60, w, 32);
    rr(g, -w / 2 + 34, -6, 64, 48, 9); const chip = g.createLinearGradient(0, -6, 0, 42); chip.addColorStop(0, '#ffe39a'); chip.addColorStop(1, '#d9a531'); g.fillStyle = chip; g.fill();
    g.fillStyle = hexA(t.bg[1], .35); [0, 1, 2].forEach(i => { rr(g, -w / 2 + 130, 2 + i * 22, 210 - i * 50, 10, 5); g.fill(); });
    g.fillStyle = '#fff'; g.font = `800 34px ${FONT}`; g.textAlign = 'left'; g.fillText('GIFT CARD', -w / 2 + 30, -h / 2 + 58);
    g.restore();
  }

  function iconDiamond(g, t, cx, cy, s = 1) {
    g.save(); g.translate(cx, cy); g.scale(s, s);
    const top = -110, mid = -40, bot = 150, w1 = 95, w2 = 170;
    glowShape(g, hexA(t.glow, .9), 80, () => { g.beginPath(); g.moveTo(-w1, top); g.lineTo(w1, top); g.lineTo(w2, mid); g.lineTo(0, bot); g.lineTo(-w2, mid); g.closePath(); g.fillStyle = t.glow; g.fill(); });
    const faces = [
      [[-w1, top], [0, top], [-55, mid], '#ffffff'], [[0, top], [w1, top], [55, mid], '#e8f6ff'],
      [[-w1, top], [-55, mid], [-w2, mid], t.accent], [[w1, top], [55, mid], [w2, mid], '#ffffff'],
      [[-55, mid], [55, mid], [0, top], t.glow],
      [[-w2, mid], [-55, mid], [0, bot], t.bg[2]], [[-55, mid], [55, mid], [0, bot], t.glow], [[55, mid], [w2, mid], [0, bot], t.bg[1]],
    ];
    faces.forEach(([a, b, c, col]) => { g.beginPath(); g.moveTo(...a); g.lineTo(...b); g.lineTo(...c); g.closePath(); g.fillStyle = col; g.globalAlpha = .92; g.fill(); });
    g.globalAlpha = 1; g.strokeStyle = 'rgba(255,255,255,.65)'; g.lineWidth = 3;
    g.beginPath(); g.moveTo(-w1, top); g.lineTo(w1, top); g.lineTo(w2, mid); g.lineTo(0, bot); g.lineTo(-w2, mid); g.closePath(); g.stroke();
    g.restore();
  }

  function iconGem(g, t, cx, cy) {
    g.save(); g.translate(cx, cy);
    const pts = [[0, -150], [130, -60], [95, 120], [-95, 120], [-130, -60]];
    glowShape(g, hexA('#3cff8f', .8), 80, () => { g.beginPath(); pts.forEach((p, i) => i ? g.lineTo(...p) : g.moveTo(...p)); g.closePath(); g.fillStyle = '#2fe07d'; g.fill(); });
    const cols = ['#7dffb4', '#3be38a', '#1fa85c', '#178a4a', '#55f09c'];
    pts.forEach((p, i) => { const q = pts[(i + 1) % 5]; g.beginPath(); g.moveTo(0, 0); g.lineTo(...p); g.lineTo(...q); g.closePath(); g.fillStyle = cols[i]; g.fill(); });
    g.strokeStyle = 'rgba(255,255,255,.7)'; g.lineWidth = 4; g.beginPath(); pts.forEach((p, i) => i ? g.lineTo(...p) : g.moveTo(...p)); g.closePath(); g.stroke();
    g.fillStyle = 'rgba(255,255,255,.75)'; g.beginPath(); g.ellipse(-40, -70, 26, 12, -0.6, 0, Math.PI * 2); g.fill();
    g.restore();
  }

  function iconCoin(g, t, cx, cy, label) {
    [[60, 70, .8], [-50, 30, .9], [0, -20, 1]].forEach(([dx, dy, s]) => {
      g.save(); g.translate(cx + dx, cy + dy); g.scale(s, s);
      glowShape(g, hexA(t.glow, .7), 50, () => { g.beginPath(); g.arc(0, 0, 130, 0, Math.PI * 2); g.fillStyle = '#d99a1e'; g.fill(); });
      const rg = g.createRadialGradient(-40, -50, 10, 0, 0, 130); rg.addColorStop(0, '#fff3c4'); rg.addColorStop(.5, '#ffc93c'); rg.addColorStop(1, '#c47f0e');
      g.beginPath(); g.arc(0, 0, 130, 0, Math.PI * 2); g.fillStyle = rg; g.fill();
      g.beginPath(); g.arc(0, 0, 104, 0, Math.PI * 2); g.strokeStyle = 'rgba(140,80,0,.55)'; g.lineWidth = 8; g.stroke();
      g.fillStyle = '#8a4b00'; g.font = `900 ${label.length > 2 ? 64 : 84}px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(label, 0, 6);
      g.restore();
    });
  }

  function iconStar(g, t, cx, cy) {
    g.save(); g.translate(cx, cy);
    const star = r => { g.beginPath(); for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, rad = i % 2 ? r * .45 : r; g.lineTo(Math.cos(a) * rad, Math.sin(a) * rad); } g.closePath(); };
    glowShape(g, 'rgba(255,214,90,.95)', 90, () => { star(170); g.fillStyle = '#ffcf3f'; g.fill(); });
    const rg = g.createRadialGradient(-40, -60, 10, 0, 0, 170); rg.addColorStop(0, '#fff7cf'); rg.addColorStop(.6, '#ffc928'); rg.addColorStop(1, '#e08a00');
    star(170); g.fillStyle = rg; g.fill(); g.strokeStyle = 'rgba(255,255,255,.7)'; g.lineWidth = 5; g.stroke();
    g.restore();
  }

  function pill(g, x, y, text, { bg = 'rgba(255,255,255,.14)', fg = '#fff', size = 30, pad = 22, stroke = 'rgba(255,255,255,.28)', align = 'left' } = {}) {
    g.font = `700 ${size}px ${FONT}`; const w = g.measureText(text).width + pad * 2, h = size + 26;
    const x0 = align === 'right' ? x - w : x;
    rr(g, x0, y, w, h, h / 2); g.fillStyle = bg; g.fill(); g.strokeStyle = stroke; g.lineWidth = 2; g.stroke();
    g.fillStyle = fg; g.textAlign = 'left'; g.textBaseline = 'middle'; g.fillText(text, x0 + pad, y + h / 2 + 1);
    return w;
  }

  function bigNumber(g, t, amount, unit, x, y) {
    g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    // номинал и единица уменьшаются вместе, пока не поместятся в одну строку
    let size = 230, us = 92, w = 0, uw = 0;
    for (; size > 90; size -= 8) {
      us = Math.round(size * .4);
      g.font = `900 ${size}px ${FONT}`; w = g.measureText(amount).width;
      g.font = `900 ${us}px ${FONT}`; uw = unit ? g.measureText(unit).width + 22 : 0;
      if (w + uw <= 590) break;  // правее начинается иллюстрация
    }
    g.font = `900 ${size}px ${FONT}`;
    g.save(); g.shadowColor = 'rgba(0,0,0,.45)'; g.shadowBlur = 30; g.shadowOffsetY = 12;
    const grad = g.createLinearGradient(0, y - size, 0, y); grad.addColorStop(0, '#ffffff'); grad.addColorStop(1, t.accent);
    g.fillStyle = grad; g.fillText(amount, x, y); g.restore();
    g.lineWidth = 3; g.strokeStyle = 'rgba(255,255,255,.35)'; g.strokeText(amount, x, y);
    if (!unit) return;
    g.font = `900 ${us}px ${FONT}`;
    const ug = g.createLinearGradient(0, y - us, 0, y); ug.addColorStop(0, t.glow); ug.addColorStop(1, '#ffffff');
    g.save(); g.shadowColor = hexA(t.glow, .8); g.shadowBlur = 24; g.fillStyle = ug;
    g.fillText(unit, x + w + 22, y);
    g.restore();
  }

  // Маскот магазина DragDiller — дракон-гонщик (драг-рейсинг = моментальная выдача).
  // Рисуется в своих координатах 135×200 и масштабируется.
  function mascot(s) {
    const c = document.createElement('canvas'); c.width = Math.ceil(135 * s); c.height = Math.ceil(200 * s);
    const m = c.getContext('2d'); m.scale(s, s);
    const fill = (col, f) => { m.fillStyle = col; f(); m.fill(); };
    const ell = (x, y, rx, ry) => { m.beginPath(); m.ellipse(x, y, rx, ry, 0, 0, Math.PI * 2); };
    const path = d => new Path2D(d);
    m.strokeStyle = 'rgba(255,255,255,.85)'; m.lineWidth = 3; m.lineCap = 'round';
    m.stroke(path('M8 120 L30 120 M4 136 L28 136 M10 152 L30 152'));
    m.fillStyle = '#0F6E56'; m.fill(path('M40 112 L14 82 L24 112 L10 122 L40 130 Z')); m.fill(path('M95 112 L121 82 L111 112 L125 122 L95 130 Z'));
    m.fillStyle = '#1D9E75'; m.fill(path('M88 168 Q122 172 118 146 L127 150 L121 136 L111 146 Q114 162 86 158 Z'));
    fill('#1D9E75', () => ell(67, 152, 30, 30)); fill('#9FE1CB', () => ell(67, 158, 18, 21));
    fill('#0F6E56', () => ell(52, 182, 10, 6)); fill('#0F6E56', () => ell(82, 182, 10, 6));
    fill('#1D9E75', () => ell(67, 88, 30, 30));
    m.fillStyle = '#E24B4A'; m.fill(path('M34 92 Q34 52 67 52 Q100 52 100 92 Z'));
    m.fillStyle = '#fff'; m.fillRect(62, 53, 10, 39);
    fill('#26215C', () => rr(m, 40, 76, 54, 18, 9)); fill('#85B7EB', () => rr(m, 46, 80, 18, 10, 5)); fill('#85B7EB', () => rr(m, 70, 80, 18, 10, 5));
    fill('rgba(255,255,255,.8)', () => rr(m, 49, 81, 6, 3, 1.5)); fill('rgba(255,255,255,.8)', () => rr(m, 73, 81, 6, 3, 1.5));
    fill('#9FE1CB', () => ell(67, 104, 17, 10)); fill('#04342C', () => ell(61, 102, 2, 2)); fill('#04342C', () => ell(73, 102, 2, 2));
    m.strokeStyle = '#04342C'; m.lineWidth = 2; m.stroke(path('M57 110 Q67 117 77 110'));
    m.fillStyle = '#FAC775'; m.strokeStyle = '#854F0B'; m.lineWidth = 1.2;
    const bolt = path('M108 118 L98 140 L106 140 L100 160 L118 132 L109 132 L115 118 Z'); m.fill(bolt); m.stroke(bolt);
    return c;
  }

  function brandPill(g, x, y) {
    const size = 30, text = 'DragDiller'; g.font = `800 ${size}px ${FONT}`;
    const flag = 30, pad = 18, w = pad + flag + 12 + g.measureText(text).width + pad, h = size + 26;
    rr(g, x, y, w, h, h / 2); g.fillStyle = 'rgba(255,255,255,.95)'; g.fill();
    const q = flag / 4, fy = y + (h - flag) / 2;
    for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { g.fillStyle = (i + j) % 2 ? '#ffffff' : '#141414'; g.fillRect(x + pad + i * q, fy + j * q, q, q); }
    g.strokeStyle = '#141414'; g.lineWidth = 2; g.strokeRect(x + pad, fy, flag, flag);
    g.fillStyle = '#141414'; g.textAlign = 'left'; g.textBaseline = 'middle'; g.fillText(text, x + pad + flag + 12, y + h / 2 + 1);
    return w;
  }

  function smallIcon(g, t, icon, cx, cy, s) {
    g.save(); g.translate(cx, cy); g.scale(s, s);
    if (icon === 'diamond') iconDiamond(g, t, 0, 0);
    else if (icon === 'gem') iconGem(g, t, 0, 0);
    else if (icon === 'coin') iconCoin(g, t, 0, 0, t.coin || '$');
    else if (icon === 'star') iconStar(g, t, 0, 0);
    else iconCard(g, t, 0, 0);
    g.restore();
  }

  function draw(canvas, spec) {
    canvas.width = W; canvas.height = H; const g = canvas.getContext('2d');
    const t = Object.assign({}, DEFAULT, THEMES[spec.brand] || {}, { title: spec.title || (THEMES[spec.brand] || {}).title || spec.brand });
    background(g, t);
    // справа: маскот с белым ореолом и значок товара рядом
    const ms = mascot(2.9);
    g.save(); g.shadowColor = 'rgba(255,255,255,.55)'; g.shadowBlur = 40; g.drawImage(ms, 765, 50); g.restore();
    smallIcon(g, t, spec.icon || t.icon, 745, 585, 0.42);
    // шапка: сервис, магазин и регион
    const tw = pill(g, 60, 56, t.title, { size: 38, bg: 'rgba(0,0,0,.28)' });
    brandPill(g, 60 + tw + 14, 59);
    if (spec.region) pill(g, W - 60, 56, spec.region, { size: 34, align: 'right', bg: 'rgba(255,255,255,.92)', fg: '#151515', stroke: 'rgba(255,255,255,.9)' });
    // номинал
    bigNumber(g, t, String(spec.amount), spec.unit || '', 64, 470);
    g.font = `700 46px ${FONT}`; g.fillStyle = 'rgba(255,255,255,.92)'; g.textAlign = 'left'; g.textBaseline = 'alphabetic';
    g.fillText(spec.subtitle || 'Подарочная карта', 68, 560);
    // плашки доверия
    let bx = 60; ['⚡ Моментально', '🛡 Гарантия', '🕐 24/7'].forEach(b => { bx += pill(g, bx, 768, b, { size: 32, bg: 'rgba(0,0,0,.32)' }) + 16; });
    // «выгодно» — лента под подписью (справа маскот, в правом нижнем углу водяной знак Playerok)
    g.save(); g.translate(240, 668); g.rotate(-0.06);
    const lg = g.createLinearGradient(-150, 0, 150, 0); lg.addColorStop(0, '#ff3d6e'); lg.addColorStop(1, '#ff9a3d');
    glowShape(g, 'rgba(255,80,100,.7)', 30, () => { rr(g, -160, -44, 320, 88, 22); g.fillStyle = lg; g.fill(); });
    g.fillStyle = '#fff'; g.font = `900 46px ${FONT}`; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText('ВЫГОДНО', 0, 3);
    g.restore();
    return canvas;
  }

  function toBlob(spec) {
    const c = document.createElement('canvas'); draw(c, spec);
    return new Promise(r => c.toBlob(r, 'image/png'));
  }

  root.ArbCard = { draw, toBlob, THEMES };
})(typeof window !== 'undefined' ? window : globalThis);
