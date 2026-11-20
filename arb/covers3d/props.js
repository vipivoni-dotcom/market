// Предметы в руке маскота: обычные вещи без логотипов и без копий игровых моделей.
// Ручка идёт вдоль оси Y через начало координат, лицевая сторона смотрит вдоль +Z.
import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

const mat = (color, o = {}) => new THREE.MeshPhysicalMaterial({ color, roughness: .4, clearcoat: .5, clearcoatRoughness: .3, ...o });
const METAL = () => mat('#aeb6c2', { metalness: .85, roughness: .28 }), GOLD = () => mat('#ffc21f', { metalness: .7, roughness: .24, clearcoat: 1, emissive: '#7a4a00', emissiveIntensity: .25 });
const add = (g, geo, m, p = [0, 0, 0], r = [0, 0, 0]) => { const o = new THREE.Mesh(geo, m); o.position.set(...p); o.rotation.set(...r); o.castShadow = true; o.receiveShadow = true; g.add(o); return o; };
const disc = (r, h, seg = 96) => new THREE.CylinderGeometry(r, r, h, seg).rotateX(Math.PI / 2);

// Сковородка: тёмная сторона к зрителю, на ней вмятины от пуль и блик по кругу.
function pan() {
  const g = new THREE.Group(), R = .56, cy = .98;
  const prof = [[0, -.07], [R - .07, -.07], [R - .01, -.03], [R + .03, .07], [R + .015, .09], [R - .05, .02], [0, .02]].map(([r, y]) => new THREE.Vector2(r, y));
  add(g, new THREE.LatheGeometry(prof, 128).rotateX(Math.PI / 2), mat('#41454d', { metalness: .6, roughness: .38, clearcoat: .7 }), [0, cy, 0]);
  add(g, new THREE.TorusGeometry(R + .018, .017, 12, 128), METAL(), [0, cy, .08]);
  add(g, new THREE.TorusGeometry(R * .62, .007, 8, 96), mat('#555b66', { metalness: .9, roughness: .3 }), [0, cy, .028]);
  // вмятины: тёмное углубление со светлым валиком
  [[-.22, .16, .07], [.2, .24, .055], [.1, -.2, .08], [-.28, -.16, .045]].forEach(([x, y, r]) => {
    add(g, disc(r, .01, 32), mat('#0f1114', { metalness: .6, roughness: .6 }), [x, cy + y, .027]);
    add(g, new THREE.TorusGeometry(r, r * .22, 8, 32), mat('#70767f', { metalness: .9, roughness: .26 }), [x, cy + y, .03]);
  });
  add(g, new RoundedBoxGeometry(.16, .3, .07, 4, .03), METAL(), [0, .42, .02]);
  add(g, new RoundedBoxGeometry(.15, .86, .1, 6, .045), mat('#6b3f1d', { roughness: .62 }), [0, -.02, .02]);
  [.3, -.36].forEach(y => add(g, new THREE.SphereGeometry(.022, 12, 12), METAL(), [0, y, .075]));
  add(g, new THREE.TorusGeometry(.05, .014, 8, 24), METAL(), [0, -.48, .02]);
  return g;
}

function drumstick() {
  const g = new THREE.Group();
  const meat = [[0, .72], [.12, .71], [.27, .63], [.36, .48], [.36, .32], [.28, .18], [.16, .08], [.08, 0]].reverse().map(([r, y]) => new THREE.Vector2(r, y));
  add(g, new THREE.LatheGeometry(meat, 64), mat('#b8651d', { roughness: .32, clearcoat: 1, clearcoatRoughness: .2, emissive: '#3a1500', emissiveIntensity: .3 }));
  [[-.16, .48, .3, .09], [.14, .36, .31, .07], [.02, .58, .24, .08]].forEach(([x, y, z, r]) => { const o = add(g, new THREE.SphereGeometry(r, 16, 16), mat('#8a430f', { roughness: .4, clearcoat: .8 }), [x, y, z]); o.scale.z = .35; });
  add(g, new THREE.CylinderGeometry(.06, .055, .46, 24), mat('#f3e7cf', { roughness: .5 }), [0, -.14, 0]);
  [-.05, .05].forEach(x => add(g, new THREE.SphereGeometry(.075, 20, 20), mat('#f3e7cf', { roughness: .5 }), [x, -.38, 0]));
  return g;
}

