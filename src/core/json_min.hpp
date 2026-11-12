#pragma once
// ----------------------------------------------------------------------------
// json_min — a small, dependency-free JSON writer + reader.
//
// Exists so checkpoints can be plain JSON without pulling a library into a
// header-only core. It handles exactly the subset this project emits: objects,
// arrays, strings, numbers, booleans, null. No comments, no NaN/Inf literals.
//
// FLOAT EXACTNESS is the whole point, so it is worth stating precisely: floats
// are written with %.9g. Nine significant decimal digits (FLT_DECIMAL_DIG) is
// the smallest count that uniquely identifies every float32, so a value written
// here and read back through a correctly-rounded strtod (glibc, and every
// browser's JSON.parse) returns the IDENTICAL bit pattern. That is what lets a
// checkpoint resume a run bit-for-bit rather than approximately.
// ----------------------------------------------------------------------------
#include <string>
#include <vector>
#include <utility>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cmath>

namespace jsonm {

// ---------------------------------------------------------------- writing ---
// A streaming writer: the caller drives structure, so there is no intermediate
// tree to build for the large arrays a checkpoint contains.
class Writer {
public:
    explicit Writer(std::string& out) : out_(out) {}

    void beginObject() { comma(); out_ += '{'; first_.push_back(true); }
    void endObject()   { out_ += '}'; first_.pop_back(); afterValue(); }
    void beginArray()  { comma(); out_ += '['; first_.push_back(true); }
    void endArray()    { out_ += ']'; first_.pop_back(); afterValue(); }

    void key(const char* k) {
        comma();
        quote(k);
        out_ += ':';
        pendingKey_ = true;      // the value that follows must not emit a comma
    }

    void value(float f)              { comma(); out_ += fmtFloat(f); afterValue(); }
    void value(double d)             { comma(); out_ += fmtDouble(d); afterValue(); }
    void value(int i)                { comma(); out_ += std::to_string(i); afterValue(); }
    void value(long long i)          { comma(); out_ += std::to_string(i); afterValue(); }
    void value(unsigned long long i) { comma(); out_ += std::to_string(i); afterValue(); }
    void value(bool b)               { comma(); out_ += (b ? "true" : "false"); afterValue(); }
    void value(const std::string& s) { comma(); quote(s.c_str()); afterValue(); }
    void value(const char* s)        { comma(); quote(s); afterValue(); }
    void nullValue() { comma(); out_ += "null"; afterValue(); }

    // convenience: key + value in one call
    template <typename T>
    void field(const char* k, T v) { key(k); value(v); }

    void newline() { out_ += '\n'; }

    // %.9g round-trips every float32 exactly (see the header comment).
    static std::string fmtFloat(float f) {
        char buf[40];
        std::snprintf(buf, sizeof(buf), "%.9g", (double)f);
        return buf;
    }
    static std::string fmtDouble(double d) {
        char buf[40];
        std::snprintf(buf, sizeof(buf), "%.17g", d);
        return buf;
    }

private:
    void quote(const char* s) {
        out_ += '"';
        for (const char* p = s; *p; ++p) {
            switch (*p) {
                case '"':  out_ += "\\\""; break;
                case '\\': out_ += "\\\\"; break;
                case '\n': out_ += "\\n";  break;
                case '\r': out_ += "\\r";  break;
                case '\t': out_ += "\\t";  break;
                default:
                    if ((unsigned char)*p < 0x20) {
                        char b[8];
                        std::snprintf(b, sizeof(b), "\\u%04x", (unsigned)(unsigned char)*p);
                        out_ += b;
                    } else {
                        out_ += *p;
                    }
            }
        }
        out_ += '"';
    }
    void comma() {
        if (pendingKey_) { pendingKey_ = false; return; }
        if (!first_.empty()) {
            if (!first_.back()) out_ += ',';
            first_.back() = false;
        }
    }
    void afterValue() {}

    std::string& out_;
    std::vector<bool> first_;
    bool pendingKey_ = false;
};

// ---------------------------------------------------------------- reading ---
struct Value {
    enum class Type { Null, Bool, Number, String, Array, Object };
    Type type = Type::Null;
    bool        b   = false;
    double      num = 0.0;
    std::string str;
    std::vector<Value> arr;
    std::vector<std::pair<std::string, Value>> obj;

