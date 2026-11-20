// Лепка по полю расстояний: части сливаются без швов, нормали и затенение в складках считаются из самого поля.
import * as THREE from 'three';

export const smin = (a, b, k) => { const h = Math.max(k - Math.abs(a - b), 0) / k; return Math.min(a, b) - h * h * k * .25; };
export const smax = (a, b, k) => -smin(-a, -b, k);
export const sstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };

export function ell(x, y, z, cx, cy, cz, rx, ry, rz) {
  const px = x - cx, py = y - cy, pz = z - cz;
  const k0 = Math.sqrt(px * px / (rx * rx) + py * py / (ry * ry) + pz * pz / (rz * rz));
  const k1 = Math.sqrt(px * px / (rx * rx * rx * rx) + py * py / (ry * ry * ry * ry) + pz * pz / (rz * rz * rz * rz));
  return k1 < 1e-9 ? -Math.min(rx, ry, rz) : k0 * (k0 - 1) / k1;
}

export function roundBox(x, y, z, cx, cy, cz, hx, hy, hz, r) {
  const qx = Math.abs(x - cx) - hx + r, qy = Math.abs(y - cy) - hy + r, qz = Math.abs(z - cz) - hz + r;
  const ax = Math.max(qx, 0), ay = Math.max(qy, 0), az = Math.max(qz, 0);
  return Math.sqrt(ax * ax + ay * ay + az * az) + Math.min(Math.max(qx, qy, qz), 0) - r;
}

// Конус со скруглёнными концами от точки a (радиус r1) до точки b (радиус r2).
export function roundCone(a, b, r1, r2) {
  const bx = b[0] - a[0], by = b[1] - a[1], bz = b[2] - a[2];
  const l2 = bx * bx + by * by + bz * bz, rr = r1 - r2, a2 = l2 - rr * rr, il2 = 1 / l2, sg = Math.sign(rr), kk = sg * rr * rr;
  return (x, y, z) => {
    const px = x - a[0], py = y - a[1], pz = z - a[2];
    const dy = px * bx + py * by + pz * bz, dz = dy - l2;
    const qx = px * l2 - bx * dy, qy = py * l2 - by * dy, qz = pz * l2 - bz * dy;
    const x2 = qx * qx + qy * qy + qz * qz, y2 = dy * dy * l2, z2 = dz * dz * l2, k = kk * x2;
    if (Math.sign(dz) * a2 * z2 > k) return Math.sqrt(x2 + z2) * il2 - r2;
    if (Math.sign(dy) * a2 * y2 < k) return Math.sqrt(x2 + y2) * il2 - r1;
    return (Math.sqrt(x2 * a2 * il2) + dy * rr) * il2 - r1;
  };
}

// Гладкая цепочка конусов: хвост, руки, рёбра крыла.
export function chain(points, radii, k = .05) {
  const parts = [];
  for (let i = 0; i < points.length - 1; i++) parts.push(roundCone(points[i], points[i + 1], radii[i], radii[i + 1]));
  return (x, y, z) => { let d = parts[0](x, y, z); for (let i = 1; i < parts.length; i++) d = smin(d, parts[i](x, y, z), k); return d; };
}

// Плоский многоугольник: знаковое расстояние в плоскости.
export function polygon2d(pts) {
  return (x, y) => {
    let d = Infinity, s = 1;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i, i++) {
      const ax = pts[i].x, ay = pts[i].y, bx = pts[j].x, by = pts[j].y, ex = bx - ax, ey = by - ay, wx = x - ax, wy = y - ay;
      const t = Math.min(1, Math.max(0, (wx * ex + wy * ey) / (ex * ex + ey * ey))), qx = wx - ex * t, qy = wy - ey * t;
      d = Math.min(d, qx * qx + qy * qy);
      const c1 = y >= ay, c2 = y < by, c3 = ex * wy > ey * wx;
      if ((c1 && c2 && c3) || (!c1 && !c2 && !c3)) s = -s;
    }
    return s * Math.sqrt(d);
  };
}

const AO_STEPS = [[.035, .34], [.09, .3], [.2, .24], [.42, .12]];

