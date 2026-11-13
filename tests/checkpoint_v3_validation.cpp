#include <cstdint>
#include <cstdlib>
#include <new>
#include <cstdio>
// Bound cumulative allocation requests during a load. A regressed initializer
// fails safely rather than attempting billions of disposable founders.
static size_t allocationBudget = SIZE_MAX;
void* operator new(size_t n) {
    if (n > allocationBudget) throw std::bad_alloc();
    if (allocationBudget != SIZE_MAX) allocationBudget -= n;
    if (void* p = std::malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n) { return ::operator new(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }
#include "../wasm/evo_wasm.cpp"
static int failures = 0;
#define CHECK(x) do { if (!(x)) { std::printf("FAIL line %d: %s\n", __LINE__, #x); ++failures; } } while (0)
#include "checkpoint_test_helpers.hpp"

int main() {
    using namespace g2pr1;
    CHECK(evo_init(5150, 640, 480, 3,
        R"({"weightMutationMode":"saturating","predatorBrain":true,"predatorCount":1,"currentStrength":1,"currentEddies":2,"foodPatches":2})") == 1);
    const std::string good = checkpoint::serialize(*g_world, "test");
    int last = 0;
    auto section = [&](const char* name) {
        std::printf("%s: %d failures\n", name, failures - last);
        last = failures;
    };
    auto refuse = [&](auto edit) {
        // Direct destination and both RNG streams must survive a refused load.
        rejectBeforeInit(good, edit);
        jsonm::Value j;
        std::string error, bad;
        CHECK(jsonm::Parser::parse(good, j, error));
        edit(j);
        jsonm::Writer w(bad); emit(w, j);
        World* prior = g_world;
        const std::string before = checkpoint::serialize(*g_world, "test");
        const std::string state = rng.state();
        CHECK(evo_load_checkpoint(bad.c_str()) == 0);
        CHECK(g_world == prior);
        CHECK(rng.state() == state);
        CHECK(checkpoint::serialize(*g_world, "test") == before);
    };
    refuse([](auto& j) { member(member(j, "creatures"), "bodyLen") = number(7); });
    section("bodyLen refusal and sentinel/shim preservation");
    // Every ordinary serialized column: shape, stored float, integer and type.
    jsonm::Value schema;
    std::string error;
    CHECK(jsonm::Parser::parse(good, schema, error));
    for (const char* block : {"creatures", "predators", "food"}) {
        for (const auto& kv : member(schema, block).obj) {
            if (!kv.second.isArray() || kv.second.arr.empty()) continue;
            const std::string key = kv.first;
            refuse([&](auto& j) { member(member(j, block), key.c_str()).arr.pop_back(); });
            for (double bad : {1e100, 0.5}) {
                // Fractional values are legal float state, but not integer state.
                bool ints = key == "id" || key == "lineageId" || key == "parentId" ||
                    key == "generation" || key == "captures" || key == "alive" ||
                    key == "genes" || key == "genomeLengths";
                if (bad == 0.5 && !ints) continue;
                refuse([&](auto& j) { member(member(j, block), key.c_str()).arr[0] = number(bad); });
            }
        }
    }
    section("population columns");
    for (const char* block : {"world", "counters"}) {
        for (const auto& kv : member(schema, block).obj) {
            if (kv.second.type != jsonm::Value::Type::Number) continue;
            const std::string key = kv.first;
            for (double bad : {-1.0, 0.5, 1e100})
                refuse([&](auto& j) { member(member(j, block), key.c_str()) = number(bad); });
        }
    }
    section("world and counter scalars");
    for (const char* key : {"currentVortices", "foodPatchCenters"}) {
        refuse([&](auto& j) { member(j, key).arr.pop_back(); });
        refuse([&](auto& j) { member(j, key).arr[0] = number(1e100); });
        refuse([&](auto& j) { member(j, key) = number(1); });
    }
    for (const char* key : {"cols", "rows", "cellSize"})
        refuse([&](auto& j) { member(member(j, "signals"), key) = number(999); });
    refuse([](auto& j) { member(member(j, "signals"), "rle").arr.pop_back(); });
    for (double bad : {-1.0, 0.5, 1e100})
        refuse([&](auto& j) { member(member(j, "signals"), "rle").arr[0] = number(bad); });
    section("environment and signal state");
    for (const char* key : {"rngState", "predatorRngState"}) {
        refuse([&](auto& j) {
            std::string zero;
            for (int i = 0; i < 624; ++i) zero += "0 ";
            zero += "624";
            member(j, key) = string(zero.c_str());
        });
    }
    section("zero RNG streams");
    // Saved payload, not startup settings, controls restoration allocations.
    for (const char* key : {"predatorCount", "targetFood", "foodPatches", "currentEddies"}) {
        jsonm::Value j;
        CHECK(jsonm::Parser::parse(good, j, error));
        member(member(j, "config"), key) = number(2147483647);
        std::string text; jsonm::Writer w(text); emit(w, j);
        World restored;
        bool loaded = false;
        allocationBudget = 8 * 1024 * 1024;
        try { loaded = checkpoint::deserialize(text, restored, error); }
        catch (const std::bad_alloc&) { /* fail the assertion below */ }
        allocationBudget = SIZE_MAX;
        CHECK(loaded);
        if (loaded) {
            CHECK(restored.creatures.size() == 3);
            CHECK(restored.predators.size() == 1);
            // Complete round trip also checks retained startup settings and RNG.
            jsonm::Value again;
            CHECK(jsonm::Parser::parse(checkpoint::serialize(restored, "test"), again, error));
            CHECK(checkpoint::v3::sameValue(j, again));
        }
    }
    section("allocation-bounded restoration");
    std::printf("checkpoint v3 validation: %d failures\n", failures);
    return failures ? 1 : 0;
}
