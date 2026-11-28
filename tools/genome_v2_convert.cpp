#include <filesystem>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <vector>
#include <iostream>
#include "core/checkpoint_io.hpp"
#include "core/genome_v2_conversion.hpp"

int main(int argc, char** argv) {
    if (argc != 5 || (std::string(argv[4]) != "0" && std::string(argv[4]) != "1")) {
        std::cerr << "usage: genome_v2_convert INPUT OUTPUT SOURCE_SHA256 BIAS(0|1)\n";
        return 2;
    }
    namespace fs = std::filesystem;
    const fs::path input = fs::absolute(argv[1]).lexically_normal();
    const fs::path output = fs::absolute(argv[2]).lexically_normal();
    if (input == output || fs::exists(output)) {
        std::cerr << "output must be a new path distinct from input\n"; return 2;
    }
    World world;
    std::string error;
    if (!checkpoint::load(input.string(), world, error) ||
        !convertWorldToGenomeV2(world, std::string(argv[4]) == "1", argv[3], error)) {
        std::cerr << error << '\n'; return 1;
    }
    const auto text = checkpoint::serialize(world, EVO_VERSION);
    // An exclusive sibling stays private until every byte and close succeed.
    // link() publishes atomically and refuses even a dangling destination symlink.
    std::string pattern = (output.parent_path() / ".genome_v2_convert.XXXXXX").string();
    std::vector<char> temporary(pattern.begin(), pattern.end());
    temporary.push_back('\0');
    const int fd = ::mkstemp(temporary.data());
    if (fd < 0) { std::cerr << "could not create converted checkpoint: " << std::strerror(errno) << '\n'; return 1; }
    // Match ordinary checkpoint creation's permissions instead of mkstemp's 0600.
    const mode_t mask = ::umask(0);
    ::umask(mask);
    const mode_t mode = 0666 & ~mask;
    auto writeAndClose = [&](int file, bool setMode) {
        int failure = 0;
        if (setMode && ::fchmod(file, mode) != 0) failure = errno;
        size_t offset = 0;
        while (!failure && offset < text.size()) {
            const auto written = ::write(file, text.data() + offset, text.size() - offset);
            if (written < 0 && errno == EINTR) continue;
            if (written <= 0) { failure = written < 0 ? errno : EIO; break; }
            offset += static_cast<size_t>(written);
        }
        if (!failure && ::fsync(file) != 0) failure = errno;
        // Do not retry close: the descriptor may already have been released.
        if (::close(file) != 0 && !failure) failure = errno;
        return failure;
    };
    int failure = writeAndClose(fd, true);
    bool published = false;
    if (!failure) {
        if (::link(temporary.data(), output.c_str()) == 0) published = true;
        else {
            failure = errno;
            if (failure == EPERM || failure == ENOTSUP || failure == EXDEV) {
                // Filesystems without hard links still get exclusive, no-follow
                // creation. Only our own incomplete output is removed on failure.
                const int direct = ::open(output.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, mode);
                if (direct < 0) failure = errno;
                else {
                    failure = writeAndClose(direct, false);
                    if (failure) {
                        if (::unlink(output.c_str()) != 0)
                            std::cerr << "warning: could not remove incomplete checkpoint: " << std::strerror(errno) << '\n';
                    } else published = true;
                }
            }
        }
    }
    if (::unlink(temporary.data()) != 0)
        std::cerr << "warning: could not remove temporary checkpoint: " << std::strerror(errno) << '\n';
    if (published) {
        const int directory = ::open(output.parent_path().c_str(), O_RDONLY | O_DIRECTORY);
        if (directory < 0) failure = errno;
        else {
            if (::fsync(directory) != 0) failure = errno;
            if (::close(directory) != 0 && !failure) failure = errno;
        }
    }
    if (failure) {
        std::cerr << "could not publish converted checkpoint: " << std::strerror(failure) << '\n';
        return 1;
    }
    return 0;
}
