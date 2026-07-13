// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef CREATOR_AUTH_H
#define CREATOR_AUTH_H

/**
 * Token storage API for secure credential management.
 *
 * MEMORY MANAGEMENT:
 * Functions returning char* (get_token_from_keyring, get_refresh_token_from_keyring)
 * allocate memory that the caller must free.
 *
 * IMPORTANT: Always use free_token_secure() instead of free() for tokens.
 * This ensures sensitive credential data is securely zeroed before deallocation.
 */

bool store_token_to_keyring(const char* token);

/**
 * Retrieves the access token from the system keyring.
 * @return Allocated string with token, or NULL if not found.
 *         Caller MUST free with free_token_secure().
 */
char* get_token_from_keyring();

bool delete_token_from_keyring();

bool store_refresh_token_to_keyring(const char* token);

/**
 * Retrieves the refresh token from the system keyring.
 * @return Allocated string with token, or NULL if not found.
 *         Caller MUST free with free_token_secure().
 */
char* get_refresh_token_from_keyring();

bool delete_refresh_token_from_keyring();

/**
 * Securely frees token memory by zeroing before deallocation.
 * Always use this instead of free() for tokens to prevent
 * sensitive data from lingering in memory.
 */
void free_token_secure(char* token);

#endif