// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

// Required for memset_s on macOS (C11 Annex K)
#if defined(__APPLE__)
#define __STDC_WANT_LIB_EXT1__ 1
#endif

#include "creator_auth.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <wincred.h>
#elif defined(__APPLE__)
#include <Security/Security.h>
#include <CoreFoundation/CoreFoundation.h>
#else
// Linux
#ifdef HAVE_LIBSECRET
#include <libsecret/secret.h>
#endif
#endif

static const char* SERVICE_NAME = "MixarSafeStorage";
static const char* ACCOUNT_NAME = "AccessToken";
static const char* REFRESH_ACCOUNT_NAME = "RefreshToken";

#ifdef _WIN32
// Use "username@service" format to match Python keyring's compound TargetName format
static const char* WIN_TARGET_NAME = "AccessToken@MixarSafeStorage";
static const char* WIN_REFRESH_TARGET_NAME = "RefreshToken@MixarSafeStorage";
#endif

#ifdef __linux__
#ifdef HAVE_LIBSECRET
// Schema for libsecret to match Python keyring's SecretService backend
static const SecretSchema mixar_schema = {
    "org.freedesktop.Secret.Generic",
    SECRET_SCHEMA_NONE,
    {
        {"service", SECRET_SCHEMA_ATTRIBUTE_STRING},
        {"username", SECRET_SCHEMA_ATTRIBUTE_STRING},
        {NULL, SECRET_SCHEMA_ATTRIBUTE_STRING}
    }
};
#endif
#endif

// Helper to securely zero memory before freeing
static void secure_zero_free(char* ptr, size_t len) {
    if (ptr) {
#ifdef _WIN32
        SecureZeroMemory(ptr, len);
#elif defined(__APPLE__)
        // macOS: Use memset_s (C11) or manual volatile approach
        memset_s(ptr, len, 0, len);
#else
        // Linux: Use explicit_bzero if available
        explicit_bzero(ptr, len);
#endif
        free(ptr);
    }
}

