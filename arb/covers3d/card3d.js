// 3D-обложка карточки: маскот и товар рендерятся в Three.js, подписи рисуются поверх на холсте.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { FontLoader } from 'three/addons/loaders/FontLoader.js';
import { TextGeometry } from 'three/addons/geometries/TextGeometry.js';
import { makeMascot } from './mascot.js';
import { PROPS } from './props.js';

const W = 1200, H = 900, SS = 2;
const FONT = 'Inter, "Segoe UI", Arial, sans-serif';

const THEMES = {
  mobile_legends: { backdrop: 'shards', title: 'Mobile Legends', bg: ['#071238', '#123a9c', '#2f8cf0'], glow: '#6fc3ff', accent: '#ffd66b', gem: '#49b6ff', side: '#0b2a78' },
  free_fire: { backdrop: 'shards', title: 'Free Fire', bg: ['#210803', '#8a2406', '#f0701a'], glow: '#ffb35c', accent: '#ffd66b', gem: '#ff9a3d', side: '#5c1703' },
  genshin: { backdrop: 'crystals', title: 'Genshin Impact', bg: ['#0c1136', '#3a3a9e', '#a98cf2'], glow: '#d9c8ff', accent: '#ffe6a3', gem: '#b89bff', side: '#23226b' },
  google_play: { backdrop: 'tiles', title: 'Google Play', bg: ['#031f33', '#0a6480', '#10b090'], glow: '#6df5cc', accent: '#c9fff0', gem: '#3fe0b0', side: '#053a4a' },
  apple: { backdrop: 'tiles', title: 'App Store', bg: ['#120c2e', '#3b1d8f', '#c2389b'], glow: '#ff8fdf', accent: '#ffd6f3', gem: '#ff7ad9', side: '#2a1466' },
  psn: { backdrop: 'hex', title: 'PlayStation', bg: ['#04102e', '#0c3a96', '#2277e0'], glow: '#7fbcff', accent: '#d8ebff', gem: '#5aa6ff', side: '#08265f' },
  telegram: { backdrop: 'stars', title: 'Telegram Stars', bg: ['#03182b', '#0b5f9e', '#2aabee'], glow: '#ffe08a', accent: '#ffd66b', gem: '#ffc933', side: '#06395f' },
  pubg: { backdrop: 'crates', title: 'PUBG Mobile', bg: ['#12140a', '#3d4220', '#a5873a'], glow: '#ffd25c', accent: '#ffd66b', gem: '#ffc233', side: '#2b2f14' },
  // 06.11: новые сервисы. coin — надпись на монете игровой валюты (текст, не логотип)
  steam: { backdrop: 'hex', title: 'Steam', bg: ['#0b1420', '#1b2838', '#2a6f9c'], glow: '#66c0f4', accent: '#c7ecff', gem: '#66c0f4', side: '#0e1a28' },
  xbox: { backdrop: 'hex', title: 'Xbox', bg: ['#041a04', '#0e4f0e', '#1f9a1f'], glow: '#7dff7d', accent: '#d6ffd6', gem: '#3ee03e', side: '#06300a' },
  nintendo: { backdrop: 'tiles', title: 'Nintendo eShop', bg: ['#2a0004', '#8a0010', '#e60012'], glow: '#ff8a95', accent: '#ffe0e3', gem: '#ff3b4d', side: '#5c000a' },
  battlenet: { backdrop: 'crystals', title: 'Battle.net', bg: ['#030b1f', '#0b2e6b', '#148eff'], glow: '#7fd0ff', accent: '#d3efff', gem: '#4fb3ff', side: '#06204d' },
  razer: { backdrop: 'hex', title: 'Razer Gold', bg: ['#020602', '#0d2a0a', '#2f8f1f'], glow: '#6dff4d', accent: '#d8ffcf', gem: '#44d62c', side: '#071a05' },
  telegram_premium: { backdrop: 'stars', title: 'Telegram Premium', bg: ['#120a2e', '#3f2a8f', '#8a5cf0'], glow: '#d6c2ff', accent: '#ffe08a', gem: '#b18cff', side: '#24176b' },
  discord_nitro: { backdrop: 'shards', title: 'Discord Nitro', bg: ['#0d0f2e', '#2c34a8', '#5865f2'], glow: '#aab2ff', accent: '#ffd6f5', gem: '#ff73fa', side: '#1c2170' },
  brawl_stars: { backdrop: 'shards', title: 'Brawl Stars', bg: ['#1a0636', '#5a1aa8', '#ffb800'], glow: '#ffe066', accent: '#ffe066', gem: '#3ee07a', side: '#360d6b' },
  roblox: { backdrop: 'tiles', title: 'Roblox', bg: ['#141518', '#3a3d42', '#9aa0a8'], glow: '#ffffff', accent: '#ffe9a8', gem: '#ffd02e', side: '#22252a', coin: ['R$', 440] },
  fortnite: { backdrop: 'crystals', title: 'Fortnite', bg: ['#0b0a35', '#3a2a9e', '#2fb3ff'], glow: '#8fe0ff', accent: '#fff36b', gem: '#4fc3ff', side: '#221a6b', coin: ['V', 620] },
  valorant: { backdrop: 'shards', title: 'Valorant', bg: ['#0f1923', '#5a1520', '#ff4655'], glow: '#ff8a94', accent: '#ece8e1', gem: '#ff4655', side: '#2a0c12', coin: ['VP', 440] },
  clash_royale: { backdrop: 'crystals', title: 'Clash Royale', bg: ['#06143a', '#1a4fb0', '#4fa8ff'], glow: '#ffe27a', accent: '#ffd66b', gem: '#3ee07a', side: '#0b2e70' },
  clash_of_clans: { backdrop: 'crates', title: 'Clash of Clans', bg: ['#140c04', '#5a3510', '#c98a2a'], glow: '#ffd66b', accent: '#ffd66b', gem: '#3ee07a', side: '#3a2208' },
  honkai_star_rail: { backdrop: 'stars', title: 'Honkai: Star Rail', bg: ['#070b24', '#1b2a6b', '#5a7fe0'], glow: '#bcd2ff', accent: '#ffd98a', gem: '#9ec3ff', side: '#101a4a' },
  zenless_zone_zero: { backdrop: 'tiles', title: 'Zenless Zone Zero', bg: ['#0d0d0f', '#2b2b30', '#c9a800'], glow: '#ffe14d', accent: '#ffe14d', gem: '#ffd500', side: '#1a1a1d' },
  wuthering_waves: { backdrop: 'crystals', title: 'Wuthering Waves', bg: ['#041a1f', '#0d4a52', '#2ec4b6'], glow: '#8ff5ea', accent: '#f2e6b8', gem: '#6fe8dc', side: '#07343a' },
  codm: { backdrop: 'crates', title: 'Call of Duty: Mobile', bg: ['#14120c', '#4a4230', '#c2a35a'], glow: '#ffd27a', accent: '#ffd66b', gem: '#ffc233', side: '#2b2619', coin: ['CP', 440] },
  fc_mobile: { backdrop: 'hex', title: 'EA SPORTS FC Mobile', bg: ['#04102e', '#0b2f8a', '#1f6fff'], glow: '#8fd0ff', accent: '#c8ff5a', gem: '#5aa6ff', side: '#081f5c', coin: ['FC', 440] },
  honor_of_kings: { backdrop: 'shards', title: 'Honor of Kings', bg: ['#1c0406', '#6b1218', '#d4a032'], glow: '#ffd98a', accent: '#ffe08a', gem: '#ffcf4a', side: '#3d090d' },
  standoff2: { backdrop: 'crates', title: 'Standoff 2', bg: ['#0c0e12', '#2e333b', '#ff8a1e'], glow: '#ffb35c', accent: '#ffd27a', gem: '#ffb23f', side: '#1c1f24', coin: ['G', 620] },
};
// Образ маскота на каждом сервисе и набор поз с предметами, которые чередуются внутри сервиса.
const LOOKS = {
  pubg: { outfit: 'tactical', lens: 'gold', cuff: '#5f6d3a', looks: [['wave', 'pan'], ['raise', 'coin'], ['cheer', 'drumstick'], ['hip', 'pan']] },
  mobile_legends: { outfit: 'knight', lens: 'blue', cuff: '#ffc21f', looks: [['raise', 'sword'], ['point', 'sword'], ['hip', 'sword'], ['wave', 'gem'], ['cheer', 'sword'], ['raise', 'gem']] },
  free_fire: { outfit: 'survivor', lens: 'amber', cuff: '#d3271f', looks: [['cheer', 'flame'], ['point', 'flame'], ['raise', 'flame'], ['wave', 'gem']] },
  genshin: { outfit: 'mage', lens: 'violet', cuff: '#ffcf5c', cape: '#5c3ba6', looks: [['raise', 'staff'], ['point', 'staff']] },
  google_play: { outfit: 'courier', lens: 'green', cuff: '#0b6d72', looks: [['front', 'gift'], ['point', 'gift'], ['raise', 'gift'], ['wave', 'bolt']] },
  apple: { outfit: 'music', lens: 'pink', cuff: '#ff5fbf', looks: [['wave', 'phone'], ['point', 'phone'], ['raise', 'phone']] },
  psn: { outfit: 'gamer', lens: 'ruby', cuff: '#3fd9ff', looks: [['front', 'gamepad'], ['cheer', 'gamepad']] },
  telegram: { outfit: 'pilot', lens: 'sky', cuff: '#6d4324', looks: [['raise', 'wand'], ['front', 'gift'], ['point', 'wand'], ['cheer', 'wand']] },
  steam: { outfit: 'steam', lens: 'sky', cuff: '#66c0f4', looks: [['front', 'gamepad'], ['point', 'gift'], ['cheer', 'gamepad'], ['raise', 'gift']] },
  xbox: { outfit: 'xbox', lens: 'lime', cuff: '#107c10', looks: [['front', 'gamepad'], ['cheer', 'gamepad'], ['point', 'gift']] },
  nintendo: { outfit: 'nintendo', lens: 'red', cuff: '#e60012', looks: [['front', 'gamepad'], ['wave', 'gift'], ['cheer', 'gamepad']] },
  battlenet: { outfit: 'battle', lens: 'blue', cuff: '#148eff', cape: '#0b2e6b', looks: [['raise', 'sword'], ['point', 'sword'], ['front', 'gift']] },
  razer: { outfit: 'razer', lens: 'lime', cuff: '#44d62c', looks: [['front', 'gift'], ['point', 'bolt'], ['raise', 'gift']] },
  telegram_premium: { outfit: 'premium', lens: 'violet', cuff: '#5b3fa8', looks: [['raise', 'wand'], ['front', 'gift'], ['point', 'wand']] },
  discord_nitro: { outfit: 'nitro', lens: 'pink', cuff: '#5865f2', looks: [['wave', 'phone'], ['front', 'gift'], ['cheer', 'gem']] },
  brawl_stars: { outfit: 'brawl', lens: 'amber', cuff: '#ffc400', looks: [['cheer', 'gem'], ['point', 'flame'], ['raise', 'gem'], ['wave', 'drumstick']] },
  roblox: { outfit: 'roblox', lens: 'ruby', cuff: '#d62a20', looks: [['raise', 'coin'], ['front', 'gift'], ['point', 'coin']] },
  fortnite: { outfit: 'vbucks', lens: 'sky', cuff: '#4fc3ff', looks: [['raise', 'coin'], ['cheer', 'coin'], ['point', 'gift']] },
  valorant: { outfit: 'valorant', lens: 'red', cuff: '#ff4655', looks: [['raise', 'coin'], ['point', 'sword'], ['hip', 'coin']] },
  clash_royale: { outfit: 'royal', lens: 'gold', cuff: '#ffc21f', cape: '#1d4fc4', looks: [['raise', 'sword'], ['point', 'gem'], ['cheer', 'sword']] },
  clash_of_clans: { outfit: 'clans', lens: 'amber', cuff: '#ffd23f', cape: '#7a3b12', looks: [['raise', 'staff'], ['point', 'gem'], ['wave', 'staff']] },
  honkai_star_rail: { outfit: 'starrail', lens: 'sky', cuff: '#ffd98a', cape: '#2a3f8f', looks: [['raise', 'staff'], ['point', 'wand'], ['cheer', 'staff']] },
  zenless_zone_zero: { outfit: 'zenless', lens: 'amber', cuff: '#ffd500', looks: [['point', 'phone'], ['cheer', 'gem'], ['wave', 'phone']] },
  wuthering_waves: { outfit: 'waves', lens: 'green', cuff: '#2ec4b6', looks: [['raise', 'staff'], ['point', 'gem'], ['cheer', 'staff']] },
  codm: { outfit: 'codm', lens: 'orange', cuff: '#c2a35a', looks: [['raise', 'coin'], ['hip', 'coin'], ['point', 'gift']] },
  fc_mobile: { outfit: 'football', lens: 'blue', cuff: '#1f6fff', looks: [['cheer', 'coin'], ['raise', 'coin'], ['point', 'gift']] },
  honor_of_kings: { outfit: 'kings', lens: 'gold', cuff: '#ffcf4a', cape: '#7a0f16', looks: [['raise', 'sword'], ['point', 'gem'], ['cheer', 'sword']] },
  standoff2: { outfit: 'standoff', lens: 'orange', cuff: '#ff8a1e', looks: [['raise', 'coin'], ['point', 'coin'], ['hip', 'gift']] },
};
// Игры из games.json: цвета обложки и образ дракона
export function addGames(games) {
  for (const [k, g] of Object.entries(games)) { THEMES[k] ??= {title: g.title, ...g.theme}; LOOKS[k] ??= g.look; }
}
const RU_FLAG = ['#fff', '#2a5bd7', '#d8232a'];
const REGIONS = {
  ru: ['Только РФ', RU_FLAG], cis: ['РФ и СНГ', RU_FLAG], global: ['Global, не РФ', null],
  tr: ['Турция', ['#e30a17', '#e30a17', '#e30a17']], in: ['Индия', ['#ff9933', '#fff', '#138808']], de: ['Германия', ['#111', '#d00', '#ffce00']],
  es: ['Испания', ['#c60b1e', '#ffc400', '#c60b1e']], fr: ['Франция', null], pl: ['Польша', ['#fff', '#fff', '#dc143c']], us: ['США', ['#b22234', '#fff', '#b22234']], id: ['Индонезия', ['#ce1126', '#ce1126', '#fff']],
  nl: ['Нидерланды', ['#ae1c28', '#fff', '#21468b']],
  br: ['Бразилия', null], jp: ['Япония', null],  // полосами их флаги не узнать — только подпись
  // 06.11: страны карт Steam, Xbox, Nintendo, Battle.net, Razer — только подпись
  kz: ['Казахстан', null], ar: ['Аргентина', null], mx: ['Мексика', null], ca: ['Канада', null], au: ['Австралия', null],
  gb: ['Великобритания', null], hk: ['Гонконг', null], my: ['Малайзия', null], ph: ['Филиппины', null], cl: ['Чили', null],
  no: ['Норвегия', null], ch: ['Швейцария', null], ae: ['ОАЭ', null], sa: ['Сауд. Аравия', null], za: ['ЮАР', null],
  nz: ['Новая Зеландия', null], co: ['Колумбия', null], pe: ['Перу', null], th: ['Таиланд', null], cn: ['Китай', null],
  eu: ['Европа', null],
};

