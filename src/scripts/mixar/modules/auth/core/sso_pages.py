# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""HTML served on the loopback callback once the browser delivers the auth code."""

SUCCESS_PAGE = b"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Login Successful \xe2\x80\x94 Mixar</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
      background: #0a0a0a;
      color: #fff;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem;
      -webkit-font-smoothing: antialiased;
    }
    .card {
      width: 100%;
      max-width: 480px;
      background: rgba(255, 255, 255, 0.02);
      border: 1px solid rgba(0, 192, 199, 0.15);
      border-radius: 24px;
      padding: 3rem;
      backdrop-filter: blur(20px);
      text-align: center;
      animation: fadeUp 0.6s ease forwards;
    }
    .check {
      width: 64px;
      height: 64px;
      background: rgba(34, 197, 94, 0.1);
      border: 1px solid rgba(34, 197, 94, 0.3);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 1.5rem;
    }
    .check svg { color: #22c55e; }
    h1 {
      font-size: 2rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
      background: linear-gradient(135deg, #00C0C7 0%, #85C449 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
    }
    p { font-size: 1rem; color: rgba(255, 255, 255, 0.5); line-height: 1.6; }
    @keyframes fadeUp {
      from { opacity: 0; transform: translateY(40px); }
      to   { opacity: 1; transform: translateY(0); }
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="check">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="2.5">
        <polyline points="20 6 9 17 4 12" />
      </svg>
    </div>
    <h1>Login Successful</h1>
    <p>You can close this tab and return to Mixar.</p>
  </div>
  <script>window.close();</script>
</body>
</html>"""
