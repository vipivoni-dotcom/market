// Дракон DragDiller: цельная лепная фигурка с позами и костюмами. Детали тела и костюма кэшируются отдельно.
import * as THREE from 'three';
import { sculpt, smin, smax, sstep, ell, roundCone, chain, roundBox, polygon2d } from './sculpt.js';

const rgb = hex => { const c = new THREE.Color(hex); return [c.r, c.g, c.b]; };
const put = (o, c) => { o[0] = c[0]; o[1] = c[1]; o[2] = c[2]; };
const mixTo = (o, c, t) => { o[0] += (c[0] - o[0]) * t; o[1] += (c[1] - o[1]) * t; o[2] += (c[2] - o[2]) * t; };
const v = { add: (a, b, k = 1) => a.map((x, i) => x + b[i] * k), dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2], norm: a => { const l = Math.hypot(...a) || 1; return a.map(x => x / l); }, cross: (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]] };

// Наклон головы задаёт поза, поэтому координаты головы считаются от текущих значений.
const HEAD_Y = .98;
let CZ = 1, SZ = 0;
const CX = Math.cos(.05), SX = Math.sin(.05);
const setTilt = t => { CZ = Math.cos(t); SZ = Math.sin(t); };
let hx = 0, hy = 0, hz = 0;
function toHead(x, y, z) {
  const py = y - HEAD_Y, x1 = x * CZ + py * SZ, y1 = -x * SZ + py * CZ;
  hx = x1; hy = y1 * CX - z * SX; hz = y1 * SX + z * CX;
}
const inHead = f => (x, y, z) => { toHead(x, y, z); return f(hx, hy, hz); };

const curve = (pts, r0, r1, n, k) => {
  const c = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)));
  return chain(c.getPoints(n).map(p => [p.x, p.y, p.z]), Array.from({ length: n + 1 }, (_, i) => r0(i / n, r1)), k);
};

// Рисунок кожи: неровная чешуя, которая видна в бликах и не даёт швов на любой части тела.
const reptile = (x, y, z) => { const f = 68; return Math.sin(f * x) * Math.cos(f * y) + Math.sin(f * y) * Math.cos(f * z) + Math.sin(f * z) * Math.cos(f * x); };

const headBall = (x, y, z) => ell(x, y, z, 0, 0, 0, 1.08, .94, 1);
const muzzle = (x, y, z) => ell(x, y, z, 0, -.4, .6, .7, .44, .56);
const faceD = (x, y, z) => smin(headBall(x, y, z), muzzle(x, y, z), .18);
const fin1 = roundCone([1, -.12, -.1], [1.46, .1, -.34], .17, .03), fin2 = roundCone([.98, -.36, -.14], [1.32, -.4, -.38], .12, .025);
const SMILE = new THREE.CatmullRomCurve3([[-.17, -.57], [0, -.59], [.17, -.57], [.31, -.49], [.4, -.39]].map(p => new THREE.Vector3(p[0], p[1], 0))).getPoints(32).filter(p => p.x >= 0);
function smileD(ax, y) {
  let d = 1e3;
  for (let i = 0; i < SMILE.length - 1; i++) {
    const a = SMILE[i], b = SMILE[i + 1], ex = b.x - a.x, ey = b.y - a.y;
    const t = Math.min(1, Math.max(0, ((ax - a.x) * ex + (y - a.y) * ey) / (ex * ex + ey * ey)));
    const q = (i + t) / (SMILE.length - 1);
    d = Math.min(d, Math.hypot(ax - a.x - ex * t, y - a.y - ey * t) - (.016 - .009 * sstep(.7, 1, q)));
  }
  return d;
}
function headSkin(x, y, z) {
  const ax = Math.abs(x);
  let d = faceD(x, y, z);
  d = smin(d, fin1(ax, y, z), .09); d = smin(d, fin2(ax, y, z), .07);
  // щёки приподняты улыбкой
  d = smin(d, ell(ax, y, z, .52, -.36, .78, .17, .12, .12), .1);
  return smax(d, -ell(ax, y, z, .17, -.29, 1.12, .05, .036, .05), .028);
}

const chest = (x, y, z) => ell(x, y, z, 0, -.12, 0, .62, .62, .56);
const tum = (x, y, z) => ell(x, y, z, 0, -.52, .04, .76, .68, .66);
const torso = (x, y, z) => smin(chest(x, y, z), tum(x, y, z), .2);
const thigh = roundCone([.42, -.82, .05], [.5, -1.2, .12], .31, .25);
const toes = [[.3, .66], [.52, .74], [.74, .66]];
function foot(ax, y, z) {
  let d = ell(ax, y, z, .52, -1.36, .24, .37, .22, .46);
  for (const [tx, tz] of toes) d = smin(d, ell(ax, y, z, tx, -1.41, tz, .11, .1, .13), .06);
  return smax(d, -(y + 1.52), .035);
}
const TAIL = [[.25, -.75, -.5], [.85, -1.18, -.7], [1.45, -1.2, -.35], [1.82, -.85, 0], [1.86, -.42, .12]];
const tailR = (t, e) => .36 - (.36 - e) * Math.pow(t, .8);
const tail = curve(TAIL, tailR, .04, 14, .04);

// Гребень вдоль хвоста: пластины уменьшаются к кончику.
const tailC = new THREE.CatmullRomCurve3(TAIL.map(p => new THREE.Vector3(...p)));
const plates = Array.from({ length: 9 }, (_, i) => {
  const t = .1 + i * .1, p = tailC.getPoint(t), T = tailC.getTangent(t), up = new THREE.Vector3(0, 1, 0).addScaledVector(T, -T.y).normalize(), r = tailR(t, .04);
  const base = p.clone().addScaledVector(up, r * .72), tip = base.clone().addScaledVector(up, .1 + r * .36).addScaledVector(T, .05);
  return roundCone(base.toArray(), tip.toArray(), .075 + r * .1, .012);
});
const platesD = (x, y, z) => { let d = plates[0](x, y, z); for (let i = 1; i < plates.length; i++) d = Math.min(d, plates[i](x, y, z)); return d; };
const body = (x, y, z) => {
  const ax = Math.abs(x); toHead(x, y, z);
  let d = smin(torso(x, y, z), headSkin(hx, hy, hz), .14);
  d = smin(d, thigh(ax, y, z), .14); d = smin(d, foot(ax, y, z), .1);
  return smin(d, tail(x, y, z), .16);
};

