/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/* Mixar Virtual Camera — main app glue.
 * Gate → sensor permission → WebSocket pairing → 60 Hz control loop. */
"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const gate = $("gate"), main = $("main");
  const gateStatus = $("gate-status");
  const streamImg = $("stream"), streamOff = $("stream-off");

  const joyLeft = Joystick($("joy-left"));
  const joyRight = Joystick($("joy-right"));

  let sendRateHz = 60;
  let sendTimer = null;
  let motionEnabled = false;
  let lastStreamUrl = null;
  let wakeLock = null;

  /* ---------- Gate / connect flow ---------- */

  $("btn-connect").addEventListener("click", async () => {
    if (!Net.hasToken()) {
      gateStatus.textContent =
        "Missing pairing token — scan the QR code shown in Mixar again.";
      return;
    }
    const sensor = await Sensors.requestAccess();
    if (!sensor.ok) {
      motionEnabled = false;
      if (sensor.reason === "denied") {
        gateStatus.textContent =
          "Motion permission denied — joystick control only. Connecting…";
      } else if (!Sensors.isSecureContext()) {
        gateStatus.textContent =
          "No secure connection: motion sensors unavailable, joystick control only. Connecting…";
      } else {
        gateStatus.textContent = "Motion sensors unavailable — joystick control only. Connecting…";
      }
    } else {
      motionEnabled = true;
      gateStatus.textContent = "Connecting…";
    }
    Net.connect();
  });

  Net.on("open", () => {
    gate.classList.add("hidden");
    main.classList.remove("hidden");
    $("conn-dot").classList.add("ok");
    setMotionButton();
    startControlLoop();
    acquireWakeLock();
  });

  Net.on("close", () => {
    $("conn-dot").classList.remove("ok");
    stopControlLoop();
    if (!gate.classList.contains("hidden")) {
      /* Never got through: `main` is still hidden and the toast lives
       * inside it, so a failure here used to be completely silent — the
       * phone sat on "Connecting…" for as long as anyone was willing to
       * wait. The gate is the only surface it can see. */
      gateStatus.textContent =
        "Could not reach Mixar — check it is still showing the QR code, " +
        "and that the phone is on the same network. Retrying…";
      return;
    }
    toast("Connection lost — reconnecting…");
  });

  /* ---------- Control loop ---------- */

  function startControlLoop() {
    stopControlLoop();
    sendTimer = setInterval(() => {
      const q = motionEnabled ? Sensors.latestQuat() : null;
      Net.send({ t: "ctl", q, j1: joyLeft.value(), j2: joyRight.value() });
    }, Math.max(1000 / sendRateHz, 16));
  }
  function stopControlLoop() {
    if (sendTimer) { clearInterval(sendTimer); sendTimer = null; }
  }

  /* ---------- Server messages ---------- */

  Net.on("message", (msg) => {
    if (msg.t === "welcome" || msg.t === "state") applyState(msg);
    else if (msg.t === "toast") toast(msg.msg);
  });

  Net.on("frame", (buf) => {
    const url = URL.createObjectURL(new Blob([buf]));
    streamImg.src = url;
    streamOff.classList.add("hidden");
    if (lastStreamUrl) URL.revokeObjectURL(lastStreamUrl);
    lastStreamUrl = url;
  });

  function applyState(s) {
    if (s.cameras) {
      const sel = $("camera-select");
      sel.replaceChildren();
      for (const name of s.cameras) {
        const opt = document.createElement("option");
        opt.value = opt.textContent = name;
        sel.appendChild(opt);
      }
      if (s.active) sel.value = s.active;
    } else if (s.active !== undefined) {
      $("camera-select").value = s.active;
    }
    if (s.frame !== undefined) $("frame-readout").textContent = s.frame;
    if (s.playing !== undefined) $("btn-play").textContent = s.playing ? "❙❙" : "▶";
    if (s.recording !== undefined) $("btn-record").classList.toggle("on", s.recording);
    if (s.lens !== undefined) {
      $("lens-slider").value = s.lens;
      $("lens-value").textContent = `${Math.round(s.lens)}mm`;
    }
    if (s.stream_fps !== undefined && s.stream_fps === 0) {
      streamOff.classList.remove("hidden");
    }
    if (s.settings) applySettings(s.settings);
  }

  function applySettings(cfg) {
    if (cfg.move_scale !== undefined) {
      $("set-scale").value = Math.log10(cfg.move_scale);
      $("set-scale-val").textContent = `${cfg.move_scale.toFixed(1)}×`;
    }
    if (cfg.smoothing !== undefined) {
      $("set-smooth").value = cfg.smoothing;
      $("set-smooth-val").textContent = Number(cfg.smoothing).toFixed(2);
    }
    if (cfg.send_rate !== undefined) {
      sendRateHz = cfg.send_rate;
      $("set-rate").value = cfg.send_rate;
      $("set-rate-val").textContent = `${cfg.send_rate} Hz`;
      if (sendTimer) startControlLoop();
    }
    if (cfg.stream_fps !== undefined) {
      $("set-fps").value = cfg.stream_fps;
      $("set-fps-val").textContent = cfg.stream_fps === 0 ? "off" : cfg.stream_fps;
    }
    if (cfg.stream_quality !== undefined) {
      $("set-quality").value = cfg.stream_quality;
      $("set-quality-val").textContent = ["", "low", "medium", "high"][cfg.stream_quality];
    }
    if (cfg.vertigo !== undefined) $("set-vertigo").checked = cfg.vertigo;
  }

  /* ---------- Top bar ---------- */

  $("camera-select").addEventListener("change", (e) =>
    Net.send({ t: "cmd", name: "camera_select", args: { name: e.target.value } }));
  $("btn-new-camera").addEventListener("click", () =>
    Net.send({ t: "cmd", name: "camera_new" }));
  $("btn-revert").addEventListener("click", () =>
    Net.send({ t: "cmd", name: "camera_revert" }));
  $("btn-play").addEventListener("click", () =>
    Net.send({ t: "cmd", name: "play_toggle" }));
  $("btn-stop").addEventListener("click", () =>
    Net.send({ t: "cmd", name: "stop" }));
  $("btn-record").addEventListener("click", () =>
    Net.send({ t: "cmd", name: "record_toggle" }));
  $("btn-settings").addEventListener("click", () =>
    $("sheet").classList.toggle("hidden"));
  $("sheet-close").addEventListener("click", () =>
    $("sheet").classList.add("hidden"));

  /* ---------- Motion / recenter ---------- */

  function setMotionButton() {
    const b = $("btn-motion");
    b.textContent = motionEnabled ? "Motion: on" : "Motion: off";
    b.classList.toggle("on", motionEnabled);
  }

  $("btn-motion").addEventListener("click", async () => {
    if (!motionEnabled) {
      const r = await Sensors.requestAccess();
      motionEnabled = r.ok;
      if (!r.ok) toast("Motion sensors unavailable on this connection.");
      else Net.send({ t: "cmd", name: "recenter" });
    } else {
      motionEnabled = false;
    }
    setMotionButton();
  });

  $("btn-recenter").addEventListener("click", () =>
    Net.send({ t: "cmd", name: "recenter" }));

  /* ---------- Lens ---------- */

  const lensSlider = $("lens-slider");
  lensSlider.addEventListener("input", () => {
    const mm = Number(lensSlider.value);
    $("lens-value").textContent = `${mm}mm`;
    Net.send({ t: "set", key: "lens", value: mm });
  });
  for (const btn of document.querySelectorAll(".btn-preset")) {
    btn.addEventListener("click", () => {
      lensSlider.value = btn.dataset.lens;
      lensSlider.dispatchEvent(new Event("input"));
    });
  }

  /* ---------- Settings sheet ---------- */

  $("set-scale").addEventListener("input", (e) => {
    const scale = Math.pow(10, Number(e.target.value));
    const shown = scale >= 10 ? scale.toFixed(0) : scale.toFixed(1);
    $("set-scale-val").textContent = `${shown}×`;
    Net.send({ t: "set", key: "move_scale", value: scale });
  });
  $("set-smooth").addEventListener("input", (e) => {
    $("set-smooth-val").textContent = Number(e.target.value).toFixed(2);
    Net.send({ t: "set", key: "smoothing", value: Number(e.target.value) });
  });
  $("set-rate").addEventListener("input", (e) => {
    sendRateHz = Number(e.target.value);
    $("set-rate-val").textContent = `${sendRateHz} Hz`;
    Net.send({ t: "set", key: "send_rate", value: sendRateHz });
    if (sendTimer) startControlLoop();
  });
  $("set-fps").addEventListener("input", (e) => {
    const fps = Number(e.target.value);
    $("set-fps-val").textContent = fps === 0 ? "off" : fps;
    if (fps === 0) streamOff.classList.remove("hidden");
    Net.send({ t: "set", key: "stream_fps", value: fps });
  });
  $("set-quality").addEventListener("input", (e) => {
    const v = Number(e.target.value);
    $("set-quality-val").textContent = ["", "low", "medium", "high"][v];
    Net.send({ t: "set", key: "stream_quality", value: v });
  });
  $("set-vertigo").addEventListener("change", (e) =>
    Net.send({ t: "set", key: "vertigo", value: e.target.checked }));

  /* ---------- Misc ---------- */

  let toastTimer = null;
  function toast(text) {
    const el = $("toast");
    el.textContent = text;
    el.classList.remove("hidden");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 2600);
  }

  async function acquireWakeLock() {
    try {
      if ("wakeLock" in navigator) {
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", () => { wakeLock = null; });
      }
    } catch { /* not fatal */ }
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && !wakeLock) acquireWakeLock();
  });

  if (!Net.hasToken()) {
    gateStatus.textContent =
      "No pairing token in this link — scan the QR code shown in Mixar.";
  }
})();
