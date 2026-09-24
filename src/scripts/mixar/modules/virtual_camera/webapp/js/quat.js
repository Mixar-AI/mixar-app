/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* Minimal quaternion helpers (no dependencies).
 * Quaternions are [w, x, y, z]. */
"use strict";

const Quat = {
  identity() { return [1, 0, 0, 0]; },

  multiply(a, b) {
    const [aw, ax, ay, az] = a;
    const [bw, bx, by, bz] = b;
    return [
      aw * bw - ax * bx - ay * by - az * bz,
      aw * bx + ax * bw + ay * bz - az * by,
      aw * by - ax * bz + ay * bw + az * bx,
      aw * bz + ax * by - ay * bx + az * bw,
    ];
  },

  normalize(q) {
    const n = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
    return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
  },

  fromAxisAngle(x, y, z, angle) {
    const h = angle / 2;
    const s = Math.sin(h);
    return [Math.cos(h), x * s, y * s, z * s];
  },

  /* Euler (radians) applied in YXZ intrinsic order — matches the standard
   * device-orientation convention used by three.js. */
  fromEulerYXZ(x, y, z) {
    const c1 = Math.cos(x / 2), s1 = Math.sin(x / 2);
    const c2 = Math.cos(y / 2), s2 = Math.sin(y / 2);
    const c3 = Math.cos(z / 2), s3 = Math.sin(z / 2);
    return [
      c1 * c2 * c3 + s1 * s2 * s3,
      s1 * c2 * c3 + c1 * s2 * s3,
      c1 * s2 * c3 - s1 * c2 * s3,
      c1 * c2 * s3 - s1 * s2 * c3,
    ];
  },
};