// Кисти. Открытая: ладонь, три пальца, большой, коготки; указательный жест вытягивает средний палец.
function makeOpen({ palm, up, side, wrist, pointing }) {
  const U = v.norm(up), S = v.norm(v.add(side, U, -v.dot(side, U))); let F = v.cross(S, U); if (F[2] < 0) F = F.map(x => -x);
  const W = (a, b, c) => [palm[0] + S[0] * a + U[0] * b + F[0] * c, palm[1] + S[1] * a + U[1] * b + F[1] * c, palm[2] + S[2] * a + U[2] * b + F[2] * c];
  const OPEN = [
    [[[-.11, .07, .01], [-.19, .17, .03], [-.24, .26, .06]], [.074, .068, .058]],
    [[[0, .1, .02], [-.01, .22, .05], [-.01, .33, .08]], [.076, .07, .06]],
    [[[.11, .07, .01], [.17, .17, .04], [.21, .26, .07]], [.074, .068, .058]],
    [[[.12, -.06, .06], [.22, -.02, .11], [.28, .06, .15]], [.08, .07, .058]],
  ];
  const POINT = [
    [[[-.1, .08, .03], [-.1, .15, .11], [-.08, .07, .17]], [.074, .068, .058]],
    [[[0, .1, .02], [0, .28, .03], [0, .46, .05]], [.074, .066, .054]],
    [[[.1, .08, .03], [.1, .15, .11], [.08, .07, .17]], [.074, .068, .058]],
    [[[.13, -.03, .07], [.12, .06, .15], [.03, .05, .2]], [.08, .07, .058]],
  ];
  const fingers = (pointing ? POINT : OPEN).map(([p, r]) => [p.map(q => W(...q)), r]);
  const parts = fingers.map(([p, r]) => chain(p, r, .06)), wc = roundCone(wrist, palm, .11, .09);
  const sdf = (x, y, z) => {
    const far = Math.hypot(x - palm[0], y - palm[1], z - palm[2]); if (far > 1.1) return far - .55;
    const px = x - palm[0], py = y - palm[1], pz = z - palm[2];
    let d = smin(ell(px * S[0] + py * S[1] + pz * S[2], px * U[0] + py * U[1] + pz * U[2], px * F[0] + py * F[1] + pz * F[2], 0, 0, 0, .155, .145, .095), wc(x, y, z), .05);
    for (const f of parts) d = smin(d, f(x, y, z), .03);
    return d;
  };
  const clawCones = fingers.filter((_, i) => !pointing || i === 1).map(([p]) => { const a = p[1], b = p[2], dir = v.norm(v.add(b, a, -1)); return roundCone(v.add(b, dir, -.01), v.add(b, dir, .068), .03, .006); });
  const claws = (x, y, z) => { let d = 1e3; for (const c of clawCones) d = Math.min(d, c(x, y, z)); return d; };
  return { sdf, claws, center: palm };
}

// Кулак: пальцы обхватывают предмет вокруг оси, большой палец лежит сверху или поднят вверх.
function makeFist({ grip, axis, out, wrist, rho = [.17, .14], thumbUp }) {
  const A = v.norm(axis), E1 = v.norm(v.add(out, A, -v.dot(out, A))); let E2 = v.cross(E1, A); if (E2[2] < -.01) E2 = E2.map(x => -x);
  const gp = (s, th) => [0, 1, 2].map(i => grip[i] + A[i] * s + E1[i] * rho[0] * Math.cos(th) + E2[i] * rho[1] * Math.sin(th));
  const arc = (s, a, b, r0, r1) => chain(Array.from({ length: 6 }, (_, i) => gp(s, a + (b - a) * i / 5)), Array.from({ length: 6 }, (_, i) => r0 + (r1 - r0) * i / 5), .015);
  const fingers = [-.1, .012, .124].map(s => arc(s, -.7, 2.45, .064, .05));
  const palm = [0, 1, 2].map(i => grip[i] + E1[i] * .13 - E2[i] * .06);
  const root = thumbUp ? [0, 1, 2].map(i => grip[i] + thumbUp[i] * .08) : gp(-.2, 3.5);
  const thumb = thumbUp ? chain([root, v.add(root, thumbUp, .16), v.add(root, thumbUp, .3)], [.08, .07, .056], .05) : arc(-.2, 3.5, 1.15, .068, .05);
  const rootC = roundCone(palm, root, .1, .07), wc = roundCone(wrist, palm, .11, .11);
  const sdf = (x, y, z) => {
    const far = Math.hypot(x - grip[0], y - grip[1], z - grip[2]); if (far > 1.1) return far - .55;
    let d = smin(ell(x, y, z, palm[0], palm[1], palm[2], .15, .17, .13), wc(x, y, z), .05);
    d = smin(d, rootC(x, y, z), .05);
    for (const f of fingers) d = smin(d, f(x, y, z), .018);
    return smin(d, thumb(x, y, z), .018);
  };
  return { sdf, center: grip };
}

const FIST_R_UP = { grip: [1.05, .57, .62], axis: [-.42, -.9, 0], out: [.9, -.42, 0], wrist: [1.12, .3, .54], elbow: [1.17, -.16, .32] };
const RAISED_R = { grip: [1.3, .88, .55], axis: [-.2, -.98, 0], out: [.98, -.2, 0], wrist: [1.36, .56, .44], elbow: [1.24, 0, .24] };
const POSES = {
  // машет свободной рукой, в другой поднят предмет
  wave: { tilt: .07, R: FIST_R_UP, L: { open: { palm: [-1.25, .2, .47], up: [0, 1, 0], side: [1, 0, 0], wrist: [-1.2, .02, .42] }, wrist: [-1.2, .02, .42], elbow: [-1, -.28, .26] } },
  // предмет высоко над плечом, второй рукой показывает большой палец
  raise: { tilt: -.09, R: RAISED_R, L: { fist: { grip: [-1.12, -.06, .78], axis: [1, 0, 0], out: [0, 0, -1], rho: [.105, .105], thumbUp: [0, 1, .06] }, wrist: [-1.14, -.18, .52], elbow: [-1.04, -.38, .22] } },
  // указывает на номинал
  point: { tilt: .13, R: FIST_R_UP, L: { open: { palm: [-1.5, .17, .5], up: [-.97, .13, .12], side: [0, 1, 0], wrist: [-1.36, .13, .45], pointing: true }, wrist: [-1.36, .13, .45], elbow: [-1.02, -.05, .3] } },
  // предмет на плече, вторая рука на бедре
  hip: { tilt: -.09, R: { grip: [1.02, .42, .72], axis: [-.36, -.88, .24], out: [.9, -.36, 0], wrist: [1.12, .12, .62], elbow: [1.18, -.3, .36] }, L: { fist: { grip: [-.88, -.5, .46], axis: [0, -1, 0], out: [-.7, 0, -.7], rho: [.105, .105] }, wrist: [-1, -.44, .3], elbow: [-1.2, -.2, .1] } },
  // обе руки держат предмет перед грудью
  front: { tilt: .07, center: [0, -.2, 1.12], R: { grip: [.5, -.2, 1.02], axis: [0, -1, .1], out: [.8, 0, -.6], rho: [.13, .13], wrist: [.72, -.26, .84], elbow: [1.04, -.36, .4] }, L: { fist: { grip: [-.5, -.2, 1.02], axis: [0, -1, .1], out: [-.8, 0, -.6], rho: [.13, .13] }, wrist: [-.72, -.26, .84], elbow: [-1.04, -.36, .4] } },
  // обе руки вверх: победа
  cheer: { tilt: -.09, R: RAISED_R, L: { fist: { grip: [-1.3, .88, .55], axis: [.2, -.98, 0], out: [-.98, -.2, 0], rho: [.105, .105] }, wrist: [-1.36, .56, .44], elbow: [-1.24, 0, .24] } },
};

