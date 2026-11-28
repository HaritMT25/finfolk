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
#include <fcntl.h>
#include <sys/stat.h>
bool temporary(int fd) {
    char path[64], target[4096];
    std::snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
    const auto n = readlink(path, target, sizeof target - 1);
    if (n < 0) return false;
    target[n] = 0;
    return std::strstr(target, "/.genome_v2_convert.");
}
bool direct(int fd) {
    char path[64], target[4096];
    std::snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
    const auto n = readlink(path, target, sizeof target - 1);
    if (n < 0) return false;
    target[n] = 0;
    const char* output = std::getenv("CONVERT_OUTPUT");
    return output && !std::strcmp(target, output);
}
void trace(const char* message) {
    if (const char* path = std::getenv("CONVERT_TRACE")) {
        auto file = std::fopen(path, "a");
        if (!file) std::abort();
        std::fputs(message, file); std::fclose(file);
    }
}
extern "C" ssize_t write(int fd, const void* data, size_t size) {
    const auto real = reinterpret_cast<ssize_t(*)(int,const void*,size_t)>(dlsym(RTLD_NEXT,"write"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && (temporary(fd) || direct(fd))) {
        static int temporaryCalls = 0, directCalls = 0;
        const int calls = temporary(fd) ? ++temporaryCalls : ++directCalls;
        if (!std::strcmp(mode,"write") || (!std::strcmp(mode,"fallback_write") && direct(fd))) {
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
    const bool fail = mode && ((!std::strcmp(mode,"close") && temporary(fd)) || (!std::strcmp(mode,"fallback_close") && direct(fd)));
    const int result = real(fd);
    if (fail) { errno = EIO; return -1; }
    return result;
}
extern "C" int link(const char* source, const char* destination) noexcept {
    const auto real = reinterpret_cast<int(*)(const char*,const char*)>(dlsym(RTLD_NEXT,"link"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && (!std::strcmp(mode,"race") || !std::strcmp(mode,"fallback_race"))) {
        // A competing publisher wins after the converter's initial check.
        const auto competitor = std::fopen(destination,"wx");
        if (!competitor) std::abort();
        std::fputs("competitor",competitor);
        std::fclose(competitor);
    }
    if (mode && !std::strncmp(mode,"fallback",8)) {
        errno = !std::strcmp(mode,"fallback_exdev") ? EXDEV : !std::strcmp(mode,"fallback_enotsup") ? ENOTSUP : EPERM;
        return -1;
    }
    return real(source,destination);
}
extern "C" int fsync(int fd) {
    const auto real = reinterpret_cast<int(*)(int)>(dlsym(RTLD_NEXT,"fsync"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (temporary(fd) || direct(fd)) {
        trace("file fsync\n");
        if (mode && (!std::strcmp(mode,"fsync") || (!std::strcmp(mode,"fallback_fsync") && direct(fd)))) { errno = EIO; return -1; }
    } else {
        struct stat info{};
        if (fstat(fd, &info) == 0 && S_ISDIR(info.st_mode)) trace("directory fsync\n");
    }
    return real(fd);
}
extern "C" int unlink(const char* path) noexcept {
    const auto real = reinterpret_cast<int(*)(const char*)>(dlsym(RTLD_NEXT,"unlink"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && !std::strcmp(mode,"unlink") && std::strstr(path,"/.genome_v2_convert.")) { errno = EPERM; return -1; }
    return real(path);
}
''')
    library = work / 'fault.so'
    subprocess.run(['c++', '-std=c++20', '-shared', '-fPIC', str(shim), '-ldl', '-o', str(library)], check=True)
    def run(output, fault=None, expected=0):
        env = dict(os.environ)
        if fault:
            env.update(LD_PRELOAD=str(library), CONVERT_FAULT=fault, CONVERT_OUTPUT=str(output), CONVERT_TRACE=str(work / "trace"))
        p = subprocess.run([converter, str(source), str(output), 'a'*64, '1'], env=env, capture_output=True, umask=0o027)
        assert p.returncode == expected, (fault, p.returncode, p.stderr)
        assert source.read_bytes() == original
        leaked = list(work.glob('.genome_v2_convert.*'))
        if fault == 'unlink':
            assert leaked and b'warning: could not remove temporary checkpoint' in p.stderr
            for path in leaked: path.unlink()
        else:
            assert not leaked, 'temporary output leaked'
        return p
    destination = work / 'converted.json'
    run(destination)
    converted = destination.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o640, 'respects umask'
    parsed = json.loads(converted)
    assert parsed['config']['genomeVersion'] == 2
    run(destination, expected=2)
    assert destination.read_bytes() == converted
    run(source, expected=2)
    for fault in ['write', 'close', 'fsync', 'fallback_write', 'fallback_close', 'fallback_fsync']:
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
    for fault in ['fallback', 'fallback_exdev', 'fallback_enotsup', 'unlink']:
        output = work / (fault + '.json')
        (work / 'trace').write_text('')
        run(output, fault)
        assert output.read_bytes() == converted
        assert output.stat().st_mode & 0o777 == 0o640
        events = (work / 'trace').read_text().splitlines()
        assert events and events[-1] == 'directory fsync' and 'file fsync' in events
    output = work / 'fallback_race.json'
    run(output, 'fallback_race', 1)
    assert output.read_bytes() == b'competitor'
    output = work / 'dangling.json'
    output.symlink_to('missing.json')
    run(output, expected=1)
    run(output, 'fallback', expected=1)
    assert output.is_symlink() and os.readlink(output) == 'missing.json'
print('PASS atomic converter (permissions, durability, fallback, cleanup warning): success, short writes/EINTR, write/close failures, no-clobber race, symlink, cleanup and source identity')
