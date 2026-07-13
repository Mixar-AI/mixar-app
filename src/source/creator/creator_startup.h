// SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
//
// SPDX-License-Identifier: GPL-3.0-or-later

#ifndef CREATOR_STARTUP_H
#define CREATOR_STARTUP_H

#include "creator_auth.h"

// Function to get base URL based on MIXAR_ENV environment variable
const char* get_mixar_base_url();

#define MIXAR_AUTH_ENDPOINT "/api/v1/auth/login"

extern "C" int GHOST_HACK_getFirstFile(char buf[]);

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <winhttp.h>
#pragma comment(lib, "winhttp.lib")

#else
// macOS and Linux use libcurl for HTTP requests
#include <curl/curl.h>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <string>

#ifdef __APPLE__
#include <CoreFoundation/CoreFoundation.h>
#endif

// Initialize curl globally (call once at program start)
void init_auth_system(void);

// Cleanup curl globally (call once at program end)
void cleanup_auth_system(void);
#endif

#ifdef _WIN32
#include <windows.h>
#include <commctrl.h>
#include <uxtheme.h>

#define IDC_USERNAME 1001
#define IDC_PASSWORD 1002
#define IDC_LOGIN    1003
#define IDC_CANCEL   1004

typedef struct {
    char username[256];
    char password[256];
    bool result;
    bool dialogClosed;
    HICON hIcon;
    HFONT hFont;
    HFONT hTitleFont;
} LoginData;

// Window procedure for login dialog
LRESULT CALLBACK LoginWindowProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam);

// Show startup dialog
bool show_startup_dialog(void);

#elif defined(__APPLE__)
#include <CoreFoundation/CoreFoundation.h>

// Show startup dialog
bool show_startup_dialog(void);

#else
#include <cstdlib>
#include <cstring>
#include <string>
#include <sstream>
#include <fstream>
#include <iostream>

// Show startup dialog
bool show_startup_dialog(void);
#endif

#endif // CREATOR_STARTUP_H
