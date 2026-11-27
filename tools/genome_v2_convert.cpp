#include <filesystem>
#include <fstream>
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
    std::ofstream out(output, std::ios::binary);
    out.write(text.data(), static_cast<std::streamsize>(text.size()));
    if (!out) { std::cerr << "could not write converted checkpoint\n"; return 1; }
}
