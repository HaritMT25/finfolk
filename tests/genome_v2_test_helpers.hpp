#pragma once
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <bit>
#include "core/genome.hpp"
#define G2_CHECK(x, name) do { if (!(x)) { std::fprintf(stderr, "FAIL %s line %d\n", name, __LINE__); std::exit(1); } } while (0)
inline Gene g2Gene(int st, int sn, int kt, int kn, unsigned code) {
    Gene g{}; g.sourceType = st; g.sourceNum = sn; g.sinkType = kt; g.sinkNum = kn;
    g.weight = logweight::store(code); return g;
}
inline bool g2Same(const Genome& a, const Genome& b) {
    if (a.schema != b.schema || a.size() != b.size()) return false;
    for (size_t i = 0; i < a.size(); ++i) {
        const auto& x = a[i]; const auto& y = b[i];
        if (x.sourceType != y.sourceType || x.sourceNum != y.sourceNum || x.sinkType != y.sinkType || x.sinkNum != y.sinkNum || x.weight != y.weight) return false;
    }
    return true;
}
inline bool g2Bits(float a, float b) { return std::bit_cast<unsigned>(a) == std::bit_cast<unsigned>(b); }