const vinyl = (color, o = {}) => new THREE.MeshPhysicalMaterial({ color, roughness: .38, clearcoat: .7, clearcoatRoughness: .22, ...o });
function heldProp(kind, t) {
  const g = new THREE.Group(), gold = () => new THREE.MeshPhysicalMaterial({ color: '#ffc21f', metalness: .3, roughness: .22, clearcoat: 1, clearcoatRoughness: .1, emissive: '#ff9d00', emissiveIntensity: .32 });
  let o;
  if (kind === 'coin') { o = coinOf(t); o.scale.setScalar(.5); o.position.y = .48; o.rotation.y = -.1; }
  else if (kind === 'bolt') { o = new THREE.Mesh(new THREE.ExtrudeGeometry(boltShape(), { depth: .1, bevelEnabled: true, bevelThickness: .06, bevelSize: .06, bevelSegments: 12 }), gold()); o.geometry.center(); o.scale.setScalar(.8); o.position.set(.06, .36, 0); o.rotation.z = -.2; o.castShadow = true; }
  else if (kind === 'gem') { o = makeGem(t.gem); o.scale.setScalar(.42); o.position.y = .46; o.rotation.set(.3, .4, 0); }
  else if (kind === 'staff') o = PROPS.staff(makeCrystal(t.gem));
  else if (kind === 'wand') o = PROPS.wand(makeStar());
  else if (kind === 'gift') { o = PROPS.gift(); o.position.y = .46; }
  else if (kind === 'gamepad') { o = PROPS.gamepad(); o.position.y = .3; }
  else o = PROPS[kind]();
  g.add(o); g.userData.centered = kind === 'gift' || kind === 'gamepad';
  o.traverse(m => { if (m.isMesh) m.castShadow = true; });
  return g;
}

