/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Mixar: voice input through Apple's Speech framework.
 *
 * The chat's Voice mode: the microphone feeds an SFSpeechRecognizer (on
 * device where the system supports it, so nothing leaves the machine and
 * the first words appear within a few hundred milliseconds), and every
 * partial transcription is QUEUED here as an event for the main thread to
 * pop (mixie_chat.voice_poll). Python owns the composer text; this file owns
 * nothing but the audio engine, the recognition task and the event queue.
 *
 * Runtime-loaded like the Vision helper (dlopen + NSClassFromString): no
 * Speech/AVFoundation class or constant symbol is named, so GHOST gains no
 * link-time dependency. Requires NSMicrophoneUsageDescription and
 * NSSpeechRecognitionUsageDescription in the app's Info.plist — without them
 * macOS terminates the process on first microphone access — and, under the
 * hardened runtime, the audio-input entitlement the release build already
 * carries. TCC reads those strings from the bundle of the process
 * RESPONSIBLE for us, which is only Mixar itself when Mixar was launched
 * from Finder or `open`; see `tcc_request_allowed` for the terminal case.
 *
 * GHOST is compiled without ARC: everything kept in a static is retained
 * explicitly and released when replaced; blocks retain what they capture
 * when dispatch copies them.
 */

#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#import <Speech/Speech.h>

#include <cstdint>
#include <cstring>
#include <deque>
#include <objc/message.h>
#include <dlfcn.h>
#include <libproc.h>
#include <mutex>
#include <string>
#include <unistd.h>

#if __has_feature(objc_arc)
#  define MIXAR_RETAIN(obj) (obj)
#  define MIXAR_RELEASE(obj) ((void)0)
#else
#  define MIXAR_RETAIN(obj) [(obj) retain]
#  define MIXAR_RELEASE(obj) [(obj) release]
#endif