function buildPose(name) {
  const P = POSES[name], arm = (s, a) => chain([[s * .58, -.02, .12], a.elbow, a.wrist], [.19, .145, .115], .05);
  const armL = arm(-1, P.L), armR = arm(1, P.R);
  const handR = makeFist(P.R);
  const handL = P.L.open ? makeOpen(P.L.open) : makeFist({ ...P.L.fist, wrist: P.L.wrist });
  const cuffOf = a => { const d = v.norm(v.add(a.wrist, a.elbow, -1)); return roundCone(v.add(a.wrist, d, -.05), v.add(a.wrist, d, .04), .136, .13); };
  const cl = cuffOf(P.L), cr = cuffOf(P.R), cuffs = (x, y, z) => Math.min(cl(x, y, z), cr(x, y, z));
  const skin = (x, y, z) => {
    let d = body(x, y, z);
    d = smin(d, armL(x, y, z), .08); d = smin(d, armR(x, y, z), .08);
    if (Math.abs(d) < .05) {
      const e = (x / .56) ** 2 + ((y + .42) / .62) ** 2;
      // рёбра живота и чешуя вне живота и морды
      if (z > .1 && y < .2 && e < 1.1) { const yy = y + .42 + x * x * .2; d += .011 * Math.exp(-Math.pow(((yy + 10.09) % .2 - .1) / .02, 2)) * sstep(1.1, .9, e); }
      toHead(x, y, z);
      const fm = hz > 0 && hy < .1 ? (hx / .78) ** 2 + ((hy + .42) / .46) ** 2 + ((hz - .86) / .62) ** 2 : 9;
      const mask = (z > 0 ? sstep(.95, 1.25, e) : 1) * sstep(1.15, 1.6, fm);
      if (mask > 0) d -= .0015 * reptile(x, y, z) * mask;
    }
    return d;
  };
  const GREEN = rgb('#10a06f'), DEEP = rgb('#075f47'), LITE = rgb('#2fc690'), MINT = rgb('#a9ebce'), LINE = rgb('#0a4f3d'), BLUSH = rgb('#ff8fa6'), SOLE = rgb('#0e8a68');
  const paint = (x, y, z, o) => {
    put(o, GREEN);
    mixTo(o, DEEP, sstep(.1, -1.5, y) * .35 + sstep(.1, -.9, z) * .4);
    const h = reptile(x, y, z); mixTo(o, DEEP, sstep(.3, 1.4, h) * .28); mixTo(o, LITE, sstep(-.5, -1.4, h) * .3);
    toHead(x, y, z);
    const ax = Math.abs(x), e = (x / .56) ** 2 + ((y + .42) / .62) ** 2;
    if (z > 0) {
      mixTo(o, MINT, sstep(1.02, .97, e));
      const yy = y + .42 + ax * ax * .2;
      if (e < 1) mixTo(o, DEEP, .6 * Math.exp(-Math.pow(((yy + 10.09) % .2 - .1) / .014, 2)));
    }
    if (hz > 0 && hy < .1) {
      const m = (hx / .78) ** 2 + ((hy + .42) / .46) ** 2 + ((hz - .86) / .62) ** 2;
      mixTo(o, MINT, sstep(1.04, .94, m));
      const b = Math.hypot(Math.abs(hx) - .74, hy + .22); mixTo(o, BLUSH, sstep(.25, .04, b) * .85);
      const nos = ell(Math.abs(hx), hy, hz, .17, -.29, 1.12, .062, .048, .06); mixTo(o, LINE, sstep(.03, 0, nos));
    }
    if (y < -1.1) mixTo(o, SOLE, sstep(-1.1, -1.3, y) * .75);
  };
  const handOcc = (x, y, z) => Math.min(body(x, y, z), handL.sdf(x, y, z), handR.sdf(x, y, z));
  const occ = (x, y, z) => Math.min(skin(x, y, z), handL.sdf(x, y, z), handR.sdf(x, y, z), cuffs(x, y, z));
  const box = (c, r = .78) => ({ min: c.map(q => q - r), max: c.map(q => q + r) });
  const HAND = rgb('#a9ebce'), PALM = rgb('#c8f5e0'), paintHand = (x, y, z, o) => { put(o, HAND); mixTo(o, PALM, sstep(.45, .7, z) * .6); };
  const WHITE = [1, 1, 1], CREAM = rgb('#ffe9b8');
  const res = {
    skin: sculpt({ sdf: skin, occluder: occ, min: [-1.9, -1.6, -1.5], max: [2.1, 2.15, 1.5], voxel: .013, paint }),
    handL: sculpt({ sdf: handL.sdf, occluder: handOcc, ...box(handL.center), voxel: .006, ao: 1, paint: paintHand }),
    handR: sculpt({ sdf: handR.sdf, occluder: handOcc, ...box(handR.center), voxel: .006, ao: 1, paint: paintHand }),
    cuffs: sculpt({ sdf: cuffs, occluder: occ, min: [-1.7, -.5, 0], max: [1.7, .85, 1.1], voxel: .008, ao: .7, paint: (x, y, z, o) => put(o, WHITE) }),
  };
  if (handL.claws) res.handClaws = sculpt({ sdf: handL.claws, occluder: handOcc, ...box(handL.center), voxel: .005, ao: .4, paint: (x, y, z, o) => put(o, CREAM) });
  return res;
}

// Голова: шлем со срезом, рога с кольцами, очки с затемнённым стеклом.
const cutLine = (y, z) => (.1 + .34 * z) - y;
function helmetShell(x, y, z) {
  const ax = Math.abs(x), cut = cutLine(y, z);
  let d = smax(ell(x, y, z, 0, .02, -.02, 1.14, 1.04, 1.1), cut, .03);
  const lip = Math.max(ell(x, y, z, 0, .02, -.02, 1.162, 1.062, 1.122), Math.abs(cut) - .04);
  d = smin(d, lip, .025);
  return smin(d, ell(ax, y, z, .6, .8, -.05, .17, .09, .17), .05);
}
const rivetAt = (a, t) => { const z = Math.cos(a) * 1.12, x = Math.sin(a) * 1.13; return [x, .1 + .34 * z + t, z]; };
const RIVETS = [-1.5, -1.05, -.6, .6, 1.05, 1.5].map(a => rivetAt(a, .1));
const rivets = (x, y, z) => { let d = 1e3; for (const r of RIVETS) d = Math.min(d, Math.hypot(x - r[0], (y - r[1]) * 1.1, z - r[2]) - .03); return d; };

const hornP = chain([[.6, .82, -.05], [.8, 1.14, -.1], [.8, 1.42, -.22]], [.15, .095, .012], .05);
const hornD = (x, y, z) => { const d = hornP(Math.abs(x), y, z); return Math.abs(d) < .03 ? d + .004 * Math.sin(y * 52) * sstep(1.3, .9, y) : d; };
const fang = roundCone([.2, -.565, 1.09], [.2, -.665, 1.068], .036, .006);
const clawCones = toes.map(([tx, tz]) => roundCone([tx, -1.43, tz + .05], [tx, -1.46, tz + .17], .055, .012));

const LENS_X = .39, LENS_Y = .12, LENS_Z = 1.02, YAW = .34, PITCH = .24, CY = Math.cos(YAW), SY = Math.sin(YAW), CP = Math.cos(PITCH), SP = Math.sin(PITCH), RIM_R = .265;
let eu = 0, ev = 0, ew = 0;
function toEye(x, y, z) {
  const x0 = Math.abs(x) - LENS_X, y0 = y - LENS_Y, z0 = z - LENS_Z, z1 = x0 * SY + z0 * CY;
  eu = x0 * CY - z0 * SY; ev = y0 * CP - z1 * SP; ew = z1 * CP + y0 * SP;
}
function fromEye(u, vv, w) {
  const z1 = w * CP - vv * SP;
  return [LENS_X + u * CY + z1 * SY, LENS_Y + w * SP + vv * CP, LENS_Z - u * SY + z1 * CY];
}
const bridgeA = fromEye(-RIM_R * 1.08, .03, 0), bridge = roundCone(bridgeA, [0, bridgeA[1] + .015, bridgeA[2] + .012], .052, .048);
function frame(x, y, z) {
  const ax = Math.abs(x);
  toEye(x, y, z);
  const r = Math.hypot(eu / 1.08, ev);
  let d = smax(Math.abs(headBall(x, y, z) - .012) - .026, Math.abs(y - LENS_Y - ax * .02) - .072, .02);
  if (z > 0) d = smax(d, .6 - ax, .02);
  const rim = Math.hypot(r - RIM_R, ew) - .056;
  const cup = smax(smax(r - .296, ew - .004, .012), -.42 - ew, .01);
  d = Math.min(d, smin(rim, cup, .012));
  return z > 0 ? smin(d, bridge(ax, y, z), .02) : d;
}
function lensD(x, y, z) {
  toEye(x, y, z);
  const r = Math.hypot(eu / 1.08, ev), q = r / .236, dome = .014 + .058 * Math.max(0, 1 - q * q);
  return smax(smax(ew - dome, r - .236, .008), -.035 - ew, .005);
}