function boltShape() {
  const s = new THREE.Shape();
  [[.12, .9], [-.42, -.08], [-.06, -.08], [-.2, -.9], [.44, .2], [.06, .2], [.3, .9]].forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y)));
  s.closePath(); return s;
}

function makeGem(color) {
  const ring = (n, r, y, off = 0) => Array.from({ length: n }, (_, i) => { const a = (i + off) / n * Math.PI * 2; return new THREE.Vector3(Math.cos(a) * r, y, Math.sin(a) * r); });
  const table = ring(8, .56, .6), star = ring(8, .8, .42, .5), girdle = ring(16, 1, .14), culet = new THREE.Vector3(0, -1, 0), tri = [];
  for (let i = 0; i < 8; i++) {
    const j = (i + 1) % 8, g0 = i * 2, g1 = (g0 + 1) % 16, g2 = (g0 + 2) % 16, tc = new THREE.Vector3(0, .6, 0);
    tri.push(tc, table[j], table[i]);
    tri.push(table[i], table[j], star[i]);
    tri.push(table[i], star[i], girdle[g0]); tri.push(star[i], table[j], girdle[g2]);
    tri.push(star[i], girdle[g1], girdle[g0]); tri.push(star[i], girdle[g2], girdle[g1]);
    tri.push(girdle[g0], girdle[g1], culet); tri.push(girdle[g1], girdle[g2], culet);
  }
  const geo = new THREE.BufferGeometry().setFromPoints(tri); geo.computeVertexNormals();
  // Постоянный разброс оттенков граней даёт блеск без случайного мерцания между обложками.
  const base = new THREE.Color(color), hi = new THREE.Color('#ffffff'), col = [];
  for (let f = 0; f < tri.length / 3; f++) { const k = ((f * 37) % 11) / 11, c = base.clone().lerp(k < .5 ? new THREE.Color('#06123a') : hi, Math.abs(k - .5) * .9); for (let v = 0; v < 3; v++) col.push(c.r, c.g, c.b); }
  geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  const g = new THREE.Group();
  const inner = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ vertexColors: true, side: THREE.BackSide, flatShading: true, roughness: .12, metalness: .3, emissive: color, emissiveIntensity: .5 })); g.add(inner);
  const outer = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ vertexColors: true, flatShading: true, roughness: .04, metalness: .35, clearcoat: 1, clearcoatRoughness: .02, iridescence: .5, iridescenceIOR: 1.6, envMapIntensity: 1.3, transparent: true, opacity: .86, emissive: color, emissiveIntensity: .1 }));
  outer.castShadow = true; g.add(outer);
  return g;
}

function makeStar() {
  const s = new THREE.Shape();
  for (let i = 0; i < 10; i++) {
    const a = Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? .46 : 1, x = Math.cos(a) * r, y = Math.sin(a) * r;
    if (i) s.lineTo(x, y); else s.moveTo(x, y);
  }
  s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: .22, bevelEnabled: true, bevelThickness: .14, bevelSize: .12, bevelSegments: 12 }); g.center();
  return new THREE.Mesh(g, new THREE.MeshPhysicalMaterial({ color: '#ffd02e', metalness: .35, roughness: .24, clearcoat: 1, emissive: '#ff9d00', emissiveIntensity: .42 }));
}

function makeCard(spec, t) {
  const c = document.createElement('canvas'); c.width = 1024; c.height = 640; const x = c.getContext('2d');
  const lg = x.createLinearGradient(0, 0, 1024, 640); lg.addColorStop(0, t.bg[1]); lg.addColorStop(1, t.bg[2]); x.fillStyle = lg; x.fillRect(0, 0, 1024, 640);
  x.globalAlpha = .13; x.fillStyle = '#fff'; x.beginPath(); x.arc(860, 560, 400, 0, Math.PI * 2); x.fill(); x.globalAlpha = 1;
  x.fillStyle = '#ffd66b'; x.beginPath(); x.roundRect(76, 96, 136, 104, 22); x.fill();
  x.fillStyle = '#fff'; x.font = `900 104px ${FONT}`; x.textBaseline = 'middle'; x.fillText(t.title, 72, 480);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 16;
  const edge = vinyl(t.side, { roughness: .3 }), face = new THREE.MeshPhysicalMaterial({ map: tex, roughness: .5, clearcoat: .35, clearcoatRoughness: .35, envMapIntensity: .6 });
  const m = new THREE.Mesh(new RoundedBoxGeometry(3.2, 2, .14, 8, .06), [edge, edge, edge, edge, face, edge]);
  m.castShadow = true; m.receiveShadow = true;
  // вторая карта позади даёт стопке толщину
  const back = new THREE.Mesh(new RoundedBoxGeometry(3.2, 2, .12, 8, .05), vinyl(t.gem, { roughness: .28 })); back.position.set(.2, .13, -.26); back.rotation.z = -.07; back.castShadow = true;
  const g = new THREE.Group(); g.add(back, m); return g;
}

function coinFace(label, size) {
  const c = document.createElement('canvas'); c.width = c.height = 1024; const x = c.getContext('2d');
  const rg = x.createRadialGradient(400, 340, 60, 512, 512, 620); rg.addColorStop(0, '#fff3b5'); rg.addColorStop(.55, '#ffc928'); rg.addColorStop(1, '#d68a00'); x.fillStyle = rg; x.fillRect(0, 0, 1024, 1024);
  x.font = `900 ${size}px Inter, Arial`; x.textAlign = 'center'; x.textBaseline = 'middle'; x.fillStyle = '#7d4c00'; x.fillText(label, 512, 540);
  const b = document.createElement('canvas'); b.width = b.height = 1024; const y = b.getContext('2d');
  y.fillStyle = '#404040'; y.fillRect(0, 0, 1024, 1024); y.filter = 'blur(5px)'; y.font = x.font; y.textAlign = 'center'; y.textBaseline = 'middle'; y.fillStyle = '#fff'; y.fillText(label, 512, 540);
  const map = new THREE.CanvasTexture(c), bump = new THREE.CanvasTexture(b); map.colorSpace = THREE.SRGBColorSpace; map.anisotropy = bump.anisotropy = 16;
  return { map, bump };
}

