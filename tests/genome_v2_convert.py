#!/usr/bin/env python3
"""Atomic converter integration checks (Linux, c++ for a syscall fault shim).

After native-serial builds:
  nice -n 19 python3 tests/genome_v2_convert.py build_serial/genome_v2_convert build_serial/evo_boids
All artifacts live in an independent temporary directory; no network/browser.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

converter, engine = (str(Path(p).resolve()) for p in sys.argv[1:])
with tempfile.TemporaryDirectory(prefix='genome_v2_convert.') as work:
    work = Path(work)
    source = work / 'source.json'
    subprocess.run([engine, '--no-render', '--headless', '1', '--population', '3',
                    '--min-pop', '0', '--seed', '42', '--name', 'atomic',
                    '--save-checkpoint', str(source)], cwd=work, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    original = source.read_bytes()
    # Real converter, injected syscall failures. Match the temp descriptor via
    # /proc so runtime/loader I/O remains untouched. The close fault closes the
    # real fd first, reproducing a deferred write error reported at close.
    shim = work / 'fault.cpp'
    shim.write_text(r'''
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <cstdio>
#include <dlfcn.h>
#include <unistd.h>
bool temporary(int fd) {
    char path[64], target[4096];
    std::snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
    const auto n = readlink(path, target, sizeof target - 1);
    if (n < 0) return false;
    target[n] = 0;
    return std::strstr(target, "/.genome_v2_convert.");
}
extern "C" ssize_t write(int fd, const void* data, size_t size) {
    const auto real = reinterpret_cast<ssize_t(*)(int,const void*,size_t)>(dlsym(RTLD_NEXT,"write"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && temporary(fd)) {
        static int calls = 0;
        ++calls;
        if (!std::strcmp(mode,"write")) {
            if (calls == 1) return real(fd,data,size > 7 ? 7 : size);
            errno = ENOSPC; return -1;
        }
        if (!std::strcmp(mode,"short")) {
            if (calls == 1) { errno = EINTR; return -1; }
            if (size > 71) size = 71;
        }
    }
    return real(fd,data,size);
}
extern "C" int close(int fd) {
    const auto real = reinterpret_cast<int(*)(int)>(dlsym(RTLD_NEXT,"close"));
    const char* mode = std::getenv("CONVERT_FAULT");
    const bool fail = mode && !std::strcmp(mode,"close") && temporary(fd);
    const int result = real(fd);
    if (fail) { errno = EIO; return -1; }
    return result;
}
extern "C" int link(const char* source, const char* destination) noexcept {
    const auto real = reinterpret_cast<int(*)(const char*,const char*)>(dlsym(RTLD_NEXT,"link"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && !std::strcmp(mode,"race")) {
        // A competing publisher wins after the converter's initial check.
        const auto competitor = std::fopen(destination,"wx");
        if (!competitor) std::abort();
        std::fputs("competitor",competitor);
        std::fclose(competitor);
    }
    return real(source,destination);
}
''')
    library = work / 'fault.so'
    subprocess.run(['c++', '-std=c++20', '-shared', '-fPIC', str(shim), '-ldl', '-o', str(library)], check=True)
    def run(output, fault=None, expected=0):
        env = dict(os.environ)
        if fault:
            env.update(LD_PRELOAD=str(library), CONVERT_FAULT=fault)
        p = subprocess.run([converter, str(source), str(output), 'a'*64, '1'], env=env, capture_output=True)
        assert p.returncode == expected, (fault, p.returncode, p.stderr)
        assert source.read_bytes() == original
        assert not list(work.glob('.genome_v2_convert.*')), 'temporary output leaked'
    destination = work / 'converted.json'
    run(destination)
    converted = destination.read_bytes()
    parsed = json.loads(converted)
    assert parsed['config']['genomeVersion'] == 2
    run(destination, expected=2)
    assert destination.read_bytes() == converted
    run(source, expected=2)
    for fault in ['write', 'close']:
        output = work / (fault+'.json')
        run(output, fault, 1)
        assert not output.exists(), 'failed conversion published partial output'
        run(output)  # Failure leaves the requested name available for retry.
        assert output.read_bytes() == converted
    output = work / 'short.json'
    run(output, 'short')
    assert output.read_bytes() == converted
    output = work / 'race.json'
    run(output, 'race', 1)
    assert output.read_bytes() == b'competitor'
    output = work / 'dangling.json'
    output.symlink_to('missing.json')
    run(output, expected=1)
    assert output.is_symlink() and os.readlink(output) == 'missing.json'
print('PASS atomic converter: success, short writes/EINTR, write/close failures, no-clobber race, symlink, cleanup and source identity')