function sword() {
  const g = new THREE.Group(), s = new THREE.Shape();
  [[-.1, .2], [-.085, 1.42], [0, 1.68], [.085, 1.42], [.1, .2]].forEach(([x, y], i) => (i ? s.lineTo(x, y) : s.moveTo(x, y))); s.closePath();
  const blade = new THREE.ExtrudeGeometry(s, { depth: .012, bevelEnabled: true, bevelThickness: .035, bevelSize: .022, bevelSegments: 2 }).translate(0, 0, -.006);
  add(g, blade, mat('#d9e4f2', { metalness: .9, roughness: .17, clearcoat: 1 }));
  add(g, new RoundedBoxGeometry(.035, 1.06, .03, 3, .01), mat('#7da7d8', { metalness: .8, roughness: .24, emissive: '#2b6cd6', emissiveIntensity: .4 }), [0, .78, .034]);
  add(g, new RoundedBoxGeometry(.62, .09, .12, 5, .04), GOLD(), [0, .2, 0]);
  [-.31, .31].forEach(x => add(g, new THREE.SphereGeometry(.07, 20, 20), GOLD(), [x, .2, 0]));
  add(g, new THREE.OctahedronGeometry(.06), mat('#ff3b5c', { roughness: .1, clearcoat: 1, emissive: '#a00020', emissiveIntensity: .5, flatShading: true }), [0, .2, .07]);
  add(g, new THREE.CylinderGeometry(.055, .055, .4, 24), mat('#4a2412', { roughness: .7 }), [0, -.02, 0]);
  add(g, new THREE.SphereGeometry(.085, 20, 20), GOLD(), [0, -.25, 0]);
  g.scale.setScalar(.84);
  return g;
}

// Факел: три слоя пламени светятся от жёлтого к красному.
function flame() {
  const g = new THREE.Group();
  add(g, new THREE.CylinderGeometry(.05, .07, .62, 24), mat('#4a2c16', { roughness: .75 }), [0, -.02, 0]);
  add(g, new THREE.CylinderGeometry(.13, .08, .16, 24), METAL(), [0, .34, 0]);
  // языки пламени лежат друг перед другом, поэтому видны все три цвета
  const tongue = k => {
    const p = new THREE.Shape(); p.moveTo(0, 0);
    p.bezierCurveTo(-.34 * k, .02 * k, -.42 * k, .34 * k, -.2 * k, .56 * k);
    p.bezierCurveTo(-.2 * k, .44 * k, -.12 * k, .4 * k, -.08 * k, .42 * k);
    p.bezierCurveTo(-.14 * k, .68 * k, -.02 * k, .92 * k, .1 * k, 1.04 * k);
    p.bezierCurveTo(.06 * k, .84 * k, .18 * k, .72 * k, .24 * k, .62 * k);
    p.bezierCurveTo(.26 * k, .68 * k, .3 * k, .72 * k, .34 * k, .74 * k);
    p.bezierCurveTo(.46 * k, .42 * k, .36 * k, .02 * k, 0, 0);
    return new THREE.ExtrudeGeometry(p, { depth: .03, bevelEnabled: true, bevelThickness: .03, bevelSize: .02, bevelSegments: 3, curveSegments: 18 });
  };
  [['#ff3d0a', 1, .4, 0], ['#ff8a12', .74, .42, .07], ['#ffd84a', .48, .43, .14], ['#fff6c2', .24, .44, .2]].forEach(([c, k, y, z]) => {
    const o = new THREE.Mesh(tongue(k), new THREE.MeshBasicMaterial({ color: c, fog: false, toneMapped: false })); o.position.set(0, y, z); g.add(o);
  });
  return g;
}

function staff(crystal) {
  const g = new THREE.Group();
  add(g, new THREE.CylinderGeometry(.04, .05, 1.8, 20), mat('#4a2c6e', { roughness: .5 }), [0, .3, 0]);
  [-.5, .1, .9].forEach(y => add(g, new THREE.TorusGeometry(.055, .018, 10, 24).rotateX(Math.PI / 2), GOLD(), [0, y, 0]));
  add(g, new THREE.TorusGeometry(.3, .026, 12, 64), GOLD(), [0, 1.36, 0]);
  crystal.scale.setScalar(.27); crystal.position.set(0, 1.36, 0); g.add(crystal);
  g.scale.setScalar(.8);
  return g;
}

function wand(star) {
  const g = new THREE.Group();
  add(g, new THREE.CylinderGeometry(.035, .045, .95, 20), mat('#f3f6ff', { roughness: .3, clearcoat: 1 }), [0, .15, 0]);
  [-.1, .25].forEach(y => add(g, new THREE.CylinderGeometry(.048, .048, .05, 20), GOLD(), [0, y, 0]));
  star.scale.setScalar(.4); star.position.set(0, .92, 0); g.add(star);
  return g;
}