function makeCoinMesh(label, size) {
  const { map, bump } = coinFace(label, size);
  const prof = [[0, .075], [.76, .075], [.8, .12], [.9, .135], [.97, .115], [1, .07], [1, -.07], [.97, -.115], [.9, -.135], [.8, -.12], [.76, -.075], [0, -.075]].map(([r, y]) => new THREE.Vector2(r, y));
  const geo = new THREE.LatheGeometry(prof, 144);
  const pos = geo.attributes.position, uv = geo.attributes.uv;
  for (let i = 0; i < pos.count; i++) uv.setXY(i, pos.getX(i) * .5 + .5, -pos.getZ(i) * .5 + .5);
  const m = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ map, bumpMap: bump, bumpScale: 2.4, metalness: .3, roughness: .32, clearcoat: .7, clearcoatRoughness: .2, emissive: '#ff9d00', emissiveIntensity: .1 }));
  m.rotation.x = Math.PI / 2; m.castShadow = true; m.receiveShadow = true;
  const g = new THREE.Group(); g.add(m); return g;
}
const makeCoin = () => makeCoinMesh('UC', 440);
const coinOf = t => (t && t.coin ? makeCoinMesh(...t.coin) : makeCoin());

function makeCrystal(color) {
  const p = [[0, -1.25], [.56, -.42], [.56, .42], [0, 1.25]].map(([x, y]) => new THREE.Vector2(x, y));
  const geo = new THREE.LatheGeometry(p, 6).toNonIndexed(); geo.computeVertexNormals();
  return new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ color, flatShading: true, roughness: .05, metalness: .15, clearcoat: 1, iridescence: .8, iridescenceIOR: 1.5, envMapIntensity: 1.7, emissive: color, emissiveIntensity: .2 }));
}

// Значок товара: глянцевая плитка с маленьким объёмным предметом. Логотипы брендов не рисуем.
function makeIcon(spec, t) {
  const g = new THREE.Group();
    const well = new THREE.Mesh(new RoundedBoxGeometry(.92, .92, .16, 10, .08), new THREE.MeshPhysicalMaterial({ color: t.bg[1], roughness: .3, clearcoat: 1 })); well.castShadow = true; g.add(well);
  let o;
  if (spec.hero === 'gem') { o = makeGem(t.gem); o.scale.setScalar(.36); o.rotation.set(.3, .5, 0); o.position.y = .05; }
  else if (spec.hero === 'uc') { o = coinOf(t); o.scale.setScalar(.31); o.rotation.y = -.25; }
  else if (spec.hero === 'star') { o = makeStar(); o.scale.setScalar(.31); o.rotation.y = -.25; }
  else if (spec.hero === 'crystal') { o = makeCrystal(t.gem); o.scale.setScalar(.3); o.rotation.set(.1, .4, .25); }
  else {
    o = new THREE.Group(); const cd = new THREE.Mesh(new RoundedBoxGeometry(.66, .44, .06, 6, .03), new THREE.MeshPhysicalMaterial({ color: t.gem, roughness: .25, clearcoat: 1, emissive: t.gem, emissiveIntensity: .15 })); o.add(cd);
    const band = new THREE.Mesh(new THREE.BoxGeometry(.66, .08, .07), new THREE.MeshPhysicalMaterial({ color: '#ffd02e', roughness: .25, clearcoat: 1 })); band.position.y = .08; o.add(band); o.rotation.set(0, -.25, .12);
  }
  o.position.z = .24; g.add(o); g.rotation.set(.03, .1, 0); return g;
}

// Объёмный фон: свой рисунок у каждой темы; набор случайных чисел постоянный, чтобы обложки не «плясали».
function makeBackdrop(t) {
  let seed = 11; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const a = new THREE.Color(t.side), b = new THREE.Color(t.bg[2]), g = new THREE.Group(), dummy = new THREE.Object3D();
  const place = (geo, mat, items) => {
    const im = new THREE.InstancedMesh(geo, mat, items.length);
    items.forEach((it, i) => { dummy.position.set(...it.p); dummy.rotation.set(...it.r); dummy.scale.set(...it.s); dummy.updateMatrix(); im.setMatrixAt(i, dummy.matrix); im.setColorAt(i, a.clone().lerp(b, it.c)); });
    g.add(im);
  };
  const mode = t.backdrop, rows = [];
  const CX = 2.4, bowl = x => -10.5 + .62 * Math.abs(x - CX), turn = x => -Math.sign(x - CX) * .55;
  const tone = (x, y) => THREE.MathUtils.clamp(.2 + (x + 12) / 24 * .5 + (y + 8) / 16 * .12 + rnd() * .22, 0, 1);
  if (mode === 'hex') {
    for (let y = -10; y <= 11; y++) for (let x = -19; x <= 19; x++) { const px = x * 1.08 + (y % 2 ? .54 : 0), py = y * .94; rows.push({ p: [px, py, bowl(px) + rnd() * 1.6], r: [Math.PI / 2, 0, 0], s: [.6, 2.4, .6], c: tone(px, py) }); }
    place(new THREE.CylinderGeometry(1, 1, 1, 6), new THREE.MeshPhysicalMaterial({ roughness: .35, metalness: .45, clearcoat: .6 }), rows);
  } else if (mode === 'tiles') {
    for (let y = -8; y <= 9; y++) for (let x = -16; x <= 16; x++) { const px = x * 1.22, py = y * 1.22; rows.push({ p: [px, py, bowl(px) + rnd() * 1.8], r: [(rnd() - .5) * .35, turn(px) + (rnd() - .5) * .35, 0], s: [1, 1, 1], c: tone(px, py) }); }
    place(new RoundedBoxGeometry(1.1, 1.1, .3, 5, .1), new THREE.MeshPhysicalMaterial({ roughness: .24, metalness: .25, clearcoat: 1 }), rows);
  } else if (mode === 'crates') {
    // штабель ящиков стоит на полу и расходится в стороны, как стены склада
    for (let y = 0; y <= 9; y++) for (let x = -13; x <= 13; x++) { const px = x * 1.62 + (y % 2 ? .8 : 0), py = -2.7 + .7 + y * 1.42; if (rnd() < .12 && y > 5) continue; rows.push({ p: [px, py, bowl(px) + rnd() * 1.1], r: [0, turn(px) + (rnd() - .5) * .14, 0], s: [1, 1, 1], c: tone(px, py) * .46 }); }
    place(new RoundedBoxGeometry(1.5, 1.4, 1.1, 3, .05), new THREE.MeshStandardMaterial({ roughness: .78, metalness: .1 }), rows);
    const bars = rows.flatMap(r => [-.48, .48].map(d => ({ p: [r.p[0] + Math.sin(r.r[1]) * .56, r.p[1] + d, r.p[2] + Math.cos(r.r[1]) * .56], r: r.r, s: [1, 1, 1], c: r.c + .1 })));
    place(new THREE.BoxGeometry(1.5, .13, .06), new THREE.MeshStandardMaterial({ roughness: .7, metalness: .2 }), bars);
  } else if (mode === 'stars') {
    for (let i = 0; i < 170; i++) { const z = -4 - rnd() * 13, k0 = (15 - z) / 15, px = CX + (rnd() - .5) * 15 * k0, py = (rnd() - .5) * 10 * k0, k = .22 + rnd() * .5; rows.push({ p: [px, py, z], r: [(rnd() - .5) * .8, (rnd() - .5) * .8, rnd() * 6], s: [k, k, k], c: tone(px, py) }); }
    const st = makeStar(); place(st.geometry, new THREE.MeshPhysicalMaterial({ roughness: .3, metalness: .3, clearcoat: 1 }), rows);
  } else {
    // кристаллы и осколки разбросаны в глубину: ближние крупнее и резче, дальние тонут в дымке
    const crystals = mode === 'crystals';
    for (let i = 0; i < 260; i++) { const z = -3.5 - rnd() * 13, k0 = (15 - z) / 15, px = CX + (rnd() - .5) * 17 * k0, py = (rnd() - .35) * 9 * k0, k = .55 + rnd() * 1.1; if (z > -7 && Math.hypot(px - CX, py) < 3.2) continue; rows.push({ p: [px, py, z], r: [(rnd() - .5) * (crystals ? .5 : 2.6), (rnd() - .5) * 2, crystals ? (rnd() - .5) * .5 : rnd() * 6], s: [k, k * (crystals ? 1.6 : 1), k], c: tone(px, py) }); }
    const lg = makeCrystal('#ffffff').geometry;
    place(lg, new THREE.MeshPhysicalMaterial({ flatShading: true, roughness: .16, metalness: .3, clearcoat: 1 }), rows);
  }
  return g;
}

