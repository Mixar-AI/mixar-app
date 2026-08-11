// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

#include "creator_startup.h"
#include "mixar_env_config.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <winhttp.h>
#include <bcrypt.h>
#pragma comment(lib, "winhttp.lib")
#pragma comment(lib, "bcrypt.lib")

#else
// macOS and Linux use libcurl for HTTP requests
#include <curl/curl.h>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <string>

#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#include <CommonCrypto/CommonDigest.h>
#else
#include <unistd.h>
#include <openssl/sha.h>
#endif

// Response data structure for curl callback
struct CurlResponse {
    char* data;
    size_t size;
};

// Callback function to write response data
static size_t WriteResponseCallback(void* contents, size_t size, size_t nmemb, CurlResponse* response) {
    size_t totalSize = size * nmemb;
    char* ptr = (char*)realloc(response->data, response->size + totalSize + 1);

    if (ptr == NULL) {
        printf("Not enough memory (realloc returned NULL)\n");
        return 0;
    }

    response->data = ptr;
    memcpy(&(response->data[response->size]), contents, totalSize);
    response->size += totalSize;
    response->data[response->size] = '\0';

    return totalSize;
}

// Initialize curl globally (call once at program start)
void init_auth_system(void) {
    curl_global_init(CURL_GLOBAL_DEFAULT);
}

// Cleanup curl globally (call once at program end)
void cleanup_auth_system(void) {
    curl_global_cleanup();
}
#endif

const char* get_mixar_base_url() {
    return MIXAR_BASE_URL;
}

static char* get_app_icon_path() {
    static char iconPath[512];

#ifdef _WIN32
    // Windows
    char exePath[MAX_PATH];
    GetModuleFileNameA(NULL, exePath, MAX_PATH);

    // Remove executable name, go up to app directory
    char* lastSlash = strrchr(exePath, '\\');
    if (lastSlash) *lastSlash = '\0';

    snprintf(iconPath, sizeof(iconPath), "%s\\..\\Resources\\blender_icon.ico", exePath);

#elif defined(__APPLE__)
    // macOS - use CFBundle
    CFBundleRef mainBundle = CFBundleGetMainBundle();
    if (mainBundle) {
        CFURLRef iconURL = CFBundleCopyResourceURL(mainBundle, CFSTR("mixar_icon"), CFSTR("icns"), NULL);
        if (iconURL) {
            CFStringRef iconPathRef = CFURLCopyFileSystemPath(iconURL, kCFURLPOSIXPathStyle);
            CFStringGetCString(iconPathRef, iconPath, sizeof(iconPath), kCFStringEncodingUTF8);
            CFRelease(iconPathRef);
            CFRelease(iconURL);
            return iconPath;
        }
    }

    // Fallback
    strcpy(iconPath, "./mixar_icon.icns");

#else
    // Linux
    char exePath[512];
    ssize_t len = readlink("/proc/self/exe", exePath, sizeof(exePath) - 1);
    if (len != -1) {
        exePath[len] = '\0';
        char* lastSlash = strrchr(exePath, '/');
        if (lastSlash) *lastSlash = '\0';

        snprintf(iconPath, sizeof(iconPath), "%s/../share/blender/icons/blender_icon.png", exePath);
    } else {
        strcpy(iconPath, "./blender_icon.png");
    }
#endif

    return iconPath;
}

#include "mixar_local_auth_server.h"
#include "creator_auth.h"

// ---------------------------------------------------------------------------
// PKCE helpers
// ---------------------------------------------------------------------------

