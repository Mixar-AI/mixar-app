/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

#import <Cocoa/Cocoa.h>
#import <AVFoundation/AVFoundation.h>
#include <atomic>
#include <dlfcn.h>
#include <libproc.h>
#include <unistd.h>

/* No speech-recognition permission: Unmute transcribes, macOS only captures. */
extern "C" int Mixar_MicrophonePermission(const bool request)
{
  static std::atomic<bool> pending{false};
  dlopen("/System/Library/Frameworks/AVFoundation.framework/AVFoundation", RTLD_LAZY);
  Class device = NSClassFromString(@"AVCaptureDevice");
  if (!device) {
    return -1;
  }
  const AVAuthorizationStatus status = [device authorizationStatusForMediaType:@"soun"];
  if (status == AVAuthorizationStatusAuthorized) {
    return 1;
  }
  if (status != AVAuthorizationStatusNotDetermined) {
    return -1;
  }
  if (!request || pending) {
    return 0;
  }
  /* TCC reads the responsible application's plist, not necessarily our own. */
  NSBundle *bundle = [NSBundle mainBundle];
  using ResponsibleFn = pid_t (*)(pid_t);
  const auto responsible_fn = reinterpret_cast<ResponsibleFn>(
      dlsym(RTLD_DEFAULT, "responsibility_get_pid_responsible_for_pid"));
  const pid_t responsible = responsible_fn ? responsible_fn(getpid()) : getpid();
  if (responsible > 0 && responsible != getpid()) {
    bundle = nil;
    char path[PROC_PIDPATHINFO_MAXSIZE] = {};
    if (proc_pidpath(responsible, path, sizeof(path)) > 0) {
      for (NSString *dir = [NSString stringWithUTF8String:path]; dir.length > 1;
           dir = dir.stringByDeletingLastPathComponent) {
        if ([dir.pathExtension isEqualToString:@"app"]) {
          bundle = [NSBundle bundleWithPath:dir];
          break;
        }
      }
    }
  }
  id description = [bundle objectForInfoDictionaryKey:@"NSMicrophoneUsageDescription"];
  if (![description isKindOfClass:[NSString class]] || ![(NSString *)description length]) {
    return -2;
  }
  pending = true;
  [device requestAccessForMediaType:@"soun" completionHandler:^(BOOL) { pending = false; }];
  return 0;
}