const heroOf = (spec, t) => (spec.hero === 'card' ? makeCard(spec, t) : spec.hero === 'star' ? makeStar() : spec.hero === 'uc' ? coinOf(t) : spec.hero === 'crystal' ? makeCrystal(t.gem) : makeGem(t.gem));
const smallOf = (spec, t) => {
  if (spec.hero === 'star') return makeStar();
  if (spec.hero === 'uc') return coinOf(t);
  if (spec.hero === 'crystal') return makeCrystal(t.gem);
  if (spec.hero === 'card') return new THREE.Mesh(new THREE.TorusGeometry(.6, .24, 32, 64), new THREE.MeshPhysicalMaterial({ color: '#ffd02e', metalness: .35, roughness: .24, clearcoat: 1, emissive: '#ff9d00', emissiveIntensity: .42 }));
  return makeGem(t.gem);
};

// Студия: мягкий купол и размытые софтбоксы в цвете темы, поэтому блики плавные, без прямоугольных пятен.
function studioEnv(renderer, t) {
  const sc = new THREE.Scene(), c = document.createElement('canvas'); c.width = 16; c.height = 256; const x = c.getContext('2d');
  const lg = x.createLinearGradient(0, 0, 0, 256); lg.addColorStop(0, '#f4f6ff'); lg.addColorStop(.42, t.glow); lg.addColorStop(.6, t.bg[1]); lg.addColorStop(1, t.bg[0]); x.fillStyle = lg; x.fillRect(0, 0, 16, 256);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  sc.add(new THREE.Mesh(new THREE.SphereGeometry(30, 32, 32), new THREE.MeshBasicMaterial({ map: tex, color: new THREE.Color(.42, .42, .42), side: THREE.BackSide })));
  const box = (color, power, w, h, p) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(power), side: THREE.DoubleSide })); m.position.set(...p); m.lookAt(0, 0, 0); sc.add(m); };
  box('#fff5e6', 6, 13, 9, [-10, 15, 12]); box(t.glow, 5, 4, 22, [18, 3, -6]); box('#ffffff', 1.1, 22, 4, [5, -3, 20]); box(t.glow, 2.5, 4, 20, [-20, 0, -4]);
  const pm = new THREE.PMREMGenerator(renderer), env = pm.fromScene(sc, .05).texture; pm.dispose(); return env;
}

let core = null;
const envs = {};
async function getCore() {
  if (core) return core;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1); renderer.setSize(W * SS, H * SS, false); renderer.setClearColor(0, 0);
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1; renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const font = await new FontLoader().loadAsync(new URL('./vendor/helvetiker_bold.typeface.json', import.meta.url).href);
  await Promise.all(['600 30px Inter', '700 30px Inter', '800 30px Inter', '900 30px Inter'].map(f => document.fonts.load(f, 'Алмазов123')));
  return (core = { renderer, font });
}

// Детали флагов поверх полос: по одним полосам Турцию и США не узнать.
const FLAG_MARKS = {
  tr: (g, x, y) => {
    g.fillStyle = '#fff'; g.beginPath(); g.arc(x - 4, y, 11, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#e30a17'; g.beginPath(); g.arc(x - 1.5, y, 8.8, 0, Math.PI * 2); g.fill();
    g.fillStyle = '#fff'; g.beginPath();
    for (let i = 0; i < 10; i++) { const a = -Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 2.2 : 5.2; g.lineTo(x + 9 + Math.cos(a) * r, y + Math.sin(a) * r); }
    g.closePath(); g.fill();
  },
  us: (g, x, y) => { g.fillStyle = '#3c3b6e'; g.fillRect(x - 20, y - 20, 22, 20); g.fillStyle = '#fff'; [[-11, -13], [-4, -13], [-11, -6], [-4, -6]].forEach(([a, b]) => { g.beginPath(); g.arc(x + a, y + b, 1.9, 0, Math.PI * 2); g.fill(); }); },
  in: (g, x, y) => { g.strokeStyle = '#000080'; g.lineWidth = 1.8; g.beginPath(); g.arc(x, y, 5, 0, Math.PI * 2); g.stroke(); },
};

// Мягкое пятно контактной тени: предмет стоит на поверхности, а не висит над ней.
let blobTex = null;
function makeBlob(x, y, z, rx, rz, opacity) {
  if (!blobTex) {
    const c = document.createElement('canvas'); c.width = c.height = 256; const b = c.getContext('2d');
    const rg = b.createRadialGradient(128, 128, 0, 128, 128, 128); rg.addColorStop(0, 'rgba(0,0,0,1)'); rg.addColorStop(.5, 'rgba(0,0,0,.72)'); rg.addColorStop(1, 'rgba(0,0,0,0)');
    b.fillStyle = rg; b.fillRect(0, 0, 256, 256); blobTex = new THREE.CanvasTexture(c);
  }
  const m = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), new THREE.MeshBasicMaterial({ map: blobTex, transparent: true, opacity, depthWrite: false, fog: false, toneMapped: false }));
  m.rotation.x = -Math.PI / 2; m.scale.set(rx, rz, 1); m.position.set(x, y, z); return m;
}

function rr(g, x, y, w, h, r) { g.beginPath(); g.roundRect(x, y, w, h, r); }

function drawBase(g, t) {
  const lin = g.createLinearGradient(0, 0, W, H);
  lin.addColorStop(0, t.bg[0]); lin.addColorStop(.55, t.bg[1]); lin.addColorStop(1, t.bg[2]); g.fillStyle = lin; g.fillRect(0, 0, W, H);
}

// Затемняем левую часть под текстом, за маскотом оставляем свет и лучи.
function drawVeil(g, t) {
  const lv = g.createLinearGradient(0, 0, 780, 0); lv.addColorStop(0, t.bg[0] + 'f2'); lv.addColorStop(.62, t.bg[0] + 'b0'); lv.addColorStop(1, t.bg[0] + '00'); g.fillStyle = lv; g.fillRect(0, 0, W, H);
  const rad = g.createRadialGradient(880, 400, 0, 880, 400, 540); rad.addColorStop(0, t.glow + '80'); rad.addColorStop(1, t.glow + '00'); g.fillStyle = rad; g.fillRect(0, 0, W, H);
  g.save(); g.globalCompositeOperation = 'overlay'; g.translate(880, 400);
  for (let i = 0; i < 18; i++) { g.rotate(Math.PI / 9); g.beginPath(); g.moveTo(0, 0); g.lineTo(1100, -70); g.lineTo(1100, 70); g.closePath(); g.fillStyle = 'rgba(255,255,255,.05)'; g.fill(); }
  g.restore();
  const vig = g.createRadialGradient(W / 2, H / 2, 400, W / 2, H / 2, 860); vig.addColorStop(0, 'rgba(0,0,0,0)'); vig.addColorStop(1, 'rgba(0,0,10,.55)'); g.fillStyle = vig; g.fillRect(0, 0, W, H);
}

