/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* Device-orientation capture → camera quaternion in Blender world convention.
 *
 * Pipeline (standard device-orientation-to-camera math):
 *   1. alpha/beta/gamma (deg) → quaternion via YXZ euler (device frame, Y-up world)
 *   2. rotate -90° about X so the screen faces the viewer (back camera looks forward)
 *   3. compensate the screen-orientation angle about the view axis
 *   4. convert the Y-up world to Blender's Z-up world (+90° about X)
 * Camera local convention matches Blender's (look down -Z, +Y up), so no
 * further local correction is needed. */
"use strict";

const Sensors = (() => {
  const DEG = Math.PI / 180;
  const Q_SCREEN = Quat.fromAxisAngle(1, 0, 0, -Math.PI / 2); // step 2
  const Q_ZUP = Quat.fromAxisAngle(1, 0, 0, Math.PI / 2);     // step 4

  let latest = null;        // latest Blender-convention quaternion [w,x,y,z]
  let available = false;
  let onFirstReading = null;

  function screenAngle() {
    if (screen.orientation && typeof screen.orientation.angle === "number") {
      return screen.orientation.angle;
    }
    return typeof window.orientation === "number" ? window.orientation : 0;
  }

  function handleOrientation(e) {
    if (e.alpha === null || e.beta === null || e.gamma === null) return;
    const alpha = e.alpha * DEG, beta = e.beta * DEG, gamma = e.gamma * DEG;

    let q = Quat.fromEulerYXZ(beta, alpha, -gamma);
    q = Quat.multiply(q, Q_SCREEN);
    q = Quat.multiply(q, Quat.fromAxisAngle(0, 0, 1, -screenAngle() * DEG));
    q = Quat.multiply(Q_ZUP, q);
    latest = Quat.normalize(q);

    if (!available) {
      available = true;
      if (onFirstReading) onFirstReading();
    }
  }

  /* Must be called from a user gesture: iOS 13+ gates sensor access behind
   * DeviceOrientationEvent.requestPermission(), and only in a secure context. */
  async function requestAccess() {
    if (typeof DeviceOrientationEvent === "undefined") {
      return { ok: false, reason: "no-sensor-api" };
    }
    if (window.isSecureContext !== true) {
      /* Android has no `requestPermission` gate, so nothing below fails —
       * `deviceorientation` simply never fires outside a secure context and
       * the phone sits on a motion button that reports success and does
       * nothing. iOS reaches the same answer through a denied permission. */
      return { ok: false, reason: "insecure-context" };
    }
    if (typeof DeviceOrientationEvent.requestPermission === "function") {
      let state;
      try {
        state = await DeviceOrientationEvent.requestPermission();
      } catch (err) {
        return { ok: false, reason: "permission-error" };
      }
      if (state !== "granted") return { ok: false, reason: "denied" };
    }
    window.addEventListener("deviceorientation", handleOrientation, true);
    return { ok: true };
  }

  return {
    requestAccess,
    isSecureContext: () => window.isSecureContext === true,
    hasReading: () => available,
    setFirstReadingCallback: (fn) => { onFirstReading = fn; },
    latestQuat: () => latest,
  };
})();
