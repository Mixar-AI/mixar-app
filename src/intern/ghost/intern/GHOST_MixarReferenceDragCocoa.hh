/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

#import <Cocoa/Cocoa.h>

#include "GHOST_Types.hh"

/** Cocoa's window callback sends no payload until release. File URLs are
 * already available on the drag pasteboard; copy only their paths so the
 * application can reveal its destination during hover. The GHOST event owns
 * and frees this array, just like a completed file drop. */
inline GHOST_TStringArray *mixar_drag_preview_paths()
{
  @autoreleasepool {
    NSPasteboard *board = [NSPasteboard pasteboardWithName:NSPasteboardNameDrag];
    NSArray<NSURL *> *urls = [board readObjectsForClasses:@[ [NSURL class] ]
                                                  options:@{
                                                    NSPasteboardURLReadingFileURLsOnlyKey : @YES
                                                  }];
    if (urls.count == 0) {
      return nullptr;
    }
    auto *paths = static_cast<GHOST_TStringArray *>(calloc(1, sizeof(GHOST_TStringArray)));
    if (!paths) {
      return nullptr;
    }
    paths->strings = static_cast<uint8_t **>(calloc(urls.count, sizeof(uint8_t *)));
    if (!paths->strings) {
      free(paths);
      return nullptr;
    }
    for (NSURL *url in urls) {
      const char *path = url.path.UTF8String;
      if (path) {
        auto *copy = reinterpret_cast<uint8_t *>(strdup(path));
        if (!copy) {
          break;
        }
        paths->strings[paths->count++] = copy;
      }
    }
    return paths;
  }
}
