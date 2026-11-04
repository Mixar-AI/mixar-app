/* SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-3.0-or-later */

/** \file
 * \ingroup creator
 *
 * See mixar_crash_info.h. Self-contained (system headers only) so the writer
 * can also be compiled into a small test program.
 */

#include "mixar_crash_info.h"

#include <cinttypes>
#include <cstdint>
#include <cstring>

#if defined(__has_include)
#  if __has_include("mixar_env_config.h")
#    include "mixar_env_config.h" /* MIXAR_APP_VERSION, MIXAR_GIT_SHA (generated). */
#  endif
#endif
#ifndef MIXAR_APP_VERSION
#  define MIXAR_APP_VERSION "unknown"
#endif
#ifndef MIXAR_GIT_SHA
#  define MIXAR_GIT_SHA "unknown"
#endif

#if defined(__APPLE__)
#  include <dlfcn.h>
#  include <execinfo.h>
#  include <mach-o/loader.h>
#elif defined(__linux__)
#  ifndef _GNU_SOURCE
#    define _GNU_SOURCE
#  endif
#  include <dlfcn.h>
#  include <elf.h>
#  include <execinfo.h>
#  include <link.h>
#elif defined(_WIN32)
#  include <windows.h>
#endif

namespace {

constexpr int MAX_FRAMES = 64;
constexpr int MAX_IMAGES = 32;

struct CrashImage {
  uint64_t base;   /* Load address of the image (its first byte in memory). */
  uint64_t vmaddr; /* The image's own (link-time) address for `base`. */
  uint64_t size;
  char id[80];     /* Debug id, lower-case hex, "" when unknown. */
  char name[128];  /* File name only. */
};

const char *path_basename(const char *path)
{
  const char *name = path;
  for (const char *c = path; *c; c++) {
    if (*c == '/' || *c == '\\') {
      name = c + 1;
    }
  }
  return name;
}

void copy_name(char *dst, size_t dst_len, const char *path)
{
  if (path == nullptr) {
    dst[0] = '\0';
    return;
  }
  const char *name = path_basename(path);
  size_t len = strlen(name);
  if (len >= dst_len) {
    len = dst_len - 1;
  }
  memcpy(dst, name, len);
  dst[len] = '\0';
}

void hex_bytes(char *dst, size_t dst_len, const uint8_t *bytes, size_t count)
{
  static const char digits[] = "0123456789abcdef";
  size_t out = 0;
  for (size_t i = 0; i < count && out + 2 < dst_len; i++) {
    dst[out++] = digits[bytes[i] >> 4];
    dst[out++] = digits[bytes[i] & 0xf];
  }
  dst[out] = '\0';
}

const char *arch_name()
{
#if defined(__aarch64__) || defined(_M_ARM64)
  return "arm64";
#elif defined(__x86_64__) || defined(_M_X64)
  return "x86_64";
#else
  return "unknown";
#endif
}

#if defined(__APPLE__)

bool image_for_address(uint64_t address, CrashImage *r_image)
{
  Dl_info info;
  if (!dladdr(reinterpret_cast<const void *>(address), &info) || info.dli_fbase == nullptr) {
    return false;
  }
  const mach_header_64 *header = static_cast<const mach_header_64 *>(info.dli_fbase);
  if (header->magic != MH_MAGIC_64) {
    return false;
  }
  r_image->base = uint64_t(uintptr_t(info.dli_fbase));
  copy_name(r_image->name, sizeof(r_image->name), info.dli_fname);
  const load_command *command = reinterpret_cast<const load_command *>(header + 1);
  for (uint32_t i = 0; i < header->ncmds; i++) {
    if (command->cmd == LC_UUID) {
      const uuid_command *uuid = reinterpret_cast<const uuid_command *>(command);
      hex_bytes(r_image->id, sizeof(r_image->id), uuid->uuid, sizeof(uuid->uuid));
    }
    else if (command->cmd == LC_SEGMENT_64) {
      const segment_command_64 *segment = reinterpret_cast<const segment_command_64 *>(command);
      if (strncmp(segment->segname, "__TEXT", sizeof(segment->segname)) == 0) {
        r_image->vmaddr = segment->vmaddr;
        r_image->size = segment->vmsize;
      }
    }
    command = reinterpret_cast<const load_command *>(reinterpret_cast<const char *>(command) +
                                                     command->cmdsize);
  }
  return true;
}

int collect_frames(const void * /*os_info*/, uint64_t *r_frames)
{
  void *buffer[MAX_FRAMES];
  const int count = backtrace(buffer, MAX_FRAMES);
  for (int i = 0; i < count; i++) {
    r_frames[i] = uint64_t(uintptr_t(buffer[i]));
  }
  return count;
}

#elif defined(__linux__)

struct PhdrLookup {
  uint64_t address;
  CrashImage *image;
  bool found;
};

void elf_build_id(const dl_phdr_info *info, const ElfW(Phdr) *phdr, CrashImage *r_image)
{
  const char *note = reinterpret_cast<const char *>(info->dlpi_addr + phdr->p_vaddr);
  const char *end = note + phdr->p_memsz;
  while (note + sizeof(ElfW(Nhdr)) <= end) {
    const ElfW(Nhdr) *header = reinterpret_cast<const ElfW(Nhdr) *>(note);
    const char *name = note + sizeof(ElfW(Nhdr));
    const char *desc = name + ((header->n_namesz + 3) & ~3u);
    if (desc + header->n_descsz > end) {
      return;
    }
    if (header->n_type == NT_GNU_BUILD_ID && header->n_namesz == 4 && memcmp(name, "GNU", 4) == 0) {
      hex_bytes(r_image->id,
                sizeof(r_image->id),
                reinterpret_cast<const uint8_t *>(desc),
                header->n_descsz);
      return;
    }
    note = desc + ((header->n_descsz + 3) & ~3u);
  }
}

int phdr_callback(dl_phdr_info *info, size_t /*size*/, void *data)
{
  PhdrLookup *lookup = static_cast<PhdrLookup *>(data);
  bool hit = false;
  uint64_t end = 0;
  for (int i = 0; i < info->dlpi_phnum; i++) {
    const ElfW(Phdr) *phdr = &info->dlpi_phdr[i];
    if (phdr->p_type != PT_LOAD) {
      continue;
    }
    const uint64_t start = info->dlpi_addr + phdr->p_vaddr;
    if (lookup->address >= start && lookup->address < start + phdr->p_memsz) {
      hit = true;
    }
    if (phdr->p_vaddr + phdr->p_memsz > end) {
      end = phdr->p_vaddr + phdr->p_memsz;
    }
  }
  if (!hit) {
    return 0;
  }
  CrashImage *image = lookup->image;
  /* The image's own addresses are `address - dlpi_addr`. */
  image->base = info->dlpi_addr;
  image->vmaddr = 0;
  image->size = end;
  for (int i = 0; i < info->dlpi_phnum; i++) {
    if (info->dlpi_phdr[i].p_type == PT_NOTE) {
      elf_build_id(info, &info->dlpi_phdr[i], image);
      if (image->id[0]) {
        break;
      }
    }
  }
  lookup->found = true;
  return 1;
}

bool image_for_address(uint64_t address, CrashImage *r_image)
{
  PhdrLookup lookup = {address, r_image, false};
  dl_iterate_phdr(phdr_callback, &lookup);
  if (!lookup.found) {
    return false;
  }
  Dl_info info;
  if (dladdr(reinterpret_cast<const void *>(address), &info) && info.dli_fname) {
    copy_name(r_image->name, sizeof(r_image->name), info.dli_fname);
  }
  return true;
}

int collect_frames(const void * /*os_info*/, uint64_t *r_frames)
{
  void *buffer[MAX_FRAMES];
  const int count = backtrace(buffer, MAX_FRAMES);
  for (int i = 0; i < count; i++) {
    r_frames[i] = uint64_t(uintptr_t(buffer[i]));
  }
  return count;
}

#elif defined(_WIN32)

bool image_for_address(uint64_t address, CrashImage *r_image)
{
  HMODULE module = nullptr;
  if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                              GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                          reinterpret_cast<LPCSTR>(address),
                          &module))
  {
    return false;
  }
  const uint8_t *base = reinterpret_cast<const uint8_t *>(module);
  const IMAGE_DOS_HEADER *dos = reinterpret_cast<const IMAGE_DOS_HEADER *>(base);
  if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
    return false;
  }
  const IMAGE_NT_HEADERS *nt = reinterpret_cast<const IMAGE_NT_HEADERS *>(base + dos->e_lfanew);
  if (nt->Signature != IMAGE_NT_SIGNATURE) {
    return false;
  }
  r_image->base = uint64_t(uintptr_t(base));
  r_image->vmaddr = uint64_t(nt->OptionalHeader.ImageBase);
  r_image->size = nt->OptionalHeader.SizeOfImage;
  char path[MAX_PATH];
  if (GetModuleFileNameA(module, path, MAX_PATH)) {
    copy_name(r_image->name, sizeof(r_image->name), path);
  }
  const IMAGE_DATA_DIRECTORY &directory =
      nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_DEBUG];
  const IMAGE_DEBUG_DIRECTORY *entries = reinterpret_cast<const IMAGE_DEBUG_DIRECTORY *>(
      base + directory.VirtualAddress);
  const DWORD count = directory.Size / sizeof(IMAGE_DEBUG_DIRECTORY);
  for (DWORD i = 0; directory.VirtualAddress && i < count; i++) {
    if (entries[i].Type != IMAGE_DEBUG_TYPE_CODEVIEW || entries[i].AddressOfRawData == 0) {
      continue;
    }
    const uint8_t *codeview = base + entries[i].AddressOfRawData;
    if (memcmp(codeview, "RSDS", 4) != 0) {
      continue;
    }
    GUID guid;
    DWORD age;
    memcpy(&guid, codeview + 4, sizeof(guid));
    memcpy(&age, codeview + 20, sizeof(age));
    /* The symbol-server key: GUID fields as printed in a GUID string, then the age. */
    snprintf(r_image->id,
             sizeof(r_image->id),
             "%08lx%04x%04x%02x%02x%02x%02x%02x%02x%02x%02x%lx",
             (unsigned long)guid.Data1,
             guid.Data2,
             guid.Data3,
             guid.Data4[0],
             guid.Data4[1],
             guid.Data4[2],
             guid.Data4[3],
             guid.Data4[4],
             guid.Data4[5],
             guid.Data4[6],
             guid.Data4[7],
             (unsigned long)age);
    break;
  }
  return true;
}

