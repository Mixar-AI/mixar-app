/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** Private PCM capture for cloud dictation. No scene/RNA or network access. */
#include <Python.h>
#ifdef WITH_OPENAL
#  include <al.h>
#  include <alc.h>
#endif
#ifdef __APPLE__
extern "C" int Mixar_MicrophonePermission(bool request);
#endif

namespace blender {
#ifdef WITH_OPENAL
struct Capture {
  ALCdevice *device;
};
static constexpr const char *capsule_name = "mixar.microphone";

static void capture_free(PyObject *capsule)
{
  Capture *capture = static_cast<Capture *>(PyCapsule_GetPointer(capsule, capsule_name));
  if (capture) {
    if (capture->device) {
      alcCaptureStop(capture->device);
      alcCaptureCloseDevice(capture->device);
    }
    delete capture;
  }
}

static PyObject *capture_permission(PyObject *, PyObject *)
{
#  ifdef __APPLE__
  return PyLong_FromLong(Mixar_MicrophonePermission(true));
#  else
  return PyLong_FromLong(1);
#  endif
}

static PyObject *capture_open(PyObject *, PyObject *)
{
#  ifdef __APPLE__
  if (Mixar_MicrophonePermission(true) != 1) {
    PyErr_SetString(PyExc_RuntimeError, "Microphone permission is required");
    return nullptr;
  }
#  endif
  /* The driver converts the device's native format to mono PCM16 at 16 kHz. */
  ALCdevice *device = alcCaptureOpenDevice(nullptr, 16000, AL_FORMAT_MONO16, 32000);
  if (!device) {
    PyErr_SetString(PyExc_RuntimeError, "Microphone unavailable. Check input device and privacy settings.");
    return nullptr;
  }
  alcCaptureStart(device);
  if (alcGetError(device) != ALC_NO_ERROR) {
    alcCaptureCloseDevice(device);
    PyErr_SetString(PyExc_RuntimeError, "Microphone could not start");
    return nullptr;
  }
  Capture *capture = new Capture{device};
  PyObject *capsule = PyCapsule_New(capture, capsule_name, capture_free);
  if (!capsule) {
    alcCaptureStop(device);
    alcCaptureCloseDevice(device);
    delete capture;
  }
  return capsule;
}

static PyObject *capture_read_impl(PyObject *capsule, const bool stop)
{
  Capture *capture = static_cast<Capture *>(PyCapsule_GetPointer(capsule, capsule_name));
  if (!capture) {
    return nullptr;
  }
  if (!capture->device) {
    return PyBytes_FromStringAndSize(nullptr, 0);
  }
#ifndef __APPLE__
  if (stop) {
    alcCaptureStop(capture->device);
  }
#endif
  /* Apple's OpenAL reports the buffer capacity as ALC_CAPTURE_SAMPLES after
   * alcCaptureStop, rather than the unread count. Drain while still running
   * there; the close below stops immediately after this synchronous read. */
  ALCint samples = 0;
  alcGetIntegerv(capture->device, ALC_CAPTURE_SAMPLES, 1, &samples);
  if (samples >= 32000 || samples < 0 || alcGetError(capture->device) != ALC_NO_ERROR) {
    alcCaptureStop(capture->device);
    alcCaptureCloseDevice(capture->device);
    capture->device = nullptr;
    PyErr_SetString(PyExc_RuntimeError, "Microphone stalled or capture buffer overflowed");
    return nullptr;
  }
  PyObject *result = PyBytes_FromStringAndSize(nullptr, Py_ssize_t(samples) * 2);
  if (!result) {
    return nullptr;
  }
  if (samples) {
    alcCaptureSamples(capture->device, PyBytes_AS_STRING(result), samples);
  }
  const bool failed = alcGetError(capture->device) != ALC_NO_ERROR;
  if (stop || failed) {
    alcCaptureStop(capture->device);
    alcCaptureCloseDevice(capture->device);
    capture->device = nullptr;
  }
  if (failed) {
    Py_DECREF(result);
    PyErr_SetString(PyExc_RuntimeError, "Microphone disconnected");
    return nullptr;
  }
  return result;
}

static PyObject *capture_read(PyObject *, PyObject *capsule)
{
  return capture_read_impl(capsule, false);
}
static PyObject *capture_stop(PyObject *, PyObject *capsule)
{
  return capture_read_impl(capsule, true);
}

static PyObject *capture_permission_status(PyObject *, PyObject *)
{
#  ifdef __APPLE__
  return PyLong_FromLong(Mixar_MicrophonePermission(false));
#  else
  /* Windows desktop privacy/device availability is checked by capture_open. */
  return PyLong_FromLong(1);
#  endif
}

static PyMethodDef methods[] = {
    {"_mixar_capture_permission_status", capture_permission_status, METH_NOARGS,
     "Check permission without prompting or opening the microphone."},
    {"_mixar_capture_permission", capture_permission, METH_NOARGS, "Request microphone permission."},
    {"_mixar_capture_open", capture_open, METH_NOARGS, "Open default input: 16 kHz mono PCM16LE."},
    {"_mixar_capture_read", capture_read, METH_O, "Read available PCM without blocking."},
    {"_mixar_capture_stop", capture_stop, METH_O, "Stop, drain remaining PCM, and close."},
    {nullptr, nullptr, 0, nullptr},
};
#endif

void mixar_capture_register(PyObject *module)
{
#ifdef WITH_OPENAL
  PyModule_AddFunctions(module, methods);
#else
  (void)module;
#endif
}
}  // namespace blender