// Шарф
const SC = { off: .045, endA: -.74, endB: -.54 };
const scarfFold1 = (x, y, z) => {
  const py = y - .13 + z * .1, a = Math.atan2(z, x);
  return (Math.hypot(Math.hypot(x / 1.06, z / .92) - .6, py / .72) - .165) * .72 - .008 * Math.sin(a * 5 + 1);
};
const scarfFold2 = (x, y, z) => {
  const py = y + .01 + z * .17 - x * .04, a = Math.atan2(z, x);
  return (Math.hypot(Math.hypot(x / 1.06, z / .92) - .645, py / .66) - .14) * .66 - .007 * Math.sin(a * 4 - .6);
};
const scarfKnot = (x, y, z) => ell(x, y, z, -.35, -.1, .68, .135, .105, .1);
function ribbon(x, y, z, cx, w, top, end, off) {
  const t = Math.min(1, Math.max(0, (top - y) / (top - end)));
  let d = smax(Math.abs(torso(x, y, z) - off - .007 * Math.sin(t * 9)) - .024, Math.abs(x - cx(t)) - w(t), .014);
  d = smax(d, y - top, .012); d = smax(d, end - y, .018);
  return smax(d, .1 - z, .01);
}
const ribbonA = (x, y, z) => ribbon(x, y, z, t => -.33 + .03 * Math.sin(t * 3.4) - .01 * t, t => .085 + .035 * t, -.04, SC.endA, SC.off + .012);
const ribbonB = (x, y, z) => ribbon(x, y, z, t => -.46 - .08 * t + .012 * Math.sin(t * 5), t => .07 + .03 * t, -.06, SC.endB, SC.off);
const scarf = (x, y, z) => {
  let d = smin(scarfFold1(x, y, z), scarfFold2(x, y, z), .018);
  d = smin(d, scarfKnot(x, y, z), .025);
  return smin(smin(d, ribbonA(x, y, z), .018), ribbonB(x, y, z), .012);
};
const scarfPart = (c1, c2, c3, opt = {}) => ({
  before: () => { SC.off = opt.off ?? .045; SC.endA = opt.endA ?? -.74; SC.endB = opt.endB ?? -.54; },
  sdf: scarf, min: [-1.05, -1, -.95], max: [1.05, .48, 1.1], voxel: .009, mat: 'matte',
  paint: (x, y, z, o) => {
    const f1 = scarfFold1(x, y, z), f2 = scarfFold2(x, y, z), ra = ribbonA(x, y, z), rb = ribbonB(x, y, z), m = Math.min(f1, f2, ra, rb, scarfKnot(x, y, z));
    put(o, c1);
    if (m === f1) mixTo(o, c2, sstep(.05, .03, Math.abs(y - .13 + z * .1)) * sstep(.01, .05, scarfKnot(x, y, z)));
    if (m === rb) mixTo(o, c3, .35);
    if (m === ra || m === rb) { const e = m === ra ? SC.endA : SC.endB; mixTo(o, c2, sstep(.042, .028, Math.abs(y - e - .1))); mixTo(o, c2, sstep(.018, .008, Math.abs(y - e - .19))); }
  },
});

// Одежда лежит оболочкой поверх туловища; вырез спереди открывает живот.
function garment(x, y, z, off, yB, yT, open = 0) {
  let d = smax(torso(x, y, z) - off, yB - y, .05); d = smax(d, y - yT, .04);
  if (open) d = smax(d, smin(open - Math.abs(x), z - .1, .05), .03);
  return d;
}
const cape = (x, y, z) => {
  const t = Math.min(1, Math.max(0, (.1 - y) / 1.45)), zc = -.58 - .3 * t + .05 * Math.sin(x * 6) * t;
  let d = smax(Math.abs(z - zc) - .028, Math.abs(x) - (.72 + .62 * t), .02);
  d = smax(d, y - .12, .02);
  return smax(d, -1.34 + .05 * Math.sin(x * 6) - y, .02);
};
const pauldron = (ax, y, z) => { let d = ell(ax, y, z, .74, .13, .1, .3, .2, .29); d = smin(d, ell(ax, y, z, .8, .02, .1, .26, .14, .26), .015); return smin(d, ell(ax, y, z, .84, -.08, .1, .21, .1, .22), .015); };
const beltD = (x, y, z, off, yc, w) => smax(Math.abs(torso(x, y, z) - off) - .018, Math.abs(y - yc) - w, .012);
const diag = (x, y, off, k = .7) => Math.abs(x * k - y * .72 - off);
const hoodD = (x, y, z) => smin(Math.hypot(Math.hypot(x / 1.08, z / .96) - .62, (y - .1 + z * .1) / .7) * .7 - .13, ell(x, y, z, 0, .1, -.72, .5, .36, .24), .08);

// Гарнитуры: дуга над головой и чашки у ушей.
const earBand = (x, y, z) => smax(smax(Math.abs(Math.hypot(x / 1.13, y / 1.05) - 1) - .036, Math.abs(z + .02) - .075, .02), -.02 - y, .02);
const earCup = (ax, y, z) => { const r = Math.hypot(y - .05, z + .04); return smax(r - .3, Math.abs(ax - 1.13) - .1, .05); };

const shellPaint = (c1, c2, rim, stripe) => (x, y, z, o) => {
  toHead(x, y, z); put(o, c1);
  if (stripe) { const a = Math.abs(hx); mixTo(o, c2, sstep(.2, .18, a)); mixTo(o, stripe, sstep(.165, .145, a)); }
  mixTo(o, rim, sstep(.07, .05, Math.abs(cutLine(hy, hz))));
};
const headBox = { min: [-1.6, 0, -1.65], max: [1.6, 3, 1.6] };
const shell = (paint, extra = () => 1e3, mat = 'paint') => ({ head: true, sdf: inHead((x, y, z) => Math.min(helmetShell(x, y, z), extra(x, y, z))), ...headBox, voxel: .011, ao: .9, mat, paint });

