cmake_minimum_required(VERSION 3.16)
project(evo_boids VERSION 0.26.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_CXX_FLAGS_RELEASE "-O3")
set(CMAKE_CXX_FLAGS_DEBUG "-g -O0")

# Reproducible floating point. Without this the compiler is free to fuse a*b+c
# into a single-rounded FMA wherever it likes, which makes results depend on
# -march, compiler version and target: two builds of IDENTICAL source then
# disagree in the last bits and diverge (chaotic system). WebAssembly has no
# scalar FMA instruction at all, so a native build WITH contraction can never
# reproduce a wasm build.
#
# Keeping contraction off is what lets a fixed --seed mean the same run
# everywhere, which is the premise of the deterministic serial build, of
# resuming from a checkpoint, and of verifying a result by replaying it. It is
# also what makes the flattened feedForward provably identical to the original
# (see NeuralNet::flat in genome.hpp and the equivalence test in core_tests).
# Do not add -ffast-math: it implies contraction and much worse.
add_compile_options(-ffp-contract=off)

# Serial build switch. OpenMP parallelises the sensor/movement phase with
# per-thread RNGs, which makes runs NON-reproducible even at a fixed --seed (see
# the Stage-A schooling finding). Configure with -DEVO_NO_OPENMP=ON to build a
# fully single-threaded, DETERMINISTIC binary (slower, but a fixed --seed
# reproduces exactly) — the recommended target for definitive cause-and-effect
# runs. Default OFF keeps the fast parallel build.
option(EVO_NO_OPENMP "Build single-threaded (deterministic at a fixed --seed)" OFF)

# Thread-pool switch. Runs the same per-creature loop on src/core/thread_pool.hpp
# instead of OpenMP. This is how the Emscripten pthreads build parallelises (no
# OpenMP runtime there); natively it exists to test that path (e.g. under
# -fsanitize=thread). Same contract as OpenMP: NOT reproducible at a fixed seed.
option(EVO_POOL_THREADS "Parallelise with the built-in thread pool instead of OpenMP" OFF)

if(EMSCRIPTEN)
    message(STATUS "Emscripten -> browser module only (EVO_POOL_THREADS=${EVO_POOL_THREADS})")
elseif(EVO_POOL_THREADS)
    message(STATUS "EVO_POOL_THREADS=ON -> thread-pool build (no OpenMP, not deterministic)")
elseif(EVO_NO_OPENMP)
    message(STATUS "EVO_NO_OPENMP=ON -> serial, deterministic build (no OpenMP)")
else()
    find_package(OpenMP)
endif()

# ------------------------------------------------------------------
# evo_core — the simulation. Header-only and SFML-FREE.
# Anything that links this can be built and tested without SFML.
# ------------------------------------------------------------------
add_library(evo_core INTERFACE)
target_include_directories(evo_core INTERFACE ${CMAKE_SOURCE_DIR}/src)
if(OpenMP_CXX_FOUND)
    target_link_libraries(evo_core INTERFACE OpenMP::OpenMP_CXX)
    target_compile_definitions(evo_core INTERFACE USE_OPENMP)
endif()
if(EVO_POOL_THREADS)
    target_compile_definitions(evo_core INTERFACE EVO_POOL_THREADS)
    if(EMSCRIPTEN)
        target_compile_options(evo_core INTERFACE -pthread)
        target_link_options(evo_core INTERFACE -pthread)
    else()
        find_package(Threads REQUIRED)
        target_link_libraries(evo_core INTERFACE Threads::Threads)
    endif()
endif()

# ------------------------------------------------------------------
# Emscripten: the browser module only (wasm/wasm.cmake), then stop —
# no SFML window, no native tests. See CMakePresets.json (wasm-st, wasm-mt).
# ------------------------------------------------------------------
if(EMSCRIPTEN)
    include(wasm/wasm.cmake)
    return()
endif()

# ------------------------------------------------------------------
# evo_boids — the SFML frontend (window, rendering, input).
# SFML is required ONLY for this target; without it the core, the tests and
# the benchmark still build.
# ------------------------------------------------------------------
find_package(SFML 2.6 COMPONENTS graphics window system QUIET)
if(SFML_FOUND)
    add_executable(evo_boids
        src/app/main.cpp
        src/render/sfml_renderer.cpp
    )
    target_link_libraries(evo_boids PRIVATE evo_core sfml-graphics sfml-window sfml-system)
    target_compile_definitions(evo_boids PRIVATE EVO_VERSION="${PROJECT_VERSION}")
    file(COPY ${CMAKE_SOURCE_DIR}/img DESTINATION ${CMAKE_CURRENT_BINARY_DIR})
else()
    message(WARNING "SFML 2.6 not found: skipping the evo_boids app; core_tests, "
                    "predator_smoke and core_bench still build")
endif()

# ------------------------------------------------------------------
# core_tests — unit tests for the core. No SFML.
# Run with: ctest  (or execute the binary directly)
# ------------------------------------------------------------------
enable_testing()
add_executable(core_tests tests/core_tests.cpp)
target_link_libraries(core_tests PRIVATE evo_core)
add_test(NAME core_tests COMMAND core_tests)

# predator_smoke — a longer no-SFML integration run with predators ON, asserting
# the run-level invariants (pop floor, finite positions, predation occurs,
# predator_align in range, deaths == predation+starvation+age, fixed predator
# count). Core-only, so it joins the same `ctest` suite as core_tests.
add_executable(predator_smoke tests/predator_smoke.cpp)
target_link_libraries(predator_smoke PRIVATE evo_core)
add_test(NAME predator_smoke COMMAND predator_smoke)

# reseed_after_load — the app's --reseed-after-load flag, end to end through the
# real binary (exact resume without it; same S = same bytes; different S
# diverge). Needs the app (SFML) and the serial build, the only one in which a
# resume is bit-exact.
if(SFML_FOUND AND EVO_NO_OPENMP AND NOT EVO_POOL_THREADS)
    add_test(NAME reseed_after_load
             COMMAND bash ${CMAKE_SOURCE_DIR}/tests/reseed_after_load.sh
                     $<TARGET_FILE:evo_boids> ${CMAKE_CURRENT_BINARY_DIR}/reseed_after_load_work)
endif()

# ------------------------------------------------------------------
# core_bench — single-binary throughput benchmark for World::update.
# Core-only (no SFML). Build Release and run e.g. `./core_bench 2000`.
# Links evo_core, so the OpenMP speedup is included when OpenMP is found.
# ------------------------------------------------------------------
add_executable(core_bench tests/bench.cpp)
target_link_libraries(core_bench PRIVATE evo_core)
