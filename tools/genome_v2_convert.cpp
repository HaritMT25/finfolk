#include <filesystem>
#include <cerrno>
#include <cstring>
#include <cstdlib>
#include <unistd.h>
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
    const auto text = checkpoint::serialize(world, "0.27.0");
    // An exclusive sibling stays private until every byte and close succeed.
    // link() publishes atomically and refuses even a dangling destination symlink.
    std::string pattern = (output.parent_path() / ".genome_v2_convert.XXXXXX").string();
    std::vector<char> temporary(pattern.begin(), pattern.end());
    temporary.push_back('\0');
    const int fd = ::mkstemp(temporary.data());
    if (fd < 0) { std::cerr << "could not create converted checkpoint: " << std::strerror(errno) << '\n'; return 1; }
    int failure = 0;
    size_t offset = 0;
    while (offset < text.size()) {
        const auto written = ::write(fd, text.data() + offset, text.size() - offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) { failure = written < 0 ? errno : EIO; break; }
        offset += static_cast<size_t>(written);
    }
    // Do not retry close: on some systems the fd has already been released.
    if (::close(fd) != 0 && !failure) failure = errno;
    if (!failure && ::link(temporary.data(), output.c_str()) != 0) failure = errno;
    const int cleanup = ::unlink(temporary.data());
    if (failure || cleanup != 0) {
        const int why = failure ? failure : errno;
        std::cerr << "could not publish converted checkpoint: " << std::strerror(why) << '\n';
        return 1;
    }
}
