// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

#include "mixar_local_auth_server.h"
#include "mixar_sso_success_page.h"
#include "mixar_sso_failure_page.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>

/* Mixar 5.2 port: creator code stays in the global namespace; blender::
 * symbols are reached through a using-directive (declare the namespace
 * first — only system headers precede this point). */
namespace blender {}
using namespace blender;
#define SOCKET int
#define INVALID_SOCKET -1
#define SOCKET_ERROR -1
#define closesocket close
#endif

// The callback receives a top-level browser navigation (the frontend redirects
// the browser to http://127.0.0.1:PORT/?code=...&state=...), not a CORS
// request. We deliberately do NOT send Access-Control-Allow-Origin: the
// previous wildcard policy would let any web page the user visits during the
// 120-second SSO window read this server's responses or fire requests at it.
// State validation defends against unsolicited callbacks; removing CORS
// closes the cross-origin readability channel.
static const char* CONNECTION_CLOSE = "Connection: close\r\n";

// Monotonic milliseconds: the 120 s callback deadline and each client's budget.
static long long now_ms() {
#ifdef _WIN32
    return (long long)GetTickCount64();
#else
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
#endif
}

// One accepted client may hold the (pre-UI, main-thread) wait for at most this
// long: a silent peer such as an endpoint-security probe or a browser's
// speculative preconnect must never hang app launch (the Python SSO server has
// the same per-connection timeout, auth/core/sso.py).
static const long long CLIENT_BUDGET_MS = 5000;

// Bound the next blocking recv()/send() on a client to what is left of its
// budget. A zero timeout means "block forever" on both platforms, so clamp
// to 1 ms. Windows takes a DWORD of milliseconds, POSIX a timeval.
static void set_client_timeouts(SOCKET socket, long long remaining_ms) {
    if (remaining_ms < 1) remaining_ms = 1;
#ifdef _WIN32
    DWORD timeout = (DWORD)remaining_ms;
#else
    struct timeval timeout;
    timeout.tv_sec = (time_t)(remaining_ms / 1000);
    timeout.tv_usec = (int)((remaining_ms % 1000) * 1000);
#endif
    setsockopt(socket, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));
    setsockopt(socket, SOL_SOCKET, SO_SNDTIMEO, (const char*)&timeout, sizeof(timeout));
}

// This runs before Python sets SIGPIPE to ignored, so a peer that disconnects
// mid-response must not raise SIGPIPE: SO_NOSIGPIPE on the socket (macOS/BSD)
// and MSG_NOSIGNAL on every send (Linux). Newer macOS SDKs also define
// MSG_NOSIGNAL; SO_NOSIGPIPE already covers every supported macOS there.
#if defined(MSG_NOSIGNAL) && !defined(__APPLE__)
#define MIXAR_SEND_FLAGS MSG_NOSIGNAL
#else
#define MIXAR_SEND_FLAGS 0
#endif

// Embedded webfonts make the response larger than a single socket write may accept.
static bool send_all(SOCKET socket, const char *data, int length, long long deadline_ms) {
    while (length > 0) {
        const long long remaining_ms = deadline_ms - now_ms();
        if (remaining_ms <= 0) return false;
        set_client_timeouts(socket, remaining_ms);
        const int sent = (int)send(socket, data, length, MIXAR_SEND_FLAGS);
        if (sent == SOCKET_ERROR) {
#ifdef _WIN32
            if (WSAGetLastError() == WSAEINTR) continue;
#else
            if (errno == EINTR) continue;
#endif
            return false;  // timeout, reset or error: drop this client
        }
        if (sent == 0) return false;
        data += sent;
        length -= sent;
    }
    return true;
}