function headset(cBody, cAcc, cLed, cHood, cStripe, mic) {
  const boom = chain([[1.1, -.02, .22], [.95, -.42, .62], [.48, -.62, .98]], [.03, .026, .022], .03), micHead = (x, y, z) => ell(x, y, z, .44, -.63, 1.01, .07, .055, .055);
  return [
    { head: true, sdf: inHead((x, y, z) => { const ax = Math.abs(x); let d = smin(earBand(x, y, z), earCup(ax, y, z), .03); if (mic) d = Math.min(d, boom(x, y, z), micHead(x, y, z)); return d; }), ...headBox, voxel: .009, ao: .8, mat: 'paint', paint: (x, y, z, o) => { toHead(x, y, z); put(o, cBody); const ax = Math.abs(hx); if (ax > 1.17) { const r = Math.hypot(hy - .05, hz + .04); mixTo(o, cLed, sstep(.17, .14, r) * .98); } if (mic && hz > .4 && hy < -.4) put(o, cAcc); if (hy > .4 && ax < .4) mixTo(o, cAcc, .85); } },
    { sdf: (x, y, z) => Math.min(garment(x, y, z, .05, -1.02, .06), hoodD(x, y, z), roundBox(x, y, z, 0, -.78, .76, .36, .15, .05, .04)), min: [-1.15, -1.15, -1.05], max: [1.15, .55, 1], voxel: .01, mat: 'matte', paint: (x, y, z, o) => { put(o, cHood); if (hoodD(x, y, z) < .01) mixTo(o, cStripe, .22); if (z > .3 && Math.abs(x) < .38 && y < -.62 && y > -.94) mixTo(o, cStripe, .14); if (z > .3 && Math.abs(Math.abs(x) - .16) < .017 && y > -.5) put(o, cStripe); } },
  ];
}