namespace {

/* Event kinds — lockstep with VOICE_EVENT_* in space_mixie_chat/constants.py. */
enum SpeechEventKind {
  SPEECH_EVENT_NONE = 0,
  SPEECH_EVENT_LISTENING = 1, /* Engine running, recogniser attached. */
  SPEECH_EVENT_PARTIAL = 2,   /* text = best transcription so far. */
  SPEECH_EVENT_FINAL = 3,     /* text = the utterance's final transcription. */
  SPEECH_EVENT_STOPPED = 4,   /* Session over; no more events follow. */
  SPEECH_EVENT_ERROR = 5,     /* text = what went wrong. */
  SPEECH_EVENT_DENIED = 6,    /* text = "microphone" | "speech recognition". */
};

struct SpeechEvent {
  int kind;
  std::string text;
};

std::mutex g_events_mutex;
std::deque<SpeechEvent> g_events;
constexpr size_t EVENT_QUEUE_CAP = 128;

/* Session objects. Main thread only. */
SFSpeechRecognizer *g_recognizer = nil;
SFSpeechAudioBufferRecognitionRequest *g_request = nil;
SFSpeechRecognitionTask *g_task = nil;
AVAudioEngine *g_engine = nil;
bool g_listening = false;
/* Set by Mixar_SpeechStop so the task's closing error (no speech, cancelled)
 * is reported as a normal stop, not a failure. */
bool g_stopping = false;
/* Bumped per session; a task's completion for an older session is ignored. */
int g_session = 0;

void push_event(const int kind, const std::string &text)
{
  std::lock_guard<std::mutex> lock(g_events_mutex);
  g_events.push_back({kind, text});
  while (g_events.size() > EVENT_QUEUE_CAP) {
    g_events.pop_front();
  }
}

void push_event_ns(const int kind, NSString *text)
{
  const char *utf8 = (text != nil) ? text.UTF8String : nullptr;
  push_event(kind, utf8 ? utf8 : "");
}

bool speech_loaded()
{
  static bool tried = false;
  static bool loaded = false;
  if (!tried) {
    tried = true;
    void *speech = dlopen("/System/Library/Frameworks/Speech.framework/Speech", RTLD_LAZY);
    /* AVAudioEngine lives in AVFAudio (a separate framework since macOS 12,
     * inside AVFoundation before); AVCaptureDevice in AVFoundation. */
    void *avf = dlopen("/System/Library/Frameworks/AVFoundation.framework/AVFoundation", RTLD_LAZY);
    dlopen("/System/Library/Frameworks/AVFAudio.framework/AVFAudio", RTLD_LAZY);
    loaded = (speech != nullptr) && (avf != nullptr) &&
             (NSClassFromString(@"SFSpeechRecognizer") != nil) &&
             (NSClassFromString(@"SFSpeechAudioBufferRecognitionRequest") != nil) &&
             (NSClassFromString(@"AVAudioEngine") != nil);
  }
  return loaded;
}

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

/* Tear the audio side down. The recognition task is left to finish on its
 * own (endAudio makes it deliver the final transcription, then complete). */
void stop_audio()
{
  if (g_engine != nil) {
    [g_engine stop];
    [[g_engine inputNode] removeTapOnBus:0];
    MIXAR_RELEASE(g_engine);
    g_engine = nil;
  }
  if (g_request != nil) {
    [g_request endAudio];
  }
  g_listening = false;
}

void release_session()
{
  if (g_task != nil) {
    MIXAR_RELEASE(g_task);
    g_task = nil;
  }
  if (g_request != nil) {
    MIXAR_RELEASE(g_request);
    g_request = nil;
  }
  if (g_recognizer != nil) {
    MIXAR_RELEASE(g_recognizer);
    g_recognizer = nil;
  }
}

/* Main thread, permissions granted. */
bool start_now()
{
  if (g_listening) {
    return true;
  }
  release_session();
  g_stopping = false;
  const int session = ++g_session;

  Class recognizer_cls = NSClassFromString(@"SFSpeechRecognizer");
  SFSpeechRecognizer *recognizer = [[recognizer_cls alloc] init];
  if (recognizer == nil || !recognizer.isAvailable) {
    MIXAR_RELEASE(recognizer);
    push_event(SPEECH_EVENT_ERROR, "Speech recognition is not available for the system language");
    return false;
  }

  Class request_cls = NSClassFromString(@"SFSpeechAudioBufferRecognitionRequest");
  SFSpeechAudioBufferRecognitionRequest *request = [[request_cls alloc] init];
  request.shouldReportPartialResults = YES;
  /* On device when the system has the dictation assets: private, offline and
   * lowest latency. Otherwise Apple's server recogniser, which the user
   * consented to with the speech-recognition permission. */
  if ([recognizer respondsToSelector:@selector(supportsOnDeviceRecognition)] &&
      recognizer.supportsOnDeviceRecognition)
  {
    request.requiresOnDeviceRecognition = YES;
  }
  if (@available(macOS 13.0, *)) {
    request.addsPunctuation = YES;
  }

  Class engine_cls = NSClassFromString(@"AVAudioEngine");
  AVAudioEngine *engine = [[engine_cls alloc] init];
  AVAudioInputNode *input = engine.inputNode;
  AVAudioFormat *format = (input != nil) ? [input outputFormatForBus:0] : nil;
  if (format == nil || format.sampleRate <= 0.0 || format.channelCount == 0) {
    MIXAR_RELEASE(engine);
    MIXAR_RELEASE(request);
    MIXAR_RELEASE(recognizer);
    push_event(SPEECH_EVENT_ERROR, "No microphone input is available");
    return false;
  }

  [input installTapOnBus:0
              bufferSize:1024
                  format:format
                   block:^(AVAudioPCMBuffer *buffer, AVAudioTime * /*when*/) {
                     [request appendAudioPCMBuffer:buffer];
                   }];
  [engine prepare];
  NSError *error = nil;
  if (![engine startAndReturnError:&error]) {
    [input removeTapOnBus:0];
    MIXAR_RELEASE(engine);
    MIXAR_RELEASE(request);
    MIXAR_RELEASE(recognizer);
    push_event_ns(SPEECH_EVENT_ERROR,
                  error ? error.localizedDescription : @"The microphone could not be started");
    return false;
  }

  g_recognizer = recognizer;
  g_request = request;
  g_engine = engine;
  g_listening = true;

  SFSpeechRecognitionTask *task = [recognizer
      recognitionTaskWithRequest:request
                   resultHandler:^(SFSpeechRecognitionResult *result, NSError *task_error) {
                     if (result != nil) {
                       push_event_ns(result.isFinal ? SPEECH_EVENT_FINAL : SPEECH_EVENT_PARTIAL,
                                     result.bestTranscription.formattedString);
                     }
                     if (task_error != nil || (result != nil && result.isFinal)) {
                       NSString *why = (task_error != nil) ? task_error.localizedDescription : nil;
                       dispatch_async(dispatch_get_main_queue(), ^{
                         if (session != g_session) {
                           return; /* A later session replaced this one. */
                         }
                         const bool user_stopped = g_stopping;
                         stop_audio();
                         release_session();
                         /* The task's own closing error after a user stop
                          * ("no speech detected", cancelled) is not a
                          * failure of anything. */
                         if (why != nil && !user_stopped) {
                           push_event_ns(SPEECH_EVENT_ERROR, why);
                         }
                         push_event(SPEECH_EVENT_STOPPED, "");
                       });
                     }
                   }];
  g_task = MIXAR_RETAIN(task);
  push_event(SPEECH_EVENT_LISTENING, "");
  return true;
}

/* TCC attributes a permission REQUEST to the process responsible for us and
 * reads the usage description from THAT bundle's Info.plist. A Mixar launched
 * from a terminal (`make run` in Cursor, VS Code or Terminal.app) is the
 * terminal's responsibility, and none of them declares
 * NSSpeechRecognitionUsageDescription, so TCC answered the request by
 * SIGKILLing the client ("attempted to access privacy-sensitive data without
 * a usage description", 2026-09-05) although Mixar's own plist carries both
 * strings. A Mixar launched from Finder or `open` is its own responsibility.
 * Read the string the way TCC will, and refuse instead of asking. */
struct TccAttribution {
  NSBundle *bundle;   /* Whose Info.plist TCC reads; nil for a bare executable. */
  NSString *app_name; /* For the explanation. */
  bool self;          /* Mixar is its own responsible process. */
};

TccAttribution tcc_attribution()
{
  TccAttribution out = {[NSBundle mainBundle], @"Mixar", true};
  typedef pid_t (*ResponsibleFn)(pid_t);
  static const ResponsibleFn responsible_fn = (ResponsibleFn)dlsym(
      RTLD_DEFAULT, "responsibility_get_pid_responsible_for_pid");
  const pid_t me = getpid();
  const pid_t responsible = responsible_fn ? responsible_fn(me) : me;
  if (responsible <= 0 || responsible == me) {
    return out;
  }
  out.self = false;
  out.bundle = nil;
  out.app_name = @"the app that launched it";
  char path[PROC_PIDPATHINFO_MAXSIZE] = {0};
  if (proc_pidpath(responsible, path, sizeof(path)) <= 0) {
    return out;
  }
  NSString *exe = [NSString stringWithUTF8String:path];
  out.app_name = exe.lastPathComponent;
  for (NSString *dir = exe; dir.length > 1; dir = dir.stringByDeletingLastPathComponent) {
    if ([dir.pathExtension isEqualToString:@"app"]) {
      out.bundle = [NSBundle bundleWithPath:dir];
      NSString *name = [out.bundle objectForInfoDictionaryKey:@"CFBundleName"];
      out.app_name = name.length ? name : dir.lastPathComponent.stringByDeletingPathExtension;
      break;
    }
  }
  return out;
}

/* True when asking for the permission behind `usage_key` cannot get us killed.
 * Otherwise the explanation and STOPPED are queued and nothing is asked. */
bool tcc_request_allowed(NSString *usage_key, const char *permission)
{
  const TccAttribution who = tcc_attribution();
  id value = [who.bundle objectForInfoDictionaryKey:usage_key];
  if ([value isKindOfClass:[NSString class]] && [(NSString *)value length] > 0) {
    return true;
  }
  NSString *why;
  if (who.self) {
    why = [NSString stringWithFormat:@"this build's Info.plist has no %@, and macOS would "
                                     @"end Mixar for requesting %s access",
                                     usage_key,
                                     permission];
  }
  else {
    why = [NSString stringWithFormat:@"Mixar was launched from %@, so macOS asks %@ for the "
                                     @"%s permission text and it has none. Launch Mixar.app "
                                     @"from Finder (or with `open`) to use Voice",
                                     who.app_name,
                                     who.app_name,
                                     permission];
  }
  push_event_ns(SPEECH_EVENT_ERROR, why);
  push_event(SPEECH_EVENT_STOPPED, "");
  return false;
}

void request_microphone_then_start()
{
  Class device_cls = NSClassFromString(@"AVCaptureDevice");
  if (device_cls != nil) {
    /* @"soun" is the audio media type's raw value — the literal keeps this
     * file free of the framework's constant symbols (see the file comment). */
    const AVAuthorizationStatus mic = [device_cls authorizationStatusForMediaType:@"soun"];
    if (mic == AVAuthorizationStatusNotDetermined) {
      if (!tcc_request_allowed(@"NSMicrophoneUsageDescription", "microphone")) {
        return;
      }
      [device_cls requestAccessForMediaType:@"soun"
                          completionHandler:^(BOOL granted) {
                            dispatch_async(dispatch_get_main_queue(), ^{
                              if (granted) {
                                start_now();
                              }
                              else {
                                push_event(SPEECH_EVENT_DENIED, "microphone");
                                push_event(SPEECH_EVENT_STOPPED, "");
                              }
                            });
                          }];
      return;
    }
    if (mic != AVAuthorizationStatusAuthorized) {
      push_event(SPEECH_EVENT_DENIED, "microphone");
      push_event(SPEECH_EVENT_STOPPED, "");
      return;
    }
  }
  if (!start_now()) {
    push_event(SPEECH_EVENT_STOPPED, "");
  }
}

}  // namespace