// Read the request head until "\r\n\r\n", EOF, a full buffer or the client's
// budget. Returns the bytes read (NUL-terminated) or -1 on timeout or error.
static int recv_request_head(SOCKET socket, char *buffer, int size, long long deadline_ms) {
    int total = 0;
    buffer[0] = '\0';
    while (total < size - 1) {
        const long long remaining_ms = deadline_ms - now_ms();
        if (remaining_ms <= 0) return -1;
        set_client_timeouts(socket, remaining_ms);
        const int n = (int)recv(socket, buffer + total, size - 1 - total, 0);
        if (n == SOCKET_ERROR) {
#ifdef _WIN32
            if (WSAGetLastError() == WSAEINTR) continue;
#else
            if (errno == EINTR) continue;
#endif
            return -1;
        }
        if (n == 0) break;  // EOF: parse whatever arrived
        total += n;
        buffer[total] = '\0';
        if (strstr(buffer, "\r\n\r\n") != NULL) break;
    }
    return total;
}

// Send an HTTP response for GET requests.
// result > 0: auth code received - success HTML
// result == 0: GET arrived with query but no code, or state mismatch — failure HTML
// result < 0: stray request (favicon, no query, etc.) - plain OK
static void send_http_response(SOCKET client_socket, int result, long long deadline_ms) {
    // Send headers first, then body separately (pages exceed small buffer)
    char headers[256];
    const char* body;

    if (result > 0) {
        snprintf(headers, sizeof(headers),
            "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n%s\r\n", CONNECTION_CLOSE);
        body = SUCCESS_PAGE;
    } else if (result == 0) {
        snprintf(headers, sizeof(headers),
            "HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n%s\r\n", CONNECTION_CLOSE);
        body = FAILURE_PAGE;
    } else {
        snprintf(headers, sizeof(headers),
            "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n%s\r\nOK", CONNECTION_CLOSE);
        body = NULL;
    }

    int hdr_len = (int)strlen(headers);
    if (!send_all(client_socket, headers, hdr_len, deadline_ms)) {
        printf("Warning: send() failed for HTTP headers (result=%d).\n", result);
        return;
    }
    if (body) {
        int body_len = (int)strlen(body);
        if (!send_all(client_socket, body, body_len, deadline_ms)) {
            printf("Warning: send() failed for HTTP body (result=%d).\n", result);
        }
    }
}

// Constant-time string comparison. Returns true iff strings are equal in
// content and length. Used for state validation to avoid timing oracles
// even though state matching isn't typically a timing-attackable surface
// (defensive — costs nothing).
static bool constant_time_streq(const char* a, const char* b) {
    if (a == NULL || b == NULL) return false;
    size_t la = strlen(a);
    size_t lb = strlen(b);
    if (la != lb) return false;
    unsigned char diff = 0;
    for (size_t i = 0; i < la; i++) {
        diff |= (unsigned char)a[i] ^ (unsigned char)b[i];
    }
    return diff == 0;
}

// URL decode with bounded output. Writes at most dst_len-1 chars + NUL.
static void url_decode(char *dst, size_t dst_len, const char *src) {
    char a, b;
    size_t j = 0;
    while (*src && j + 1 < dst_len) {
        if ((*src == '%') &&
            ((a = src[1]) && (b = src[2])) &&
            (isxdigit(a) && isxdigit(b))) {
            if (a >= 'a') a -= 'a'-'A';
            if (a >= 'A') a -= ('A' - 10);
            else a -= '0';
            if (b >= 'a') b -= 'a'-'A';
            if (b >= 'A') b -= ('A' - 10);
            else b -= '0';
            dst[j++] = 16*a+b;
            src+=3;
        } else if (*src == '+') {
            dst[j++] = ' ';
            src++;
        } else {
            dst[j++] = *src++;
        }
    }
    dst[j] = '\0';
}

intptr_t auth_server_start(int preferred_port, int* out_port) {
#ifdef _WIN32
    WSADATA wsaData;
    if (WSAStartup(MAKEWORD(2, 2), &wsaData) != 0) {
        printf("WSAStartup failed.\n");
        return -1;
    }
#endif

    SOCKET listen_socket = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (listen_socket == INVALID_SOCKET) {
        printf("Error creating socket.\n");
#ifdef _WIN32
        WSACleanup();
#endif
        return -1;
    }

    int opt = 1;
#ifdef _WIN32
    // SO_REUSEADDR on Windows lets another socket bind the same port, making
    // which process receives the callback nondeterministic. Claim it
    // exclusively; a busy port falls back to an OS-assigned one below.
    setsockopt(listen_socket, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char*)&opt, sizeof(opt));
