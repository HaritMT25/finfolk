#include <iostream>
#include <iomanip>
#include <chrono>
#include <string>
#include <cstdlib>
#include <cmath>
#include <memory>
#include <algorithm>
#include <fstream>
#include <filesystem>
#include <sstream>
#include <cstdio>

#include "core/world.hpp"
#include "core/stats.hpp"
#include "core/cluster_map_io.hpp"
#include "core/wiring_log.hpp"
#include "core/birth_log.hpp"
#include "core/checkpoint_io.hpp"
#include "core/predator_stats.hpp"
#include "core/transplant.hpp"
#include "render/sfml_renderer.hpp"  // the only translation unit pulling SFML

// Set by CMake (project version). Falls back to "dev" for ad-hoc builds.
#ifndef EVO_VERSION
#define EVO_VERSION "dev"
#endif

namespace {

void printUsage(const char* prog) {
    std::cout <<
        "Usage: " << prog << " [options]\n\n"
        "Options:\n"
        "  --headless N      Run N simulation steps with no window, THEN open the\n"
        "                    window so you can watch the evolved population.\n"
        "  --no-render       Exit after the headless run instead of opening a window.\n"
        "                    Use on a display-less box, or when piping output to a file.\n"
        "  --csv PATH        Write per-interval metrics to PATH as CSV (headless only).\n"
        "  --name NAME       Name the run: logs to runs/NAME.csv (dir auto-created).\n"
        "                    Ignored if --csv is also given.\n"
        "  --log-every N     Sample/print interval in steps (default 1000).\n"
        "  --flush-every N   Flush the CSV to disk every N logged rows (default 5).\n"
        "  --seed S          Seed the RNG for repeatable runs (see note below).\n"
        "  --version         Print version + build time, then exit.\n"
        "  --help, -h        Show this message.\n\n"
        "Simulation parameters (defaults reproduce the original behaviour):\n"
        "  --toroidal            wrap-around senses: neighbour/food/predator perception,\n"
        "                        pheromones and the long probe cross the world seam, and\n"
        "                        the boundary sensors read no-wall (default off; positions\n"
        "                        have always wrapped — this makes the SENSES wrap too)\n"
        "  --repro-max-distance F  match distance: a pair farther apart than F in the folded\n"
        "                        (source,sink) connectivity space emits no successor;\n"
        "                        <0 = off (default off). Measured scale: unrelated genomes\n"
        "                        sit ~19.5 apart and in-run neighbour pairs ~18-20, so the\n"
        "                        live window is roughly 12-22 — below ~12 almost nothing\n"
        "                        pairs and the live count falls to the --min-pop floor\n"
        "  --repro-soft-width F  [needs --repro-max-distance >= 0] widen the gate into a\n"
        "                        linear acceptance ramp F wide above the threshold: a pair\n"
        "                        at distance d is admitted with probability 1 below the\n"
        "                        threshold, 0 at threshold+F, linear between. <=0 = off =\n"
        "                        the hard cliff (default off). ON adds one rng draw per\n"
        "                        gate evaluation, so it is a different random stream\n"
        "  --repro-grace F       [needs --repro-max-distance >= 0] founders (the initial\n"
        "                        spawn and every --min-pop reseed) bypass the gate while\n"
        "                        younger than F seconds, so a refilled creature can breed\n"
        "                        once before the gate applies; <=0 = off (default off),\n"
        "                        and <=5 is inert too (reproduction already needs age > 5)\n"
        "  --body-model          heritable body size + elongation (default off). Bigger =>\n"
        "                        slower (speed x 2/(1+size)) and costlier (metabolism x size);\n"
        "                        longer => turns worse (turn rate x 2/(1+elong), triangular\n"
        "                        motion only). Founders start at 1.0; a child inherits the\n"
        "                        parent mean plus a uniform jitter, clamped to [0.5, 2.0].\n"
        "                        NOTE --max-speed then bounds a DEFAULT body: the ceiling\n"
        "                        runs 0.67x (largest) to 1.33x (smallest) of it\n"
        "  --body-mutation F     [body model] uniform mutation half-width per parameter per\n"
        "                        birth, F >= 0 (default 0.1); 0 = inheritance with no drift\n"
        "  --population N        starting creature count (default 300)\n"
        "  --min-pop N           reseed floor (default 50)\n"
        "  --max-pop N           hard birth cap, 0 = unlimited (default 0)\n"
        "  --target-food N       baseline food count (default 600)\n"
        "  --food-spawn F        mean food spawned/step (default 3)\n"
        "  --food-amp F          food abundance swing (default 2)\n"
        "  --food-energy F       energy per food eaten (default 5)\n"
        "  --pickup-radius F     food pickup distance (default 10)\n"
        "  --metabolism F        energy burned/sec (default 1.5)\n"
        "  --gene-cost F         extra energy/sec per gene, parsimony pressure (default 0)\n"
        "  --move-cost F         kinetic cost: extra energy/sec = F * speed^2, 0=off (default 0)\n"
        "  --max-age F           death age (default 120)\n"
        "  --repro-energy F      energy needed to breed (default 20)\n"
        "  --newborn-energy F    child starting energy (default 25)\n"
        "  --perception F        sensing radius / grid cell (default 80)\n"
        "  --interact-radius F   social range (default 20)\n"
        "  --max-neighbors N     attend to only the N nearest neighbours in range,\n"
        "                        0=all (default 0 = metric interaction)\n"
        "  --topological         shorthand for --max-neighbors 7 (Ballerini et al. 2008:\n"
        "                        starlings track ~6-7 nearest; fish studies suggest fewer)\n"
        "  --repro-cooldown F    (default 3)   --interact-cooldown F (default 2)\n"
        "  --min-speed F         (default 30)  --max-speed F (default 150)\n"
        "  --triangular-motion   couple speed+turn: fast=>can't turn, slow=>turns freely (default off)\n"
        "  --max-turn-rate F     [triangular] max heading change in rad/s at zero forward drive (default 4.0)\n"
        "  --genome-min N        (default 16)  --genome-max N (default 80)\n"
        "  --genome-init-min N   (default 24)  --genome-init-max N (default 48)\n"
        "  --mutation F          mutation-rate multiplier (default 1.0)\n"
        "  --current F           ocean-current peak speed, 0=off (default 0)\n"
        "  --current-mode M      'eddies' (moving vortices) or 'gyre' (double-gyre) (default eddies)\n"
        "  --current-eddies N    [eddies] number of vortices / 'eyes' (default 5)\n"
        "  --current-core F      [eddies] eddy radius (default 150)\n"
        "  --current-drift F     how fast the field evolves, 0=static (default 1.0)\n"
        "  --gyre-eps F          [gyre] dividing-line oscillation amount (default 0.25)\n"
        "  --food-patches N      cluster food into N patches, 0=uniform (default 0)\n"
        "  --food-patch-radius F spread of food around a patch (default 120)\n"
        "  --food-drift          advect food with the current (forms filaments)\n"
        "Predator (Stage A: scripted, immortal, fixed-count; off by default):\n"
        "  --predators N             number of predators, 0=none (default 0)\n"
        "  --predator-perception F   predator prey-detection radius (default 150; >--perception => ambush asymmetry)\n"
        "  --predator-speed F        predator cruise speed (default 110)\n"
        "  --predator-capture-radius F  contact distance that catches a prey (default 14)\n"
        "  --predator-cooldown F     digestion cooldown in seconds after a kill (default 3)\n"
        "Predator energy economy (Stage B: predators starve/reproduce; opt-in):\n"
        "  --predator-economy        turn the economy ON (default off => Stage A immortal)\n"
        "  --predator-metabolism F   predator energy burn/sec (default 2.0)\n"
        "  --predator-move-cost F    predator kinetic cost coeff; <0 reuses --move-cost (default reuse)\n"
        "  --predator-repro-energy F energy needed to bud a child (default 60)\n"
        "  --predator-newborn-energy F  child / initial predator energy (default 30)\n"
        "  --predator-meal F         energy per kill; <0 absorbs the victim's reserves (default absorb)\n"
        "  --predator-max-age F      predator death age; 0=immortal-until-starved (default 0)\n"
        "  --predator-min-pop N      [economy] refill to at least N predators each step;\n"
        "                            0=off, extinction is final (default 0). Refills are\n"
        "                            counted in predator_reseeds_cum\n"
        "  --predator-max-pop N      [economy] no budding while N predators are alive;\n"
        "                            0=no cap (default 0)\n"
        "  --predator-inherit        [economy] buds inherit the parent's speed and budding\n"
        "                            threshold (x0.5..x2) with a mutation (default off)\n"
        "  --predator-trait-mutation F  uniform mutation half-width per trait per bud (default 0.1)\n"
        "Neural predators (Stage C; opt-in, off => every output is v0.26.0's):\n"
        "  --predator-brain          the hunt is a network built from each predator's genome (21\n"
        "                            inputs, TURN + THRUST out). With --predator-economy a bud\n"
        "                            inherits its parent's genome with a mutation, so predators\n"
        "                            evolve; without it they are immortal and fixed in number\n"
        "                            (the frozen mode a time-shift assay runs in). Recipe for an\n"
        "                            evolving run: --predator-economy --predator-max-pop N\n"
        "                            --predator-min-pop M --predator-max-age 120 (without a max\n"
        "                            age, capped predators never die or bud and stop evolving)\n"
        "  --predator-mutation F     multiplies the per-bud mutation rate, F >= 0 (default 1)\n"
        "  --predator-turn-rate F    rad/s at full TURN (default 4)\n"
        "  --predator-min-speed F    THRUST's floor; 0 lets a predator stop (default 0)\n"
        "  --predator-primer         founders start with two pursuit genes (PREY_LR -> TURN,\n"
        "                            PREY_PROX -> THRUST); default off = random genomes\n"
        "  --predator-log            stream every predator founding/bud/death to <name>.predlog.csv\n"
        "                            (never overwritten; a run from a checkpoint opens it with L/T rows)\n"
        "  (on a resume of a checkpoint without brains, every Stage C flag is an error)\n"
        "  (with the brain on, a CSV run also writes <name>.predators.csv every --log-every)\n"
        "Transplant (Stage C time-shift assays; needs --load-checkpoint X and --transplant-out):\n"
        "  --predators-from Y|random  replace X's predators with K of checkpoint Y's (their genomes,\n"
        "                            lineages and traits; everything else reset) or K random founders\n"
        "  --transplant-count K      how many (default: all of Y's; required with 'random')\n"
        "  --transplant-seed S       the transplant's own stream: sample, placement (default 1)\n"
        "  --assay frozen|frozen-newborn|live\n"
        "                            frozen (default): energy and age accounted, no deaths or buds,\n"
        "                            no floor/cap, prey --min-pop 0; frozen-newborn: the economy\n"
        "                            off (ENERGY and AGE read 0, an ablation); live: X's config\n"
        "  --transplant-allow-mismatch  accept X and Y with different predator physics (X's stand)\n"
        "  --transplant-out FILE     write the arena checkpoint (+ FILE's .manifest.json) and exit;\n"
        "                            run the assay with --load-checkpoint FILE --reseed-after-load R\n\n"
        "Analysis / inspection:\n"
        "  --cluster-map             at end of run, write <name>.deaths.csv + <name>.cluster.svg\n"
        "                            (a 2-D projection of each dead creature's network)\n"
        "  --cluster-epoch N         deaths per colour band in the map (default 1000)\n"
        "  --cluster-max N           max points kept in RAM; uniformly decimated above this (default 20000)\n"
        "  --cluster-pca             use PCA axes (per-run, variance-aligned) instead of the fixed random map\n"
        "  --cluster-color M         'epoch' (time, default) or 'lineage' (colour points by clade)\n"
        "  --wiring-log              write <name>.wiring.csv: per-sensor wiring fraction over time (headless)\n"
        "  --repro-log               write <name>.births.csv: one row per pairing event (which two\n"
        "                            records produced a successor) — the pairing graph (headless)\n"
        "  --repro-log-max N         max pairing records kept in RAM; decimated above this (default 20000)\n"
        "  --repro-window N          pairing events in the trailing graph window behind the\n"
        "                            repro_components CSV column, 0 = disable it (default 2000)\n"
        "  --repro-min-cluster N     ignore pairing-graph components smaller than N (default 3)\n"
        "  --profile                 print a build/parallel/serial phase timing breakdown at end (headless)\n"
        "  --fast-tanh               approximate the neural activations (~1.2-1.3x faster, CHANGES\n"
        "                            results; exploratory sweeps only — see config.hpp)\n"
        "  --save-checkpoint FILE    write the full world state to FILE (JSON) at end of run\n"
        "  --load-checkpoint FILE    resume from FILE instead of starting fresh. In a serial\n"
        "                            build the continuation is bit-for-bit identical. Edit the\n"
        "                            'config' block in the file to change settings mid-run.\n"
        "  --reseed-after-load S     [needs --load-checkpoint] after the load, seed the rng\n"
        "                            with S instead of continuing the checkpoint's saved rng\n"
        "                            stream, so replicate continuations of ONE checkpoint differ\n"
        "                            (--seed is ignored on resume). Same S => the same run, bit\n"
        "                            for bit, in a serial build. Off by default (exact resume)\n"
        "  --checkpoint-every N      also write <name>.<frame>.json every N steps\n"
        "  (In the live window: LEFT-CLICK a fish to watch its neural net fire in a top-right panel.)\n\n"
        "Log to CSV and then watch the result (omit --no-render):\n"
        "  " << prog << " --headless 50000 --name evolved_50k --log-every 2000\n\n"
        "Log to CSV on a headless box and capture the console too:\n"
        "  " << prog << " --headless 50000 --name evolved_50k --no-render | tee runs/evolved_50k.log\n\n"
        "Note: in an OpenMP build, --seed makes the single-threaded parts (spawning,\n"
        "interactions, deaths, init) repeatable; the parallel sensor/movement phase\n"
        "uses per-thread RNGs. For a fully deterministic run, build the serial target.\n";
}

}  // namespace