/* Walk the faulting thread from the exception context with the x64 / ARM64
 * unwind tables. A corrupt stack can fault while unwinding: the walk stops
 * there and keeps what it has. */
int walk_context(CONTEXT context, uint64_t *r_frames)
{
  int count = 0;
  __try {
    while (count < MAX_FRAMES) {
#  if defined(_M_X64)
      const DWORD64 pc = context.Rip;
#  elif defined(_M_ARM64)
      const DWORD64 pc = context.Pc;
#  else
      const DWORD64 pc = 0;
#  endif
      if (pc == 0 || (count > 0 && r_frames[count - 1] == pc)) {
        break;
      }
      r_frames[count++] = pc;
      DWORD64 image_base = 0;
      PRUNTIME_FUNCTION function = RtlLookupFunctionEntry(pc, &image_base, nullptr);
      if (function == nullptr) {
        /* A leaf function: the return address is where the stack (x64) or
         * the link register (ARM64) says. */
#  if defined(_M_X64)
        context.Rip = *reinterpret_cast<const DWORD64 *>(context.Rsp);
        context.Rsp += 8;
#  elif defined(_M_ARM64)
        context.Pc = context.Lr;
#  endif
      }
      else {
        PVOID handler_data = nullptr;
        DWORD64 establisher_frame = 0;
        RtlVirtualUnwind(UNW_FLAG_NHANDLER,
                         image_base,
                         pc,
                         function,
                         &context,
                         &handler_data,
                         &establisher_frame,
                         nullptr);
      }
    }
  }
  __except (EXCEPTION_EXECUTE_HANDLER) {
  }
  return count;
}