#else
    // POSIX SO_REUSEADDR only permits rebinding over TIME_WAIT (a quick re-login).
    setsockopt(listen_socket, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#endif

    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK); // 127.0.0.1

    // Try preferred port first, fall back to OS-assigned port (0)
    int ports_to_try[] = {preferred_port, 0};
    int num_ports = (preferred_port != 0) ? 2 : 1;
    bool bound = false;

    for (int i = 0; i < num_ports; i++) {
        server_addr.sin_port = htons(ports_to_try[i]);
        if (bind(listen_socket, (struct sockaddr*)&server_addr, sizeof(server_addr)) != SOCKET_ERROR) {
            bound = true;
            break;
        }
        if (i == 0 && num_ports > 1) {
            printf("Port %d in use, trying OS-assigned port...\n", preferred_port);
        }
    }

    if (!bound) {
        printf("Bind failed on all attempted ports.\n");
        closesocket(listen_socket);
#ifdef _WIN32
        WSACleanup();
#endif
        return -1;
    }

    // Retrieve the actual bound port
    struct sockaddr_in bound_addr;
    socklen_t addr_len = sizeof(bound_addr);
    if (getsockname(listen_socket, (struct sockaddr*)&bound_addr, &addr_len) == SOCKET_ERROR) {
        printf("getsockname failed.\n");
        closesocket(listen_socket);
#ifdef _WIN32
        WSACleanup();
#endif
        return -1;
    }
    *out_port = ntohs(bound_addr.sin_port);

    if (listen(listen_socket, 5) == SOCKET_ERROR) {
        printf("Listen failed.\n");
        closesocket(listen_socket);
#ifdef _WIN32
        WSACleanup();
#endif
        return -1;
    }

    printf("Auth server listening on http://127.0.0.1:%d/\n", *out_port);
    return (intptr_t)listen_socket;
}