bool store_token_to_keyring(const char* token) {
    if (!token || token[0] == '\0') {
        return false;
    }

#ifdef _WIN32
    CREDENTIALA cred = {0};
    cred.Type = CRED_TYPE_GENERIC;
    // Use "username@service" format to match Python keyring's compound format
    cred.TargetName = (LPSTR)WIN_TARGET_NAME;
    cred.CredentialBlobSize = (DWORD)strlen(token);
    cred.CredentialBlob = (LPBYTE)token;
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE;
    cred.UserName = (LPSTR)ACCOUNT_NAME;

    return CredWriteA(&cred, 0) != 0;

#elif defined(__APPLE__)
    // Use modern SecItem API
    CFStringRef service = CFStringCreateWithCString(NULL, SERVICE_NAME, kCFStringEncodingUTF8);
    CFStringRef account = CFStringCreateWithCString(NULL, ACCOUNT_NAME, kCFStringEncodingUTF8);
    CFDataRef tokenData = CFDataCreate(NULL, (const UInt8*)token, strlen(token));

    if (!service || !account || !tokenData) {
        if (service) CFRelease(service);
        if (account) CFRelease(account);
        if (tokenData) CFRelease(tokenData);
        return false;
    }

    // First, try to delete any existing item
    CFMutableDictionaryRef deleteQuery = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(deleteQuery, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(deleteQuery, kSecAttrService, service);
    CFDictionarySetValue(deleteQuery, kSecAttrAccount, account);
    SecItemDelete(deleteQuery);
    CFRelease(deleteQuery);

    // Now add the new item
    CFMutableDictionaryRef addQuery = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(addQuery, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(addQuery, kSecAttrService, service);
    CFDictionarySetValue(addQuery, kSecAttrAccount, account);
    CFDictionarySetValue(addQuery, kSecValueData, tokenData);

    OSStatus status = SecItemAdd(addQuery, NULL);

    CFRelease(addQuery);
    CFRelease(service);
    CFRelease(account);
    CFRelease(tokenData);

    return (status == errSecSuccess);

#else
    // Linux: Use libsecret to match Python keyring's SecretService backend
#ifdef HAVE_LIBSECRET
    GError* error = NULL;
    gboolean result = secret_password_store_sync(
        &mixar_schema,
        SECRET_COLLECTION_DEFAULT,
        "MixarSafeStorage Access Token",  // Label shown in secret manager
        token,
        NULL,  // GCancellable
        &error,
        "service", SERVICE_NAME,
        "username", ACCOUNT_NAME,
        NULL);

    if (error) {
        g_error_free(error);
        return false;
    }
    return result == TRUE;
#else
    // libsecret not available at compile time
    (void)token;
    return false;
#endif
#endif
}

char* get_token_from_keyring() {
#ifdef _WIN32
    PCREDENTIALA cred;
    // Use "username@service" format to match Python keyring's compound format
    if (CredReadA(WIN_TARGET_NAME, CRED_TYPE_GENERIC, 0, &cred)) {
        char* token = (char*)malloc(cred->CredentialBlobSize + 1);
        if (token == NULL) {
            CredFree(cred);
            return NULL;
        }
        memcpy(token, cred->CredentialBlob, cred->CredentialBlobSize);
        token[cred->CredentialBlobSize] = '\0';
        CredFree(cred);
        return token;
    }
    return NULL;

#elif defined(__APPLE__)
    // Use modern SecItem API
    CFStringRef service = CFStringCreateWithCString(NULL, SERVICE_NAME, kCFStringEncodingUTF8);
    CFStringRef account = CFStringCreateWithCString(NULL, ACCOUNT_NAME, kCFStringEncodingUTF8);

    if (!service || !account) {
        if (service) CFRelease(service);
        if (account) CFRelease(account);
        return NULL;
    }

    CFMutableDictionaryRef query = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(query, kSecAttrService, service);
    CFDictionarySetValue(query, kSecAttrAccount, account);
    CFDictionarySetValue(query, kSecReturnData, kCFBooleanTrue);
    CFDictionarySetValue(query, kSecMatchLimit, kSecMatchLimitOne);
    /* Suppress the SecurityAgent "Mixar wants to access your keychain"
     * prompt. The previous build's keychain item is ACL-bound to a
     * different code signature / path (especially under App
     * Translocation on first DMG launch from Finder), so without this
     * the prompt fires on the main thread before Blender is up and
     * a background SSL handshake races with it, corrupting Python
     * state and crashing the autoshow timer. With UIFail we instead
     * get errSecInteractionNotAllowed and treat it as a stale item. */
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    CFDictionarySetValue(query, kSecUseAuthenticationUI, kSecUseAuthenticationUIFail);
#pragma clang diagnostic pop

    CFDataRef resultData = NULL;
    OSStatus status = SecItemCopyMatching(query, (CFTypeRef*)&resultData);

    CFRelease(query);

    if (status == errSecSuccess && resultData) {
        CFIndex length = CFDataGetLength(resultData);
        char* token = (char*)malloc(length + 1);
        if (token) {
            memcpy(token, CFDataGetBytePtr(resultData), length);
            token[length] = '\0';
        }
        CFRelease(resultData);
        CFRelease(service);
        CFRelease(account);
        return token;
    }

    /* Stale ACL from a previous install: drop the item so the OAuth
     * flow recreates it cleanly under this binary's signature. */
    if (status == errSecAuthFailed || status == errSecInteractionNotAllowed ||
        status == errSecInteractionRequired)
    {
        CFMutableDictionaryRef del = CFDictionaryCreateMutable(
            NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        CFDictionarySetValue(del, kSecClass, kSecClassGenericPassword);
        CFDictionarySetValue(del, kSecAttrService, service);
        CFDictionarySetValue(del, kSecAttrAccount, account);
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        CFDictionarySetValue(del, kSecUseAuthenticationUI, kSecUseAuthenticationUIFail);
#pragma clang diagnostic pop
        SecItemDelete(del);
        CFRelease(del);
    }

    CFRelease(service);
    CFRelease(account);
    return NULL;

#else
    // Linux: Use libsecret to match Python keyring's SecretService backend
#ifdef HAVE_LIBSECRET
    GError* error = NULL;
    gchar* password = secret_password_lookup_sync(
        &mixar_schema,
        NULL,  // GCancellable
        &error,
        "service", SERVICE_NAME,
        "username", ACCOUNT_NAME,
        NULL);

    if (error) {
        g_error_free(error);
        return NULL;
    }

    if (password) {
        // Copy to malloc'd buffer since caller expects to free with free()
        char* token = (char*)malloc(strlen(password) + 1);
        if (token) {
            strcpy(token, password);
        }
        secret_password_free(password);
        return token;
    }
    return NULL;
#else
    // libsecret not available at compile time
    return NULL;
#endif
#endif
}

bool delete_token_from_keyring() {
#ifdef _WIN32
    // Use "username@service" format to match Python keyring's compound format
    if (CredDeleteA(WIN_TARGET_NAME, CRED_TYPE_GENERIC, 0)) {
        return true;
    }
    // Consider "not found" as success (nothing to delete)
    return GetLastError() == ERROR_NOT_FOUND;

#elif defined(__APPLE__)
    // Use modern SecItem API
    CFStringRef service = CFStringCreateWithCString(NULL, SERVICE_NAME, kCFStringEncodingUTF8);
    CFStringRef account = CFStringCreateWithCString(NULL, ACCOUNT_NAME, kCFStringEncodingUTF8);

    if (!service || !account) {
        if (service) CFRelease(service);
        if (account) CFRelease(account);
        return false;
    }

    CFMutableDictionaryRef query = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(query, kSecAttrService, service);
    CFDictionarySetValue(query, kSecAttrAccount, account);

    OSStatus status = SecItemDelete(query);

    CFRelease(query);
    CFRelease(service);
    CFRelease(account);

    return (status == errSecSuccess || status == errSecItemNotFound);

#else
    // Linux: Use libsecret to match Python keyring's SecretService backend
#ifdef HAVE_LIBSECRET
    GError* error = NULL;
    gboolean result = secret_password_clear_sync(
        &mixar_schema,
        NULL,  // GCancellable
        &error,
        "service", SERVICE_NAME,
        "username", ACCOUNT_NAME,
        NULL);

    if (error) {
        // If item not found, consider it success
        bool not_found = (error->code == SECRET_ERROR_NO_SUCH_OBJECT);
        g_error_free(error);
        return not_found;
    }
    return true;  // No error = success
#else
    // libsecret not available at compile time
    return false;
#endif
#endif
}

// ============================================================================
// Refresh Token Functions
// ============================================================================

bool store_refresh_token_to_keyring(const char* token) {
    if (!token || token[0] == '\0') {
        return false;
    }

#ifdef _WIN32
    CREDENTIALA cred = {0};
    cred.Type = CRED_TYPE_GENERIC;
    cred.TargetName = (LPSTR)WIN_REFRESH_TARGET_NAME;
    cred.CredentialBlobSize = (DWORD)strlen(token);
    cred.CredentialBlob = (LPBYTE)token;
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE;
    cred.UserName = (LPSTR)REFRESH_ACCOUNT_NAME;

    return CredWriteA(&cred, 0) != 0;

#elif defined(__APPLE__)
    CFStringRef service = CFStringCreateWithCString(NULL, SERVICE_NAME, kCFStringEncodingUTF8);
    CFStringRef account = CFStringCreateWithCString(NULL, REFRESH_ACCOUNT_NAME, kCFStringEncodingUTF8);
    CFDataRef tokenData = CFDataCreate(NULL, (const UInt8*)token, strlen(token));

    if (!service || !account || !tokenData) {
        if (service) CFRelease(service);
        if (account) CFRelease(account);
        if (tokenData) CFRelease(tokenData);
        return false;
    }

    // First, try to delete any existing item
    CFMutableDictionaryRef deleteQuery = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(deleteQuery, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(deleteQuery, kSecAttrService, service);
    CFDictionarySetValue(deleteQuery, kSecAttrAccount, account);
    SecItemDelete(deleteQuery);
    CFRelease(deleteQuery);

    // Now add the new item
    CFMutableDictionaryRef addQuery = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(addQuery, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(addQuery, kSecAttrService, service);
    CFDictionarySetValue(addQuery, kSecAttrAccount, account);
    CFDictionarySetValue(addQuery, kSecValueData, tokenData);

    OSStatus status = SecItemAdd(addQuery, NULL);

    CFRelease(addQuery);
    CFRelease(service);
    CFRelease(account);
    CFRelease(tokenData);

    return (status == errSecSuccess);

#else
    // Linux: Use libsecret
#ifdef HAVE_LIBSECRET
    GError* error = NULL;
    gboolean result = secret_password_store_sync(
        &mixar_schema,
        SECRET_COLLECTION_DEFAULT,
        "MixarSafeStorage Refresh Token",
        token,
        NULL,
        &error,
        "service", SERVICE_NAME,
        "username", REFRESH_ACCOUNT_NAME,
        NULL);

    if (error) {
        g_error_free(error);
        return false;
    }
    return result == TRUE;
#else
    (void)token;
    return false;
#endif
#endif
}

char* get_refresh_token_from_keyring() {
#ifdef _WIN32
    PCREDENTIALA cred;
    if (CredReadA(WIN_REFRESH_TARGET_NAME, CRED_TYPE_GENERIC, 0, &cred)) {
        char* token = (char*)malloc(cred->CredentialBlobSize + 1);
        if (token == NULL) {
            CredFree(cred);
            return NULL;
        }
        memcpy(token, cred->CredentialBlob, cred->CredentialBlobSize);
        token[cred->CredentialBlobSize] = '\0';
        CredFree(cred);
        return token;
    }
    return NULL;

#elif defined(__APPLE__)
    CFStringRef service = CFStringCreateWithCString(NULL, SERVICE_NAME, kCFStringEncodingUTF8);
    CFStringRef account = CFStringCreateWithCString(NULL, REFRESH_ACCOUNT_NAME, kCFStringEncodingUTF8);

    if (!service || !account) {
        if (service) CFRelease(service);
        if (account) CFRelease(account);
        return NULL;
    }

    CFMutableDictionaryRef query = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(query, kSecAttrService, service);
    CFDictionarySetValue(query, kSecAttrAccount, account);
    CFDictionarySetValue(query, kSecReturnData, kCFBooleanTrue);
    CFDictionarySetValue(query, kSecMatchLimit, kSecMatchLimitOne);
    /* See note in get_token_from_keyring(): never let SecurityAgent
     * UI block the main thread on a stale ACL. */
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    CFDictionarySetValue(query, kSecUseAuthenticationUI, kSecUseAuthenticationUIFail);
#pragma clang diagnostic pop

    CFDataRef resultData = NULL;
    OSStatus status = SecItemCopyMatching(query, (CFTypeRef*)&resultData);

    CFRelease(query);

    if (status == errSecSuccess && resultData) {
        CFIndex length = CFDataGetLength(resultData);
        char* token = (char*)malloc(length + 1);
        if (token) {
            memcpy(token, CFDataGetBytePtr(resultData), length);
            token[length] = '\0';
        }
        CFRelease(resultData);
        CFRelease(service);
        CFRelease(account);
        return token;
    }

    if (status == errSecAuthFailed || status == errSecInteractionNotAllowed ||
        status == errSecInteractionRequired)
    {
        CFMutableDictionaryRef del = CFDictionaryCreateMutable(
            NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        CFDictionarySetValue(del, kSecClass, kSecClassGenericPassword);
        CFDictionarySetValue(del, kSecAttrService, service);
        CFDictionarySetValue(del, kSecAttrAccount, account);
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        CFDictionarySetValue(del, kSecUseAuthenticationUI, kSecUseAuthenticationUIFail);
#pragma clang diagnostic pop
        SecItemDelete(del);
        CFRelease(del);
    }

    CFRelease(service);
    CFRelease(account);
    return NULL;

#else
    // Linux: Use libsecret
#ifdef HAVE_LIBSECRET
    GError* error = NULL;
    gchar* password = secret_password_lookup_sync(
        &mixar_schema,
        NULL,
        &error,
        "service", SERVICE_NAME,
        "username", REFRESH_ACCOUNT_NAME,
        NULL);

    if (error) {
        g_error_free(error);
        return NULL;
    }

    if (password) {
        char* token = (char*)malloc(strlen(password) + 1);
        if (token) {
            strcpy(token, password);
        }
        secret_password_free(password);
        return token;
    }
    return NULL;
#else
    return NULL;
#endif
#endif
}

bool delete_refresh_token_from_keyring() {
#ifdef _WIN32
    if (CredDeleteA(WIN_REFRESH_TARGET_NAME, CRED_TYPE_GENERIC, 0)) {
        return true;
    }
    // Consider "not found" as success (nothing to delete)
    return GetLastError() == ERROR_NOT_FOUND;

#elif defined(__APPLE__)
    CFStringRef service = CFStringCreateWithCString(NULL, SERVICE_NAME, kCFStringEncodingUTF8);
    CFStringRef account = CFStringCreateWithCString(NULL, REFRESH_ACCOUNT_NAME, kCFStringEncodingUTF8);

    if (!service || !account) {
        if (service) CFRelease(service);
        if (account) CFRelease(account);
        return false;
    }

    CFMutableDictionaryRef query = CFDictionaryCreateMutable(
        NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
    CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(query, kSecAttrService, service);
    CFDictionarySetValue(query, kSecAttrAccount, account);

    OSStatus status = SecItemDelete(query);

    CFRelease(query);
    CFRelease(service);
    CFRelease(account);

    return (status == errSecSuccess || status == errSecItemNotFound);

#else
    // Linux: Use libsecret
#ifdef HAVE_LIBSECRET
    GError* error = NULL;
    gboolean result = secret_password_clear_sync(
        &mixar_schema,
        NULL,
        &error,
        "service", SERVICE_NAME,
        "username", REFRESH_ACCOUNT_NAME,
        NULL);

    if (error) {
        bool not_found = (error->code == SECRET_ERROR_NO_SUCH_OBJECT);
        g_error_free(error);
        return not_found;
    }
    return true;  // No error = success
#else
    return false;
#endif
#endif
}

// Secure free function for callers to use when done with tokens
void free_token_secure(char* token) {
    if (token) {
        secure_zero_free(token, strlen(token));
    }
}