int main(int argc, char** argv) {
    // Not const: resuming from a checkpoint adopts that world's dimensions.
    int W = 1920;
    int H = 1080;

    int         headlessSteps = 0;
    int         logEvery      = 1000;
    int         flushEvery    = 5;     // flush CSV to disk every N logged rows
    bool        noRender      = false;
    bool        haveSeed      = false;
    unsigned    seed          = 0;
    std::string csvPath;
    std::string runName;
    std::string saveCheckpoint;    // --save-checkpoint FILE (written at end of run)
    std::string loadCheckpoint;    // --load-checkpoint FILE (resume)
    int         checkpointEvery = 0;   // --checkpoint-every N (0 = off)
    std::string checkpointBase;        // prefix for the periodic files
    // --reseed-after-load S: CLI-only on purpose. It is not world state (the
    // checkpoint written at the end records the rng state it produced, so that
    // file still resumes exactly) and it is not a SimConfig field, so nothing
    // the engine or the wasm module sees changes.
    bool        haveReseedAfterLoad = false;
    unsigned    reseedAfterLoad     = 0;
    // Stage C transplant (CLI-only, like --reseed-after-load).
    transplant::Options transplantOpt;
    bool        haveTransplantSeed  = false;
    std::string transplantOut;
    std::vector<std::string> brainCli;   // Stage C flags given on this command line
    bool        loadedArenaStart = false; // the loaded checkpoint is a transplant's arena, not yet run

    int       initialPopulation = 300;  // starting creature count
    SimConfig cfg;                       // all other tunable parameters

    // Parse args. next() consumes the following token as this flag's value.
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto next = [&](const char* name) -> const char* {
            if (i + 1 >= argc) {
                std::cerr << name << " requires a value\n";
                std::exit(1);
            }
            return argv[++i];
        };

        if      (arg == "--headless")  headlessSteps = std::atoi(next("--headless"));
        else if (arg == "--log-every") logEvery      = std::max(1, std::atoi(next("--log-every")));
        else if (arg == "--flush-every") flushEvery   = std::max(1, std::atoi(next("--flush-every")));
        else if (arg == "--csv")       csvPath       = next("--csv");
        else if (arg == "--name")      runName       = next("--name");
        else if (arg == "--seed")    { seed = static_cast<unsigned>(std::strtoul(next("--seed"), nullptr, 10)); haveSeed = true; }
        else if (arg == "--no-render") noRender      = true;
        // --- simulation parameters (override SimConfig defaults) ---
        else if (arg == "--repro-max-distance") cfg.reproMaxDistance = std::atof(next("--repro-max-distance"));
        else if (arg == "--repro-soft-width")  cfg.reproSoftWidth    = std::atof(next("--repro-soft-width"));
        else if (arg == "--repro-grace")       cfg.reproGracePeriod  = std::atof(next("--repro-grace"));
        else if (arg == "--body-model")       cfg.bodyModel         = true;
        else if (arg == "--body-mutation")    cfg.bodyMutation      = std::atof(next("--body-mutation"));
        else if (arg == "--population")       initialPopulation     = std::atoi(next("--population"));
        else if (arg == "--min-pop")          cfg.minPopulation     = std::atoi(next("--min-pop"));
        else if (arg == "--max-pop")          cfg.maxPopulation     = std::atoi(next("--max-pop"));
        else if (arg == "--target-food")      cfg.targetFood        = std::atoi(next("--target-food"));
        else if (arg == "--food-spawn")       cfg.foodSpawnBase     = std::atof(next("--food-spawn"));
        else if (arg == "--food-amp")         cfg.foodSpawnAmp      = std::atof(next("--food-amp"));
        else if (arg == "--food-energy")      cfg.foodEnergy        = std::atof(next("--food-energy"));
        else if (arg == "--pickup-radius")    cfg.pickupRadius      = std::atof(next("--pickup-radius"));
        else if (arg == "--metabolism")       cfg.metabolicRate     = std::atof(next("--metabolism"));
        else if (arg == "--gene-cost")         cfg.geneCost          = std::atof(next("--gene-cost"));
        else if (arg == "--move-cost")         cfg.moveCost          = std::atof(next("--move-cost"));
        else if (arg == "--max-age")          cfg.maxAge            = std::atof(next("--max-age"));
        else if (arg == "--repro-energy")     cfg.reproEnergy       = std::atof(next("--repro-energy"));
        else if (arg == "--newborn-energy")   cfg.newbornEnergy     = std::atof(next("--newborn-energy"));
        else if (arg == "--perception")       cfg.perceptionRadius  = std::atof(next("--perception"));
        else if (arg == "--interact-radius")  cfg.interactRadius    = std::atof(next("--interact-radius"));
        else if (arg == "--save-checkpoint")  saveCheckpoint        = next("--save-checkpoint");
        else if (arg == "--load-checkpoint")  loadCheckpoint        = next("--load-checkpoint");
        else if (arg == "--reseed-after-load") {
            reseedAfterLoad = static_cast<unsigned>(std::strtoul(next("--reseed-after-load"), nullptr, 10));
            haveReseedAfterLoad = true;
        }
        else if (arg == "--checkpoint-every") checkpointEvery       = std::atoi(next("--checkpoint-every"));
        else if (arg == "--max-neighbors")    cfg.maxNeighbors      = std::atoi(next("--max-neighbors"));
        else if (arg == "--topological")      cfg.maxNeighbors      = 7;
        else if (arg == "--fast-tanh")        cfg.fastTanh          = true;
        else if (arg == "--repro-cooldown")   cfg.reproCooldown     = std::atof(next("--repro-cooldown"));
        else if (arg == "--interact-cooldown")cfg.interactCooldown  = std::atof(next("--interact-cooldown"));
        else if (arg == "--min-speed")        cfg.minSpeed          = std::atof(next("--min-speed"));
        else if (arg == "--max-speed")        cfg.maxSpeed          = std::atof(next("--max-speed"));
        else if (arg == "--toroidal")         cfg.toroidal          = true;
        else if (arg == "--triangular-motion") cfg.triangularMotion = true;
        else if (arg == "--max-turn-rate")    cfg.maxTurnRate       = std::atof(next("--max-turn-rate"));
        else if (arg == "--genome-min")       cfg.genomeMinLength   = std::atoi(next("--genome-min"));
        else if (arg == "--genome-max")       cfg.genomeMaxLength   = std::atoi(next("--genome-max"));
        else if (arg == "--genome-init-min")  cfg.genomeInitMin     = std::atoi(next("--genome-init-min"));
        else if (arg == "--genome-init-max")  cfg.genomeInitMax     = std::atoi(next("--genome-init-max"));
        else if (arg == "--mutation")         cfg.mutationMultiplier= std::atof(next("--mutation"));
        // --- currents / spatial food (environment) ---
        else if (arg == "--current")           cfg.currentStrength   = std::atof(next("--current"));
        else if (arg == "--current-mode")    { std::string m = next("--current-mode"); cfg.currentMode = (m == "gyre") ? 1 : 0; }
        else if (arg == "--current-eddies")    cfg.currentEddies     = std::atoi(next("--current-eddies"));
        else if (arg == "--current-core")      cfg.currentCore       = std::atof(next("--current-core"));
        else if (arg == "--current-drift")     cfg.currentDrift      = std::atof(next("--current-drift"));
        else if (arg == "--gyre-eps")          cfg.currentGyreEps    = std::atof(next("--gyre-eps"));
        else if (arg == "--food-patches")      cfg.foodPatches       = std::atoi(next("--food-patches"));
        else if (arg == "--food-patch-radius") cfg.foodPatchRadius   = std::atof(next("--food-patch-radius"));
        else if (arg == "--food-drift")        cfg.foodDrift         = true;
        // --- predator (Stage A) ---
        else if (arg == "--predators")              cfg.predatorCount       = std::atoi(next("--predators"));
        else if (arg == "--predator-perception")    cfg.predatorPerception  = std::atof(next("--predator-perception"));
        else if (arg == "--predator-speed")         cfg.predatorSpeed       = std::atof(next("--predator-speed"));
        else if (arg == "--predator-capture-radius")cfg.predatorCaptureRadius = std::atof(next("--predator-capture-radius"));
        else if (arg == "--predator-cooldown")      cfg.predatorCooldown    = std::atof(next("--predator-cooldown"));
        // --- predator energy economy (Stage B) ---
        else if (arg == "--predator-economy")       cfg.predatorEconomy     = true;
        else if (arg == "--predator-metabolism")    cfg.predatorMetabolism  = std::atof(next("--predator-metabolism"));
        else if (arg == "--predator-move-cost")     cfg.predatorMoveCost    = std::atof(next("--predator-move-cost"));
        else if (arg == "--predator-repro-energy")  cfg.predatorReproEnergy = std::atof(next("--predator-repro-energy"));
        else if (arg == "--predator-newborn-energy")cfg.predatorNewbornEnergy = std::atof(next("--predator-newborn-energy"));
        else if (arg == "--predator-meal")          cfg.predatorMeal        = std::atof(next("--predator-meal"));
        else if (arg == "--predator-max-age")       cfg.predatorMaxAge      = std::atof(next("--predator-max-age"));
        // --- predator floor + heritable traits (v0.26.0) ---
        else if (arg == "--predator-min-pop")       cfg.predatorMinPopulation = std::atoi(next("--predator-min-pop"));
        else if (arg == "--predator-max-pop")       cfg.predatorMaxPopulation = std::atoi(next("--predator-max-pop"));
        else if (arg == "--predator-inherit")       cfg.predatorInheritance = true;
        else if (arg == "--predator-trait-mutation")cfg.predatorTraitMutation = std::atof(next("--predator-trait-mutation"));
        // --- neural predators (Stage C) + the transplant ---
        else if (arg == "--predator-brain")       { cfg.predatorBrain       = true; brainCli.push_back("predatorBrain"); }
        else if (arg == "--predator-mutation")    { cfg.predatorMutation    = std::atof(next("--predator-mutation")); brainCli.push_back("predatorMutation"); }
        else if (arg == "--predator-turn-rate")   { cfg.predatorTurnRate    = std::atof(next("--predator-turn-rate")); brainCli.push_back("predatorTurnRate"); }
        else if (arg == "--predator-min-speed")   { cfg.predatorMinSpeed    = std::atof(next("--predator-min-speed")); brainCli.push_back("predatorMinSpeed"); }
        else if (arg == "--predator-primer")      { cfg.predatorPrimer      = true; brainCli.push_back("predatorPrimer"); }
        else if (arg == "--predator-log")         { cfg.predatorLog         = true; brainCli.push_back("predatorLog"); }
        else if (arg == "--predators-from")         transplantOpt.predatorsFrom = next("--predators-from");
        else if (arg == "--transplant-count") {
            // a whole number >= -1 (-1 = all of the source's); anything else is refused
            const char* v = next("--transplant-count");
            char* end = nullptr;
            const long k = std::strtol(v, &end, 10);
            if (end == v || *end != '\0' || k < -1 || k > 1000000) {
                std::cerr << "Error: --transplant-count must be a whole number >= 0 (got '" << v << "').\n";
                return 1;
            }
            transplantOpt.count = (int)k;
        }
        else if (arg == "--transplant-seed")      { transplantOpt.seed = static_cast<unsigned>(std::strtoul(next("--transplant-seed"), nullptr, 10)); haveTransplantSeed = true; }
        else if (arg == "--assay")                  transplantOpt.assay = next("--assay");
        else if (arg == "--transplant-allow-mismatch") transplantOpt.allowMismatch = true;
        else if (arg == "--transplant-out")         transplantOut = next("--transplant-out");
        else if (arg == "--cluster-map")            cfg.clusterMap          = true;
        else if (arg == "--cluster-max")             cfg.clusterMax          = std::atoi(next("--cluster-max"));
        else if (arg == "--cluster-epoch")           cfg.clusterEpoch        = std::max(1, std::atoi(next("--cluster-epoch")));
        else if (arg == "--cluster-pca")             cfg.clusterPca          = true;
        else if (arg == "--cluster-color")         { std::string m = next("--cluster-color"); cfg.clusterColor = (m == "lineage") ? 1 : 0; }
        else if (arg == "--wiring-log")              cfg.wiringLog           = true;
        else if (arg == "--repro-log")               cfg.reproLog            = true;
        else if (arg == "--repro-log-max")           cfg.reproLogMax         = std::atoi(next("--repro-log-max"));
        else if (arg == "--repro-window")            cfg.reproWindow         = std::max(0, std::atoi(next("--repro-window")));
        else if (arg == "--repro-min-cluster")       cfg.reproMinCluster     = std::max(1, std::atoi(next("--repro-min-cluster")));
        else if (arg == "--profile")                 cfg.profile             = true;
        else if (arg == "--version") {
            std::cout << "evo_boids " << EVO_VERSION
                      << " (built " << __DATE__ << " " << __TIME__ << ")\n";
            return 0;
        }
        else if (arg == "--help" || arg == "-h") { printUsage(argv[0]); return 0; }
        else {
            std::cerr << "Unknown option: " << arg << "\n\n";
            printUsage(argv[0]);
            return 1;
        }
    }

    if (haveSeed) rng.seed(seed);

    // Reseeding only means something on top of a loaded rng state; without a
    // checkpoint it would silently be a second --seed. Refuse instead.
    if (haveReseedAfterLoad && loadCheckpoint.empty()) {
        std::cerr << "Error: --reseed-after-load needs --load-checkpoint (use --seed for a fresh run).\n";
        return 1;
    }

    // A named run logs to runs/<name>.csv unless an explicit --csv path is given.
    if (csvPath.empty() && !runName.empty()) {
        csvPath = "runs/" + runName + ".csv";
    }

    // Base path for the death-cluster map outputs (<stem>.deaths.csv / .cluster.svg).
    std::string clusterStem;
    if (!runName.empty())      clusterStem = "runs/" + runName;
    else if (!csvPath.empty()) clusterStem = std::filesystem::path(csvPath).replace_extension("").string();
    else                       clusterStem = "runs/cluster";

    if (!csvPath.empty() && headlessSteps <= 0) {
        std::cerr << "Note: CSV logging only happens during the --headless run; "
                     "nothing will be written without --headless.\n";
    }

    // Light validation: keep ranges sane and warn on anything clamped.
    auto fixOrder = [](auto& lo, auto& hi, const char* what) {
        if (lo > hi) { std::cerr << "Note: " << what << " min > max; swapping.\n"; std::swap(lo, hi); }
    };
    fixOrder(cfg.minSpeed, cfg.maxSpeed, "speed");
    fixOrder(cfg.genomeMinLength, cfg.genomeMaxLength, "genome length");
    fixOrder(cfg.genomeInitMin, cfg.genomeInitMax, "genome init");
    if (cfg.perceptionRadius < 1.0f) { std::cerr << "Note: perception clamped to 1.\n"; cfg.perceptionRadius = 1.0f; }
    if (cfg.maxNeighbors < 0)        { std::cerr << "Note: max-neighbors < 0 treated as 0 (unlimited).\n"; cfg.maxNeighbors = 0; }
    // A negative body-mutation half-width would make rng.range(lo,hi) run
    // backwards — same draw, mirrored sign. Harmless numerically but it means
    // something different from what the flag says, so refuse it rather than
    // silently reinterpreting it. Non-finite is worse than wrong: std::atof
    // parses "nan" and "inf", and rng.range(-inf, +inf) evaluates to NaN, which
    // the clamp does NOT filter — every newborn body becomes NaN, poisons the
    // speed/turn/metabolism factors, and lands in the checkpoint as a bare
    // `nan` token that is not even valid JSON. The test is written negated
    // because NaN compares false to everything, so `< 0.0f` waves it through.
    if (!(cfg.bodyMutation >= 0.0f) || !std::isfinite(cfg.bodyMutation)) {
        std::cerr << "Error: --body-mutation must be finite and >= 0 (got " << cfg.bodyMutation << ").\n";
        return 1;
    }
    // The predator trait mutation feeds rng.range the same way, with the same
    // failure modes, so it is refused on the same terms.
    if (!(cfg.predatorTraitMutation >= 0.0f) || !std::isfinite(cfg.predatorTraitMutation)) {
        std::cerr << "Error: --predator-trait-mutation must be finite and >= 0 (got "
                  << cfg.predatorTraitMutation << ").\n";
        return 1;
    }
    // The floor, the ceiling and inheritance act on the economy only; say so
    // instead of letting the flag be silently inert.
    if (!cfg.predatorEconomy && (cfg.predatorMinPopulation > 0 || cfg.predatorMaxPopulation > 0 ||
                                 cfg.predatorInheritance))
        std::cerr << "Note: --predator-min-pop, --predator-max-pop and --predator-inherit need"
                     " --predator-economy; ignored.\n";
    if (cfg.predatorMaxPopulation > 0 && cfg.predatorMinPopulation > cfg.predatorMaxPopulation)
        std::cerr << "Note: --predator-min-pop is above --predator-max-pop; the floor wins.\n";
    // Stage C. The knobs are refused on the terms of the other mutation knobs.
    if (const char* why = predatorBrainConfigError(cfg)) {
        std::cerr << "Error: " << why << ".\n";
        return 1;
    }
    if (cfg.predatorBrain && loadCheckpoint.empty()) {
        if (!cfg.predatorEconomy)
            std::cerr << "Note: --predator-brain without --predator-economy: immortal, fixed-count neural\n"
                         "      predators that never bud (the frozen mode); nothing evolves.\n";
        else if (cfg.predatorMaxPopulation > 0 && !(cfg.predatorMaxAge > 0.0f))
            std::cerr << "Warning: --predator-brain with --predator-max-pop and no --predator-max-age:\n"
                         "      predators at the cap neither die nor bud, so evolution stops there.\n"
                         "      The Stage C recipe adds --predator-max-age (e.g. 120).\n";
    }
    if ((cfg.predatorPrimer || cfg.predatorLog) && !cfg.predatorBrain && transplantOpt.predatorsFrom.empty() &&
        loadCheckpoint.empty())
        std::cerr << "Note: --predator-primer and --predator-log need --predator-brain; ignored.\n";
    const bool transplantMode = !transplantOpt.predatorsFrom.empty() || !transplantOut.empty();
    // The lineage log is the only copy of a run's phylogeny: never overwrite
    // one. Each run (or resumed segment) writes its own <name>.predlog.csv;
    // stitch segments by the rule in docs/evo_boids_flags.md.
    if (cfg.predatorLog && headlessSteps > 0 && !transplantMode && (cfg.predatorBrain || !loadCheckpoint.empty()) &&
        std::filesystem::exists(clusterStem + ".predlog.csv")) {
        std::cerr << "Error: " << clusterStem << ".predlog.csv exists; the lineage log is never overwritten.\n"
                     "       Give this run (or resumed segment) its own --name, or move the old log.\n";
        return 1;
    }
    if (transplantMode) {
        if (loadCheckpoint.empty() || transplantOpt.predatorsFrom.empty() || transplantOut.empty()) {
            std::cerr << "Error: a transplant needs --load-checkpoint X, --predators-from Y|random and"
                         " --transplant-out FILE.\n";
            return 1;
        }
        if (headlessSteps > 0 || haveReseedAfterLoad) {
            std::cerr << "Error: --transplant-out writes the arena and exits; run the assay as a separate\n"
                         "       --load-checkpoint ARENA --reseed-after-load R --headless N run.\n";
            return 1;
        }
    }
    // A NEGATIVE soft width or grace period is not an error — like
    // --repro-max-distance, anything <= 0 means off. Non-finite is different:
    // std::atof parses "nan" and "inf", and both silently inverts the soft
    // gate's meaning (every comparison against NaN is false, so a NaN width
    // rejects EVERY pair while still burning a draw; an infinite width does the
    // same via inf < inf) — the opposite of the "wider = more permissive"
    // contract the flag advertises. Refuse them the way --body-mutation does,
    // and for the same reason: silently meaning something else is worse than
    // stopping. The threshold has the same hole with the opposite signs: a NaN
    // --repro-max-distance ARMS the gate (NaN < 0 is false) and then rejects
    // every pair (dsq <= NaN*NaN is false), silently pinning the run to the
    // --min-pop floor with no diagnostic; +inf arms a gate that admits
    // everything while claiming to gate. Refuse all three.
    if (!std::isfinite(cfg.reproSoftWidth) || !std::isfinite(cfg.reproGracePeriod) ||
        !std::isfinite(cfg.reproMaxDistance)) {
        std::cerr << "Error: --repro-max-distance, --repro-soft-width and --repro-grace"
                     " must be finite (negative = off).\n";
        return 1;
    }
    // The genetic gate folds a genome into a fixed stack buffer. --genome-max is
    // an unbounded int, so refuse the combination rather than silently folding a
    // truncated genome and gating on a distance that means nothing.
    if (cfg.reproMaxDistance >= 0.0f &&
        cfg.genomeMaxLength > isolation_detail::ISO_MAX_GENES) {
        std::cerr << "Error: --repro-max-distance needs --genome-max <= "
                  << isolation_detail::ISO_MAX_GENES << " (got " << cfg.genomeMaxLength << ").\n";
        return 1;
    }
    if (checkpointEvery > 0) {
        checkpointBase = !saveCheckpoint.empty() ? saveCheckpoint
                       : (!runName.empty() ? ("runs/" + runName) : std::string("runs/checkpoint"));
        // strip a trailing .json so the periodic files read name.<frame>.json
        if (checkpointBase.size() > 5 && checkpointBase.compare(checkpointBase.size() - 5, 5, ".json") == 0)
            checkpointBase.resize(checkpointBase.size() - 5);
        // A bare file name (--save-checkpoint end.json) has no parent, and
        // create_directories("") throws: guard it like --save-checkpoint below.
        const auto cpParent = std::filesystem::path(checkpointBase).parent_path();
        if (!cpParent.empty()) std::filesystem::create_directories(cpParent);
    }
    if (!saveCheckpoint.empty()) {
        const auto parent = std::filesystem::path(saveCheckpoint).parent_path();
        if (!parent.empty()) std::filesystem::create_directories(parent);
    }
    if (cfg.maxNeighbors > MAX_TOPOLOGICAL_NEIGHBORS) {
        std::cerr << "Note: max-neighbors clamped to " << MAX_TOPOLOGICAL_NEIGHBORS
                  << " (use 0 for unlimited/metric interaction).\n";
        cfg.maxNeighbors = MAX_TOPOLOGICAL_NEIGHBORS;
    }
    if (initialPopulation < 0)       initialPopulation = 0;

    // Init world with the chosen configuration.
    World world;
    world.cfg = cfg;

    if (!loadCheckpoint.empty()) {
        // Resuming replaces the whole world, including its config, so the flags
        // on this command line are ignored EXCEPT the ones that don't live in a
        // checkpoint (--headless, --name, logging). To change a simulation
        // setting on resume, edit the "config" block inside the checkpoint —
        // that is the supported way to intervene mid-run.
        std::string err;
        if (!checkpoint::load(loadCheckpoint, world, err)) {
            std::cerr << "!! cannot resume from '" << loadCheckpoint << "': " << err << "\n";
            return 1;
        }
        // A checkpoint's format version decides whether its predators have
        // brains (checkpoint_io.hpp). A Stage C flag on a version-1 resume can
        // never be honoured, so refuse it rather than run scripted predators for
        // days with only a missing file to show for it. (On a version-2 resume
        // the file's own keys stand, as for every other setting; a transplant
        // takes them for its "random" founders.)
        if (!world.cfg.predatorBrain && !transplantMode && !brainCli.empty()) {
            std::cerr << "Error: this checkpoint's predators have no genomes (format version 1), so";
            for (const std::string& k : brainCli) std::cerr << " " << k;
            std::cerr << " cannot apply.\n"
                         "       Give the world brains first: --load-checkpoint X --predators-from random\n"
                         "       --transplant-count K --transplant-out ARENA, then resume ARENA.\n";
            return 1;
        }
        // The arena's first run logs its predators as transplanted (T rows);
        // every later checkpoint of it is an ordinary one.
        const bool arenaStart = world.arenaFresh_;
        if (!transplantMode) world.arenaFresh_ = false;
        loadedArenaStart = arenaStart;
        if (!transplantMode && world.cfg.predatorBrain && world.cfg.predatorEconomy && !world.cfg.predatorFrozen &&
            world.cfg.predatorMaxPopulation > 0 && !(world.cfg.predatorMaxAge > 0.0f))
            std::cerr << "Warning: neural predators with a cap and no max age: at the cap they neither die\n"
                         "      nor bud, so evolution stops there (the Stage C recipe sets predatorMaxAge).\n";
        std::cout << "Resumed from " << loadCheckpoint
                  << " at frame " << world.frame
                  << " (" << world.creatures.size() << " creatures, "
                  << world.predators.size() << " predators)\n";
        // AFTER the load: deserialize() restores the saved rng state last, so
        // seeding any earlier would be overwritten. Everything else in the
        // world is exactly the checkpoint's; only the random stream from here
        // on is S's, which is what makes replicate forks of one state differ.
        if (haveReseedAfterLoad) {
            // rng.seed(S), then (brain worlds only) the predators' stream from
            // one draw of it (WorldCommon::reseedStreams).
            world.reseedStreams(reseedAfterLoad);
            std::cout << "Reseeded the rng after the load: " << reseedAfterLoad << "\n";
        }
        // Stage C transplant: the loaded world is X; write the arena and stop.
        if (transplantMode) {
            std::string yText;
            if (transplantOpt.predatorsFrom != "random") {
                std::ifstream yf(transplantOpt.predatorsFrom, std::ios::binary);
                if (!yf) {
                    std::cerr << "!! cannot read '" << transplantOpt.predatorsFrom << "'\n";
                    return 1;
                }
                std::ostringstream ss;
                ss << yf.rdbuf();
                yText = ss.str();
            }
            transplantOpt.preyPath = loadCheckpoint;
            {
                std::ifstream xf(loadCheckpoint, std::ios::binary);
                std::ostringstream ss;
                ss << xf.rdbuf();
                transplantOpt.preyHash = transplant::fnv1a64(ss.str());
            }
            transplantOpt.cliKeys = brainCli;
            std::string manifest, err;
            if (!transplant::apply(world, transplantOpt, yText, manifest, err)) {
                std::cerr << "!! transplant failed: " << err << "\n";
                return 1;
            }
            const auto parent = std::filesystem::path(transplantOut).parent_path();
            if (!parent.empty()) std::filesystem::create_directories(parent);
            if (!checkpoint::save(world, transplantOut, EVO_VERSION, err)) {
                std::cerr << "!! cannot write the arena: " << err << "\n";
                return 1;
            }
            std::string mpath = transplantOut;
            if (mpath.size() > 5 && mpath.compare(mpath.size() - 5, 5, ".json") == 0) mpath.resize(mpath.size() - 5);
            mpath += ".manifest.json";
            {
                std::ofstream mf(mpath, std::ios::binary);
                if (!(mf << manifest)) {
                    std::cerr << "!! cannot write the manifest '" << mpath << "'\n";
                    return 1;
                }
            }
            std::cout << "Arena " << transplantOut << ": " << world.creatures.size() << " prey (frame "
                      << world.frame << ") + " << world.predators.size() << " predators from "
                      << transplantOpt.predatorsFrom << ", assay " << transplantOpt.assay
                      << ", transplant seed " << transplantOpt.seed
                      << (haveTransplantSeed ? "" : " (default)") << "; manifest " << mpath << "\n";
            if (transplantOpt.assay == "live" && world.cfg.predatorEconomy && world.cfg.predatorMaxPopulation > 0 &&
                !(world.cfg.predatorMaxAge > 0.0f))
                std::cerr << "Warning: a live arena with a predator cap and no max age: at the cap the predators\n"
                             "      neither die nor bud.\n";
            return 0;
        }
#ifndef EVO_DETERMINISTIC
        std::cerr << "Note: this is a multi-threaded build, so the resumed run will NOT reproduce\n"
                  << "      the original bit-for-bit. Build -DEVO_NO_OPENMP=ON for that.\n";
#endif
        W = world.width;
        H = world.height;
    } else {
        world.init(W, H, initialPopulation);
    }

    // --- Headless phase: pure CPU, fixed dt, no rendering ---
    if (headlessSteps > 0) {
        std::cout << "evo_boids " << EVO_VERSION
                  << " (built " << __DATE__ << " " << __TIME__ << ")\n";
        if (!runName.empty()) std::cout << "Run: " << runName << "\n";
        std::cout << "Headless mode: simulating " << headlessSteps
                  << " steps (logging every " << logEvery << ")";
        if (haveSeed) std::cout << ", seed=" << seed;
        std::cout << "...\n";
        std::cout << "Config: population=" << initialPopulation << "\n"
                  << world.cfg.dump() << "\n";

        std::ofstream csv;
        if (!csvPath.empty()) {
            const std::filesystem::path p(csvPath);
            if (p.has_parent_path()) std::filesystem::create_directories(p.parent_path());
            csv.open(csvPath);
            if (!csv) {
                std::cerr << "Could not open CSV file for writing: " << csvPath << "\n";
                return 1;
            }
            csv << statsCsvHeader() << "\n";
            csv.flush();  // header on disk immediately, so `tail -f` works from t=0

            // Sidecar: record exactly what produced this CSV, so a run is
            // self-documenting (open <stem>.config.txt next to the .csv).
            std::filesystem::path meta = p;
            meta.replace_extension(".config.txt");
            if (std::ofstream m{meta}) {
                m << "evo_boids " << EVO_VERSION
                  << " (built " << __DATE__ << " " << __TIME__ << ")\n";
                if (!runName.empty()) m << "run: " << runName << "\n";
                m << "seed: " << (haveSeed ? std::to_string(seed) : std::string("random")) << "\n";
                // Only when used, so every existing sidecar reads as before.
                if (haveReseedAfterLoad)
                    m << "reseed_after_load: " << reseedAfterLoad << "\n";
                m << "steps: " << headlessSteps << "   log_every: " << logEvery << "\n"
                  << "population: " << initialPopulation << "\n"
                  << world.cfg.dump() << "\n";
            }
        }

        const float fixedDt = 0.016f;
        const auto  startTime = std::chrono::steady_clock::now();

        // Optional per-sensor wiring log (headless, opt-in). Separate file so the
        // metrics CSV format is untouched.
        std::ofstream wiringCsv;
        if (world.cfg.wiringLog) {
            const std::string wpath = clusterStem + ".wiring.csv";
            const std::filesystem::path wp(wpath);
            if (wp.has_parent_path()) std::filesystem::create_directories(wp.parent_path());
            wiringCsv.open(wpath);
            if (wiringCsv) { wiringCsv << wiring::header() << "\n"; wiringCsv.flush(); }
        }

        // Stage C outputs (brain on only; each its own file, so the metrics CSV
        // keeps one schema): per-interval predator metrics next to the CSV, the
        // predator wiring next to the wiring log, the streamed lineage log.
        const bool brain = world.cfg.predatorBrain;
        std::ofstream predCsv, predWiring;
        std::FILE* predLog = nullptr;
        predstats::Last predLast;
        predLast.births = world.totalPredatorBirths; predLast.starv = world.totalPredatorDeathsStarvation;
        predLast.age = world.totalPredatorDeathsAge; predLast.reseeds = world.totalPredatorReseeds;
        if (brain) {
            auto openNext = [&](const std::string& path) {
                const std::filesystem::path pp(path);
                if (pp.has_parent_path()) std::filesystem::create_directories(pp.parent_path());
            };
            if (!csvPath.empty()) {
                const std::string ppath = clusterStem + ".predators.csv";
                openNext(ppath);
                predCsv.open(ppath);
                if (predCsv) { predCsv << predstats::header() << "\n"; predCsv.flush(); }
            }
            if (world.cfg.wiringLog) {
                const std::string ppath = clusterStem + ".pwiring.csv";
                openNext(ppath);
                predWiring.open(ppath);
                if (predWiring) { predWiring << predstats::wiringHeader() << "\n"; predWiring.flush(); }
            }
            if (world.cfg.predatorLog) {
                const std::string ppath = clusterStem + ".predlog.csv";
                openNext(ppath);
                predLog = std::fopen(ppath.c_str(), "w");   // absent: checked before the run
                if (predLog) {
                    std::fprintf(predLog, "%s\n", predstats::logHeader().c_str());
                    // A run from a checkpoint starts its segment with the predators
                    // alive at the load: L rows, or T rows for an arena's first run.
                    if (!loadCheckpoint.empty())
                        world.notePredatorsAtStart(world.predators, loadedArenaStart ? 'T' : 'L');
                    predstats::drainLog(world, predLog);   // ... or the founders of init()
                    std::fflush(predLog);
                } else {
                    std::cerr << "Could not open " << ppath << " for writing.\n";
                }
            }
        }

        auto      lastSampleTime  = startTime;
        int       lastSampleStep  = 0;
        long long lastTotalBirths = 0;
        long long lastTotalDeaths = 0;
        long long lastTotalKills  = 0;
        long long lastTotalStarv  = 0;
        long long lastTotalAge    = 0;
        long long lastPredBirths  = 0;
        long long lastPredStarv   = 0;
        long long lastPredAge     = 0;
        int       rowsWritten     = 0;

        // Take one measurement: rich console line + optional CSV row. Per-interval
        // birth/death counts and steps/sec are diffed against the previous sample.
        auto sample = [&](int stepsDone) {
            const auto   now     = std::chrono::steady_clock::now();
            const double elapsed = std::chrono::duration<double>(now - startTime).count();
            const double dStep   = static_cast<double>(stepsDone - lastSampleStep);
            const double dSecs   = std::chrono::duration<double>(now - lastSampleTime).count();
            const double sps     = (dSecs > 1e-9) ? dStep / dSecs : 0.0;

            const WorldStats st = computeStats(world);
            const int birthsInt = static_cast<int>(st.totalBirths - lastTotalBirths);
            const int deathsInt = static_cast<int>(st.totalDeaths - lastTotalDeaths);
            // Per-interval death decomposition (cumulative totals, diffed like
            // births/deaths). By construction these partition deathsInt:
            //   deathsInt == killsInt + starvInt + ageInt.
            const int killsInt  = static_cast<int>(st.totalKills            - lastTotalKills);
            const int starvInt  = static_cast<int>(st.totalDeathsStarvation - lastTotalStarv);
            const int ageInt    = static_cast<int>(st.totalDeathsAge        - lastTotalAge);
            // Predator economy per-interval diffs (Stage B; all 0 in Stage A).
            const int pBirthsInt = static_cast<int>(st.totalPredatorBirths           - lastPredBirths);
            const int pStarvInt  = static_cast<int>(st.totalPredatorDeathsStarvation - lastPredStarv);
            const int pAgeInt    = static_cast<int>(st.totalPredatorDeathsAge         - lastPredAge);

            std::cout << "  step " << std::setw(7) << stepsDone << '/' << headlessSteps
                      << "  pop "  << std::setw(5) << st.population
                      << "  food " << std::setw(5) << st.food
                      << "  +"     << std::setw(4) << birthsInt
                      << " -"      << std::setw(4) << deathsInt
                      << std::fixed
                      << "  age "  << std::setprecision(1) << std::setw(5) << st.avgAge
                      << "  gLen " << std::setprecision(1) << std::setw(5) << st.avgGenomeLen
                      << "  div "  << std::setprecision(2) << st.geneticDiversity
                      << "  sp "   << std::setw(3) << st.species
                      << "  algn " << std::setprecision(2) << std::setw(5) << st.avgNeighborAlign;
            // Predator segment: only printed when predators are active, so the
            // default (no-predator) console output is byte-for-byte unchanged.
            if (st.predatorPop > 0) {
                std::cout << "  pred " << std::setw(3) << st.predatorPop
                          << "  kills " << std::setw(4) << killsInt
                          << "  pAlign " << std::setprecision(2) << std::setw(5) << st.avgPredatorAlign;
                // Stage B economy readout: mean predator energy + this interval's
                // predator births / deaths (the oscillator at a glance).
                if (world.cfg.predatorEconomy) {
                    std::cout << "  pE " << std::setprecision(1) << std::setw(6) << st.predatorAvgEnergy
                              << "  p+" << std::setw(3) << pBirthsInt
                              << " p-" << std::setw(3) << (pStarvInt + pAgeInt);
                    // v0.26.0, each only when its flag is on (so every
                    // existing configuration prints what it printed before):
                    // the floor's refills so far, and the mean speed trait.
                    if (world.cfg.predatorMinPopulation > 0)
                        std::cout << " pR" << st.totalPredatorReseeds;
                    if (world.cfg.predatorInheritance)
                        std::cout << "  pSpd " << std::setprecision(2) << st.predatorSpeedFactor;
                }
            }
            // Stage C (brain on only): this interval's predator readout.
            if (brain) {
                const predstats::Row pr = predstats::sample(world, fixedDt, predLast);
                if (st.predatorPop > 0)
                    std::cout << "  pGen " << std::setprecision(1) << pr.genMean
                              << " pLen " << std::setprecision(1) << pr.genomeLenMean
                              << " pAln " << std::setprecision(2) << pr.pursuitAlign;
                if (predCsv.is_open()) {
                    predCsv << predstats::row(stepsDone, pr) << "\n";
                    if ((rowsWritten + 1) % flushEvery == 0) predCsv.flush();
                }
                if (predWiring.is_open()) predWiring << predstats::wiringRow(stepsDone, world) << "\n";
                if (predLog) { predstats::drainLog(world, predLog); std::fflush(predLog); }
            }
            std::cout << "  ("     << std::setprecision(1) << elapsed << "s, "
                      << static_cast<long>(sps) << "/s)\n";

            if (csv) {
                csv << statsCsvRow(st, elapsed, sps, birthsInt, deathsInt,
                                   killsInt, starvInt, ageInt,
                                   pBirthsInt, pStarvInt, pAgeInt) << "\n";
                ++rowsWritten;
                // Periodic flush: keeps the on-disk file at most `flushEvery`
                // rows behind, so it is readable mid-run and a Ctrl-C loses at
                // most that many rows instead of the whole buffer.
                if (rowsWritten % flushEvery == 0) csv.flush();
            }

            if (wiringCsv) {
                float wf[NUM_SENSES]; wiring::fractions(world, wf);
                wiringCsv << stepsDone;
                for (int s = 0; s < NUM_SENSES; ++s) wiringCsv << ',' << wf[s];
                wiringCsv << "\n";
                if (rowsWritten % flushEvery == 0) wiringCsv.flush();
            }

            lastSampleTime  = now;
            lastSampleStep  = stepsDone;
            lastTotalBirths = st.totalBirths;
            lastTotalDeaths = st.totalDeaths;
            lastTotalKills  = st.totalKills;
            lastTotalStarv  = st.totalDeathsStarvation;
            lastTotalAge    = st.totalDeathsAge;
            lastPredBirths  = st.totalPredatorBirths;
            lastPredStarv   = st.totalPredatorDeathsStarvation;
            lastPredAge     = st.totalPredatorDeathsAge;
        };

        // Periodic checkpoints are written to <name>.<frame>.json so a long run
        // leaves a trail you can rewind to, rather than a single end state.
        auto writeCheckpoint = [&](const std::string& path) {
            std::string err;
            // The lineage log is on disk up to this frame before the checkpoint
            // is: a run killed after it loses nothing a resume would not redo.
            if (predLog) { predstats::drainLog(world, predLog); std::fflush(predLog); }
            if (!checkpoint::save(world, path, EVO_VERSION, err)) {
                std::cerr << "!! checkpoint failed: " << err << "\n";
                return false;
            }
            std::cout << "  checkpoint -> " << path << " (frame " << world.frame << ")\n";
            return true;
        };

        for (int i = 0; i < headlessSteps; ++i) {
            world.update(fixedDt);
            const int stepsDone = i + 1;
            if (stepsDone % logEvery == 0) sample(stepsDone);
            if (checkpointEvery > 0 && stepsDone % checkpointEvery == 0) {
                writeCheckpoint(checkpointBase + "." + std::to_string(world.frame) + ".json");
            }
        }
        // Always capture the final state, even if it isn't on an interval boundary.
        if (headlessSteps % logEvery != 0) sample(headlessSteps);

        if (!saveCheckpoint.empty() && !writeCheckpoint(saveCheckpoint)) return 1;

        const auto   endTime = std::chrono::steady_clock::now();
        const double total   = std::chrono::duration<double>(endTime - startTime).count();
        std::cout << "Headless done. " << headlessSteps << " steps in "
                  << std::fixed << std::setprecision(1) << total << "s ("
                  << static_cast<long>(headlessSteps / std::max(1e-9, total)) << " steps/sec)\n";
        if (csv) {
            csv.close();
            std::cout << "Wrote " << rowsWritten << " rows to " << csvPath << "\n";
        }
        if (wiringCsv) {
            wiringCsv.close();
            std::cout << "Wrote sensor-wiring log to " << clusterStem << ".wiring.csv\n";
        }
        if (predCsv.is_open()) {
            predCsv.close();
            std::cout << "Wrote predator metrics to " << clusterStem << ".predators.csv\n";
        }
        if (predWiring.is_open()) predWiring.close();
        if (predLog) {
            predstats::drainLog(world, predLog);
            std::fclose(predLog);
            std::cout << "Wrote predator lineage log to " << clusterStem << ".predlog.csv\n";
        }

        if (noRender) {
            if (world.cfg.profile) world.dumpProfile();
            if (world.cfg.clusterMap) {
                auto [cpath, spath] = clustermap::write(world, clusterStem);
                if (!spath.empty())
                    std::cout << "Wrote death-cluster map: " << spath
                              << " (+ " << cpath << ", " << world.deathLog.size()
                              << " of " << world.totalDeathsLogged_ << " deaths)\n";
            }
            // Reproduction-graph archive. Same headless-only rule as the cluster
            // map: these are end-of-run analysis products, not live outputs.
            if (world.cfg.reproLog) {
                const std::string bpath = clusterStem + ".births.csv";
                const std::filesystem::path bp(bpath);
                if (bp.has_parent_path()) std::filesystem::create_directories(bp.parent_path());
                std::ofstream bcsv(bpath);
                if (bcsv) {
                    const std::size_t n = birthlog::write(bcsv, world);
                    bcsv.close();
                    std::cout << "Wrote birth log: " << bpath << " (" << n
                              << " of " << world.totalBirthsLogged_ << " births)\n";
                } else {
                    std::cerr << "Could not open " << bpath << " for writing.\n";
                }
            }
            return 0;
        }
        std::cout << "Opening window...\n";
    }

    // The live neural inspector captures per-step activations; only needed now that
    // a window is opening (headless paid nothing for it).
    world.cfg.captureActivations = true;
    // The predator lineage log is drained only by the headless loop above.
    world.cfg.predatorLog = false;
    world.predLog_.clear();

    // --- Visual phase: drive the simulation through the renderer interface ---
    std::unique_ptr<IRenderer> renderer =
        std::make_unique<SfmlRenderer>(W, H, "evo_boids — evolved flocking");

    bool paused = false;
    bool turbo  = false;         // headless burst mode ([T], mirrors the web's Turbo)
    float turboStepsPerSec = 0.0f;
    int simSpeed = 1;  // how many sim steps per rendered frame

    // Fixed timestep, identical to the headless phase and the web frontend.
    // The old wall-clock dt made windowed sessions unrepeatable; with a fixed
    // dt the state at frame N is the same state every frontend computes.
    const float fixedDt = 0.016f;

    // [S] writes "<base>.<frame>.json" using the same base rules as
    // --checkpoint-every (--save-checkpoint path, else runs/<name>, else
    // runs/checkpoint), so windowed and headless checkpoints land together.
    auto windowCheckpointPath = [&]() {
        std::string base = !saveCheckpoint.empty() ? saveCheckpoint
                         : (!runName.empty() ? ("runs/" + runName) : std::string("runs/checkpoint"));
        if (base.size() > 5 && base.compare(base.size() - 5, 5, ".json") == 0)
            base.resize(base.size() - 5);
        const auto parent = std::filesystem::path(base).parent_path();
        if (!parent.empty()) std::filesystem::create_directories(parent);
        return base + "." + std::to_string(world.frame) + ".json";
    };

    // FPS counter (SFML-free, wall-clock based)
    int fps = 0;
    int frameCount = 0;
    auto fpsClock = std::chrono::steady_clock::now();

    while (renderer->isOpen()) {
        InputEvents ev = renderer->poll();
        if (ev.quit) break;
        if (ev.togglePause) paused = !paused;
        if (ev.speedUp)   simSpeed = std::min(simSpeed + 1, 50);
        if (ev.speedDown) simSpeed = std::max(simSpeed - 1, 1);
        if (ev.toggleTurbo) turbo = !turbo;
        if (ev.saveCheckpoint) {
            const std::string path = windowCheckpointPath();
            std::string err;
            if (checkpoint::save(world, path, EVO_VERSION, err))
                std::cout << "  checkpoint -> " << path << " (frame " << world.frame << ")\n";
            else
                std::cerr << "!! checkpoint failed: " << err << "\n";
        }

        // Simulate. Turbo = flat-out adaptive chunks (~200 ms of stepping per
        // rendered frame, so the window stays responsive at ~5 fps while the
        // sim runs at full speed); normal = simSpeed steps per rendered frame.
        if (!paused) {
            if (turbo) {
                const auto t0 = std::chrono::steady_clock::now();
                int steps = 0;
                float elapsed = 0.0f;
                do {
                    world.update(fixedDt);
                    ++steps;
                    elapsed = std::chrono::duration<float>(
                        std::chrono::steady_clock::now() - t0).count();
                } while (elapsed < 0.2f);
                turboStepsPerSec = (float)steps / elapsed;
            } else {
                for (int s = 0; s < simSpeed; ++s) {
                    world.update(fixedDt);
                }
            }
        }

        // FPS counter
        frameCount++;
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration<float>(now - fpsClock).count() >= 1.0f) {
            fps = frameCount;
            frameCount = 0;
            fpsClock = now;
        }

        // Assemble HUD data from the simulation state
        float avgGenome = 0;
        for (const auto& c : world.creatures) avgGenome += c.genome.size();
        if (!world.creatures.empty()) avgGenome /= world.creatures.size();

        HudInfo hud;
        hud.population = world.creatures.size();
        hud.food       = world.food.size();
        hud.predators  = world.predators.size();
        hud.frame      = world.frame;
        hud.births     = world.births;
        hud.deaths     = world.deaths;
        hud.avgGenome  = avgGenome;
        const GenerationSpan gen = generationSpan(world);
        hud.genMean    = (float)gen.mean;
        hud.genMax     = gen.max;
        hud.simSpeed   = simSpeed;
        hud.fps        = fps;
        hud.paused     = paused;
        hud.turbo      = turbo;
        hud.stepsPerSec = turbo ? turboStepsPerSec : 0.0f;

        renderer->render(world, hud);
    }

    return 0;
}
