// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

#include "mixar_local_auth_server.h"
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

static const char* SUCCESS_PAGE =
    "<!DOCTYPE html>"
    "<html lang=\"en\"><head><meta charset=\"UTF-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
    "<title>Login Successful — Mixar</title>"
    "<style>"
    "* { margin: 0; padding: 0; box-sizing: border-box; }"
    "body {"
    "  font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;"
    "  background: #0a0a0a; color: #fff; min-height: 100vh;"
    "  display: flex; align-items: center; justify-content: center;"
    "  padding: 2rem; -webkit-font-smoothing: antialiased;"
    "}"
    ".card {"
    "  width: 100%; max-width: 480px;"
    "  background: rgba(255, 255, 255, 0.02);"
    "  border: 1px solid rgba(0, 192, 199, 0.15);"
    "  border-radius: 24px; padding: 3rem;"
    "  backdrop-filter: blur(20px); text-align: center;"
    "  animation: fadeUp 0.6s ease forwards;"
    "}"
    ".check {"
    "  width: 64px; height: 64px;"
    "  background: rgba(34, 197, 94, 0.1);"
    "  border: 1px solid rgba(34, 197, 94, 0.3);"
    "  border-radius: 50%; display: flex;"
    "  align-items: center; justify-content: center;"
    "  margin: 0 auto 1.5rem;"
    "}"
    ".check svg { color: #22c55e; }"
    "h1 {"
    "  font-size: 2rem; font-weight: 600; margin-bottom: 0.75rem;"
    "  background: linear-gradient(135deg, #00C0C7 0%, #85C449 100%);"
    "  -webkit-background-clip: text; -webkit-text-fill-color: transparent;"
    "  background-clip: text;"
    "}"
    "p { font-size: 1rem; color: rgba(255, 255, 255, 0.5); line-height: 1.6; }"
    "@keyframes fadeUp {"
    "  from { opacity: 0; transform: translateY(40px); }"
    "  to   { opacity: 1; transform: translateY(0); }"
    "}"
    "</style></head><body>"
    "<div class=\"card\">"
    "  <div class=\"check\">"
    "    <svg width=\"32\" height=\"32\" viewBox=\"0 0 24 24\" fill=\"none\""
    "         stroke=\"currentColor\" stroke-width=\"2.5\">"
    "      <polyline points=\"20 6 9 17 4 12\" />"
    "    </svg>"
    "  </div>"
    "  <h1>Login Successful</h1>"
    "  <p>You can close this tab and return to Mixar.</p>"
    "</div>"
    "<script>window.close();</script>"
    "</body></html>";

static const char* FAILURE_PAGE =
    "<!DOCTYPE html>"
    "<html lang=\"en\"><head><meta charset=\"UTF-8\">"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">"
    "<title>Login Failed — Mixar</title>"
    "<style>"
    "* { margin: 0; padding: 0; box-sizing: border-box; }"
    "body {"
    "  font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;"
    "  background: #0a0a0a; color: #fff; min-height: 100vh;"
    "  display: flex; align-items: center; justify-content: center;"
    "  padding: 2rem; -webkit-font-smoothing: antialiased;"
    "}"
    ".card {"
    "  width: 100%; max-width: 480px;"
    "  background: rgba(255, 255, 255, 0.02);"
    "  border: 1px solid rgba(239, 68, 68, 0.15);"
    "  border-radius: 24px; padding: 3rem;"
    "  backdrop-filter: blur(20px); text-align: center;"
    "  animation: fadeUp 0.6s ease forwards;"
    "}"
    ".icon {"
    "  width: 64px; height: 64px;"
    "  background: rgba(239, 68, 68, 0.1);"
    "  border: 1px solid rgba(239, 68, 68, 0.3);"
    "  border-radius: 50%; display: flex;"
    "  align-items: center; justify-content: center;"
    "  margin: 0 auto 1.5rem;"
    "}"
    ".icon svg { color: #ef4444; }"
    "h1 {"
    "  font-size: 2rem; font-weight: 600; margin-bottom: 0.75rem;"
    "  color: #ef4444;"
    "}"
    "p { font-size: 1rem; color: rgba(255, 255, 255, 0.5); line-height: 1.6; }"
    "@keyframes fadeUp {"
    "  from { opacity: 0; transform: translateY(40px); }"
    "  to   { opacity: 1; transform: translateY(0); }"
    "}"
    "</style></head><body>"
    "<div class=\"card\">"
    "  <div class=\"icon\">"
    "    <svg width=\"32\" height=\"32\" viewBox=\"0 0 24 24\" fill=\"none\""
    "         stroke=\"currentColor\" stroke-width=\"2.5\">"
    "      <line x1=\"18\" y1=\"6\" x2=\"6\" y2=\"18\" />"
    "      <line x1=\"6\" y1=\"6\" x2=\"18\" y2=\"18\" />"
    "    </svg>"
    "  </div>"
    "  <h1>Login Failed</h1>"
    "  <p>No auth code received. Please try again.</p>"
    "</div>"
    "</body></html>";

// Send an HTTP response for GET requests.
// result > 0: auth code received - success HTML
// result == 0: GET arrived with query but no code, or state mismatch — failure HTML
// result < 0: stray request (favicon, no query, etc.) - plain OK
static void send_http_response(SOCKET client_socket, int result) {
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
    if (send(client_socket, headers, hdr_len, 0) < 0) {
        printf("Warning: send() failed for HTTP headers (result=%d).\n", result);
        return;
    }
    if (body) {
        int body_len = (int)strlen(body);
        if (send(client_socket, body, body_len, 0) < 0) {
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

    // Allow reuse of port
    int opt = 1;
    setsockopt(listen_socket, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));

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
#ifdef _WIN32
    ULONGLONG deadline = GetTickCount64() + 120000;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    long deadline_sec = ts.tv_sec + 120;
#endif

    while (!success) {
#ifdef _WIN32
        LONGLONG remaining_ms = (LONGLONG)(deadline - GetTickCount64());
        if (remaining_ms <= 0) {
            printf("Auth callback timed out after 120 seconds.\n");
            break;
        }
#else
        clock_gettime(CLOCK_MONOTONIC, &ts);
        long remaining_sec = deadline_sec - ts.tv_sec;
        if (remaining_sec <= 0) {
            printf("Auth callback timed out after 120 seconds.\n");
            break;
        }
#endif

        fd_set read_fds;
        FD_ZERO(&read_fds);
        FD_SET(listen_socket, &read_fds);
        struct timeval tv;
#ifdef _WIN32
        tv.tv_sec  = (long)(remaining_ms / 1000);
        tv.tv_usec = (long)((remaining_ms % 1000) * 1000);
#else
        // Poll in 1-second slices so the timeout check runs frequently.
        tv.tv_sec = (remaining_sec > 1) ? 1 : remaining_sec;
        tv.tv_usec = 0;
#endif

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

        // Single-shot recv is sufficient for the short auth-callback URLs
        // (typically < 500 bytes). Partial reads are not expected on loopback.
        char buffer[4096];
        int bytes_received = recv(client_socket, buffer, sizeof(buffer) - 1, 0);

        if (bytes_received > 0) {
            buffer[bytes_received] = '\0';

            if (bytes_received == sizeof(buffer) - 1) {
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

            send_http_response(client_socket, result);
        } else if (bytes_received < 0) {
            printf("Warning: recv() error on client socket.\n");
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