// Сетка Surface Nets: вершины ставятся на поверхность, нормали берутся из градиента поля.
export function sculpt({ sdf, min, max, voxel, paint, occluder = sdf, ao = 1.4 }) {
  const nx = Math.ceil((max[0] - min[0]) / voxel) + 2, ny = Math.ceil((max[1] - min[1]) / voxel) + 2, nz = Math.ceil((max[2] - min[2]) / voxel) + 2;
  const sxy = nx * ny, F = new Float32Array(sxy * nz).fill(1e3), B = 8, skip = voxel * B * Math.sqrt(3) * .8;
  // Блоки вдали от поверхности пропускаем, поле считаем только рядом с ней.
  for (let bz = 0; bz < nz - 1; bz += B) for (let by = 0; by < ny - 1; by += B) for (let bx = 0; bx < nx - 1; bx += B) {
    const c = sdf(min[0] + (bx + B / 2) * voxel, min[1] + (by + B / 2) * voxel, min[2] + (bz + B / 2) * voxel);
    const ez = Math.min(bz + B, nz - 1), ey = Math.min(by + B, ny - 1), ex = Math.min(bx + B, nx - 1);
    if (Math.abs(c) > skip) {
      if (c < 0) for (let k = bz; k <= ez; k++) for (let j = by; j <= ey; j++) F.fill(-1e3, bx + j * nx + k * sxy, ex + j * nx + k * sxy + 1);
      continue;
    }
    for (let k = bz; k <= ez; k++) for (let j = by; j <= ey; j++) for (let i = bx; i <= ex; i++)
      F[i + j * nx + k * sxy] = sdf(min[0] + i * voxel, min[1] + j * voxel, min[2] + k * voxel);
  }
  const cell = new Int32Array(F.length).fill(-1), pos = [];
  const CORNERS = [0, 1, nx, nx + 1, sxy, sxy + 1, sxy + nx, sxy + nx + 1];
  const EDGES = [[0, 1], [0, 2], [0, 4], [1, 3], [1, 5], [2, 3], [2, 6], [3, 7], [4, 5], [4, 6], [5, 7], [6, 7]];
  const OFF = [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]];
  for (let k = 0; k < nz - 1; k++) for (let j = 0; j < ny - 1; j++) for (let i = 0; i < nx - 1; i++) {
    const o = i + j * nx + k * sxy; let mask = 0;
    for (let c = 0; c < 8; c++) if (F[o + CORNERS[c]] < 0) mask |= 1 << c;
    if (mask === 0 || mask === 255) continue;
    let sx = 0, sy = 0, sz = 0, n = 0;
    for (const [a, b] of EDGES) {
      const fa = F[o + CORNERS[a]], fb = F[o + CORNERS[b]];
      if ((fa < 0) === (fb < 0)) continue;
      const t = fa / (fa - fb), A = OFF[a], Bc = OFF[b];
      sx += A[0] + (Bc[0] - A[0]) * t; sy += A[1] + (Bc[1] - A[1]) * t; sz += A[2] + (Bc[2] - A[2]) * t; n++;
    }
    cell[o] = pos.length / 3;
    pos.push(min[0] + (i + sx / n) * voxel, min[1] + (j + sy / n) * voxel, min[2] + (k + sz / n) * voxel);
  }
  // Посадка вершин на поверхность, нормали, цвет и затенение в складках.
  const count = pos.length / 3, P = new Float32Array(pos), N = new Float32Array(count * 3), C = new Float32Array(count * 3), e = voxel * .5, rgb = [0, 0, 0];
  for (let v = 0; v < count; v++) {
    let x = P[v * 3], y = P[v * 3 + 1], z = P[v * 3 + 2], gx = 0, gy = 0, gz = 0;
    for (let it = 0; it < 3; it++) {
      gx = sdf(x + e, y, z) - sdf(x - e, y, z); gy = sdf(x, y + e, z) - sdf(x, y - e, z); gz = sdf(x, y, z + e) - sdf(x, y, z - e);
      const l = Math.sqrt(gx * gx + gy * gy + gz * gz) || 1; gx /= l; gy /= l; gz /= l;
      if (it < 2) { const d = sdf(x, y, z); x -= gx * d; y -= gy * d; z -= gz * d; }
    }
    P[v * 3] = x; P[v * 3 + 1] = y; P[v * 3 + 2] = z; N[v * 3] = gx; N[v * 3 + 1] = gy; N[v * 3 + 2] = gz;
    let occ = 0;
    for (const [h, w] of AO_STEPS) occ += w * Math.max(0, (h - occluder(x + gx * h, y + gy * h, z + gz * h)) / h);
    const shade = Math.max(.12, 1 - occ * ao);
    paint(x, y, z, rgb);
    C[v * 3] = rgb[0] * shade; C[v * 3 + 1] = rgb[1] * shade; C[v * 3 + 2] = rgb[2] * shade;
  }
  // Четырёхугольники вокруг рёбер со сменой знака; сторону сверяем с нормалью поля.
  const idx = [];
  const quad = (a, b, c, d) => {
    if (a < 0 || b < 0 || c < 0 || d < 0) return;
    const ux = P[b * 3] - P[a * 3], uy = P[b * 3 + 1] - P[a * 3 + 1], uz = P[b * 3 + 2] - P[a * 3 + 2];
    const wx = P[c * 3] - P[a * 3], wy = P[c * 3 + 1] - P[a * 3 + 1], wz = P[c * 3 + 2] - P[a * 3 + 2];
    const front = (uy * wz - uz * wy) * N[a * 3] + (uz * wx - ux * wz) * N[a * 3 + 1] + (ux * wy - uy * wx) * N[a * 3 + 2] > 0;
    if (front) idx.push(a, b, c, a, c, d); else idx.push(a, c, b, a, d, c);
  };
  for (let k = 1; k < nz - 1; k++) for (let j = 1; j < ny - 1; j++) for (let i = 1; i < nx - 1; i++) {
    const o = i + j * nx + k * sxy, s = F[o] < 0;
    if (s !== (F[o + 1] < 0)) quad(cell[o], cell[o - nx], cell[o - nx - sxy], cell[o - sxy]);
    if (s !== (F[o + nx] < 0)) quad(cell[o], cell[o - 1], cell[o - 1 - sxy], cell[o - sxy]);
    if (s !== (F[o + sxy] < 0)) quad(cell[o], cell[o - 1], cell[o - 1 - nx], cell[o - nx]);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(P, 3));
  geo.setAttribute('normal', new THREE.BufferAttribute(N, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(C, 3));
  geo.setIndex(count > 65000 ? new THREE.Uint32BufferAttribute(idx, 1) : new THREE.Uint16BufferAttribute(idx, 1));
  geo.userData.keep = true;
  return geo;
}