// Base64url encode without padding (RFC 4648 §5).
// Correctly emits 2 chars for 1-byte remainder, 3 chars for 2-byte remainder.
static size_t base64url_encode(const unsigned char* input, size_t input_len,
                               char* out, size_t out_len) {
    static const char b64url[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    size_t i = 0, j = 0;
    while (i < input_len) {
        unsigned int val = (unsigned int)input[i++] << 16;
        size_t n = 2;
        if (i < input_len) { val |= (unsigned int)input[i++] << 8; n = 3; }
        if (i < input_len) { val |= (unsigned int)input[i++];      n = 4; }
        for (size_t k = 0; k < n && j + 1 < out_len; k++)
            out[j++] = b64url[(val >> (18 - 6 * k)) & 0x3F];
    }
    if (j < out_len) out[j] = '\0';
    return j;
}

// Generate a 32-byte random code_verifier, base64url-encoded without padding.
// 32 bytes → 43 output characters.
// Returns true on success, false if RNG fails (out left empty).
static bool generate_code_verifier(char* out, size_t out_len) {
    unsigned char random_bytes[32];

    if (out_len > 0) out[0] = '\0';

#ifdef _WIN32
    HCRYPTPROV hProv;
    if (!CryptAcquireContext(&hProv, NULL, NULL, PROV_RSA_FULL, CRYPT_VERIFYCONTEXT)) {
        printf("generate_code_verifier: CryptAcquireContext failed.\n");
        return false;
    }
    if (!CryptGenRandom(hProv, 32, random_bytes)) {
        CryptReleaseContext(hProv, 0);
        printf("generate_code_verifier: CryptGenRandom failed.\n");
        return false;
    }
    CryptReleaseContext(hProv, 0);
#else
    FILE* urandom = fopen("/dev/urandom", "rb");
    if (!urandom) {
        printf("generate_code_verifier: failed to open /dev/urandom.\n");
        return false;
    }
    if (fread(random_bytes, 1, 32, urandom) != 32) {
        fclose(urandom);
        printf("generate_code_verifier: failed to read 32 bytes from /dev/urandom.\n");
        return false;
    }
    fclose(urandom);
#endif

    base64url_encode(random_bytes, 32, out, out_len);
    return true;
}

// Generate an OAuth state nonce (RFC 6749 §10.12) using the same secure RNG
// path as the PKCE verifier. State binds the SSO callback to the flow this
// client initiated. The frontend echoes it back unchanged on the localhost
// redirect; the local auth server validates byte-for-byte.
static bool generate_state(char* out, size_t out_len) {
    return generate_code_verifier(out, out_len);
}

// Compute BASE64URL(SHA256(verifier)) — the PKCE code_challenge.
// 32-byte SHA256 digest → 43 output characters.
static void compute_code_challenge(const char* verifier, char* out, size_t out_len) {
    unsigned char hash[32];

#ifdef __APPLE__
    CC_SHA256(verifier, (CC_LONG)strlen(verifier), hash);
#elif defined(_WIN32)
    {
        BCRYPT_ALG_HANDLE hAlg = NULL;
        BCRYPT_HASH_HANDLE hHash = NULL;
        BCryptOpenAlgorithmProvider(&hAlg, BCRYPT_SHA256_ALGORITHM, NULL, 0);
        BCryptCreateHash(hAlg, &hHash, NULL, 0, NULL, 0, 0);
        BCryptHashData(hHash, (PUCHAR)verifier, (ULONG)strlen(verifier), 0);
        BCryptFinishHash(hHash, hash, 32, 0);
        BCryptDestroyHash(hHash);
        BCryptCloseAlgorithmProvider(hAlg, 0);
    }
#else
    SHA256((const unsigned char*)verifier, strlen(verifier), hash);
#endif

    base64url_encode(hash, 32, out, out_len);
}

// ---------------------------------------------------------------------------
// Token exchange
// ---------------------------------------------------------------------------

// Find a top-level string-valued field by key name in a flat JSON object.
//
// Returns true if `key` is found as a top-level field with a string value
// in `json`, and copies the unescaped value into `out` (NUL-terminated).
// Returns false on malformed JSON, missing key, non-string value, or if
// the unescaped value would not fit in `out_len-1` bytes (no silent
// truncation — refuse rather than emit a partial token).
//
// Scope: designed for the small, server-trusted OAuth token responses
// of the form {"access_token":"...","refresh_token":"...","expires_in":3600}.
// Not a general JSON parser: does not handle nested objects or arrays in
// values (these would cause the function to skip past them and look for the
// next top-level key correctly), and rejects anything malformed.
//
// Supported string escapes: \" \\ \/ \b \f \n \r \t and \uXXXX (where XXXX
// in the Basic Multilingual Plane is decoded to UTF-8; surrogate pairs are
// rejected to keep the parser simple).
static bool json_get_string(const char* json, const char* key,
                            char* out, size_t out_len) {
    if (json == NULL || key == NULL || out == NULL || out_len == 0) return false;
    out[0] = '\0';
    size_t key_len = strlen(key);

    const char* p = json;
    // Skip leading whitespace, expect '{'
    while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
    if (*p != '{') return false;
    p++;

    // Iterate top-level key/value pairs. Cap iterations to prevent runaway
    // on pathological input.
    for (int iter = 0; iter < 256; iter++) {
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' || *p == ',') p++;
        if (*p == '}') return false;  // End of object, key not found
        if (*p != '"') return false;  // Expected string key

        p++; // skip opening quote
        const char* k_start = p;
        // Find closing quote of the key. Keys with escapes are not expected
        // in OAuth responses; reject keys containing backslashes for safety.
        while (*p && *p != '"' && *p != '\\') p++;
        if (*p != '"') return false;
        size_t this_key_len = (size_t)(p - k_start);
        bool key_matches = (this_key_len == key_len) && (memcmp(k_start, key, key_len) == 0);
        p++; // skip closing quote of key

        // Expect colon (with optional whitespace)
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;
        if (*p != ':') return false;
        p++;
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r') p++;

        if (*p == '"') {
            // String value. Walk it, decoding escapes if this is our target.
            p++; // skip opening quote
            size_t out_pos = 0;
            while (*p && *p != '"') {
                char ch;
                if (*p == '\\') {
                    p++;
                    switch (*p) {
                        case '"':  ch = '"';  break;
                        case '\\': ch = '\\'; break;
                        case '/':  ch = '/';  break;
                        case 'b':  ch = '\b'; break;
                        case 'f':  ch = '\f'; break;
                        case 'n':  ch = '\n'; break;
                        case 'r':  ch = '\r'; break;
                        case 't':  ch = '\t'; break;
                        case 'u': {
                            // \uXXXX — decode to UTF-8 (BMP only; reject surrogates)
                            if (!p[1] || !p[2] || !p[3] || !p[4]) return false;
                            unsigned int cp = 0;
                            for (int i = 1; i <= 4; i++) {
                                char hx = p[i];
                                cp <<= 4;
                                if (hx >= '0' && hx <= '9') cp |= (unsigned)(hx - '0');
                                else if (hx >= 'a' && hx <= 'f') cp |= (unsigned)(hx - 'a' + 10);
                                else if (hx >= 'A' && hx <= 'F') cp |= (unsigned)(hx - 'A' + 10);
                                else return false;
                            }
                            if (cp >= 0xD800 && cp <= 0xDFFF) return false; // surrogate
                            // Emit UTF-8 directly into output if this is our key
                            if (key_matches) {
                                char utf8[4];
                                int n;
                                if (cp < 0x80) { utf8[0] = (char)cp; n = 1; }
                                else if (cp < 0x800) {
                                    utf8[0] = (char)(0xC0 | (cp >> 6));
                                    utf8[1] = (char)(0x80 | (cp & 0x3F));
                                    n = 2;
                                } else {
                                    utf8[0] = (char)(0xE0 | (cp >> 12));
                                    utf8[1] = (char)(0x80 | ((cp >> 6) & 0x3F));
                                    utf8[2] = (char)(0x80 | (cp & 0x3F));
                                    n = 3;
                                }
                                if (out_pos + (size_t)n + 1 > out_len) return false;
                                for (int i = 0; i < n; i++) out[out_pos++] = utf8[i];
                            }
                            p += 5;
                            continue;
                        }
                        default: return false;  // unknown escape
                    }
                    p++;
                } else {
                    ch = *p;
                    p++;
                }
                if (key_matches) {
                    if (out_pos + 1 >= out_len) return false;  // refuse truncation
                    out[out_pos++] = ch;
                }
            }
            if (*p != '"') return false;  // unterminated string
            p++; // skip closing quote
            if (key_matches) {
                out[out_pos] = '\0';
                return true;
            }
        } else {
            // Non-string value — if this was our target, fail (we only
            // accept string-valued fields). Otherwise, skip past it to
            // find the next top-level key.
            if (key_matches) return false;
            int depth = 0;
            while (*p) {
                if (*p == '{' || *p == '[') depth++;
                else if (*p == '}' || *p == ']') {
                    if (depth == 0) break;
                    depth--;
                }
                else if ((*p == ',' || *p == '}') && depth == 0) break;
                else if (*p == '"') {
                    // skip a string value to avoid mistaking , inside it for separator
                    p++;
                    while (*p && *p != '"') {
                        if (*p == '\\' && p[1]) p++;
                        p++;
                    }
                    if (*p != '"') return false;
                }
                p++;
            }
        }
    }
    return false;  // ran out of iterations
}

// Escape a string for safe embedding in a JSON string value.
// Handles \, ", and control characters. Writes at most out_len-1 chars + NUL.
static void json_escape(const char* src, char* out, size_t out_len) {
    size_t j = 0;
    for (size_t i = 0; src[i] && j + 1 < out_len; i++) {
        char c = src[i];
        if (c == '"' || c == '\\') {
            if (j + 2 >= out_len) break;
            out[j++] = '\\';
            out[j++] = c;
        } else if ((unsigned char)c < 0x20) {
            // Skip control characters
            continue;
        } else {
            out[j++] = c;
        }
    }
    out[j] = '\0';
}

// POST {backend_url}/api/v1/auth/desktop/token with {"code":"...","code_verifier":"..."}
// Parses the JSON response for access_token and refresh_token, stores in keyring.
// Returns true on success.
//
// Refuses any non-HTTPS backend URL — an HTTP endpoint would let a passive
// network attacker substitute the response body and seed arbitrary "tokens"
// into the OS keyring. Defence-in-depth on top of TLS by libcurl/WinHTTP.
static bool exchange_desktop_code(const char* code, const char* code_verifier) {
    char escaped_code[256];
    char escaped_verifier[128];
    json_escape(code, escaped_code, sizeof(escaped_code));
    json_escape(code_verifier, escaped_verifier, sizeof(escaped_verifier));

    char body[512];
    snprintf(body, sizeof(body),
             "{\"code\":\"%s\",\"code_verifier\":\"%s\"}", escaped_code, escaped_verifier);

    char url[512];
    snprintf(url, sizeof(url), "%s/api/v1/auth/desktop/token", get_mixar_base_url());

    // Refuse non-HTTPS schemes. Loopback is intentionally NOT excepted —
    // Mixar's backend is always remote in every shipped configuration, and
    // an OAuth token-exchange endpoint should never be reached over plain
    // HTTP, even in development.
    if (strncmp(url, "https://", 8) != 0) {
        fprintf(stderr, "exchange_desktop_code: refusing non-HTTPS URL: %s\n", url);
        return false;
    }

#ifdef _WIN32
    // ---------- Windows: WinHTTP ----------
    // Parse URL into host / path components
    URL_COMPONENTS urlComp;
    memset(&urlComp, 0, sizeof(urlComp));
    urlComp.dwStructSize = sizeof(urlComp);

    wchar_t wHost[256] = {0};
    wchar_t wPath[512] = {0};
    urlComp.lpszHostName    = wHost;
    urlComp.dwHostNameLength = (DWORD)(sizeof(wHost) / sizeof(wHost[0]));
    urlComp.lpszUrlPath     = wPath;
    urlComp.dwUrlPathLength  = (DWORD)(sizeof(wPath) / sizeof(wPath[0]));

    wchar_t wUrl[512] = {0};
    MultiByteToWideChar(CP_UTF8, 0, url, -1, wUrl, 512);

    if (!WinHttpCrackUrl(wUrl, 0, 0, &urlComp)) {
        printf("exchange_desktop_code: WinHttpCrackUrl failed.\n");
        return false;
    }

    HINTERNET hSession = WinHttpOpen(L"MixarDesktop/1.0",
                                     WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                     WINHTTP_NO_PROXY_NAME,
                                     WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return false;

    HINTERNET hConnect = WinHttpConnect(hSession, wHost, urlComp.nPort, 0);
    if (!hConnect) { WinHttpCloseHandle(hSession); return false; }

    DWORD dwFlags = (urlComp.nScheme == INTERNET_SCHEME_HTTPS) ? WINHTTP_FLAG_SECURE : 0;
    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST", wPath,
                                             NULL, WINHTTP_NO_REFERER,
                                             WINHTTP_DEFAULT_ACCEPT_TYPES, dwFlags);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return false;
    }

    const wchar_t* headers = L"Content-Type: application/json\r\n";
    BOOL sent = WinHttpSendRequest(hRequest, headers, (DWORD)-1,
                                   (LPVOID)body, (DWORD)strlen(body),
                                   (DWORD)strlen(body), 0);

    bool success = false;
    if (sent && WinHttpReceiveResponse(hRequest, NULL)) {
        // Check HTTP status before parsing — refuse to interpret error bodies
        // as token responses (a 500 with body "...access_token failed..."
        // would otherwise be misparsed by the old strstr-based reader).
        DWORD statusCode = 0;
        DWORD statusSize = sizeof(statusCode);
        if (!WinHttpQueryHeaders(hRequest,
                                 WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                                 WINHTTP_HEADER_NAME_BY_INDEX,
                                 &statusCode, &statusSize, WINHTTP_NO_HEADER_INDEX) ||
            statusCode < 200 || statusCode >= 300) {
            printf("exchange_desktop_code: backend returned HTTP %lu, refusing to parse.\n",
                   (unsigned long)statusCode);
        } else {
            char respBuf[4096] = {0};
            DWORD bytesRead = 0;
            DWORD offset = 0;
            while (WinHttpReadData(hRequest, respBuf + offset,
                                   (DWORD)(sizeof(respBuf) - offset - 1), &bytesRead) && bytesRead > 0) {
                offset += bytesRead;
            }
            respBuf[offset] = '\0';

            // Token responses may arrive wrapped in an envelope: parse top-level
            // first, then fall back to a "data" envelope if not found.
            const char* parse_root = respBuf;
            char data_buf[4096];
            // Quick heuristic: if response begins with {"status" or {"data" we
            // try the envelope-stripped parse if direct parse misses.

            char access_token[2048] = {0};
            char refresh_token[2048] = {0};
            bool at_ok = json_get_string(parse_root, "access_token",
                                         access_token, sizeof(access_token));
            bool rt_ok = json_get_string(parse_root, "refresh_token",
                                         refresh_token, sizeof(refresh_token));

            if (!at_ok) {
                // Try to locate a "data" sub-object and parse inside it.
                const char* data_key = strstr(respBuf, "\"data\"");
                if (data_key) {
                    const char* colon = strchr(data_key, ':');
                    if (colon) {
                        const char* obj = colon + 1;
                        while (*obj == ' ' || *obj == '\t' || *obj == '\n' || *obj == '\r') obj++;
                        if (*obj == '{') {
                            size_t n = strlen(obj);
                            if (n < sizeof(data_buf)) {
                                memcpy(data_buf, obj, n);
                                data_buf[n] = '\0';
                                at_ok = json_get_string(data_buf, "access_token",
                                                        access_token, sizeof(access_token));
                                rt_ok = json_get_string(data_buf, "refresh_token",
                                                        refresh_token, sizeof(refresh_token));
                            }
                        }
                    }
                }
            }

            if (at_ok && access_token[0] != '\0') {
                store_token_to_keyring(access_token);
                success = true;
                if (rt_ok && refresh_token[0] != '\0') {
                    store_refresh_token_to_keyring(refresh_token);
                }
            } else {
                printf("exchange_desktop_code: response missing access_token.\n");
            }
        }
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return success;

#else
    // ---------- macOS / Linux: libcurl ----------
    CURL* curl = curl_easy_init();
    if (!curl) return false;

    CurlResponse response;
    response.data = (char*)malloc(1);
    response.data[0] = '\0';
    response.size = 0;

    struct curl_slist* headers = NULL;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteResponseCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    CURLcode res = curl_easy_perform(curl);
    bool success = false;

    if (res == CURLE_OK) {
        // Check HTTP status before parsing. A 4xx/5xx error body must not
        // be interpreted as a token response.
        long http_code = 0;
        curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &http_code);
        if (http_code < 200 || http_code >= 300) {
            printf("exchange_desktop_code: backend returned HTTP %ld, refusing to parse.\n",
                   http_code);
        } else {
            const char* parse_root = response.data;
            char access_token[2048] = {0};
            char refresh_token[2048] = {0};
            bool at_ok = json_get_string(parse_root, "access_token",
                                         access_token, sizeof(access_token));
            bool rt_ok = json_get_string(parse_root, "refresh_token",
                                         refresh_token, sizeof(refresh_token));

            if (!at_ok) {
                // Envelope retry: response may be {"status":...,"data":{access_token...}}
                const char* data_key = strstr(response.data, "\"data\"");
                if (data_key) {
                    const char* colon = strchr(data_key, ':');
                    if (colon) {
                        const char* obj = colon + 1;
                        while (*obj == ' ' || *obj == '\t' || *obj == '\n' || *obj == '\r') obj++;
                        if (*obj == '{') {
                            at_ok = json_get_string(obj, "access_token",
                                                    access_token, sizeof(access_token));
                            rt_ok = json_get_string(obj, "refresh_token",
                                                    refresh_token, sizeof(refresh_token));
                        }
                    }
                }
            }

            if (at_ok && access_token[0] != '\0') {
                store_token_to_keyring(access_token);
                success = true;
                if (rt_ok && refresh_token[0] != '\0') {
                    store_refresh_token_to_keyring(refresh_token);
                }
            } else {
                printf("exchange_desktop_code: response missing access_token.\n");
            }
        }
    } else {
        printf("exchange_desktop_code: curl error: %s\n", curl_easy_strerror(res));
    }

    curl_slist_free_all(headers);
    free(response.data);
    curl_easy_cleanup(curl);
    return success;
#endif
}

