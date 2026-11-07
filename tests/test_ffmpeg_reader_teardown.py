# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute the actual destructor against a checked FFmpeg ownership model.

No FFmpeg development libraries are needed. This checks cleanup lifetime/order,
not decoder correctness; the real packed-media replay covers integration.
"""
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
REL = Path('extern/audaspace/plugins/ffmpeg/FFMPEGReader.cpp')


def destructor(text):
    start = text.index('FFMPEGReader::~FFMPEGReader()')
    return text[start:text.index('\nstd::vector<StreamInfo>', start)]


MODEL = r'''
#include <cassert>
#include <cstdlib>
#include <memory>
#include <set>
static std::set<void *> live;
static int closes = 0;
struct AVIOContext { void *buffer; };
struct AVFormatContext { AVIOContext *pb; void *codec; };
static void *alloc() { auto p = std::malloc(1); live.insert(p); return p; }
static void av_free(void *p) {
    if (!p) return;
    assert(live.erase(p) == 1);
    std::free(p);
}
static void av_freep(void **p) { av_free(*p); *p = nullptr; }
static void av_frame_free(void **p) { av_freep(p); }
static void avcodec_free_context(void **p) { av_freep(p); }
static void avcodec_close(void *p) { assert(live.count(p)); }
static void avio_context_free(AVIOContext **p) {
    assert(live.erase(*p) == 1);
    std::free(*p); *p = nullptr;
}
static void avformat_close_input(AVFormatContext **p) {
    assert(*p);
    if ((*p)->pb) {
        // FFmpeg's close path may inspect the custom pb, even though it
        // does not own it. Check BEFORE dereferencing to avoid test UB.
        assert(live.count((*p)->pb));
        assert(live.count((*p)->pb->buffer));
    }
#ifdef FFMPEG_OLD_CODE
    av_free((*p)->codec); // Legacy codec context belongs to the format.
#endif
    delete *p; *p = nullptr; ++closes;
}
class FFMPEGReader {
public:
    void *m_frame = alloc(), *m_codecCtx = alloc();
    AVIOContext *m_aviocontext = nullptr;
    AVFormatContext *m_formatCtx;
    explicit FFMPEGReader(bool memory) {
        if (memory) {
            m_aviocontext = static_cast<AVIOContext *>(std::malloc(sizeof(AVIOContext)));
            m_aviocontext->buffer = alloc();
            live.insert(m_aviocontext);
        }
        m_formatCtx = new AVFormatContext{m_aviocontext, m_codecCtx};
    }
    ~FFMPEGReader();
};
DESTRUCTOR
struct EffectReader { std::shared_ptr<FFMPEGReader> reader; };
int main(int argc, char **) {
    auto reader = std::make_shared<FFMPEGReader>(argc > 1);
    {
        EffectReader effect{reader};
        reader.reset();
        assert(closes == 0); // The effect is now the last owner.
    }
    assert(closes == 1);
    assert(live.empty());
}
'''


@pytest.mark.parametrize('legacy', [False, True])
def test_reader_teardown_keeps_custom_io_alive(tmp_path, legacy):
    compiler = shutil.which('c++')
    if not compiler:
        pytest.skip('C++ compiler unavailable')
    source = tmp_path / 'reader.cc'
    source.write_text(MODEL.replace('DESTRUCTOR', destructor((ROOT / 'src' / REL).read_text())))
    binary = tmp_path / 'reader'
    flags = ['-DFFMPEG_OLD_CODE'] if legacy else []
    subprocess.run([compiler, '-std=c++11', *flags, str(source), '-o', str(binary)], check=True)
    for args in ([], ['memory']):
        subprocess.run([str(binary), *args], check=True)


def test_overlay_changes_only_destructor():
    upstream = (ROOT / 'upstream' / REL).read_text()
    overlay = (ROOT / 'src' / REL).read_text()
    assert upstream.replace(destructor(upstream), '') == overlay.replace(destructor(overlay), '')