    bool isNull()   const { return type == Type::Null; }
    bool isObject() const { return type == Type::Object; }
    bool isArray()  const { return type == Type::Array; }

    // Linear lookup: checkpoint objects have a handful of keys, and the big
    // data lives in arrays, so a map would cost more than it saves.
    const Value* find(const char* k) const {
        if (type != Type::Object) return nullptr;
        for (const auto& kv : obj) if (kv.first == k) return &kv.second;
        return nullptr;
    }
    bool has(const char* k) const { return find(k) != nullptr; }

    double      numberOr(const char* k, double d) const { const Value* v = find(k); return (v && v->type == Type::Number) ? v->num : d; }
    float       floatOr (const char* k, float f)  const { const Value* v = find(k); return (v && v->type == Type::Number) ? (float)v->num : f; }
    int         intOr   (const char* k, int i)    const { const Value* v = find(k); return (v && v->type == Type::Number) ? (int)v->num : i; }
    long long   llOr    (const char* k, long long i) const { const Value* v = find(k); return (v && v->type == Type::Number) ? (long long)v->num : i; }
    unsigned long long ullOr(const char* k, unsigned long long i) const { const Value* v = find(k); return (v && v->type == Type::Number) ? (unsigned long long)v->num : i; }
    bool        boolOr  (const char* k, bool d)   const { const Value* v = find(k); return (v && v->type == Type::Bool) ? v->b : d; }
    std::string stringOr(const char* k, const std::string& d) const { const Value* v = find(k); return (v && v->type == Type::String) ? v->str : d; }
};

class Parser {
public:
    // Returns false and fills `error` on malformed input. Never throws.
    static bool parse(const std::string& text, Value& out, std::string& error) {
        // Reset first: a failed parse leaves whatever it managed to read behind,
        // and reusing the same Value for a second parse would otherwise append
        // to those leftovers and silently return a merged, wrong document.
        out = Value{};
        error.clear();
        Parser p(text);
        p.skipWs();
        if (!p.parseValue(out)) { error = p.error_; return false; }
        p.skipWs();
        if (p.i_ != p.s_.size()) { error = "trailing characters after JSON value"; return false; }
        return true;
    }

private:
    explicit Parser(const std::string& s) : s_(s) {}

    bool fail(const char* why) {
        error_ = std::string(why) + " at offset " + std::to_string(i_);
        return false;
    }
    void skipWs() {
        while (i_ < s_.size() && (s_[i_] == ' ' || s_[i_] == '\t' || s_[i_] == '\n' || s_[i_] == '\r')) ++i_;
    }
    bool literal(const char* lit) {
        size_t n = std::char_traits<char>::length(lit);
        if (s_.compare(i_, n, lit) != 0) return false;
        i_ += n;
        return true;
    }

    bool parseValue(Value& v) {
        skipWs();
        if (i_ >= s_.size()) return fail("unexpected end of input");
        const char c = s_[i_];
        if (c == '{') return parseObject(v);
        if (c == '[') return parseArray(v);
        if (c == '"') { v.type = Value::Type::String; return parseString(v.str); }
        if (literal("true"))  { v.type = Value::Type::Bool; v.b = true;  return true; }
        if (literal("false")) { v.type = Value::Type::Bool; v.b = false; return true; }
        if (literal("null"))  { v.type = Value::Type::Null; return true; }
        return parseNumber(v);
    }

    bool parseObject(Value& v) {
        v.type = Value::Type::Object;
        ++i_;  // '{'
        skipWs();
        if (i_ < s_.size() && s_[i_] == '}') { ++i_; return true; }
        for (;;) {
            skipWs();
            std::string k;
            if (i_ >= s_.size() || s_[i_] != '"') return fail("expected object key");
            if (!parseString(k)) return false;
            skipWs();
            if (i_ >= s_.size() || s_[i_] != ':') return fail("expected ':'");
            ++i_;
            Value child;
            if (!parseValue(child)) return false;
            v.obj.emplace_back(std::move(k), std::move(child));
            skipWs();
            if (i_ < s_.size() && s_[i_] == ',') { ++i_; continue; }
            if (i_ < s_.size() && s_[i_] == '}') { ++i_; return true; }
            return fail("expected ',' or '}'");
        }
    }