function drawOverlay(g, spec, t) {
  g.textBaseline = 'middle'; g.textAlign = 'left';
  // бренд
  const title = spec.title || t.title;
  g.font = `800 38px ${FONT}`; const tw = g.measureText(title).width + 52;
  g.save(); g.shadowColor = 'rgba(0,0,0,.5)'; g.shadowBlur = 16; g.shadowOffsetY = 7; rr(g, 180, 54, tw, 62, 31); g.fillStyle = 'rgba(255,255,255,.97)'; g.fill(); g.restore(); g.fillStyle = t.side; g.fillText(title, 206, 86);
  // регион
  const reg = REGIONS[spec.region];
  if (reg) {
    g.font = `800 34px ${FONT}`; const flagW = reg[1] ? 58 : 0, rw = g.measureText(reg[0]).width + 52 + flagW, rx = 180, ry = 126;
    rr(g, rx, ry, rw, 64, 32); g.fillStyle = 'rgba(0,0,0,.42)'; g.fill(); g.strokeStyle = 'rgba(255,255,255,.3)'; g.lineWidth = 2; g.stroke();
    if (reg[1]) {
      g.save(); g.beginPath(); g.arc(rx + 40, ry + 32, 20, 0, Math.PI * 2); g.clip();
      reg[1].forEach((c, i) => { g.fillStyle = c; g.fillRect(rx + 20, ry + 12 + i * 40 / 3, 40, 40 / 3 + 1); }); if (FLAG_MARKS[spec.region]) FLAG_MARKS[spec.region](g, rx + 40, ry + 32); g.restore();
      g.beginPath(); g.arc(rx + 40, ry + 32, 20, 0, Math.PI * 2); g.lineWidth = 2; g.strokeStyle = 'rgba(255,255,255,.8)'; g.stroke();
    }
    g.fillStyle = '#fff'; g.fillText(reg[0], rx + 26 + flagW, ry + 33);
  }
  // единица и подпись под числом
  // длинная единица («древних снов») не должна заходить на товар у подиума: ужимаем шрифт до 470 px ширины
  g.font = `900 84px ${FONT}`;
  const unitW = g.measureText(spec.unit).width;
  if (unitW > 470) g.font = `900 ${Math.floor(84 * 470 / unitW)}px ${FONT}`;
  g.save(); g.shadowColor = 'rgba(0,0,0,.65)'; g.shadowBlur = 20; g.shadowOffsetX = 5; g.shadowOffsetY = 12; g.fillStyle = t.side; g.fillText(spec.unit, 63, 573); g.restore();
  for (let i = 4; i > 0; i--) { g.fillStyle = t.side; g.fillText(spec.unit, 58 + i, 568 + i); }
  g.fillStyle = t.accent; g.fillText(spec.unit, 58, 568);
  g.save(); g.shadowColor = 'rgba(0,0,0,.6)'; g.shadowBlur = 10; g.shadowOffsetY = 3; g.font = `700 40px ${FONT}`; g.fillStyle = 'rgba(255,255,255,.96)'; g.fillText(spec.subtitle, 60, 642); g.restore();
  // преимущества
  const icons = {
    bolt: (x, y) => { g.beginPath(); [[2, -13], [-8, 2], [-1, 2], [-3, 13], [8, -3], [1, -3], [5, -13]].forEach(([a, b], i) => (i ? g.lineTo(x + a, y + b) : g.moveTo(x + a, y + b))); g.closePath(); g.fill(); },
    shield: (x, y) => { g.beginPath(); g.moveTo(x, y - 14); g.lineTo(x + 11, y - 9); g.lineTo(x + 11, y + 1); g.quadraticCurveTo(x + 10, y + 10, x, y + 14); g.quadraticCurveTo(x - 10, y + 10, x - 11, y + 1); g.lineTo(x - 11, y - 9); g.closePath(); g.fill(); g.strokeStyle = '#10222c'; g.lineWidth = 3; g.beginPath(); g.moveTo(x - 5, y); g.lineTo(x - 1, y + 4); g.lineTo(x + 6, y - 5); g.stroke(); },
    lock: (x, y) => { g.strokeStyle = g.fillStyle; g.lineWidth = 3.5; g.beginPath(); g.arc(x, y - 4, 6.5, Math.PI, 0); g.stroke(); rr(g, x - 10, y - 4, 20, 16, 4); g.fill(); },
  };
  // подарок из магазина (Fortnite) приходит через 48 ч по правилам игры — «Быстро» было бы неправдой
  const items = [[/магазин/i.test(spec.subtitle || '') ? 'Любой предмет' : 'Быстро', '#ffd66b', 'bolt'], ['Гарантия', '#7cf2c0', 'shield'], ['Без входа', '#8fd0ff', 'lock']]; let x = 60; const y = 826;
  g.font = `700 30px ${FONT}`;
  items.forEach(([s, c, ic]) => {
    g.fillStyle = c; icons[ic](x + 12, y);
    g.fillStyle = 'rgba(255,255,255,.92)'; g.fillText(s, x + 36, y + 1); x += g.measureText(s).width + 66;
  });
  // подпись продавца
  g.font = `700 26px ${FONT}`; g.fillStyle = 'rgba(255,255,255,.72)'; g.textAlign = 'right'; g.fillText('DragDiller', W - 56, 72); g.textAlign = 'left';
}

// Стили подачи (?style=…): сцена та же — маскот на подиуме и число слева, меняются фон, свет и акценты.
// classic — нынешний вид и вид автообложек; остальные — варианты на выбор владельца.
const halftone = (g, color, from = 520) => {
  g.save(); g.fillStyle = color;
  for (let y = 12; y < H; y += 22) for (let x = from + ((y / 22) % 2 ? 11 : 0); x < W; x += 22) {
    const r = Math.min(7.5, (x - from) / 70 + 1); g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
  }
  g.restore();
};
const burstPath = (g, cx, cy, r1, r2, n, rot = 0) => {
  g.beginPath();
  for (let i = 0; i < n * 2; i++) { const a = rot + i * Math.PI / n, r = i % 2 ? r2 : r1; g.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r); }
  g.closePath();
};
const neonGrid = g => {
  g.save(); g.globalCompositeOperation = 'screen'; g.beginPath(); g.rect(0, 690, W, H - 690); g.clip();
  g.shadowColor = '#ff3cdc'; g.shadowBlur = 14; g.strokeStyle = 'rgba(255,90,225,.75)'; g.lineWidth = 3;
  for (let i = 0; i < 10; i++) { const y = 696 + i * i * 2.6; g.beginPath(); g.moveTo(0, y); g.lineTo(W, y); g.stroke(); }
  for (let i = -16; i <= 16; i++) { g.beginPath(); g.moveTo(860 + i * 30, 696); g.lineTo(860 + i * 200, H); g.stroke(); }
  g.shadowColor = '#3ce6ff'; g.strokeStyle = 'rgba(90,240,255,1)'; g.lineWidth = 4; g.beginPath(); g.moveTo(0, 695); g.lineTo(W, 695); g.stroke();
  g.restore();
};
const STYLES = {
  classic: {},
  // неон: ночная сцена, розово-голубой свет, светящиеся число и сетка пола за подиумом
  neon: {
    theme: t => ({ ...t, bg: ['#03020a', '#0b0720', '#1a0b3a'], accent: '#ff5ce1' }),
    noFloor: true,
    veil(g, t) {
      g.save(); g.globalCompositeOperation = 'screen';
      const r = g.createRadialGradient(880, 420, 0, 880, 420, 520); r.addColorStop(0, t.glow + '66'); r.addColorStop(1, t.glow + '00'); g.fillStyle = r; g.fillRect(0, 0, W, H);
      const p = g.createRadialGradient(60, 900, 0, 60, 900, 700); p.addColorStop(0, 'rgba(255,60,220,.5)'); p.addColorStop(1, 'rgba(255,60,220,0)'); g.fillStyle = p; g.fillRect(0, 0, W, H);
      const c = g.createRadialGradient(1200, 40, 0, 1200, 40, 600); c.addColorStop(0, 'rgba(40,230,255,.42)'); c.addColorStop(1, 'rgba(40,230,255,0)'); g.fillStyle = c; g.fillRect(0, 0, W, H);
      g.restore(); neonGrid(g);
    },
    numGlow: 1,
  },
  // солнце: яркие тёплые лучи от маскота, как у праздничной витрины
  burst: {
    theme: t => ({ ...t, accent: '#ffe14d' }),
    veil(g, t) {
      g.save(); g.translate(880, 420);
      const c = g.createRadialGradient(0, 0, 0, 0, 0, 640); c.addColorStop(0, 'rgba(255,214,90,.75)'); c.addColorStop(.5, 'rgba(255,170,40,.28)'); c.addColorStop(1, 'rgba(255,150,30,0)'); g.fillStyle = c; g.fillRect(-900, -900, 1800, 1800);
      for (let i = 0; i < 28; i++) { g.rotate(Math.PI / 14); if (i % 2) continue; g.beginPath(); g.moveTo(0, 0); g.lineTo(1400, -170); g.lineTo(1400, 170); g.closePath(); g.fillStyle = 'rgba(255,236,160,.3)'; g.fill(); }
      g.restore();
      const lv = g.createLinearGradient(0, 0, 620, 0); lv.addColorStop(0, t.bg[0] + 'd8'); lv.addColorStop(1, t.bg[0] + '00'); g.fillStyle = lv; g.fillRect(0, 0, W, H);
    },
  },
  // комикс: растр, взрыв за числом с жирным контуром и реплика маскота
  comic: {
    theme: t => ({ ...t, accent: '#ffe14d' }),
    veil(g, t) {
      halftone(g, 'rgba(255,255,255,.16)', 470);
      g.save(); burstPath(g, 300, 420, 330, 236, 13, .12);
      g.fillStyle = t.bg[2]; g.globalAlpha = .9; g.fill(); g.globalAlpha = 1; g.lineWidth = 10; g.strokeStyle = '#0b0c12'; g.lineJoin = 'round'; g.stroke();
      g.clip(); halftone(g, 'rgba(0,0,0,.22)', 0); g.restore();
    },
    after(g, spec) {
      const x = 640, y = 92, w = 330, h = 112;
      g.save(); g.shadowColor = 'rgba(0,0,0,.45)'; g.shadowBlur = 14; g.shadowOffsetY = 8;
      rr(g, x, y, w, h, 30); g.fillStyle = '#fff'; g.fill(); g.restore();
      g.beginPath(); g.moveTo(x + w - 90, y + h - 2); g.lineTo(x + w - 40, y + h + 44); g.lineTo(x + w - 40, y + h - 2); g.closePath(); g.fillStyle = '#fff'; g.fill();
      rr(g, x, y, w, h, 30); g.lineWidth = 5; g.strokeStyle = '#11131c'; g.stroke();
      g.fillStyle = '#11131c'; g.font = `800 34px ${FONT}`; g.textAlign = 'center';
      // реплика по товару: донат по ID зачисляют, звёзды и подписки дарят, остальное — код
      const sub = spec.subtitle || '', shop = /магазин/i.test(sub), line = shop ? 'Подарим' : /ID|UID|тег|ник/i.test(sub) ? 'Зачислим' : /Подарком|ссылк/i.test(sub) ? 'Отправим' : 'Код в чате';
      const detail = /ID|UID|тег|ник/i.test(sub) ? 'По данным игрока' : 'В чате заказа';
      g.fillText(line, x + w / 2, y + 40); g.font = `700 28px ${FONT}`; g.fillText(detail, x + w / 2, y + 78); g.textAlign = 'left';
    },
  },
  // люкс: чёрное с золотом — подиум, грани числа и блики золотые у любого сервиса
  luxe: {
    theme: t => ({ ...t, bg: ['#040404', '#14100a', '#5a4318'], side: '#3a2a0c', accent: '#ffd27a', glow: '#ffcf70' }),
    veil(g) {
      g.save(); g.globalCompositeOperation = 'screen';
      [[680, .3], [860, .2], [1030, .14]].forEach(([x, a]) => {
        const lg = g.createLinearGradient(-110, 0, 110, 0); lg.addColorStop(0, 'rgba(255,210,130,0)'); lg.addColorStop(.5, `rgba(255,210,130,${a})`); lg.addColorStop(1, 'rgba(255,210,130,0)');
        g.save(); g.translate(x, 0); g.transform(1, 0, -.35, 1, 0, 0); g.fillStyle = lg; g.fillRect(-110, 0, 220, H); g.restore();
      });
      g.restore();
    },
    numGlow: .3,
  },
};