const OUTFITS = {
  racer: (p = {}) => [
    shell(shellPaint(rgb(p.A || '#e8323a'), rgb(p.B || '#17123f'), rgb(p.C || '#a81a22'), rgb(p.D || '#fbfbff')), rivets),
    scarfPart(rgb(p.A || '#e8323a'), rgb(p.D || '#ffffff'), rgb(p.C || '#8e1820')),
  ],
  // Армейская каска с наушниками, бронежилет с плитой и подсумками, рюкзак
  tactical: (p = {}) => {
    const O = rgb(p.O || '#5f6d3a'), RIM = rgb(p.RIM || '#3a4326'), POUCH = rgb(p.POUCH || '#73814c'), FLAP = rgb(p.FLAP || '#333a20'), PLATE = rgb(p.PLATE || '#454f2a'), TAN = rgb(p.TAN || '#b89a5a');
    const vest = (x, y, z) => {
      const ax = Math.abs(x);
      let d = garment(x, y, z, .05, -.92, .02);
      d = smin(d, roundBox(ax, y, z, .34, -.54, .68, .15, .17, .09, .04), .02);
      d = smin(d, roundBox(x, y, z, 0, -.54, .78, .14, .17, .09, .04), .02);
      d = smin(d, roundBox(x, y, z, 0, -.2, .62, .36, .17, .1, .05), .03);
      d = smin(d, smax(Math.abs(torso(x, y, z) - .09) - .02, Math.abs(ax - .3) - .055, .01), .01);
      return smin(d, roundBox(x, y, z, 0, -.32, -.82, .5, .55, .24, .12), .05);
    };
    return [
      shell((x, y, z, o) => { toHead(x, y, z); put(o, O); const a = Math.abs(hy - .22 - hz * .1); mixTo(o, FLAP, sstep(.05, .035, a) * .9); mixTo(o, RIM, sstep(.07, .05, Math.abs(cutLine(hy, hz)))); }, (x, y, z) => {
        const ax = Math.abs(x), cups = smax(ell(ax, y, z, 1.08, .06, -.04, .13, .27, .3), -ell(ax, y, z, 1.2, .06, -.04, .09, .15, .17), .02);
        return Math.min(cups, rivets(x, y, z));
      }),
      scarfPart(TAN, rgb('#8a7340'), rgb('#6d5a30'), { off: .095, endA: -.34, endB: -.28 }),
      { sdf: vest, min: [-.95, -1.05, -1.2], max: [.95, .3, 1], voxel: .01, mat: 'matte', paint: (x, y, z, o) => {
        put(o, O);
        const ax = Math.abs(x), inP = z > .5 && y > -.73 && y < -.36 && (ax < .16 || (ax > .18 && ax < .5));
        if (inP) { put(o, POUCH); if (y > -.47) put(o, FLAP); }
        if (z > .5 && y > -.37 && y < -.03 && ax < .36) put(o, PLATE);
        if (z < -.5) put(o, POUCH);
      } },
    ];
  },
  // Рыцарь: корона, наплечники, нагрудник, плащ
  knight: (p = {}) => {
    const GOLD = rgb(p.GOLD || '#ffc21f'), STEEL = rgb(p.STEEL || '#c5d0de'), DK = rgb(p.DK || '#7c8ba1'), RUBY = rgb(p.RUBY || '#ff2f55');
    const spikes = Array.from({ length: 7 }, (_, i) => { const q = (i - 3) * .78, px = Math.sin(q) * .98, pz = Math.cos(q) * .9, yy = .62 + pz * .1; return roundCone([px, yy, pz], [px * .95, yy + .24, pz * .95], .075, .018); });
    const crown = (x, y, z) => {
      let d = smax(Math.abs(headBall(x, y, z) - .05) - .035, Math.abs(y - .59 - z * .1) - .1, .015);
      for (const s of spikes) d = smin(d, s(x, y, z), .03);
      return d;
    };
    return [
      { head: true, sdf: inHead(crown), ...headBox, voxel: .009, ao: .7, mat: 'metal', paint: (x, y, z, o) => { toHead(x, y, z); put(o, GOLD); mixTo(o, RUBY, sstep(.09, .06, Math.hypot(hx, hy - .68)) * (hz > 0 ? 1 : 0)); mixTo(o, rgb('#b47a00'), sstep(.02, .012, Math.abs(hy - .49 - hz * .1)) * .7); } },
      { sdf: (x, y, z) => { let d = garment(x, y, z, .055, -.72, .08); d = smin(d, Math.hypot(Math.hypot(x / 1.06, z / .92) - .6, (y - .08 + z * .1) / .66) * .66 - .11, .03); return smin(d, pauldron(Math.abs(x), y, z), .02); }, min: [-1.2, -.9, -.95], max: [1.2, .5, 1], voxel: .009, mat: 'metal', paint: (x, y, z, o) => {
        put(o, STEEL); mixTo(o, GOLD, sstep(.05, .035, Math.abs(y + .72))); if (z > 0) mixTo(o, DK, sstep(.022, .012, Math.abs(x)) * .8);
        if (Math.abs(x) > .55 && y > -.25) { put(o, STEEL); mixTo(o, GOLD, sstep(.03, .018, Math.abs(y + .15))); mixTo(o, GOLD, sstep(.03, .018, Math.abs(y))); }
        if (y > -.06 && Math.abs(x) < .6) put(o, GOLD);
      } },
      { sdf: cape, min: [-1.5, -1.45, -1.05], max: [1.5, .2, -.4], voxel: .01, tint: 'cape', mat: 'matte', paint: (x, y, z, o) => put(o, [1, 1, 1]) },
    ];
  },
  // Выживший: бандана, патронная лента, пояс
  survivor: (p = {}) => {
    const RED = rgb(p.RED || '#d3271f'), WHITE = rgb(p.WHITE || '#fff4e6'), LEATHER = rgb(p.LEATHER || '#5a3418'), BRASS = rgb(p.BRASS || '#e0a93a');
    const tailA = roundCone([.08, .5, -1], [.48, .1, -1.05], .07, .025), tailB = roundCone([-.08, .5, -1], [-.5, .02, -1.04], .07, .025);
    const band = (x, y, z) => {
      let d = smax(Math.abs(headBall(x, y, z) - .04) - .035, Math.abs(y - .54 - z * .1) - .14, .02);
      d = smin(d, ell(x, y, z, 0, .52, -1, .12, .1, .08), .03);
      return smin(smin(d, tailA(x, y, z), .02), tailB(x, y, z), .02);
    };
    const shells = Array.from({ length: 7 }, (_, i) => { const t = i / 6, px = -.5 + t, py = -.56 + .6 * t, pz = .62 * Math.sqrt(Math.max(.1, 1 - (px / .8) ** 2 - ((py + .4) / .8) ** 2)) + .05; return roundCone([px, py - .07, pz + .03], [px, py + .07, pz + .03], .036, .03); });
    return [
      { head: true, sdf: inHead(band), ...headBox, voxel: .009, ao: 1, mat: 'matte', paint: (x, y, z, o) => { toHead(x, y, z); put(o, RED); const u = (hx * 8 + 100) % 1 - .5, w = (hy * 8 + 100) % 1 - .5; mixTo(o, WHITE, sstep(.2, .13, Math.hypot(u, w)) * .9); } },
      { sdf: (x, y, z) => { const dg = smax(Math.abs(torso(x, y, z) - .03) - .022, diag(x, y, .187, .43) - .085, .012); let d = smax(dg, .1 - z, .02); d = Math.min(d, beltD(x, y, z, .03, -.86, .065)); d = smin(d, roundBox(x, y, z, 0, -.86, .74, .11, .1, .05, .02), .01); return Math.min(d, scarfFold1(x, y, z) + .03); }, min: [-1, -1.05, -.95], max: [1, .45, 1], voxel: .009, mat: 'matte', paint: (x, y, z, o) => { put(o, LEATHER); if (y > -.02 && scarfFold1(x, y, z) < .04) put(o, RED); if (Math.abs(x) < .12 && Math.abs(y + .86) < .11 && z > 0) put(o, BRASS); } },
      { sdf: (x, y, z) => { let d = 1e3; for (const s of shells) d = Math.min(d, s(x, y, z)); return d; }, min: [-.75, -.75, .2], max: [.75, .25, 1], voxel: .007, mat: 'metal', paint: (x, y, z, o) => put(o, BRASS) },
    ];
  },
  // Маг: остроконечная шляпа, плащ с капюшоном, пояс с пряжкой
  mage: (p = {}) => {
    const V = rgb(p.V || '#3a2470'), V2 = rgb(p.V2 || '#5c3ba6'), G = rgb(p.G || '#ffcf5c');
    const hatCone = curve([[0, .62, -.08], [.02, 1.15, -.16], [.15, 1.6, -.28], [.46, 1.92, -.32]], (t, e) => .84 - (.84 - e) * Math.pow(t, .7), .03, 18, .03);
    const hat = (x, y, z) => { const py = y - .62 - z * .12, r = Math.hypot(x, z), brim = smax(py - .03 - .025 * Math.sin(Math.atan2(z, x) * 5), -py - .05, .02); return smin(smax(brim, r - 1.42, .03), hatCone(x, y, z), .05); };
    return [
      { head: true, sdf: inHead(hat), ...headBox, voxel: .011, ao: 1, mat: 'matte', paint: (x, y, z, o) => { toHead(x, y, z); put(o, V); mixTo(o, V2, sstep(1.2, 1.9, hy)); if (Math.hypot(hx, hz) < 1) mixTo(o, G, sstep(.08, .06, Math.abs(hy - .78 - hz * .1))); const q = Math.hypot(hx, hy - 1.06); mixTo(o, G, sstep(.1, .07, q + .03 * Math.cos(5 * Math.atan2(hx, hy - 1.06))) * (hz > 0 ? 1 : 0)); } },
      { sdf: (x, y, z) => Math.min(garment(x, y, z, .04, -1.02, .06, .24), hoodD(x, y, z), beltD(x, y, z, .07, -.5, .05)), min: [-1.15, -1.15, -1.05], max: [1.15, .55, 1], voxel: .01, mat: 'matte', paint: (x, y, z, o) => { put(o, V); if (hoodD(x, y, z) < .01) put(o, V2); if (Math.abs(y + .5) < .056) put(o, G); if (Math.abs(Math.abs(x) - .24) < .03 && z > 0) mixTo(o, G, .9); } },
      { sdf: cape, min: [-1.5, -1.45, -1.05], max: [1.5, .2, -.4], voxel: .01, tint: 'cape', mat: 'matte', paint: (x, y, z, o) => put(o, [1, 1, 1]) },
    ];
  },
  // Курьер: кепка с козырьком, почтовая сумка через плечо
  courier: (p = {}) => {
    const T = rgb(p.T || '#0b6d72'), T2 = rgb(p.T2 || '#084c50'), G = rgb(p.G || '#ffcf5c'), BAG = rgb(p.BAG || '#a56a2b');
    const visor = (x, y, z) => { const py = y - .475 - (z - 1) * .04; return smax(smax(ell(x, y, z, 0, .475, .95, .74, .3, .62), Math.abs(py) - .034, .025), .72 - z, .03); };
    const bag = (x, y, z) => roundBox(x, y, z, -.66, -.68, .46, .3, .24, .13, .06);
    return [
      shell((x, y, z, o) => { toHead(x, y, z); put(o, T); if (hz > .85 && hy > .3) mixTo(o, T2, .9); mixTo(o, G, sstep(.13, .1, Math.hypot(hx, hy - .68)) * (hz > 0 ? 1 : 0)); mixTo(o, T2, sstep(.07, .05, Math.abs(cutLine(hy, hz)))); }, visor),
      scarfPart(G, rgb('#fff4cf'), rgb('#b88a2f'), { endA: -.46, endB: -.38 }),
      { sdf: (x, y, z) => smin(smax(Math.abs(torso(x, y, z) - .03) - .02, diag(x, -y, -.28, .78) - .055, .012), bag(x, y, z), .02), min: [-1.05, -1, -.95], max: [1.05, .55, .85], voxel: .009, mat: 'matte', paint: (x, y, z, o) => { put(o, BAG); if (bag(x, y, z) < .01 && y > -.56) put(o, rgb('#7d4c1b')); if (Math.hypot(x + .66, y + .56) < .05) put(o, G); } },
    ];
  },
  // Меломан и геймер: худи и наушники
  // Наушники в своих цветах: тело, акцент, подсветка, худи, полоска, микрофон
  headset: (p) => headset(rgb(p.body), rgb(p.acc), rgb(p.led), rgb(p.hood), rgb(p.stripe), !!p.mic),
  music: () => headset(rgb('#f7f2ff'), rgb('#ff5fbf'), rgb('#ff8fdf'), rgb('#7b3fd8'), rgb('#c9a6ff'), false),
  gamer: () => headset(rgb('#1b1e28'), rgb('#3fd9ff'), rgb('#3fd9ff'), rgb('#20263a'), rgb('#3fd9ff'), true),
  // Пилот: кожаный шлем с ушами, куртка, белый шарф
  pilot: (p = {}) => {
    const B = rgb(p.B || '#6d4324'), B2 = rgb(p.B2 || '#4a2c15'), FUR = rgb(p.FUR || '#f4e6c9');
    const flaps = (x, y, z) => smin(ell(Math.abs(x), y, z, 1.02, -.15, -.02, .14, .36, .3), ell(Math.abs(x), y, z, 1, -.42, .08, .12, .14, .16), .05);
    return [
      shell((x, y, z, o) => { toHead(x, y, z); put(o, B); const a = Math.abs(hx); if (hy > .2) mixTo(o, B2, sstep(.02, .012, Math.abs(a - .26)) * .85); mixTo(o, FUR, sstep(.075, .05, Math.abs(cutLine(hy, hz)))); }, flaps, 'leather'),
      scarfPart(rgb('#ffffff'), rgb('#ffcf5c'), rgb('#c9d2dc'), { off: .09 }),
      { sdf: (x, y, z) => garment(x, y, z, .05, -.95, .02, .22), min: [-1, -1.1, -.95], max: [1, .2, 1], voxel: .01, mat: 'leather', paint: (x, y, z, o) => { put(o, B); if (y < -.82) put(o, B2); if (z > .1 && Math.abs(Math.abs(x) - .29) < .018) put(o, FUR); } },
    ];
  },
};
// Костюмы новых сервисов: свой цвет и детали на основе базового кроя. Ключ — имя образа в LOOKS.
const VARIANTS = {
  steam: ['headset', { body: '#1b2838', acc: '#66c0f4', led: '#66c0f4', hood: '#2a475e', stripe: '#c7d5e0', mic: true }],
  xbox: ['headset', { body: '#f2f4ef', acc: '#107c10', led: '#3ee03e', hood: '#0d4f0d', stripe: '#a6f5a6', mic: true }],
  nitro: ['headset', { body: '#eef0ff', acc: '#5865f2', led: '#9aa3ff', hood: '#3b44c4', stripe: '#d6daff', mic: false }],
  nintendo: ['racer', { A: '#e60012', B: '#2b2b33', C: '#9e000c', D: '#ffffff' }],
  valorant: ['racer', { A: '#ff4655', B: '#0f1923', C: '#b8202d', D: '#ece8e1' }],
  battle: ['knight', { GOLD: '#9fdcff', STEEL: '#2c5aa8', DK: '#173570', RUBY: '#7ff0ff' }],
  royal: ['knight', { GOLD: '#ffc21f', STEEL: '#3d74e0', DK: '#1d3f8f', RUBY: '#ff3d6a' }],
  razer: ['courier', { T: '#151a15', T2: '#0a0d0a', G: '#44d62c', BAG: '#2e332e' }],
  roblox: ['courier', { T: '#d62a20', T2: '#8f160f', G: '#f2f2f2', BAG: '#3a3d40' }],
  premium: ['pilot', { B: '#5b3fa8', B2: '#3a2775', FUR: '#f1e6ff' }],
  brawl: ['survivor', { RED: '#ffc400', WHITE: '#2a1650', LEATHER: '#4b2a7a', BRASS: '#ff5fa2' }],
  clans: ['mage', { V: '#7a3b12', V2: '#b5651d', G: '#ffd23f' }],
  vbucks: ['tactical', { O: '#5a3ca8', RIM: '#35226b', POUCH: '#7a5ad0', FLAP: '#2a1a57', PLATE: '#43308a', TAN: '#4fc3ff' }],
  starrail: ['mage', { V: '#1b2a5c', V2: '#3a5bb0', G: '#ffd98a' }],
  zenless: ['headset', { body: '#1c1c1f', acc: '#ffd500', led: '#ffd500', hood: '#2b2b30', stripe: '#ffd500', mic: false }],
  waves: ['survivor', { RED: '#2ec4b6', WHITE: '#e8fffb', LEATHER: '#1f3a4a', BRASS: '#d9c27a' }],
  codm: ['tactical', { O: '#8a7a55', RIM: '#5c5038', POUCH: '#a08e63', FLAP: '#4a402c', PLATE: '#6e6145', TAN: '#2f2f2f' }],
  football: ['racer', { A: '#1f6fff', B: '#0b1f4f', C: '#123f99', D: '#ffffff' }],
  kings: ['knight', { GOLD: '#ffcf4a', STEEL: '#b0262e', DK: '#6b1218', RUBY: '#ffe08a' }],
  standoff: ['tactical', { O: '#4a4f57', RIM: '#2c3036', POUCH: '#5d636c', FLAP: '#24272c', PLATE: '#383c43', TAN: '#ff8a1e' }],
};