    bool parseArray(Value& v) {
        v.type = Value::Type::Array;
        ++i_;  // '['
        skipWs();
        if (i_ < s_.size() && s_[i_] == ']') { ++i_; return true; }
        for (;;) {
            Value child;
            if (!parseValue(child)) return false;
            v.arr.push_back(std::move(child));
            skipWs();
            if (i_ < s_.size() && s_[i_] == ',') { ++i_; continue; }
            if (i_ < s_.size() && s_[i_] == ']') { ++i_; return true; }
            return fail("expected ',' or ']'");
        }
    }

    bool parseString(std::string& out) {
        ++i_;  // opening quote
        out.clear();
        while (i_ < s_.size()) {
            const char c = s_[i_++];
            if (c == '"') return true;
            if (c != '\\') { out += c; continue; }
            if (i_ >= s_.size()) return fail("unterminated escape");
            const char e = s_[i_++];
            switch (e) {
                case '"':  out += '"';  break;
                case '\\': out += '\\'; break;
                case '/':  out += '/';  break;
                case 'b':  out += '\b'; break;
                case 'f':  out += '\f'; break;
                case 'n':  out += '\n'; break;
                case 'r':  out += '\r'; break;
                case 't':  out += '\t'; break;
                case 'u': {
                    if (i_ + 4 > s_.size()) return fail("truncated \\u escape");
                    unsigned cp = (unsigned)std::strtoul(s_.substr(i_, 4).c_str(), nullptr, 16);
                    i_ += 4;
                    // Checkpoints are ASCII; encode as UTF-8 for completeness.
                    if (cp < 0x80) { out += (char)cp; }
                    else if (cp < 0x800) { out += (char)(0xC0 | (cp >> 6)); out += (char)(0x80 | (cp & 0x3F)); }
                    else { out += (char)(0xE0 | (cp >> 12)); out += (char)(0x80 | ((cp >> 6) & 0x3F)); out += (char)(0x80 | (cp & 0x3F)); }
                    break;
                }
                default: return fail("bad escape character");
            }
        }
        return fail("unterminated string");
    }

    bool parseNumber(Value& v) {
        const char* start = s_.c_str() + i_;
        char* end = nullptr;
        const double d = std::strtod(start, &end);
        if (end == start) return fail("expected a value");
        i_ += (size_t)(end - start);
        v.type = Value::Type::Number;
        v.num  = d;
        return true;
    }

    const std::string& s_;
    size_t i_ = 0;
    std::string error_;
};

// ------------------------------------------------------- array conveniences --
// Readers for the columnar arrays a checkpoint stores. Each returns false if
// the field is missing or the wrong length, so a truncated file is caught at
// load rather than producing a half-restored world.
inline bool readFloats(const Value& parent, const char* key, std::vector<float>& out, size_t expected) {
    const Value* v = parent.find(key);
    if (!v || !v->isArray()) return false;
    if (expected != (size_t)-1 && v->arr.size() != expected) return false;
    out.clear();
    out.reserve(v->arr.size());
    for (const Value& e : v->arr) {
        if (e.type != Value::Type::Number) return false;
        out.push_back((float)e.num);
    }
    return true;
}

inline bool readInts(const Value& parent, const char* key, std::vector<long long>& out, size_t expected) {
    const Value* v = parent.find(key);
    if (!v || !v->isArray()) return false;
    if (expected != (size_t)-1 && v->arr.size() != expected) return false;
    out.clear();
    out.reserve(v->arr.size());
    for (const Value& e : v->arr) {
        if (e.type != Value::Type::Number) return false;
        out.push_back((long long)e.num);
    }
    return true;
}

inline void writeFloats(Writer& w, const char* key, const std::vector<float>& v) {
    w.key(key);
    w.beginArray();
    for (float f : v) w.value(f);
    w.endArray();
}

inline void writeInts(Writer& w, const char* key, const std::vector<long long>& v) {
    w.key(key);
    w.beginArray();
    for (long long i : v) w.value(i);
    w.endArray();
}

}  // namespace jsonm
