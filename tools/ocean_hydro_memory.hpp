#pragma once
#include <cstdint>
#include <cstring>
#include <malloc.h>
#include <vector>
#ifdef __EMSCRIPTEN__
#include <emscripten/stack.h>
#else
#include <pthread.h>
#endif
namespace hydrobench {
inline std::size_t allocatorBytes() {
#ifdef __EMSCRIPTEN__
    const auto m=mallinfo();
#else
    const auto m=mallinfo2();
#endif
    return m.uordblks+m.hblkhd;
}
inline void* stackOperation(void* argument) {
    const bool exporting=argument!=nullptr;
    const auto body=hydroharness::body();
    hydro::Coefficients c;hydro::Support s;hydro::Diagnostics d;
    if(hydro::compile(body.G,1,1,body.P,hydro::Params{},c,s,exporting?&d:nullptr)!=hydro::kOk)std::abort();
    if(exporting) {
        std::array<std::uint32_t,hydro::kCoefficientFloats> words;int n=0;
        for(float x:hydro::floats(c))words[n++]=std::bit_cast<std::uint32_t>(x);
        sink=words[0]+d.compoundMass;
    } else sink=c.leanMass;
    return nullptr;
}
inline std::size_t stackPeak(bool exporting) {
    constexpr unsigned char pattern=0xa5;
#ifdef __EMSCRIPTEN__
    // Fill only unused data-stack space, leaving the caller's active frames.
    const auto low=emscripten_stack_get_end();
    const auto high=emscripten_stack_get_current()-4096;
    std::memset(reinterpret_cast<void*>(low),pattern,high-low);
    stackOperation(exporting?reinterpret_cast<void*>(1):nullptr);
    auto p=low;while(p<high&&*reinterpret_cast<const unsigned char*>(p)==pattern)++p;
    return emscripten_stack_get_base()-p;
#else
    // A dedicated painted worker stack measures actual touched bytes; includes
    // pthread entry/exit overhead. Timing windows never run on this thread.
    constexpr std::size_t bytes=4*1024*1024;
    void* memory=nullptr;if(posix_memalign(&memory,4096,bytes))throw std::runtime_error("stack allocation");
    std::memset(memory,pattern,bytes);pthread_attr_t attr;pthread_t thread;
    if(pthread_attr_init(&attr)||pthread_attr_setstack(&attr,memory,bytes)||
       pthread_create(&thread,&attr,stackOperation,exporting?reinterpret_cast<void*>(1):nullptr))
        throw std::runtime_error("stack probe pthread creation");
    pthread_attr_destroy(&attr);pthread_join(thread,nullptr);
    const auto p=static_cast<const unsigned char*>(memory);std::size_t first=0;
    while(first<bytes&&p[first]==pattern)++first;
    free(memory);return bytes-first;
#endif
}
} // namespace hydrobench