extern "C" bool Mixar_SpeechAvailable(void)
{
  @autoreleasepool {
    return speech_loaded();
  }
}

extern "C" bool Mixar_SpeechIsListening(void)
{
  return g_listening;
}

/* Begin a session. Returns true when the session is running or a permission
 * prompt is pending (the outcome arrives as events); false when it cannot
 * start at all. */
extern "C" bool Mixar_SpeechStart(void)
{
  @autoreleasepool {
    if (!speech_loaded()) {
      return false;
    }
    if (g_listening) {
      return true;
    }
    Class recognizer_cls = NSClassFromString(@"SFSpeechRecognizer");
    /* Class methods through typed objc_msgSend casts: on an untyped `Class`
     * the compiler binds `authorizationStatus` to whichever framework declared
     * that selector first (AVFoundation's, with a different enum). */
    typedef SFSpeechRecognizerAuthorizationStatus (*AuthStatusFn)(Class, SEL);
    typedef void (*RequestAuthFn)(Class, SEL, void (^)(SFSpeechRecognizerAuthorizationStatus));
    const SFSpeechRecognizerAuthorizationStatus status = ((AuthStatusFn)objc_msgSend)(
        recognizer_cls, @selector(authorizationStatus));
    if (status == SFSpeechRecognizerAuthorizationStatusNotDetermined) {
      if (!tcc_request_allowed(@"NSSpeechRecognitionUsageDescription", "speech recognition")) {
        return false;
      }
      ((RequestAuthFn)objc_msgSend)(
          recognizer_cls,
          @selector(requestAuthorization:),
          ^(SFSpeechRecognizerAuthorizationStatus granted) {
            dispatch_async(dispatch_get_main_queue(), ^{
              if (granted == SFSpeechRecognizerAuthorizationStatusAuthorized) {
                request_microphone_then_start();
              }
              else {
                push_event(SPEECH_EVENT_DENIED, "speech recognition");
                push_event(SPEECH_EVENT_STOPPED, "");
              }
            });
          });
      return true;
    }
    if (status != SFSpeechRecognizerAuthorizationStatusAuthorized) {
      push_event(SPEECH_EVENT_DENIED, "speech recognition");
      push_event(SPEECH_EVENT_STOPPED, "");
      return false;
    }
    request_microphone_then_start();
    return true;
  }
}

/* End the session. The final transcription (if any) and STOPPED follow as
 * events once the recogniser has drained. */
extern "C" void Mixar_SpeechStop(void)
{
  @autoreleasepool {
    if (!g_listening) {
      return;
    }
    g_stopping = true;
    stop_audio();
    if (g_task == nil) {
      release_session();
      push_event(SPEECH_EVENT_STOPPED, "");
    }
  }
}

extern "C" bool Mixar_SpeechPopEvent(int *r_kind, char *r_text, const int text_maxlen)
{
  std::lock_guard<std::mutex> lock(g_events_mutex);
  if (g_events.empty()) {
    return false;
  }
  const SpeechEvent &event = g_events.front();
  if (r_kind) {
    *r_kind = event.kind;
  }
  copy_utf8_truncated(event.text, r_text, text_maxlen);
  g_events.pop_front();
  return true;
}