// Затемнённое стекло без глаз: сверху почти чёрное, снизу цвет сервиса.
const TINTS = { lime: ['#061a03', '#1f6a0c', '#5fe02a'], red: ['#1c0306', '#8a0f1c', '#ff4655'], orange: ['#1c0b02', '#8a4206', '#ff9a2e'], blue: ['#030a24', '#0a2a78', '#2f7fe0'], sky: ['#03141f', '#0a4f80', '#3fb4ee'], ruby: ['#1c0308', '#7a0c20', '#e8344a'], green: ['#021a16', '#06604f', '#1fc79a'], pink: ['#1e0424', '#86187a', '#f060c8'], amber: ['#1c0a02', '#8a3a06', '#f08a1e'], violet: ['#0c0528', '#3d1d90', '#9a6bf0'], gold: ['#181203', '#6f520c', '#e8b92a'] };
function buildHead(lensTint) {
  const [a, b, c] = TINTS[lensTint].map(rgb), WHITE = [1, 1, 1], NAVY = rgb('#17123f'), CREAM = rgb('#ffe9b8'), BONE = rgb('#d7a968'), LINE = rgb('#0a4f3d');
  return {
    horns: sculpt({ sdf: inHead(hornD), min: [-1.3, .1, -.6], max: [1.3, 2.8, 1.3], voxel: .008, paint: (x, y, z, o) => { toHead(x, y, z); put(o, CREAM); mixTo(o, BONE, sstep(.95, 1.55, hy) * .7); } }),
    frame: sculpt({ sdf: inHead(frame), min: [-1.25, .55, -1.25], max: [1.25, 1.5, 1.32], voxel: .008, ao: .55, paint: (x, y, z, o) => put(o, NAVY) }),
    lens: sculpt({
      sdf: inHead((x, y, z) => (z > 0 ? lensD(x, y, z) : 1)), occluder: inHead(frame), min: [-.74, .7, .6], max: [.74, 1.4, 1.32], voxel: .005, ao: .5,
      paint: (x, y, z, o) => {
        toHead(x, y, z); toEye(hx, hy, hz);
        const vv = ev / .236, u = eu / .255, side = hx < 0 ? -1 : 1;
        put(o, a); mixTo(o, b, sstep(.75, -.15, vv)); mixTo(o, c, sstep(-.15, -1, vv) * .8);
        // косой блик идёт в одну сторону на обоих стёклах
        const s = u * side + vv * .75;
        mixTo(o, WHITE, sstep(.13, .09, Math.abs(s + .42)) * sstep(-.5, .1, vv) * .5);
        mixTo(o, WHITE, sstep(.045, .025, Math.abs(s + .14)) * sstep(-.2, .3, vv) * .32);
      },
    }),
    smile: sculpt({ sdf: inHead((x, y, z) => smax(smileD(Math.abs(x), y), Math.abs(faceD(x, y, z) - .004) - .007, .005)), min: [-.56, .25, .8], max: [.56, .8, 1.25], voxel: .004, ao: 0, paint: (x, y, z, o) => put(o, LINE) }),
    fang: sculpt({ sdf: inHead(fang), min: [.05, .2, .9], max: [.4, .55, 1.25], voxel: .004, ao: .3, paint: (x, y, z, o) => put(o, WHITE) }),
  };
}

