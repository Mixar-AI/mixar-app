// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef MIXAR_LOCAL_AUTH_SERVER_H
#define MIXAR_LOCAL_AUTH_SERVER_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Bind and listen on a local port for the SSO auth callback.
// Tries preferred_port first; if that fails, binds to port 0 (OS-assigned).
// Writes the actual bound port to *out_port.
// Returns an opaque server handle (>= 0) on success, or -1 on error.
intptr_t auth_server_start(int preferred_port, int* out_port);

// Wait for the auth callback on a previously started server.
// Blocks until a valid request arrives or the 120-second timeout expires.
// `expected_state` is the OAuth state nonce the caller generated when
// initiating the SSO flow; any callback whose `state=` query parameter does
// not exactly match this value is rejected with a 400, and the server keeps
// listening for the legitimate callback. This binds the callback to the
// flow this client started (RFC 6749 §10.12 CSRF defense).
// Writes the received PKCE auth code into code_out (at most code_len-1 chars,
// NUL-terminated). Cleans up the server handle regardless of outcome.
// Returns true if a non-empty code was received and its state matched,
// false otherwise.
bool auth_server_wait_for_code(intptr_t server_handle,
                               const char* expected_state,
                               char* code_out, size_t code_len);

#ifdef __cplusplus
}
#endif

#endif // MIXAR_LOCAL_AUTH_SERVER_H
