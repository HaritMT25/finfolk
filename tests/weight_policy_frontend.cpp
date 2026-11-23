#include <cstdio>
#include <string>
#include "../wasm/evo_wasm.cpp"

int main() {
    int failures = 0;
    auto check = [&](bool condition) {
        if (!condition) ++failures;
    };

    check(evo_init(42, 640, 480, 3, nullptr) == 1);
    check(g_world->cfg.weightMutationMode == WeightMutationMode::Legacy);
    check(checkpoint::serialize(*g_world, "test").find("weightMutationMode") ==
          std::string::npos);

    check(evo_init(42, 640, 480, 3,
                   R"({"weightMutationMode":"legacy"})") == 1);
    check(g_world->cfg.weightMutationMode == WeightMutationMode::Legacy);

    check(evo_init(42, 640, 480, 3,
                   R"({"weightMutationMode":"saturating"})") == 1);
    check(g_world->cfg.weightMutationMode == WeightMutationMode::Saturating);
    const std::string before = checkpoint::serialize(*g_world, "test");

    for (const char* bad : {
            R"({"weightMutationMode":"wrap"})",
            R"({"weightMutationMode":1})",
            R"({"weightMutationMode":true})",
            R"({"weightMutationMode":null})",
            R"({"weightMutationMode":[]})",
            R"({"weightMutationMode":{}})",
            R"({"weightMutationMode":"saturating","weightMutationMode":"legacy"})",
            R"({"weightMutationMode":"legacy","weightMutationMode":"saturating"})"
         }) {
        check(evo_init(99, 640, 480, 3, bad) == 0);
        check(checkpoint::serialize(*g_world, "test") == before);
    }
    check(evo_set_param("weightMutationMode", 1) == 0);
    check(checkpoint::serialize(*g_world, "test") == before);
    const std::string rngBefore = rng.state();
    // Exercise every persisted float (not just the mutation fields). The
    // independent serializer schema selects them; integer fields stay intact.
    SimConfig shape;
    shape.predatorBrain = true;
    std::string shapeText, error;
    jsonm::Writer sw(shapeText);
    sw.beginObject(); checkpoint::writeConfig(sw, shape); sw.endObject();
    jsonm::Value schema;
    check(jsonm::Parser::parse(shapeText, schema, error));
    for (const auto& kv : schema.find("config")->obj) {
        if (kv.second.type != jsonm::Value::Type::Number ||
            checkpoint::v3::isConfigIntKey(kv.first)) continue;
        const std::string bad = "{\"weightMutationMode\":\"saturating\",\"predatorBrain\":true,\"" + kv.first + "\":1e100}";
        check(evo_init(99, 640, 480, 3, bad.c_str()) == 0);
        check(checkpoint::serialize(*g_world, "test") == before);
        check(rng.state() == rngBefore);
    }
    for (const char* key : {"mutationMultiplier", "geneCost", "foodSpawnBase",
             "foodSpawnAmp", "foodEnergy", "metabolicRate", "moveCost", "maxAge",
             "reproEnergy", "newbornEnergy", "minSpeed", "maxSpeed", "predatorTraitMutation"}) {
        check(evo_set_param(key, 1e100) == 0);
        check(checkpoint::serialize(*g_world, "test") == before);
        check(rng.state() == rngBefore);
    }
    check(evo_init(99, 640, 480, 3,
        R"({"weightMutationMode":"saturating","predatorBrain":true,"predatorPrimer":true,"predatorCount":1,"genomeMinLength":1,"genomeMaxLength":1,"genomeInitMin":1,"genomeInitMax":1})") == 0);
    check(checkpoint::serialize(*g_world, "test") == before);
    check(rng.state() == rngBefore);
    check(evo_set_param("mutationMultiplier", 2) == 1);
    World restored;
    check(checkpoint::deserialize(checkpoint::serialize(*g_world, "test"), restored, error));
    // The new finiteness rule is opt-in; retain legacy acceptance behavior.
    check(evo_init(42, 640, 480, 3, R"({"mutationMultiplier":1e100})") == 1);
    check(std::isinf(g_world->cfg.mutationMultiplier));
    check(evo_set_param("geneCost", 1e100) == 1);
    check(std::isinf(g_world->cfg.geneCost));
    std::printf("weight policy frontend: %d failures\n", failures);
    return failures ? 1 : 0;
}