bool auth_server_wait_for_code(intptr_t server_handle,
                               const char* expected_state,
                               char* code_out, size_t code_len) {
    SOCKET listen_socket = (SOCKET)server_handle;
    bool success = false;

    if (expected_state == NULL || expected_state[0] == '\0') {
        printf("auth_server_wait_for_code: refusing to listen without expected_state.\n");
        closesocket(listen_socket);
#ifdef _WIN32
        WSACleanup();
#endif
        return false;
    }

    // Compute absolute deadline (120 seconds from now).
    // Loop handles stray requests (favicon, CORS preflight, etc.)
    // just like the Python SSO server does.
    const long long deadline_ms = now_ms() + 120000;

    while (!success) {
        const long long remaining_ms = deadline_ms - now_ms();
        if (remaining_ms <= 0) {
            printf("Auth callback timed out after 120 seconds.\n");
            break;
        }

        fd_set read_fds;
        FD_ZERO(&read_fds);
        FD_SET(listen_socket, &read_fds);
        // Poll in 1-second slices so the timeout check runs frequently.
        const long long slice_ms = (remaining_ms > 1000) ? 1000 : remaining_ms;
        struct timeval tv;
        tv.tv_sec = (long)(slice_ms / 1000);
        tv.tv_usec = (long)((slice_ms % 1000) * 1000);

        int sel = select((int)listen_socket + 1, &read_fds, NULL, NULL, &tv);
        if (sel < 0) {
            printf("select() error while waiting for auth callback.\n");
            break;
        }
        if (sel == 0) {
            continue; // No connection yet, loop and check timeout
        }

        SOCKET client_socket = accept(listen_socket, NULL, NULL);
        if (client_socket == INVALID_SOCKET) {
            continue;
        }

        // Every blocking recv()/send() on this client is bounded by its own
        // budget, clamped to the overall deadline; a silent or stalled peer is
        // dropped and the wait goes on for the real callback.
        const long long accepted_ms = now_ms();
        const long long left_ms = deadline_ms - accepted_ms;
        const long long client_deadline_ms =
            accepted_ms + ((left_ms < CLIENT_BUDGET_MS) ? left_ms : CLIENT_BUDGET_MS);
        set_client_timeouts(client_socket, client_deadline_ms - accepted_ms);
#ifdef SO_NOSIGPIPE
        int no_sigpipe = 1;
        setsockopt(client_socket, SOL_SOCKET, SO_NOSIGPIPE, (const char*)&no_sigpipe,
                   sizeof(no_sigpipe));
#endif

        char buffer[4096];
        int bytes_received = recv_request_head(client_socket, buffer, (int)sizeof(buffer),
                                               client_deadline_ms);

        if (bytes_received > 0) {
            if (bytes_received == (int)sizeof(buffer) - 1) {
                printf("Warning: recv buffer full (%d bytes), request may be truncated.\n",
                       bytes_received);
            }

            // Parse GET request. Other methods (including the old OPTIONS
            // CORS preflight) are no longer relevant; the callback is a
            // top-level browser navigation, not a CORS resource.
            // result: 1 = code accepted (state validated), 0 = state mismatch
            //         or query but no code, -1 = stray request
            int result = -1;
            char pending_code[256] = {0};
            char received_state[128] = {0};

            if (strncmp(buffer, "GET ", sizeof("GET ") - 1) == 0) {
                char* path = buffer + (sizeof("GET ") - 1);
                char* space = strchr(path, ' ');
                if (space) *space = '\0';

                char* query = strchr(path, '?');
                if (query) {
                    query++; // Skip '?'
                    result = 0; // Has query string - expect a code

                    // Parse query parameters into pending_code + received_state
                    // BEFORE we accept anything. The accept step runs after
                    // the loop with state validation.
#ifdef _WIN32
                    char* save_ptr = NULL;
                    char* pair = strtok_s(query, "&", &save_ptr);
                    while (pair != NULL) {
#else
                    char* save_ptr = NULL;
                    char* pair = strtok_r(query, "&", &save_ptr);
                    while (pair != NULL) {
#endif
                        char* eq = strchr(pair, '=');
                        if (eq) {
                            *eq = '\0';
                            char* key = pair;
                            char* val = eq + 1;

                            if (strcmp(key, "code") == 0 && strlen(val) > 0) {
                                url_decode(pending_code, sizeof(pending_code), val);
                            } else if (strcmp(key, "state") == 0 && strlen(val) > 0) {
                                url_decode(received_state, sizeof(received_state), val);
                            }
                        }
#ifdef _WIN32
                        pair = strtok_s(NULL, "&", &save_ptr);
#else
                        pair = strtok_r(NULL, "&", &save_ptr);
#endif
                    }

                    // Now validate: accept only if we got a non-empty code
                    // AND received_state exactly matches expected_state.
                    if (pending_code[0] != '\0') {
                        if (constant_time_streq(received_state, expected_state)) {
                            // Copy code into caller's buffer with bounds check
                            size_t cn = strlen(pending_code);
                            if (cn + 1 <= code_len) {
                                memcpy(code_out, pending_code, cn + 1);
                                success = true;
                                result = 1;
                            } else {
                                printf("auth callback: code too long for output buffer (%zu vs %zu)\n",
                                       cn, code_len);
                                result = 0;
                            }
                        } else {
                            printf("auth callback: state mismatch — rejecting\n");
                            result = 0;
                            // Keep listening; legitimate callback may still arrive
                        }
                    }
                }
            }

            send_http_response(client_socket, result, client_deadline_ms);
        } else if (bytes_received < 0) {
            printf("Warning: auth client timed out or failed; dropping it.\n");
        }

        // Reached only when client_socket is valid (accept succeeded above).
        // INVALID_SOCKET from accept triggers continue before this point.
#ifdef _WIN32
        shutdown(client_socket, SD_BOTH);
#else
        shutdown(client_socket, SHUT_RDWR);
#endif
        closesocket(client_socket);
    }

    closesocket(listen_socket);
#ifdef _WIN32
    WSACleanup();
#endif

    return success;
}
