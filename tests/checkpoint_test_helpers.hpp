#pragma once

namespace g2pr1 {

inline jsonm::Value& member(jsonm::Value& v, const char* key) {
    for (auto& kv : v.obj) if (kv.first == key) return kv.second;
    CHECK(false);
    return v;
}

inline void emit(jsonm::Writer& w, const jsonm::Value& v) {
    using T = jsonm::Value::Type;
    switch (v.type) {
    case T::Null: w.nullValue(); break;
    case T::Bool: w.value(v.b); break;
    case T::Number: w.value(v.num); break;
    case T::String: w.value(v.str); break;
    case T::Array:
        w.beginArray();
        for (const auto& e : v.arr) emit(w, e);
        w.endArray();
        break;
    case T::Object:
        w.beginObject();
        for (const auto& kv : v.obj) {
            w.key(kv.first.c_str());
            emit(w, kv.second);
        }
        w.endObject();
        break;
    }
}

inline jsonm::Value number(double x) {
    jsonm::Value v;
    v.type = jsonm::Value::Type::Number;
    v.num = x;
    return v;
}

inline jsonm::Value string(const char* x) {
    jsonm::Value v;
    v.type = jsonm::Value::Type::String;
    v.str = x;
    return v;
}

template <class Edit>
inline void rejectBeforeInit(const std::string& good, Edit edit) {
    jsonm::Value j;
    std::string error;
    CHECK(jsonm::Parser::parse(good, j, error));
    edit(j);
    std::string bad;
    jsonm::Writer writer(bad);
    emit(writer, j);

    rng.seed(909u);
    World sentinel;
    sentinel.init(640, 480, 3);
    const std::string before = checkpoint::serialize(sentinel, "sentinel");
    const std::string rngBefore = rng.state();
    const size_t capacityBefore = sentinel.creatures.capacity();

    CHECK(!checkpoint::deserialize(bad, sentinel, error));
    CHECK(!error.empty());
    CHECK(rng.state() == rngBefore);
    CHECK(sentinel.creatures.capacity() == capacityBefore);
    CHECK(checkpoint::serialize(sentinel, "sentinel") == before);
}

} // namespace g2pr1