// Helper to open URL in default browser
static void open_browser_url(const char* url) {
#ifdef _WIN32
    ShellExecuteA(NULL, "open", url, NULL, NULL, SW_SHOWNORMAL);
#elif defined(__APPLE__)
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "open \"%s\"", url);
    system(cmd);
#else
    char cmd[512];
    snprintf(cmd, sizeof(cmd), "xdg-open \"%s\"", url);
    system(cmd);
#endif
}

#ifdef _WIN32
#include <shellapi.h>

#define WM_AUTH_COMPLETE (WM_APP + 1)

struct AuthThreadData {
    HWND hWnd;
    char code_verifier[64];
    char state[64];
    intptr_t server_handle;
};

static DWORD WINAPI AuthWorkerThread(LPVOID param) {
    AuthThreadData* data = (AuthThreadData*)param;

    char received_code[128] = {0};
    bool got_code = auth_server_wait_for_code(data->server_handle, data->state,
                                              received_code, sizeof(received_code));
    bool result = got_code && exchange_desktop_code(received_code, data->code_verifier);

    PostMessage(data->hWnd, WM_AUTH_COMPLETE, result ? 1 : 0, 0);
    free(data);
    return 0;
}

// Window procedure for login dialog
LRESULT CALLBACK LoginWindowProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    LoginData* pData = (LoginData*)GetWindowLongPtr(hWnd, GWLP_USERDATA);

    if (GetConsoleWindow()) {
        ShowWindow(GetConsoleWindow(), SW_HIDE);
    }
    switch (message) {
        case WM_CREATE: {
            CREATESTRUCT* pCreate = (CREATESTRUCT*)lParam;
            pData = (LoginData*)pCreate->lpCreateParams;
            SetWindowLongPtr(hWnd, GWLP_USERDATA, (LONG_PTR)pData);

            // Create fonts
            pData->hFont = CreateFont(
                -15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "Segoe UI"
            );

            pData->hTitleFont = CreateFont(
                -15, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "Segoe UI"
            );

            // Layout constants
            const int margin = 32;
            const int controlHeight = 24;
            const int editHeight = 32;
            const int buttonHeight = 36;
            const int spacing = 20;
            const int labelWidth = 90;
            const int editWidth = 240;

            int yPos = margin;

            // Title label
            HWND hTitle = CreateWindow(
                "STATIC", "Opening browser for authentication...",
                WS_CHILD | WS_VISIBLE | SS_LEFT,
                margin, yPos, editWidth + labelWidth, 24,
                hWnd, NULL, GetModuleHandle(NULL), NULL
            );
            SendMessage(hTitle, WM_SETFONT, (WPARAM)pData->hFont, TRUE);
            yPos += 40;

            // Status text
            HWND hUserEdit = CreateWindowEx(
                WS_EX_CLIENTEDGE,
                "EDIT", "Waiting for browser...",
                WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL | ES_READONLY,
                margin, yPos, editWidth + labelWidth, editHeight,
                hWnd, (HMENU)IDC_USERNAME, GetModuleHandle(NULL), NULL
            );
            SendMessage(hUserEdit, WM_SETFONT, (WPARAM)pData->hFont, TRUE);
            yPos += editHeight + spacing;

            // Calculate button positions (right-aligned)
            int totalDialogWidth = margin + labelWidth + 12 + editWidth + margin;
            int buttonSpacing = 12;
            int buttonWidth = 120;
            int cancelX = totalDialogWidth - margin - buttonWidth;
            int retryX = cancelX - buttonWidth - buttonSpacing;

            // Retry button (hidden initially, shown on failure)
            HWND hLoginBtn = CreateWindow(
                "BUTTON", "Retry",
                WS_CHILD | WS_TABSTOP | BS_DEFPUSHBUTTON,
                retryX, yPos, buttonWidth, buttonHeight,
                hWnd, (HMENU)IDC_LOGIN, GetModuleHandle(NULL), NULL
            );
            SendMessage(hLoginBtn, WM_SETFONT, (WPARAM)pData->hFont, TRUE);

            // Cancel button
            HWND hCancelBtn = CreateWindow(
                "BUTTON", "Cancel",
                WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                cancelX, yPos, buttonWidth, buttonHeight,
                hWnd, (HMENU)IDC_CANCEL, GetModuleHandle(NULL), NULL
            );
            SendMessage(hCancelBtn, WM_SETFONT, (WPARAM)pData->hFont, TRUE);

            // Set icon
            if (pData && pData->hIcon) {
                SendMessage(hWnd, WM_SETICON, ICON_BIG, (LPARAM)pData->hIcon);
                SendMessage(hWnd, WM_SETICON, ICON_SMALL, (LPARAM)pData->hIcon);
            }

            // Auto-trigger login after window is shown
            PostMessage(hWnd, WM_COMMAND, MAKEWPARAM(IDC_LOGIN, BN_CLICKED), 0);
            return 0;
        }

        case WM_CTLCOLORSTATIC: {
            // Make static controls use system colors
            HDC hdc = (HDC)wParam;
            SetBkMode(hdc, TRANSPARENT);
            return (LRESULT)GetSysColorBrush(COLOR_BTNFACE);
        }

        case WM_COMMAND:
            if (!pData) break;

            switch (LOWORD(wParam)) {
                case IDC_LOGIN: {
                    // Generate PKCE verifier + challenge + OAuth state
                    char code_verifier[64] = {0};
                    char code_challenge[64] = {0};
                    char state[64] = {0};
                    if (!generate_code_verifier(code_verifier, sizeof(code_verifier))) {
                        MessageBox(hWnd, "Failed to generate secure random bytes for PKCE.", "Error", MB_OK | MB_ICONERROR);
                        return 0;
                    }
                    if (!generate_state(state, sizeof(state))) {
                        MessageBox(hWnd, "Failed to generate SSO state nonce.", "Error", MB_OK | MB_ICONERROR);
                        return 0;
                    }
                    compute_code_challenge(code_verifier, code_challenge, sizeof(code_challenge));

                    // Bind auth server first to get actual port
                    int actual_port = 0;
                    intptr_t server_handle = auth_server_start(51731, &actual_port);
                    if (server_handle < 0) {
                        MessageBox(hWnd, "Failed to start local auth server.", "Error", MB_OK | MB_ICONERROR);
                        return 0;
                    }

                    // Open SSO in browser with actual port + state (CSRF defense)
                    char url[512];
                    snprintf(url, sizeof(url),
                             "%s/app/desktop-login?port=%d&code_challenge=%s&code_challenge_method=S256&state=%s",
                             MIXAR_FRONTEND_BASE_URL, actual_port, code_challenge, state);
                    open_browser_url(url);

                    // Show waiting message
                    SetDlgItemText(hWnd, IDC_USERNAME, "Waiting for browser...");
                    EnableWindow(GetDlgItem(hWnd, IDC_LOGIN), FALSE);

                    // Run auth server on background thread to keep UI responsive
                    AuthThreadData* threadData = (AuthThreadData*)malloc(sizeof(AuthThreadData));
                    if (threadData) {
                        threadData->hWnd = hWnd;
                        threadData->server_handle = server_handle;
                        strncpy(threadData->code_verifier, code_verifier, sizeof(threadData->code_verifier) - 1);
                        threadData->code_verifier[sizeof(threadData->code_verifier) - 1] = '\0';
                        strncpy(threadData->state, state, sizeof(threadData->state) - 1);
                        threadData->state[sizeof(threadData->state) - 1] = '\0';
                        HANDLE hThread = CreateThread(NULL, 0, AuthWorkerThread, threadData, 0, NULL);
                        if (hThread) {
                            CloseHandle(hThread);
                        } else {
                            free(threadData);
                            MessageBox(hWnd, "Failed to start auth thread.", "Error", MB_OK | MB_ICONERROR);
                            SetDlgItemText(hWnd, IDC_USERNAME, "Ready");
                            EnableWindow(GetDlgItem(hWnd, IDC_LOGIN), TRUE);
                        }
                    }
                    return 0;
                }

                case IDC_CANCEL:
                    if (pData) {
                        pData->result = false;
                        pData->dialogClosed = true;
                    }
                    DestroyWindow(hWnd);
                    return 0;
            }
            break;

        case WM_KEYDOWN:
            if (wParam == VK_RETURN) {
                SendMessage(hWnd, WM_COMMAND, MAKEWPARAM(IDC_LOGIN, BN_CLICKED), 0);
                return 0;
            } else if (wParam == VK_ESCAPE) {
                SendMessage(hWnd, WM_COMMAND, MAKEWPARAM(IDC_CANCEL, BN_CLICKED), 0);
                return 0;
            }
            break;

        case WM_AUTH_COMPLETE:
            if (!pData) break;
            if (wParam) {
                pData->result = true;
                pData->dialogClosed = true;
                DestroyWindow(hWnd);
            } else {
                MessageBox(hWnd, "Failed to receive login token.", "Error", MB_OK | MB_ICONERROR);
                SetDlgItemText(hWnd, IDC_USERNAME, "Click Retry to try again");
                ShowWindow(GetDlgItem(hWnd, IDC_LOGIN), SW_SHOW);
                EnableWindow(GetDlgItem(hWnd, IDC_LOGIN), TRUE);
            }
            return 0;

        case WM_CLOSE:
            if (pData) {
                pData->result = false;
                pData->dialogClosed = true;
            }
            DestroyWindow(hWnd);
            return 0;

        case WM_DESTROY:
            if (pData) {
                pData->dialogClosed = true;
                // Clean up fonts
                if (pData->hFont) DeleteObject(pData->hFont);
                if (pData->hTitleFont) DeleteObject(pData->hTitleFont);
            }
            return 0;
    }

    return DefWindowProc(hWnd, message, wParam, lParam);
}

