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
#include <cstdarg>
#include <string>
bool temporary(int fd) {
    char path[64], target[4096];
    std::snprintf(path, sizeof path, "/proc/self/fd/%d", fd);
    const auto n = readlink(path, target, sizeof target - 1);
    if (n < 0) return false;
    target[n] = 0;
    return std::strstr(target, "/.genome_v2_convert.");
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
    if (mode && temporary(fd)) {
        static int calls = 0;
        ++calls;
        if (!std::strcmp(mode,"write") || !std::strcmp(mode,"write_cleanup_race")) {
            if (calls == 1) return real(fd,data,size > 7 ? 7 : size);
            errno = ENOSPC; return -1;
        }
        if (!std::strcmp(mode,"interrupt")) {
            if (real(fd,data,size > 7 ? 7 : size) < 0) std::abort();
            _exit(77); // abrupt process exit after incomplete temporary write
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
    trace("link\n");
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
extern "C" int renameat2(int fromfd, const char* source, int tofd, const char* destination, unsigned flags) noexcept {
    const auto real = reinterpret_cast<int(*)(int,const char*,int,const char*,unsigned)>(dlsym(RTLD_NEXT,"renameat2"));
    trace("rename noreplace\n");
    if (flags != RENAME_NOREPLACE) std::abort();
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && !std::strncmp(mode,"fallback_noprim",15)) {
        errno = !std::strcmp(mode,"fallback_noprim_enosys") ? ENOSYS :
                !std::strcmp(mode,"fallback_noprim_einval") ? EINVAL : ENOTSUP;
        return -1;
    }
    if (mode && !std::strcmp(mode,"fallback_cleanup_race")) { errno = ENOTSUP; return -1; }
    if (!real) { errno = ENOSYS; return -1; }
    return real(fromfd,source,tofd,destination,flags);
}
// Any attempted creation under the final name is visible in the trace. Neither
// publication path should ever use this, even with an exclusive open.
extern "C" int open(const char* path, int flags, ...) {
    const auto real = reinterpret_cast<int(*)(const char*,int,...)>(dlsym(RTLD_NEXT,"open"));
    mode_t mode = 0;
    if (flags & O_CREAT) { va_list args; va_start(args,flags); mode = va_arg(args,int); va_end(args); }
    const char* output = std::getenv("CONVERT_OUTPUT");
    if (output && !std::strcmp(path,output) && (flags & O_CREAT)) trace("direct publish\n");
    return real(path,flags,mode);
}
extern "C" int fsync(int fd) {
    const auto real = reinterpret_cast<int(*)(int)>(dlsym(RTLD_NEXT,"fsync"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (temporary(fd)) {
        trace("file fsync\n");
        if (mode && !std::strcmp(mode,"fsync")) { errno = EIO; return -1; }
    } else {
        struct stat info{};
        if (fstat(fd, &info) == 0 && S_ISDIR(info.st_mode)) {
            trace("directory fsync\n");
            if (mode && (!std::strcmp(mode,"dir_fsync") || !std::strcmp(mode,"fallback_dir_fsync"))) { errno = EIO; return -1; }
        }
    }
    return real(fd);
}
extern "C" int unlink(const char* path) noexcept {
    const auto real = reinterpret_cast<int(*)(const char*)>(dlsym(RTLD_NEXT,"unlink"));
    const char* mode = std::getenv("CONVERT_FAULT");
    if (mode && std::strstr(mode,"cleanup_race") && std::strstr(path,"/.genome_v2_convert.")) {
        // Replace a published output (or publish after refusal) exactly during
        // temporary cleanup. Cleanup must never unlink this competing inode.
        const char* output = std::getenv("CONVERT_OUTPUT");
        const std::string sibling = std::string(output) + ".competitor";
        const auto file = std::fopen(sibling.c_str(),"wx");
        if (!file) std::abort();
        std::fputs("replacement",file); std::fclose(file);
        if (std::rename(sibling.c_str(),output) != 0) std::abort();
        trace("competitor replacement\n");
    }
    if (mode && !std::strcmp(mode,"unlink") && std::strstr(path,"/.genome_v2_convert.")) { errno = EPERM; return -1; }
    return real(path);
}
''')
    library = work / 'fault.so'
    subprocess.run(['c++', '-std=c++20', '-shared', '-fPIC', str(shim), '-ldl', '-o', str(library)], check=True)
    def run(output, fault="none", expected=0):
        env = dict(os.environ)
        (work / "trace").write_text("")
        env.update(LD_PRELOAD=str(library), CONVERT_FAULT=fault, CONVERT_OUTPUT=str(output), CONVERT_TRACE=str(work / "trace"))
        p = subprocess.run([converter, str(source), str(output), 'a'*64, '1'], env=env, capture_output=True, umask=0o027)
        assert p.returncode == expected, (fault, p.returncode, p.stderr)
        assert source.read_bytes() == original
        leaked = list(work.glob('.genome_v2_convert.*'))
        events = (work / 'trace').read_text().splitlines()
        assert 'direct publish' not in events, 'final pathname created by open'
        if fault == 'interrupt':
            assert len(leaked) == 1 and leaked[0].stat().st_size == 7
            for path in leaked: path.unlink()
        elif fault == 'unlink':
            assert leaked and b'warning: could not remove temporary checkpoint' in p.stderr
            for path in leaked: path.unlink()
        else:
            assert not leaked, 'temporary output leaked'
        return p
    destination = work / 'converted.json'
    run(destination)
    assert (work / 'trace').read_text().splitlines() == ['file fsync', 'link', 'directory fsync']
    converted = destination.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o640, 'respects umask'
    parsed = json.loads(converted)
    assert parsed['config']['genomeVersion'] == 2
    run(destination, expected=2)
    assert destination.read_bytes() == converted
    run(source, expected=2)
    for fault in ['write', 'close', 'fsync', 'interrupt', 'fallback_noprim_enosys', 'fallback_noprim_einval', 'fallback_noprim_enotsup']:
        output = work / (fault+'.json')
        run(output, fault, 77 if fault == 'interrupt' else 1)
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
        assert events == (['file fsync', 'link', 'rename noreplace', 'directory fsync']
                          if fault.startswith('fallback') else ['file fsync', 'link', 'directory fsync']), events
    output = work / 'fallback_race.json'
    run(output, 'fallback_race', 1)
    assert output.read_bytes() == b'competitor'
    for fault in ['dir_fsync', 'fallback_dir_fsync']:
        output = work / (fault + '.json')
        run(output, fault, 1)
        assert output.read_bytes() == converted, 'directory sync failure must retain complete published output'
        assert (work / 'trace').read_text().splitlines() == (['file fsync', 'link', 'directory fsync']
            if fault == 'dir_fsync' else ['file fsync', 'link', 'rename noreplace', 'directory fsync'])
    for fault, expected in [('cleanup_race', 0), ('write_cleanup_race', 1), ('fallback_cleanup_race', 1)]:
        output = work / (fault + '.json')
        run(output, fault, expected)
        assert output.read_bytes() == b'replacement', 'cleanup deleted competing replacement'
    output = work / 'dangling.json'
    output.symlink_to('missing.json')
    run(output, expected=1)
    run(output, 'fallback', expected=1)
    assert output.is_symlink() and os.readlink(output) == 'missing.json'
print('PASS atomic converter (permissions, durability, fallback, cleanup warning): exact publish order, short writes/EINTR, interrupt, write/close/sync failures, safe-primitive refusal, replacement during cleanup, no-clobber race, symlink and source identity')
