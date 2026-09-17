# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

set(INC
  .
  ../include
  ../../makesrna

  # RNA_prototypes.hh
  ${CMAKE_BINARY_DIR}/source/blender/makesrna
)

set(INC_SYS
)

set(SRC
  mixar_audio_capture.cc
  mixar_audio_glyph.cc
  mixar_audio_state.cc
  mixar_audio_wav.cc
  miniaudio_impl.cc

  mixar_audio_intern.hh
  mixar_audio_miniaudio.hh
  extern/miniaudio.h
)

set(LIB
  PRIVATE bf::blenkernel
  PRIVATE bf::blenlib
  PRIVATE bf::dna
  PRIVATE bf::gpu
  PRIVATE bf::intern::guardedalloc
)

# miniaudio loads every backend at RUNTIME (dlopen / LoadLibrary), so there is
# nothing to link against on Windows or Linux — the app still starts on a
# machine with no audio stack. Apple is the exception: Core Audio is reached
# through frameworks that must be present at link time.
if(APPLE)
  list(APPEND LIB
    "-framework CoreAudio"
    "-framework CoreFoundation"
    "-framework AudioToolbox"
  )
elseif(UNIX)
  # dlopen for the ALSA/PulseAudio backends, pthreads for the device thread.
  list(APPEND LIB ${CMAKE_DL_LIBS} ${CMAKE_THREAD_LIBS_INIT})
endif()

blender_add_lib(bf_editor_mixar_audio "${SRC}" "${INC}" "${INC_SYS}" "${LIB}")

# Generated RNA headers — mixar_audio_state.cc reads the voice session's
# WindowManager mirror. This is a BUILD-ORDER dependency only; bf_rna must not
# list this library in its LIB or the two targets form a cycle. It reaches the
# final link through bf_editor_space_api like every other editor library.
add_dependencies(bf_editor_mixar_audio bf_rna)

# The vendored header is third-party code we do not own; holding it to
# Blender's warning settings would bury real warnings from our own files in
# thousands of lines we are never going to change.
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
  set_source_files_properties(miniaudio_impl.cc PROPERTIES COMPILE_FLAGS "-w")
elseif(MSVC)
  set_source_files_properties(miniaudio_impl.cc PROPERTIES COMPILE_FLAGS "/w")
endif()
