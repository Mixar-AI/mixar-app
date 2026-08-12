/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* Touch joysticks: each zone maps pointer offset to a normalized [-1, 1] vector. */
"use strict";

function Joystick(zoneEl) {
  const base = zoneEl.querySelector(".joy-base");
  const knob = zoneEl.querySelector(".joy-knob");
  const DEADZONE = 0.08;
  let pointerId = null;
  let center = null;
  let value = [0, 0]; // x: right+, y: up+

  function radius() { return base.clientWidth / 2; }

  function setKnob(nx, ny) {
    const r = radius() * 0.75;
    knob.style.transform =
      `translate(calc(-50% + ${nx * r}px), calc(-50% + ${-ny * r}px))`;
  }

  function update(e) {
    const r = radius();
    let nx = (e.clientX - center.x) / r;
    let ny = -(e.clientY - center.y) / r;
    const len = Math.hypot(nx, ny);
    if (len > 1) { nx /= len; ny /= len; }
    value = [nx, ny];
    setKnob(nx, ny);
  }

  function release() {
    pointerId = null;
    value = [0, 0];
    setKnob(0, 0);
    zoneEl.classList.remove("active");
  }

  zoneEl.addEventListener("pointerdown", (e) => {
    if (pointerId !== null) return;
    pointerId = e.pointerId;
    zoneEl.setPointerCapture(e.pointerId);
    zoneEl.classList.add("active");
    const rect = base.getBoundingClientRect();
    center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    update(e);
    e.preventDefault();
  });
  zoneEl.addEventListener("pointermove", (e) => {
    if (e.pointerId !== pointerId) return;
    update(e);
    e.preventDefault();
  });
  for (const ev of ["pointerup", "pointercancel"]) {
    zoneEl.addEventListener(ev, (e) => {
      if (e.pointerId !== pointerId) return;
      release();
      e.preventDefault();
    });
  }

  return {
    /* Deadzone-filtered value, re-scaled so output stays continuous. */
    value() {
      const [x, y] = value;
      const len = Math.hypot(x, y);
      if (len < DEADZONE) return [0, 0];
      const scale = (len - DEADZONE) / (1 - DEADZONE) / len;
      return [x * scale, y * scale];
    },
    isActive: () => pointerId !== null,
  };
}