bool show_startup_dialog(void) {
#ifdef MIXAR_ENV_DEV
    // Dev bypass: skip the startup SSO gate entirely.
    // The Mixar panel login button handles auth via username/password.
    return true;
#endif

    // Check if token already exists
    char* existingToken = get_token_from_keyring();
    if (existingToken) {
        free(existingToken);
        return true; // Already authenticated
    }

    LoginData loginData = {0};
    loginData.result = false;
    loginData.dialogClosed = false;

    // Load custom icon if available
    char* iconPathStr = get_app_icon_path();
    if (iconPathStr && strlen(iconPathStr) > 0) {
        // Convert to wide string for LoadImage
        wchar_t iconPathW[MAX_PATH];
        MultiByteToWideChar(CP_UTF8, 0, iconPathStr, -1, iconPathW, MAX_PATH);

        loginData.hIcon = (HICON)LoadImageW(
            NULL, iconPathW, IMAGE_ICON, 
            32, 32, LR_LOADFROMFILE
        );
    }

    // Register window class
    const char* className = "MixarLoginDialog";
    WNDCLASSEX wc = {0};
    wc.cbSize = sizeof(WNDCLASSEX);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = LoginWindowProc;
    wc.hInstance = GetModuleHandle(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = className;
    wc.hIcon = loginData.hIcon;
    wc.hIconSm = loginData.hIcon;

    RegisterClassEx(&wc);

    // Calculate dialog size
    const int margin = 32;
    const int labelWidth = 90;
    const int editWidth = 240;
    const int editHeight = 32;
    const int buttonHeight = 36;
    const int spacing = 20;

    int dialogWidth = margin + labelWidth + 12 + editWidth + margin;
    int dialogHeight = margin + 24 + 40 + editHeight + spacing + buttonHeight + margin;

    // Center position
    int x = (GetSystemMetrics(SM_CXSCREEN) - dialogWidth) / 2;
    int y = (GetSystemMetrics(SM_CYSCREEN) - dialogHeight) / 2;

    // Create the dialog window
    HWND hDlg = CreateWindowEx(
        WS_EX_DLGMODALFRAME,
        className,
        "Mixar Login",
        WS_POPUP | WS_CAPTION | WS_SYSMENU,
        x, y, dialogWidth, dialogHeight,
        NULL, NULL, GetModuleHandle(NULL), &loginData
    );

    if (!hDlg) {
        if (loginData.hIcon) DestroyIcon(loginData.hIcon);
        UnregisterClass(className, GetModuleHandle(NULL));
        return false;
    }

    ShowWindow(hDlg, SW_SHOW);
    UpdateWindow(hDlg);

    // Message loop
    MSG msg;
    while (!loginData.dialogClosed) {
        BOOL ret = GetMessage(&msg, NULL, 0, 0);
        if (ret == 0 || ret == -1) break; // WM_QUIT or error

        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }

    // Cleanup
    if (loginData.hIcon) {
        DestroyIcon(loginData.hIcon);
    }
    UnregisterClass(className, GetModuleHandle(NULL));

    return loginData.result;
}
#elif defined(__APPLE__)
#include <CoreFoundation/CoreFoundation.h>
bool show_startup_dialog(void) {
#ifdef MIXAR_ENV_DEV
    // Dev bypass: skip the startup SSO gate entirely.
    // The Mixar panel login button handles auth via username/password.
    return true;
#endif

    // Check if token already exists
    char* existingToken = get_token_from_keyring();
    if (existingToken) {
        free(existingToken);
        return true; // Already authenticated
    }

    // Generate PKCE verifier + challenge + OAuth state (CSRF defense)
    char code_verifier[64] = {0};
    char code_challenge[64] = {0};
    char state[64] = {0};
    if (!generate_code_verifier(code_verifier, sizeof(code_verifier))) {
        printf("Failed to generate secure random bytes for PKCE.\n");
        return false;
    }
    if (!generate_state(state, sizeof(state))) {
        printf("Failed to generate SSO state nonce.\n");
        return false;
    }
    compute_code_challenge(code_verifier, code_challenge, sizeof(code_challenge));

    // Bind auth server first to get actual port
    int actual_port = 0;
    intptr_t server_handle = auth_server_start(51731, &actual_port);
    if (server_handle < 0) {
        printf("Failed to start local auth server.\n");
        return false;
    }

    // Auto-open browser for SSO with actual port + state
    char url[512];
    snprintf(url, sizeof(url),
             "%s/app/desktop-login?port=%d&code_challenge=%s&code_challenge_method=S256&state=%s",
             MIXAR_FRONTEND_BASE_URL, actual_port, code_challenge, state);
    open_browser_url(url);

    // Wait for auth code from localhost callback (validates state)
    char received_code[128] = {0};
    bool got_code = auth_server_wait_for_code(server_handle, state,
                                              received_code, sizeof(received_code));
    bool result = got_code && exchange_desktop_code(received_code, code_verifier);

    // Show error message if authentication failed
    if (!result) {
        CFStringRef errorTitle = CFStringCreateWithCString(NULL, "Authentication Failed", kCFStringEncodingUTF8);
        CFStringRef errorMessage = CFStringCreateWithCString(NULL, "Failed to receive login token.", kCFStringEncodingUTF8);
        CFStringRef errorOkButton = CFStringCreateWithCString(NULL, "OK", kCFStringEncodingUTF8);

        CFMutableDictionaryRef errorDict = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        CFDictionarySetValue(errorDict, kCFUserNotificationAlertHeaderKey, errorTitle);
        CFDictionarySetValue(errorDict, kCFUserNotificationAlertMessageKey, errorMessage);
        CFDictionarySetValue(errorDict, kCFUserNotificationDefaultButtonTitleKey, errorOkButton);

        char* errorIconPathStr = get_app_icon_path();
        CFStringRef errorIconPath = CFStringCreateWithCString(NULL, errorIconPathStr, kCFStringEncodingUTF8);
        if (errorIconPath) {
            CFURLRef errorIconURL = CFURLCreateWithFileSystemPath(NULL, errorIconPath, kCFURLPOSIXPathStyle, false);
            if (errorIconURL) {
                CFDictionarySetValue(errorDict, kCFUserNotificationIconURLKey, errorIconURL);
                CFRelease(errorIconURL);
            }
            CFRelease(errorIconPath);
        }

        SInt32 errorError;
        CFUserNotificationRef errorNotification = CFUserNotificationCreate(NULL, 0,
            kCFUserNotificationPlainAlertLevel, &errorError, errorDict);

        CFOptionFlags errorResponse;
        CFUserNotificationReceiveResponse(errorNotification, 0, &errorResponse);

        CFRelease(errorTitle);
        CFRelease(errorMessage);
        CFRelease(errorOkButton);
        CFRelease(errorDict);
        CFRelease(errorNotification);
    }

    return result;
}
#else
#include <cstdlib>
#include <cstring>
#include <string>
#include <sstream>
#include <fstream>
#include <iostream>

// Alternative implementation using zenity for linux
bool show_startup_dialog(void) {
#ifdef MIXAR_ENV_DEV
    // Dev bypass: skip the startup SSO gate entirely.
    // The Mixar panel login button handles auth via username/password.
    return true;
#endif

    // Check if token already exists
    char* existingToken = get_token_from_keyring();
    if (existingToken) {
        free(existingToken);
        return true; // Already authenticated
    }

    // Generate PKCE verifier + challenge + OAuth state (CSRF defense)
    char code_verifier[64] = {0};
    char code_challenge[64] = {0};
    char state[64] = {0};
    if (!generate_code_verifier(code_verifier, sizeof(code_verifier))) {
        std::system("zenity --error --title=\"Authentication Failed\" "
                    "--text=\"Failed to generate secure random bytes.\" --width=300");
        return false;
    }
    if (!generate_state(state, sizeof(state))) {
        std::system("zenity --error --title=\"Authentication Failed\" "
                    "--text=\"Failed to generate SSO state nonce.\" --width=300");
        return false;
    }
    compute_code_challenge(code_verifier, code_challenge, sizeof(code_challenge));

    // Bind auth server first to get actual port
    int actual_port = 0;
    intptr_t server_handle = auth_server_start(51731, &actual_port);
    if (server_handle < 0) {
        std::system("zenity --error --title=\"Authentication Failed\" "
                    "--text=\"Failed to start local auth server.\" --width=300");
        return false;
    }

    // Auto-open browser for SSO with actual port + state
    char url[512];
    snprintf(url, sizeof(url),
             "%s/app/desktop-login?port=%d&code_challenge=%s&code_challenge_method=S256&state=%s",
             MIXAR_FRONTEND_BASE_URL, actual_port, code_challenge, state);
    open_browser_url(url);

    // Wait for auth code from localhost callback (validates state)
    char received_code[128] = {0};
    bool got_code = auth_server_wait_for_code(server_handle, state,
                                              received_code, sizeof(received_code));
    bool result = got_code && exchange_desktop_code(received_code, code_verifier);

    if (!result) {
        char* iconPath = get_app_icon_path();
        std::string error_cmd = "zenity --error --title=\"Authentication Failed\" "
                               "--text=\"Failed to receive login token.\" "
                               "--width=300";

        if (iconPath) {
            error_cmd += " --window-icon=\"" + std::string(iconPath) + "\"";
        }

        std::system(error_cmd.c_str());
        return false;
    }

    return true;
}
#endif