function makeWingSDF() {
  const s = new THREE.Shape();
  s.moveTo(0, 0); s.bezierCurveTo(.5, .75, 1.05, 1.18, 1.72, 1.32); s.quadraticCurveTo(1.5, .9, 1.62, .55);
  s.quadraticCurveTo(1.3, .55, 1.28, .08); s.quadraticCurveTo(.95, .22, .78, -.28); s.quadraticCurveTo(.42, -.1, 0, -.3); s.closePath();
  const outline = polygon2d(s.getPoints(14).filter((p, i, a) => i === 0 || p.distanceTo(a[i - 1]) > 1e-4).filter((p, i, a) => i < a.length - 1 || p.distanceTo(a[0]) > 1e-4));
  const tips = [[1.72, 1.32], [1.62, .55], [1.28, .08], [.78, -.28]];
  const fold = (x, y) => -.1 * x * x + .05 * Math.sin(y * 3);
  const bones = tips.map(t => chain([[0, 0, fold(0, 0)], [t[0] * .55, t[1] * .62, fold(t[0] * .55, t[1] * .62)], [t[0], t[1], fold(t[0], t[1])]], [.07, .045, .02], .02));
  const bone = (x, y, z) => { let d = bones[0](x, y, z); for (let i = 1; i < 4; i++) d = Math.min(d, bones[i](x, y, z)); return d; };
  const flatBone = (x, y) => { let d = 1e3; for (const t of tips) { const l2 = t[0] * t[0] + t[1] * t[1], u = Math.max(0, Math.min(1, (x * t[0] + y * t[1]) / l2)); d = Math.min(d, Math.hypot(x - t[0] * u, y - t[1] * u)); } return d; };
  const sdf = (x, y, z) => {
    const edge = outline(x, y), z0 = fold(x, y) - .09 * sstep(0, .32, flatBone(x, y)) * sstep(0, .14, -edge) + .005 * Math.sin((x * 2 + y) * 26) * sstep(0, .2, flatBone(x, y));
    const m = smax(edge, Math.abs(z - z0) - .02, .018);
    return smin(m, bone(x, y, z), .03);
  };
  return { sdf, flatBone };
}

const MAT = {
  skin: { roughness: .46, clearcoat: .3, clearcoatRoughness: .45, sheen: .2, sheenRoughness: .6, sheenColor: new THREE.Color('#9dffdb') },
  paint: { roughness: .28, clearcoat: 1, clearcoatRoughness: .08 },
  matte: { roughness: .62, clearcoat: .2, clearcoatRoughness: .5 },
  leather: { roughness: .5, clearcoat: .35, clearcoatRoughness: .4 },
  metal: { roughness: .28, metalness: .7, clearcoat: .6, clearcoatRoughness: .2 },
  glass: { roughness: .06, clearcoat: 1, clearcoatRoughness: .03, metalness: .1, envMapIntensity: 1.25 },
  bone: { roughness: .42, clearcoat: .5, clearcoatRoughness: .3 },
};
const meshOf = (geo, m, tint) => {
  const mesh = new THREE.Mesh(geo, new THREE.MeshPhysicalMaterial({ vertexColors: true, ...MAT[m], ...(tint ? { color: new THREE.Color(tint) } : {}) }));
  mesh.castShadow = true; mesh.receiveShadow = true; return mesh;
};

const cache = {};
const once = (key, fn) => cache[key] || (cache[key] = fn());
// Костюмы игр из games.json
export function addVariants(v) { for (const k in v) VARIANTS[k] ??= v[k]; }
const baseOutfit = name => (VARIANTS[name] || [name])[0];
function buildOutfit(name) {
  const [base, pal] = VARIANTS[name] || [name];
  return OUTFITS[base](pal).map(p => {
    if (p.before) p.before();
    return { mat: p.mat, tint: p.tint, geo: sculpt({ sdf: p.sdf, occluder: (x, y, z) => Math.min(body(x, y, z), p.sdf(x, y, z)), min: p.min, max: p.max, voxel: p.voxel, ao: p.ao ?? 1.15, paint: p.paint }) };
  });
}
function statics() {
  const CREAM = rgb('#ffe9b8'), PLATE = rgb('#0a5f49'), wing = makeWingSDF(), WINGS = rgb('#128f6c'), WINGM = rgb('#0f7a5d'), WINGB = rgb('#0a5f49');
  return {
    claws: sculpt({ sdf: (x, y, z) => { const ax = Math.abs(x); let d = 1e3; for (const c of clawCones) d = Math.min(d, c(ax, y, z)); return d; }, occluder: body, min: [-.95, -1.6, .55], max: [.95, -1.3, 1], voxel: .008, ao: .6, paint: (x, y, z, o) => put(o, CREAM) }),
    plates: sculpt({ sdf: platesD, occluder: body, min: [.1, -1.75, -1.2], max: [2.3, -.1, .6], voxel: .008, ao: .9, paint: (x, y, z, o) => put(o, PLATE) }),
    wing: sculpt({ sdf: wing.sdf, min: [-.15, -.42, -.85], max: [1.85, 1.45, .25], voxel: .01, ao: 1.1, paint: (x, y, z, o) => { put(o, WINGM); mixTo(o, WINGS, sstep(.03, .22, wing.flatBone(x, y))); mixTo(o, WINGB, sstep(.05, .012, wing.flatBone(x, y))); } }),
  };
}

// Опора предмета: ручка вдоль оси кулака, лицевая сторона повёрнута к зрителю.
function placeHeld(held, P) {
  if (P.center && held.userData.centered) { held.position.set(...P.center); held.rotation.set(.04, .34, 0); return; }
  const Y = v.norm(P.R.axis).map(q => -q), cam = [.32, .05, 1], Z = v.norm(v.add(cam, Y, -v.dot(cam, Y))), X = v.cross(Y, Z);
  held.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(new THREE.Vector3(...X), new THREE.Vector3(...Y), new THREE.Vector3(...Z)));
  held.position.set(...P.R.grip);
}

export function makeMascot({ pose = 'wave', outfit = 'racer', lens = 'blue', cuff = '#e8323a', cape: capeTint = '#b0132f' }, extras = {}) {
  const P = POSES[pose];
  setTilt(P.tilt);
  const st = once('static', statics), head = once(`head|${lens}|${P.tilt}`, () => buildHead(lens)), arms = once(`pose|${pose}`, () => buildPose(pose));
  const parts = once(`outfit|${outfit}|${P.tilt}`, () => buildOutfit(outfit));
  const g = new THREE.Group();
  g.add(meshOf(arms.skin, 'skin'), meshOf(arms.handL, 'skin'), meshOf(arms.handR, 'skin'), meshOf(arms.cuffs, 'matte', cuff));
  if (arms.handClaws) g.add(meshOf(arms.handClaws, 'bone'));
  g.add(meshOf(head.horns, 'bone'), meshOf(head.frame, 'paint'), meshOf(head.lens, 'glass'), meshOf(head.smile, 'matte'), meshOf(head.fang, 'bone'));
  g.add(meshOf(st.claws, 'bone'), meshOf(st.plates, 'skin'));
  for (const p of parts) g.add(meshOf(p.geo, p.mat, p.tint === 'cape' ? capeTint : null));
  for (const sx of [-1, 1]) {
    const w = meshOf(st.wing, 'skin');
    w.material.side = THREE.DoubleSide; w.scale.set(sx * 1.32, 1.32, 1.1); w.position.set(sx * .4, -.06, -.46); w.rotation.y = sx * .3; w.rotation.z = sx * .08; g.add(w);
  }
  if (extras.medal && pose !== 'front') { const off = { tactical: [.02, -.24, .84], knight: [.02, -.36, .82], pilot: [.02, -.34, .78], music: [.02, -.3, .86], gamer: [.02, -.3, .86], survivor: [.02, -.86, .84], headset: [.02, -.3, .86] }[baseOutfit(outfit)] || [.02, -.36, .75]; extras.medal.position.set(...off); g.add(extras.medal); }
  if (extras.held) { placeHeld(extras.held, P); g.add(extras.held); }
  return g;
}