int collect_frames(const void *os_info, uint64_t *r_frames)
{
  const EXCEPTION_POINTERS *exception = static_cast<const EXCEPTION_POINTERS *>(os_info);
  if (exception != nullptr && exception->ContextRecord != nullptr) {
    return walk_context(*exception->ContextRecord, r_frames);
  }
  void *buffer[MAX_FRAMES];
  const USHORT count = CaptureStackBackTrace(0, MAX_FRAMES, buffer, nullptr);
  for (USHORT i = 0; i < count; i++) {
    r_frames[i] = uint64_t(uintptr_t(buffer[i]));
  }
  return count;
}

#else

bool image_for_address(uint64_t /*address*/, CrashImage * /*r_image*/)
{
  return false;
}

int collect_frames(const void * /*os_info*/, uint64_t * /*r_frames*/)
{
  return 0;
}

#endif

int find_image(const CrashImage *images, int count, uint64_t address)
{
  for (int i = 0; i < count; i++) {
    if (address >= images[i].base && address < images[i].base + images[i].size) {
      return i;
    }
  }
  return -1;
}

}  // namespace

void mixar_crash_info_write(FILE *fp, const void *os_info)
{
  uint64_t frames[MAX_FRAMES];
  const int frame_count = collect_frames(os_info, frames);

  CrashImage images[MAX_IMAGES];
  memset(images, 0, sizeof(images));
  int image_count = 0;
  for (int i = 0; i < frame_count && image_count < MAX_IMAGES; i++) {
    if (find_image(images, image_count, frames[i]) != -1) {
      continue;
    }
    if (image_for_address(frames[i], &images[image_count])) {
      image_count++;
    }
  }

  fputs("\n# mixar symbolication v1\n", fp);
  fprintf(fp, "mixar_version %s\n", MIXAR_APP_VERSION);
  fprintf(fp, "git_sha %s\n", MIXAR_GIT_SHA);
  fprintf(fp, "arch %s\n", arch_name());
  for (int i = 0; i < image_count; i++) {
    fprintf(fp,
            "image base=0x%" PRIx64 " vmaddr=0x%" PRIx64 " size=0x%" PRIx64 " id=%s name=%s\n",
            images[i].base,
            images[i].vmaddr,
            images[i].size,
            images[i].id[0] ? images[i].id : "-",
            images[i].name[0] ? images[i].name : "-");
  }
  for (int i = 0; i < frame_count; i++) {
    fprintf(fp, "frame %d 0x%016" PRIx64 "\n", i, frames[i]);
  }
  fputs("\n", fp);
}