export async function renderCard(spec) {
  const { renderer, font } = await getCore();
  const S = STYLES[spec.style] || STYLES.classic;
  const t = S.theme ? S.theme(THEMES[spec.brand]) : THEMES[spec.brand];
  const envKey = `${spec.brand}:${spec.style || 'classic'}`;
  const scene = new THREE.Scene(); scene.environment = envs[envKey] || (envs[envKey] = studioEnv(renderer, t));
  scene.fog = new THREE.Fog(t.bg[1], 19, 36);
  const cam = new THREE.PerspectiveCamera(30, W / H, .1, 100); cam.position.set(0, 1.05, 14.6); cam.lookAt(0, .02, 0);

  scene.add(new THREE.AmbientLight('#ffffff', .05));
  const key = new THREE.DirectionalLight('#fff1dc', 3.4); key.position.set(-5.5, 9, 9); key.castShadow = true;
  key.shadow.mapSize.set(4096, 4096); Object.assign(key.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9, far: 40 }); key.shadow.bias = -.0003; key.shadow.normalBias = .02; scene.add(key);
  const rim = new THREE.DirectionalLight(t.glow, 3.6); rim.position.set(7, 4, -7); scene.add(rim);
  const rim2 = new THREE.DirectionalLight(t.glow, 2); rim2.position.set(-6, 1, -6); scene.add(rim2);
  const fill = new THREE.PointLight(t.glow, 16, 9, 2); fill.position.set(2.4, -1.5, 3); scene.add(fill);

  // пол растворяется в дымке, поэтому у сцены есть низ и даль, а не только фон
  const floorY = -2.72, fc = document.createElement('canvas'); fc.width = fc.height = 512; const fx = fc.getContext('2d');
  const fg = fx.createRadialGradient(256, 256, 30, 256, 256, 256); fg.addColorStop(0, '#fff'); fg.addColorStop(.55, '#bbb'); fg.addColorStop(1, '#000'); fx.fillStyle = fg; fx.fillRect(0, 0, 512, 512);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(15, 96), new THREE.MeshPhysicalMaterial({ color: t.bg[0], roughness: .34, metalness: .3, clearcoat: .6, clearcoatRoughness: .25, envMapIntensity: .3, transparent: true, alphaMap: new THREE.CanvasTexture(fc), fog: false }));
  floor.rotation.x = -Math.PI / 2; floor.position.set(2.4, floorY, -3); floor.receiveShadow = true; if (!S.noFloor) scene.add(floor);

  // ступенчатый подиум со светящимся пазом
  const stage = new THREE.Group(); stage.position.set(2.42, -1.12, 0); scene.add(stage);
  const prof = [[0, -.93], [2.08, -.93], [2.2, -.95], [2.26, -1.02], [2.26, -1.2], [2.34, -1.26], [2.72, -1.26], [2.84, -1.32], [2.9, -1.42], [2.9, -1.6], [0, -1.6]].reverse().map(([r, y]) => new THREE.Vector2(r, y));
  const podium = new THREE.Mesh(new THREE.LatheGeometry(prof, 160), new THREE.MeshPhysicalMaterial({ color: t.side, roughness: .26, metalness: .5, clearcoat: 1, clearcoatRoughness: .12 }));
  podium.castShadow = true; podium.receiveShadow = true; stage.add(podium);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(2.3, .028, 16, 200), new THREE.MeshBasicMaterial({ color: new THREE.Color(t.glow).multiplyScalar(1.6), fog: false }));
  ring.rotation.x = Math.PI / 2; ring.position.y = -1.23; stage.add(ring);
  const ring2 = new THREE.Mesh(new THREE.TorusGeometry(1.86, .016, 12, 200), new THREE.MeshBasicMaterial({ color: t.glow, fog: false }));
  ring2.rotation.x = Math.PI / 2; ring2.position.y = -.925; stage.add(ring2);

  // маскот: образ сервиса, поза и предмет зависят от карточки
  const L = LOOKS[spec.brand], [pose, kind] = L.looks[(spec.look || 0) % L.looks.length];
  const held = heldProp(kind, t);
  if (held.userData.centered && pose === 'front') { held.children[0].position.y = kind === 'gift' ? -.14 : 0; if (kind === 'gift') held.children[0].scale.setScalar(.86); }
  const medal = makeCoinMesh('D', 620); medal.scale.setScalar(.2);
  const capeT = L.outfit === 'knight' ? (spec.region === 'ru' ? '#b0132f' : '#1d4fc4') : L.cape;
  const mascot = makeMascot({ pose, outfit: L.outfit, lens: L.lens, cuff: L.cuff, cape: capeT }, { held, medal });
  mascot.scale.setScalar(1.24); mascot.rotation.y = -.34; mascot.rotation.z = .025; mascot.position.y = .97; stage.add(mascot);
  stage.add(makeBlob(.05, -.922, .28, 1.5, .95, .7), makeBlob(1.55, -.922, -.35, .95, .5, .42));

  // товар лежит у подножия: ближе к камере, крупнее, с тенью на подиуме
  const hero = heroOf(spec, t); const isCard = spec.hero === 'card'; const front = [hero];
  hero.scale.setScalar(isCard ? .74 : .86);
  if (isCard) { hero.position.set(.2, -1.2, 2.3); hero.rotation.set(-.14, .42, .1); }
  else { hero.position.set(.32, -1.28, 2.6); hero.rotation.set(.22, .46, -.14); }
  hero.traverse(o => { if (o.isMesh) o.castShadow = true; });
  scene.add(hero);
  if (!isCard) [[1.42, -1.98, 3.1, .42, .5], [-.5, -1.82, 2.9, .3, -.3]].forEach(([x, y, z, k, r]) => { const m = smallOf(spec, t); m.scale.setScalar(k); m.position.set(x, y, z); m.rotation.set(.25, r, r * .4); m.traverse(o => { if (o.isMesh) o.castShadow = true; }); scene.add(m); front.push(m); });

  // мелочь на разной глубине
  const near = isCard ? [] : [[-.4, 2.65, 1, .24]], far = isCard ? [] : [[-3.1, 3.2, -5, .36], [5, -1.2, -5, .5]];
  near.forEach(([x, y, z, s], i) => { const m = smallOf(spec, t); m.scale.setScalar(s); m.position.set(x, y, z); m.rotation.set(.35 + i * .1, .5 - i * .45, .3); scene.add(m); });
  const farGroup = new THREE.Group();
  far.forEach(([x, y, z, s], i) => { const m = smallOf(spec, t); m.scale.setScalar(s); m.position.set(x, y, z); m.rotation.set(i, i * 1.3, .4); farGroup.add(m); });
  [[3.1, -3.4, .04]].forEach(([r, z, w]) => { const halo = new THREE.Mesh(new THREE.TorusGeometry(r, w, 16, 240), new THREE.MeshBasicMaterial({ color: t.glow, fog: false })); halo.position.set(2.42, .85, z); farGroup.add(halo); });
  scene.add(farGroup);

  // передний план: крупные размытые предметы по углам усиливают глубину и не задевают подписи
  const fore = new THREE.Group();
  (isCard ? [] : [[2.72, -1.3, 7.8, .6]]).forEach(([x, y, z, k], i) => { const m = smallOf(spec, t); m.scale.setScalar(k); m.position.set(x, y, z); m.rotation.set(.7 + i, .4 + i, .5); fore.add(m); });
  scene.add(fore);

  const backdrop = makeBackdrop(t); scene.add(backdrop);
  const icon = makeIcon(spec, t); icon.position.set(-4.12, 2.92, .3); scene.add(icon);

  // объёмное число: каждая цифра отдельно, с зазором, чтобы боковины не закрывали соседние цифры
  const top = new THREE.Color('#ffffff'), low = new THREE.Color(t.accent).lerp(top, .55);
  const faceMat = new THREE.MeshPhysicalMaterial({ vertexColors: true, roughness: .3, clearcoat: 1, emissive: '#ffffff', emissiveIntensity: .34 });
  const sideMat = new THREE.MeshPhysicalMaterial({ color: t.side, roughness: .28, metalness: .55, clearcoat: 1, envMapIntensity: 1.6 });
  const num = new THREE.Group(); let adv = 0;
  for (const ch of String(spec.amount)) {
    const geo = new TextGeometry(ch, { font, size: 1, height: .5, curveSegments: 24, bevelEnabled: true, bevelThickness: .06, bevelSize: .032, bevelSegments: 10 });
    geo.computeBoundingBox(); const bb = geo.boundingBox; geo.translate(adv - bb.min.x, 0, 0); adv += bb.max.x - bb.min.x + .13;
    const colors = [], np = geo.attributes.position;
    for (let i = 0; i < np.count; i++) { const c = top.clone().lerp(low, 1 - THREE.MathUtils.clamp(np.getY(i) / .72, 0, 1)); colors.push(c.r, c.g, c.b); }
    geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    const dm = new THREE.Mesh(geo, [faceMat, sideMat]); dm.castShadow = true; dm.receiveShadow = true; num.add(dm);
  }
  const k = Math.min(1.72, 3.85 / (adv - .13));
  num.scale.setScalar(k); num.position.set(-4.38, -.32, .7); num.rotation.set(-.02, .25, 0); scene.add(num);

  // отражения слабее: форму лепит направленный свет и тени
  const seen = new Set();
  scene.traverse(o => { if (o.material) [].concat(o.material).forEach(m => { if (!seen.has(m) && m.isMeshStandardMaterial) { seen.add(m); m.envMapIntensity = (m.envMapIntensity ?? 1) * .68; } }); });

  const out = document.createElement('canvas'); out.width = W; out.height = H;
  const g = out.getContext('2d'); g.imageSmoothingQuality = 'high';
  const show = (...only) => scene.children.forEach(c => { if (!c.isLight) c.visible = only.includes(c); });
  const layer = () => renderer.domElement;
  const drop = (blur, dx, dy, alpha) => { g.save(); g.filter = `brightness(0) blur(${blur}px)`; g.globalAlpha = alpha; g.drawImage(layer(), dx, dy, W, H); g.restore(); };
  drawBase(g, t);
  // дальний план слегка размыт, предметы на глубине размыты сильнее, передний план сильнее всего
  show(backdrop); renderer.render(scene, cam);
  g.save(); g.filter = 'blur(5px)'; g.globalAlpha = .74; g.drawImage(layer(), 0, 0, W, H); g.restore();
  drawVeil(g, t);
  if (S.veil) S.veil(g, t);
  show(farGroup); renderer.render(scene, cam);
  g.save(); g.filter = 'blur(7px)'; g.globalAlpha = .8; g.drawImage(layer(), 0, 0, W, H); g.restore();
  // тени на фон: плотная у числа и широкая от всей сцены
  show(stage, num, icon); renderer.render(scene, cam); drop(30, 24, 34, .46);
  show(num, icon); renderer.render(scene, cam); drop(9, 10, 15, .6);
  // основной слой с мягким свечением
  const main = scene.children.filter(c => !c.isLight && c !== backdrop && c !== farGroup && c !== fore && !front.includes(c));
  show(...main); renderer.render(scene, cam);
  g.save(); g.globalCompositeOperation = 'screen'; g.filter = 'blur(24px)'; g.globalAlpha = .16; g.drawImage(layer(), 0, 0, W, H); g.restore();
  g.drawImage(layer(), 0, 0, W, H);
  if (S.numGlow) { show(num); renderer.render(scene, cam); g.save(); g.globalCompositeOperation = 'screen'; g.filter = 'blur(18px)'; g.globalAlpha = S.numGlow; g.drawImage(layer(), 0, 0, W, H); g.restore(); }
  // товар ближе всего к зрителю и бросает тень на подиум и маскота
  show(...front); renderer.render(scene, cam); drop(16, 16, 24, .58);
  g.drawImage(layer(), 0, 0, W, H);
  show(fore); renderer.render(scene, cam);
  g.save(); g.filter = 'blur(11px)'; g.globalAlpha = .72; g.drawImage(layer(), 0, 0, W, H); g.restore();
  drawOverlay(g, spec, t);
  if (S.after) S.after(g, spec, t);
  scene.traverse(o => { if (o.geometry && !o.geometry.userData.keep) o.geometry.dispose(); });
  return out;
}
