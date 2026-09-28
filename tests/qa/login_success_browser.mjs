// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
// SPDX-License-Identifier: GPL-3.0-or-later
// Usage: MIXAR_PLAYWRIGHT_PATH=/path/to/playwright/index.mjs node tests/qa/login_success_browser.mjs
// Exercises the real native loopback server with synthetic codes; no token exchange or keychain access.
import assert from 'node:assert/strict';
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
const { chromium } = await import(process.env.MIXAR_PLAYWRIGHT_PATH || 'playwright');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const output = mkdtempSync(join(tmpdir(), 'mixar-login-'));
const driver = join(output, 'callback.cc');
const native = join(output, 'callback');
writeFileSync(driver, `#include "mixar_local_auth_server.h"
#include <cstdio>
#include <cstring>
int main() {
  int port = 0;
  intptr_t server = auth_server_start(0, &port);
  if (server < 0) return 2;
  printf("PORT=%d\\n", port); fflush(stdout);
  char code[64];
  bool ok = auth_server_wait_for_code(server, "preview-state", code, sizeof(code));
  return ok && strcmp(code, "preview-code") == 0 ? 0 : 3;
}
`);
execFileSync('clang++', ['-std=c++17', '-I', join(root, 'src/source/creator'), driver,
  join(root, 'src/source/creator/mixar_local_auth_server.cc'), '-o', native]);
const expected = execFileSync('python3', ['-c',
  'import runpy,sys; sys.stdout.buffer.write(runpy.run_path(sys.argv[1])["SUCCESS_PAGE"])',
  join(root, 'src/scripts/mixar/modules/auth/core/sso_pages.py')]);
const browser = await chromium.launch({ channel: 'chrome' });
try {
  for (const width of [1440, 390, 320]) {
    const child = spawn(native);
    const exited = once(child, 'exit');
    const lines = createInterface({ input: child.stdout });
    const port = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Callback did not bind')), 5000);
      lines.on('line', line => { if (line.startsWith('PORT=')) { clearTimeout(timer); resolve(Number(line.slice(5))); } });
      child.once('error', reject);
    });
    const page = await browser.newPage({ viewport: { width, height: 900 }, colorScheme: 'dark', reducedMotion: 'reduce' });
    const requests = [];
    page.on('request', request => requests.push(request.url()));
    // Keep the page visible while proving that the existing close attempt runs.
    await page.addInitScript(() => { window.close = () => { window.closeAttempted = true; }; });
    try {
      const rejected = await page.request.get(`http://127.0.0.1:${port}/?code=bad&state=wrong`);
      assert.equal(rejected.status(), 400);
      const response = await page.goto(`http://127.0.0.1:${port}/?code=preview-code&state=preview-state`);
      assert.equal(response.status(), 200);
      assert.deepEqual(await response.body(), expected, 'Python and native callback pages must match byte-for-byte');
      await page.evaluate(() => document.fonts.ready);
      const state = await page.evaluate(() => ({
        background: getComputedStyle(document.body).backgroundColor,
        font: document.fonts.check('400 16px ClashGrotesk') && document.fonts.check('500 36px ClashGrotesk'),
        overflow: document.documentElement.scrollWidth > innerWidth,
        closed: window.closeAttempted,
        title: document.querySelector('h1').textContent,
      }));
      assert.deepEqual(state, { background: 'rgb(235, 235, 235)', font: true, overflow: false, closed: true, title: 'Login successful' });
      assert.equal(requests.length, 1, 'Confirmation must not depend on external assets or the closed callback server');
      await page.screenshot({ path: join(output, `success-${width}.png`) });
      assert.equal((await exited)[0], 0, 'Callback must deliver the expected code');
      console.log(`${width}px: callback, complete HTML, embedded fonts, light theme, layout, and close attempt passed`);
    } finally { await page.close(); child.kill(); }
  }
} finally { await browser.close(); }
console.log(`Screenshots: ${output}`);