function phone() {
  const g = new THREE.Group(), c = document.createElement('canvas'); c.width = 320; c.height = 640; const x = c.getContext('2d');
  const lg = x.createLinearGradient(0, 0, 320, 640); lg.addColorStop(0, '#ff6fd0'); lg.addColorStop(1, '#5b2be0'); x.fillStyle = lg; x.fillRect(0, 0, 320, 640);
  const colors = ['#ffd66b', '#7cf2c0', '#8fd0ff', '#ffffff', '#ff9a7a', '#c9b6ff', '#ffffff', '#ffd66b', '#7cf2c0'];
  colors.forEach((k, i) => { x.fillStyle = k; x.beginPath(); x.roundRect(36 + (i % 3) * 92, 110 + Math.floor(i / 3) * 104, 64, 64, 16); x.fill(); });
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  add(g, new RoundedBoxGeometry(.56, 1.08, .07, 6, .03), mat('#1b1d24', { metalness: .6, roughness: .25, clearcoat: 1 }), [0, .34, 0]);
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(.5, 1), new THREE.MeshPhysicalMaterial({ map: tex, roughness: .18, clearcoat: 1, emissive: '#ffffff', emissiveMap: tex, emissiveIntensity: .32 })); scr.position.set(0, .34, .037); g.add(scr);
  return g;
}

function gamepad() {
  const g = new THREE.Group(), body = mat('#20232c', { roughness: .36, clearcoat: .8 });
  add(g, new RoundedBoxGeometry(1.06, .46, .22, 8, .1), body);
  [-1, 1].forEach(s => { const o = add(g, new THREE.CapsuleGeometry(.14, .3, 8, 20), body, [s * .46, -.2, -.01], [0, 0, s * .34]); o.scale.z = .85; });
  // левый крест, стики и четыре кнопки разных цветов
  add(g, new RoundedBoxGeometry(.22, .065, .03, 3, .012), METAL(), [-.32, .04, .115]); add(g, new RoundedBoxGeometry(.065, .22, .03, 3, .012), METAL(), [-.32, .04, .115]);
  [[-.15, -.12], [.15, -.12]].forEach(([x, y]) => { add(g, disc(.07, .05, 28), mat('#0c0d12', { roughness: .3 }), [x, y, .125]); add(g, disc(.05, .03, 28), mat('#30343f', { roughness: .55 }), [x, y, .155]); });
  [[.32, .14, '#ffd24a'], [.43, .04, '#ff5a6a'], [.21, .04, '#4ac6ff'], [.32, -.06, '#5be08a']].forEach(([x, y, c]) => add(g, disc(.042, .04, 20), mat(c, { roughness: .2, clearcoat: 1, emissive: c, emissiveIntensity: .35 }), [x, y, .12]));
  add(g, new RoundedBoxGeometry(.2, .05, .02, 3, .01), mat('#39e6ff', { emissive: '#39e6ff', emissiveIntensity: 1.1 }), [0, .15, .115]);
  return g;
}

function gift(ribbon = '#ffd24a', box = '#ff4f6d') {
  const g = new THREE.Group(), r = mat(ribbon, { metalness: .25, roughness: .3, clearcoat: 1 });
  add(g, new RoundedBoxGeometry(.8, .62, .62, 6, .05), mat(box, { roughness: .42, clearcoat: .7 }));
  add(g, new RoundedBoxGeometry(.88, .16, .68, 6, .05), mat(box, { roughness: .38, clearcoat: .8 }), [0, .33, 0]);
  add(g, new RoundedBoxGeometry(.13, .67, .65, 3, .02), r, [0, .02, 0]); add(g, new RoundedBoxGeometry(.91, .17, .13, 3, .02), r, [0, .33, 0]); add(g, new RoundedBoxGeometry(.13, .17, .71, 3, .02), r, [0, .33, 0]);
  [-1, 1].forEach(s => { const o = add(g, new THREE.TorusGeometry(.13, .04, 12, 32), r, [s * .14, .5, 0], [0, 0, s * .5]); o.scale.y = .7; });
  add(g, new THREE.SphereGeometry(.055, 16, 16), r, [0, .47, 0]);
  return g;
}

export const PROPS = { pan, drumstick, sword, flame, staff, wand, phone, gamepad, gift };
