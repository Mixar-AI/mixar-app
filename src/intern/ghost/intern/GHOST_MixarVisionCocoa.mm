/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Mixar: on-device handwriting recognition through Apple's Vision framework.
 *
 * Scribble's instant path. The backend transcriber is a vision LLM with a
 * 1-6 s round trip; Vision's text recogniser reads a small stroke image in
 * ~100-300 ms on Apple silicon, offline. The chat's C++ operator hands over a
 * PNG path and a job id (mixie_chat.ink_recognize_local); recognition runs
 * on a background queue and the result is QUEUED here for the main thread to
 * pop (mixie_chat.ink_local_poll) — nothing ever calls into Blender off the
 * main thread, and Python decides whether a result is good enough or the
 * batch goes to the backend after all.
 *
 * Vision is loaded at RUNTIME (dlopen + NSClassFromString): this file names
 * no Vision class or constant symbol, so GHOST gains no link-time framework
 * dependency and the build files stay untouched. On a system without the
 * framework (or one where it fails to load) `Mixar_VisionAvailable` is simply
 * false and Scribble keeps its backend path.
 */

#import <Foundation/Foundation.h>
#import <Vision/Vision.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <deque>
#include <dlfcn.h>
#include <mutex>
#include <string>

namespace {

struct VisionResult {
  int job_id;
  std::string text;
  float confidence;
  bool ok;
};

std::mutex g_results_mutex;
std::deque<VisionResult> g_results;

/* Results nobody popped (a Python side that went away mid-batch) must not
 * accumulate for the rest of the session. */
constexpr size_t RESULT_QUEUE_CAP = 64;

bool vision_loaded()
{
  static bool tried = false;
  static bool loaded = false;
  if (!tried) {
    tried = true;
    void *handle = dlopen("/System/Library/Frameworks/Vision.framework/Vision", RTLD_LAZY);
    loaded = (handle != nullptr) && (NSClassFromString(@"VNRecognizeTextRequest") != nil) &&
             (NSClassFromString(@"VNImageRequestHandler") != nil);
  }
  return loaded;
}

void push_result(const int job_id, std::string text, const float confidence, const bool ok)
{
  std::lock_guard<std::mutex> lock(g_results_mutex);
  g_results.push_back({job_id, std::move(text), confidence, ok});
  while (g_results.size() > RESULT_QUEUE_CAP) {
    g_results.pop_front();
  }
}

/* Copy UTF-8 into a fixed buffer without cutting a multi-byte sequence in
 * half — the text crosses into an RNA string property afterwards. */
void copy_utf8_truncated(const std::string &src, char *dst, const int maxlen)
{
  if (dst == nullptr || maxlen <= 0) {
    return;
  }
  size_t n = src.size();
  if (n > size_t(maxlen - 1)) {
    n = size_t(maxlen - 1);
    while (n > 0 && (uint8_t(src[n]) & 0xC0) == 0x80) {
      n--;
    }
  }
  memcpy(dst, src.data(), n);
  dst[n] = '\0';
}

}  // namespace

extern "C" bool Mixar_VisionAvailable(void)
{
  @autoreleasepool {
    return vision_loaded();
  }
}

extern "C" bool Mixar_VisionRecognizeFile(const int job_id, const char *png_path)
{
  if (png_path == nullptr || png_path[0] == '\0') {
    return false;
  }
  @autoreleasepool {
    if (!vision_loaded()) {
      return false;
    }
    NSString *path = [NSString stringWithUTF8String:png_path];
    if (path == nil) {
      return false;
    }
    NSURL *url = [NSURL fileURLWithPath:path];

    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
      @autoreleasepool {
        Class handler_cls = NSClassFromString(@"VNImageRequestHandler");
        Class request_cls = NSClassFromString(@"VNRecognizeTextRequest");
        VNImageRequestHandler *handler = [[handler_cls alloc] initWithURL:url options:@{}];
        VNRecognizeTextRequest *request = [[request_cls alloc] initWithCompletionHandler:nil];
        if (handler == nil || request == nil) {
          push_result(job_id, "", 0.0f, false);
          return;
        }
        /* Accurate, not fast: fast is a line-level detector tuned for printed
         * text and reads handwriting badly; accurate still lands well under
         * the backend's floor on this input size. Language correction is
         * what joins a word's letters into that word — the same transcription
         * rule the backend prompt states. */
        request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
        request.usesLanguageCorrection = YES;
        if (@available(macOS 13.0, *)) {
          request.automaticallyDetectsLanguage = YES;
        }

        NSError *error = nil;
        const BOOL performed = [handler performRequests:@[ request ] error:&error];
        if (!performed) {
          const char *why = (error != nil) ? error.localizedDescription.UTF8String : "";
          push_result(job_id, why ? why : "", 0.0f, false);
          return;
        }

        /* Reading order: Vision's boxes are normalised with a bottom-left
         * origin, so the top line has the LARGEST y. Ties (one line) by x. */
        NSArray *observations = request.results;
        NSArray *ordered = [observations sortedArrayUsingComparator:^NSComparisonResult(id a, id b) {
          const CGRect ra = [a boundingBox];
          const CGRect rb = [b boundingBox];
          const CGFloat ya = CGRectGetMidY(ra);
          const CGFloat yb = CGRectGetMidY(rb);
          /* Same line when the vertical centres overlap within half a box. */
          const CGFloat tol = 0.5 * std::min(ra.size.height, rb.size.height);
          if (std::fabs(ya - yb) > tol) {
            return (ya > yb) ? NSOrderedAscending : NSOrderedDescending;
          }
          if (ra.origin.x < rb.origin.x) {
            return NSOrderedAscending;
          }
          if (ra.origin.x > rb.origin.x) {
            return NSOrderedDescending;
          }
          return NSOrderedSame;
        }];

        std::string text;
        float confidence_sum = 0.0f;
        int lines = 0;
        for (VNRecognizedTextObservation *obs in ordered) {
          NSArray<VNRecognizedText *> *candidates = [obs topCandidates:1];
          if (candidates.count == 0) {
            continue;
          }
          VNRecognizedText *best = candidates.firstObject;
          if (best.string.length == 0) {
            continue;
          }
          /* Wrapped handwriting joins with a space (the writing surface ran
           * out), matching the backend transcriber's rule. */
          if (!text.empty()) {
            text += " ";
          }
          const char *utf8 = best.string.UTF8String;
          text += utf8 ? utf8 : "";
          confidence_sum += float(best.confidence);
          lines++;
        }
        push_result(job_id, text, (lines > 0) ? confidence_sum / float(lines) : 0.0f, true);
      }
    });
    return true;
  }
}

extern "C" bool Mixar_VisionPopResult(
    int *r_job_id, char *r_text, const int text_maxlen, float *r_confidence, int *r_ok)
{
  std::lock_guard<std::mutex> lock(g_results_mutex);
  if (g_results.empty()) {
    return false;
  }
  const VisionResult &res = g_results.front();
  if (r_job_id) {
    *r_job_id = res.job_id;
  }
  copy_utf8_truncated(res.text, r_text, text_maxlen);
  if (r_confidence) {
    *r_confidence = res.confidence;
  }
  if (r_ok) {
    *r_ok = res.ok ? 1 : 0;
  }
  g_results.pop_front();
  return true;
}
