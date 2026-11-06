#pragma once
#include <cmath>
#include <string>
#include <sstream>
#include "genome.hpp"  // GENOME_* defaults — single source of truth for bounds

// ----------------------------------------------------------------------------
// SimConfig — runtime-tunable simulation parameters.
//
// Every default below equals the value that used to be hard-coded, so a run
// with no flags behaves exactly as before. World holds one of these (World::cfg)
// and reads from it instead of compile-time constants, so these can be set from
// the command line without recompiling.
//
// Deliberately NOT exposed (structural, not tuning knobs): NUM_SENSES /
// NUM_ACTIONS (sensor/action enums) and MAX_INTERNAL_NEURONS (sizes the neural
// net and the stats connectivity grid at compile time).
// ----------------------------------------------------------------------------
struct SimConfig {
    // --- World topology ---
    // Toroidal perception (opt-in, off = byte-identical historical behaviour).
    // Positions have ALWAYS wrapped; this makes the SENSES wrap too: neighbour/
    // food/predator queries and offsets use minimum-image distances across the
    // seam, the pheromone grid deposits and reads wrap, the long probe looks
    // through the seam, and the boundary sensors report "no wall anywhere"
    // (a torus has no walls). Without it the seam is a sensory cliff — an
    // edge-band creature perceives roughly HALF its true neighbours (measured:
    // 3.0 seen vs 5.8 physically within range), which breeds wall-hugging
    // phenotypes. Currents stay non-toroidal (the ocean is a bounded basin;
    // a wrapped traveller feels a small velocity discontinuity at the seam).
    bool toroidal = false;

    // --- Match distance (opt-in, off = byte-identical prior behaviour) ---
    // A pair whose genomes are farther apart than this in the folded
    // (source,sink) connectivity space emits no successor record; every other
    // precondition in doInteraction case 2 is unchanged. <0 = off, no gate.
    // (Precedent for "negative means disabled": predatorMoveCost below.)
    //
    // The metric is genomeDistanceSq() in isolation.hpp — NOT genomeSimilarity(),
    // which is positionally aligned and collapses on a single indel (see the
    // comment there). Measured scale, so the number means something: unrelated
    // random genomes sit ~19.5 apart, a successor sits ~13.8 from its source when
    // the live set is unstructured, and a mutated clone sits ~0. A threshold below
    // the live set's own pair distance stops essentially all insertion, so the
    // interesting window is narrow and load-dependent — see the research log's
    // v0.21.0 entry before picking a value.
    float reproMaxDistance = -1.0f;

    // --- Match-distance mitigations (opt-in; both are INERT unless
    // reproMaxDistance >= 0, and both off = byte-identical prior behaviour) ---
    //
    // Soft gate: the width of a linear acceptance ramp ABOVE reproMaxDistance,
    // in the same folded-connectivity units. With T = reproMaxDistance and
    // W = reproSoftWidth > 0 a pair at distance d is admitted iff
    // u * W < (T + W) - d for one fresh uniform draw u (softGateAccepts,
    // isolation.hpp): d <= T still always breeds, d >= T + W never does, and
    // the cliff at T becomes a ramp in between. <= 0 = off = the exact v0.21
    // hard threshold, which draws NOTHING; with W > 0 every gate evaluation
    // draws exactly one uniform, so the random stream — and every archived
    // gated run — is only perturbed when the knob is actually on. Why it
    // exists: the measured window is narrow and collapse is bistable at T ~ 16
    // and total below ~14, so a hard cliff there admits nothing at all while a
    // ramp keeps a low but nonzero pairing rate either side of it.
    float reproSoftWidth = 0.0f;

    // Refill grace: a FOUNDER younger than this bypasses the gate entirely —
    // no fold, no draw — if either partner qualifies. Founder means
    // lineageId == id, which is true of the initial spawn and of every
    // reseed-floor injection and never of a child (it inherits the maternal
    // line), so this needs no new creature state: lineageId and age are both
    // serialized already. <= 0 = off, and <= 5 is inert as well because
    // kernel::pairingAllowed requires age > 5 before the gate is reached at all.
    // Why it exists: under a tight gate the --min-pop reseed floor becomes a
    // diversity pump that cannot reproduce — random founders sit ~19.5 from
    // everyone, so they eat, never pair, and pin the population on the floor.
    // Grace lets a fresh founder enter the pool once; its descendants are
    // gated like everyone else from birth.
    float reproGracePeriod = 0.0f;

    // --- Tier-1 body model (opt-in, off = byte-identical prior behaviour) ---
    // Two heritable per-creature parameters (Creature::bodySize/bodyElong) that
    // modulate the existing speed / turn / metabolism model — see
    // body_model.hpp for the factors and why they are exact at the defaults.
    // With it on, maxSpeed below stops being a hard cap and becomes the ceiling
    // of a DEFAULT body (a small body's ceiling reaches 1.333 * maxSpeed).
    //
    // bodyModel is a HARD master switch, not just a scaling of 0: it is what
    // gates the two rng draws per insertion. With it off the body parameters
    // never leave 1.0 and the random stream is bit-for-bit the pre-0.23 one, so
    // every run in the existing corpus stays reproducible. Founders and reseeded
    // creatures always start at 1.0 even with the flag ON (diversity comes from
    // mutation, and it keeps the --min-pop reseed floor from injecting extreme
    // bodies into a struggling population).
    bool  bodyModel    = false;
    // Uniform mutation half-width applied to each parameter at each insertion:
    // child = clamp(mean(parents) + U(-bodyMutation, +bodyMutation), 0.5, 2.0).
    // Uniform, not Gaussian, and no rejection loop — the draw COUNT has to be
    // input-independent or the two builds' random streams diverge.
    float bodyMutation = 0.10f;

    // --- Population ---
    int minPopulation = 50;   // reseed floor: random creatures injected below this
    int maxPopulation = 0;    // hard birth cap (0 = unlimited)

    // --- Food ---
    int   targetFood    = 600;   // baseline food count (hard cap is 2x this)
    float foodSpawnBase = 3.0f;  // mean food spawned per step
    float foodSpawnAmp  = 2.0f;  // sinusoidal abundance swing around the base
    float foodEnergy    = 5.0f;  // energy gained per food eaten
    float pickupRadius  = 10.0f; // distance within which food is eaten

    // --- Energy / lifespan (selection pressure) ---
    float metabolicRate = 1.5f;   // energy burned per second (fixed, per creature)
    float geneCost      = 0.0f;   // extra energy/sec per gene (parsimony pressure; 0 = off)
    float moveCost      = 0.0f;   // kinetic cost: extra energy/sec = moveCost * speed^2
                                  // (0 = off => speed is free, reproducing prior behavior;
                                  //  >0 makes thrust expensive, so there's an interior
                                  //  optimal cruise speed and riding a current can pay)
    float maxAge        = 120.0f; // death age
    float reproEnergy   = 20.0f;  // energy each parent needs to reproduce
    float newbornEnergy = 25.0f;  // starting energy of a child

    // --- Sensing / interaction ranges ---
    float perceptionRadius = 80.0f; // neighbour/food sensing radius (also grid cell)
    float interactRadius   = 20.0f; // social-interaction range

    // Topological interaction cap: attend to at most the N NEAREST neighbours
    // inside perceptionRadius rather than every one of them. 0 = off = metric
    // interaction (attend to all), which is the historical behaviour and is
    // preserved byte-for-byte.
    //
    // WHY THIS IS A MODEL IMPROVEMENT, NOT JUST A SPEED KNOB: real schooling and
    // flocking animals interact topologically, not metrically. Ballerini et al.
    // (PNAS 2008) showed starlings track a fixed ~6-7 nearest neighbours
    // regardless of flock density, and fish studies find an even smaller
    // effective set — Katz et al. (PNAS 2011) and Herbert-Read et al. (PNAS
    // 2011) both find golden shiner / mosquitofish motion is explained largely
    // by the 1-2 nearest neighbours. A metric rule makes a fish in a dense
    // school average over ~150 neighbours, which no real animal does (and which
    // is what makes dense worlds expensive here).
    //
    // 7 is the recommended setting (--topological): the canonical Ballerini
    // number, and the conservative end of the fish range, so it constrains
    // attention without discarding the schooling signal. Set 1-4 to test the
    // stronger fish-specific claim.
    //
    // Only the per-neighbour INTERACTION terms are capped (average neighbour
    // offset/heading, fore-aft and left-right population balance). The density
    // percepts NEIGHBOR_COUNT and POPULATION_DENSITY still see the true count
    // inside the radius, since crowding is something a fish genuinely senses
    // and evolution should keep access to it.
    int maxNeighbors = 0;

    // --- Cooldowns ---
    float reproCooldown    = 3.0f;
    float interactCooldown = 2.0f;

    // --- Movement ---
    float minSpeed = 30.0f;
    float maxSpeed = 150.0f;
    // Triangular action space (opt-in; off = original decoupled steer/speed model).
    // When on, the net commands a forward DRIVE and a TURN, and the feasible turn is
    // throttled by drive: turnEff = turn*(1 - drive). This realises the triangular
    // (forward, turn) feasible region of Malik/Singh/Harpaz/Engert/Rajan 2025
    // (arXiv:2510.03699, Fig 1d / S2.1): "larger forward speeds permit only smaller
    // turns" — apex at max drive (strike, no turn), base at zero drive (free turn).
    // NOTE the paper's clean strike/reorient bout split emerges under their FULL
    // constraint set (this coupling + linear hinge speed/turn costs + binocular sensing
    // + vergence cost) trained with PPO; the coupling alone is necessary, not sufficient,
    // and our setting is evolutionary not RL — so bimodality is not guaranteed here yet.
    // Their model is bout-based (125 ms); ours integrates heading continuously per step.
    // For their exact triangle (near-zero forward during a reorient) pair with --min-speed 0.
    // Drive maps to speed in [minSpeed, maxSpeed]; turn to heading change up to maxTurnRate.
    bool  triangularMotion = false;
    float maxTurnRate = 4.0f;   // max heading change (rad/s) at zero forward drive

    // --- Genome ---
    int   genomeMinLength = GENOME_MIN_LENGTH;   // hard lower bound on gene count
    int   genomeMaxLength = GENOME_MAX_LENGTH;   // hard upper bound on gene count
    int   genomeInitMin   = GENOME_INITIAL_MIN;  // initial gene-count range (low)
    int   genomeInitMax   = GENOME_INITIAL_MAX;  // initial gene-count range (high)
    float mutationMultiplier = 1.0f;             // scales the per-birth mutation rate

    // --- Currents (ocean flow; off by default) ---
    float currentStrength = 0.0f;   // peak flow speed, world units/sec (0 = off)
    int   currentMode     = 0;      // 0 = eddies (moving vortices), 1 = double-gyre
    int   currentEddies   = 5;      // [eddies] number of vortices ("eyes")
    float currentCore     = 150.0f; // [eddies] eddy radius (peak speed at this distance)
    float currentDrift    = 1.0f;   // how fast the field evolves (0 = static)
    float currentGyreEps  = 0.25f;  // [gyre] how far the dividing line oscillates

    // --- Spatial food (off by default => uniform spawn, static food) ---
    int   foodPatches     = 0;      // number of food patches (0 = uniform random)
    float foodPatchRadius = 120.0f; // spread of food around each patch centre
    bool  foodDrift       = false;  // advect food with the current (forms filaments)

    // --- Predator (Stage A: scripted, immortal, fixed-count; OFF by default) ---
    // predatorCount 0 => no predators => the no-predator baseline (unchanged
    // dynamics aside from the bumped NUM_SENSES, which is the expected fresh
    // genome baseline). All of these are the Stage A tuning knobs: the goal is
    // to find the speed/radius/cooldown window where evasion appears in the prey
    // AND neither side goes extinct (see context §9).
    int   predatorCount         = 0;      // number of predators (0 = none)
    float predatorPerception    = 150.0f; // predator's prey-detection radius. LARGER than
                                          // the prey's --perception (80) => ambush
                                          // asymmetry; set equal for symmetric sensing.
    float predatorSpeed         = 110.0f; // predator cruise speed. Prey calm cruise is ~82
                                          // under move-cost 7e-5 (so a predator out-cruises
                                          // a foraging prey), but prey can sprint to
                                          // --max-speed (150) to flee at a quadratic energy
                                          // cost => a real chase/escape tension.
    float predatorCaptureRadius = 14.0f;  // contact distance at which a prey is caught
                                          // (a touch larger than the food --pickup-radius).
    float predatorCooldown      = 3.0f;   // digestion cooldown (s) after a capture: caps
                                          // each predator's kill rate (first anti-spiral knob).

    // --- Predator energy economy (Stage B: predators starve / reproduce; OFF by
    // default => Stage A immortal/fixed-count is preserved byte-for-byte). When
    // predatorEconomy is true, a predator gains energy per capture, burns
    // metabolism + a kinetic move-cost per second, buds a child above
    // predatorReproEnergy and dies below 0 energy (and optionally past
    // predatorMaxAge). The whole point is the coupled oscillator: prey crash ->
    // predators starve -> predator decline -> prey rebound -> predators recover.
    // TUNE meal/metabolism/repro on real runs until NEITHER population's trough
    // hits zero (by default there is no predator reseed floor — extinction is
    // an observable failure mode, not something to mask; the opt-in
    // predatorMinPopulation below masks it on purpose, and counts every
    // predator it adds). See context §9/§11.
    // NOTE: Stage B adds NO sensors, so NUM_SENSES is unchanged (41) and 0.9.x
    // predator runs stay comparable. (Genome/neural predators are Stage C.)
    bool  predatorEconomy       = false;  // master switch: false => Stage A (immortal)
    float predatorMetabolism    = 2.0f;   // predator fixed energy burn/sec (prey: 1.5)
    float predatorMoveCost      = -1.0f;  // predator kinetic cost/sec = coeff*speed^2.
                                          // <0 => reuse the prey --move-cost coefficient;
                                          // >=0 => predator-specific coefficient.
    float predatorReproEnergy   = 60.0f;  // energy needed to bud a child
    float predatorNewbornEnergy = 30.0f;  // child's starting energy (and the initial
                                          // predators' energy); the parent pays this on
                                          // each birth (energy-conserving budding).
    float predatorMeal          = -1.0f;  // energy gained per capture. <0 => absorb the
                                          // victim's foodReserves (the lean: carnivory is
                                          // calorie-dense, and the spiral-prone lever to
                                          // tune); >=0 => a fixed meal value (gentler).
    float predatorMaxAge        = 0.0f;   // predator death age. 0 => immortal-until-starved
                                          // (the lean); >0 => predators also die of old age.

    // --- Predator floor, ceiling and heritable traits (v0.26.0; economy only;
    // OFF by default => byte-identical to 0.25.0) ---
    // predatorMinPopulation is the predators' --min-pop: after each step's
    // births and deaths, fresh scripted predators (random position and heading,
    // predatorNewbornEnergy, traits 1.0/1.0) are added until at least this many
    // are alive. 0 = off: extinction stays final. Three rng draws per refilled
    // predator, and none unless the floor actually refills, so a run that never
    // falls below it is unchanged. Every refill is counted
    // (World::totalPredatorReseeds, CSV predator_reseeds_cum): a run held up by
    // the floor is not evidence of coexistence, and the column says how much
    // holding up it did.
    int   predatorMinPopulation = 0;
    // predatorMaxPopulation is the predators' --max-pop: a predator that has
    // reached its budding threshold does not bud while this many are alive
    // (counted with this step's buds, exactly like the prey cap); it keeps the
    // energy and buds once there is room. 0 = no cap. Draws nothing — a refused
    // bud takes no draws, which is the same as no bud. The floor is not capped:
    // a floor above the ceiling wins.
    int   predatorMaxPopulation = 0;
    // predatorInheritance: a bud inherits its parent's speedFactor and
    // buddingFactor (predator.hpp), each plus one U(-m, +m) draw, clamped to
    // [0.5, 2.0], m = predatorTraitMutation. Off => no draws and every trait
    // stays 1.0. Speed only has a price when the kinetic cost is non-zero
    // (--predator-move-cost, or a --move-cost it reuses): with both at 0,
    // faster is free and selection walks speed to the clamp.
    bool  predatorInheritance   = false;
    float predatorTraitMutation = 0.10f;  // uniform half-width per trait per bud (the
                                          // --body-mutation default)

    // --- Stage C: neural predators (v0.27.0; OFF by default => a run writes and
    // computes exactly what 0.26.0 did — no CSV column, no sidecar line, no
    // checkpoint key) ---
    // predatorBrain replaces the scripted hunt with a network built from each
    // predator's genome (predator_brain.hpp: 21 inputs, TURN and THRUST out).
    // With predatorEconomy a bud inherits its parent's genome with a mutation, so
    // the predators evolve; without it they are immortal, fixed-count neural
    // hunters that never bud, with their energy and age pinned (ENERGY and AGE
    // read 0: the "frozen-newborn" assay). predatorFrozen (with the economy) is
    // the default assay mode: energy and age are accounted, nobody dies or buds.
    // Capture, the cooldown and the meal are Stage B's. A floor refill is a
    // random-genome founder. Its draws (genomes, mutation, the RANDOM input) come
    // from WorldCommon::predRng_; every draw Stage B made stays where it was.
    bool  predatorBrain    = false;
    float predatorMutation = 1.0f;   // multiplies the per-bud mutation rate (the prey's
                                     // rate lottery, kernel::inheritGenome); >= 0
    float predatorTurnRate = 4.0f;   // rad/s at |TURN| = 1 (the prey's maxTurnRate default)
    float predatorMinSpeed = 0.0f;   // THRUST's floor; 0 lets a predator stop (ambush).
                                     // The ceiling is predatorSpeed * speedFactor.
    bool  predatorPrimer   = false;  // founders' genomes start with two "pursuit primer"
                                     // genes (PREY_LR -> TURN, PREY_PROX -> THRUST); off =
                                     // random genomes (the default)
    bool  predatorFrozen   = false;  // [brain + economy] the frozen assay (transplant.hpp,
                                     // --assay frozen): energy and age are accounted (burn,
                                     // meals, ageing) so ENERGY and AGE keep their evolved
                                     // range, but nobody starves, ages out or buds: at the
                                     // budding threshold, holding at least the newborn
                                     // energy, a predator pays it for a "virtual bud" (no
                                     // child; counted), age wraps modulo predatorMaxAge
                                     // (when > 0), energy is floored at 0.
                                     // No draws. Brain predators only.

    // --- Inspection & analysis (visual/diagnostic; do not affect dynamics) ---
    // Capture each creature's last sensor inputs / action outputs every step so a
    // click-selected creature's neural net can be drawn "firing live". Off by
    // default (zero cost in headless); main turns it on when there is a window.
    bool captureActivations = false;
    // Pairing graph — the INDEPENDENT grouping measure (repro_graph.hpp).
    // The `species` column is a SimHash of the same folded connectivity vector
    // the match-distance gate thresholds, so using it to evaluate the gate is
    // circular; worse, it is empirically SATURATED (it tracks the live-set count
    // almost one-to-one, i.e. it counts individual Creatures). An edge here
    // exists because two Creatures actually produced a successor record
    // together, which is mechanism-level and cannot be circular.
    //
    // reproWindow / reproMinCluster drive the always-on repro_components CSV
    // column. reproLog / reproLogMax are the opt-in <stem>.births.csv archive,
    // shaped exactly like clusterMap / clusterMax.
    int  reproWindow     = 2000;  // trailing events in the graph (0 = disable the column)
    int  reproMinCluster = 3;     // ignore components smaller than this (a one-off
                                  // pairing is not a group)
    bool reproLog        = false; // write <stem>.births.csv at end of run (headless)
    int  reproLogMax     = 20000; // max event records kept in RAM (decimated above this)
    // Stage C: stream every predator founding, bud, refill and death to
    // <stem>.predlog.csv (headless, needs predatorBrain). Never decimated: a
    // decimated tree is not a phylogeny. Not world state, so not serialized.
    bool predatorLog     = false;

    // Death-cluster map: log a 2-D projection of each dead creature's network and
    // write <name>.deaths.csv + <name>.cluster.svg at end of run. Off by default
    // (keeps default runs byte-for-byte and allocation-free). See world.hpp.
    bool clusterMap   = false;
    int  clusterMax   = 20000;  // max points kept in RAM (uniform decimation above this)
    int  clusterEpoch = 1000;   // deaths per colour band ("changes gradient every N")
    bool clusterPca   = false;  // map axes = PCA over the death sketches (per-run,
                                // variance-aligned) instead of the fixed random map.
    int  clusterColor = 0;      // 0 = colour by epoch (time); 1 = colour by lineage (clade)
    // Per-sensor wiring frequency over time -> <name>.wiring.csv (one row per log
    // interval: fraction of the population whose genome wires each sensor as a
    // source). Headless only, off by default. Reveals which sensors selection
    // recruits as the run evolves (e.g. predator/neighbour sensors under predation).
    bool wiringLog = false;
    // Phase profiler: accumulate per-phase timings in World and print at end of run
    // (build / parallel{gather,feedForward,apply} / serial). Diagnostic only.
    bool profile = false;

    // --- Numerics ---
    // Swap std::tanh for a rational approximation in the neural net (see
    // fastTanhApprox in genome.hpp). std::tanh is >half of feedForward's cost
    // because every creature makes MAX_INTERNAL_NEURONS + NUM_ACTIONS calls per
    // step no matter how small its genome, so this is the single largest
    // remaining speedup — but it CHANGES THE NUMBERS (|error| <= 1.0e-4 per
    // activation, which a chaotic sim amplifies into different trajectories).
    //
    // Off by default: runs must stay comparable with the existing corpus. Turn
    // it on for exploratory sweeps where throughput matters more than
    // continuity, and treat the results as a separate numerical lineage —
    // record it in the run sidecar (dump() does) and re-confirm any headline
    // finding with it off. It does NOT bias the dynamics (the approximation is
    // symmetric and monotone), but individual runs will not match.
    bool fastTanh = false;

    // Human-readable dump for run logs and the per-run sidecar file.
    std::string dump() const {
        const std::string maxPop =
            (maxPopulation > 0) ? std::to_string(maxPopulation) : std::string("unlimited");
        std::ostringstream o;
        o << "toroidal="          << (toroidal ? "on (wrap-around senses)" : "off (bounded plane)") << "\n"
          << "reproMaxDistance="  << (reproMaxDistance < 0.0f
                                      ? std::string("off (no genetic gate)")
                                      : std::to_string(reproMaxDistance)) << "\n"
          << "reproSoftWidth="    << (reproSoftWidth <= 0.0f
                                      ? std::string("off (hard gate)")
                                      : std::to_string(reproSoftWidth))
          << " reproGracePeriod=" << (reproGracePeriod <= 0.0f
                                      ? std::string("off (no founder grace)")
                                      : std::to_string(reproGracePeriod)) << "\n"
          << "bodyModel="         << (bodyModel ? "on (heritable size/elongation)" : "off")
          << " bodyMutation="     << bodyMutation << "\n"
          << "minPopulation="     << minPopulation
          << " maxPopulation="    << maxPop << "\n"
          << "targetFood="        << targetFood
          << " foodSpawnBase="    << foodSpawnBase
          << " foodSpawnAmp="     << foodSpawnAmp
          << " foodEnergy="       << foodEnergy
          << " pickupRadius="     << pickupRadius << "\n"
          << "metabolicRate="     << metabolicRate
          << " geneCost="         << geneCost
          << " moveCost="         << moveCost
          << " maxAge="           << maxAge
          << " reproEnergy="      << reproEnergy
          << " newbornEnergy="    << newbornEnergy << "\n"
          << "perceptionRadius="  << perceptionRadius
          << " interactRadius="   << interactRadius
          << " maxNeighbors="     << (maxNeighbors > 0
                                      ? std::to_string(maxNeighbors) + " (topological)"
                                      : std::string("unlimited (metric)"))
          << " reproCooldown="    << reproCooldown
          << " interactCooldown=" << interactCooldown << "\n"
          << "fastTanh="          << (fastTanh ? "on (approx activations)" : "off (std::tanh)") << "\n"
          << "minSpeed="          << minSpeed
          << " maxSpeed="         << maxSpeed << "\n"
          << "triangularMotion="  << (triangularMotion ? "on" : "off")
          << " maxTurnRate="      << maxTurnRate << "\n"
          << "genomeLength="      << genomeMinLength << ".." << genomeMaxLength
          << " genomeInit="       << genomeInitMin << ".." << genomeInitMax
          << " mutationMultiplier=" << mutationMultiplier << "\n"
          << "currentStrength="   << currentStrength
          << " currentMode="      << (currentMode == 1 ? "gyre" : "eddies")
          << " currentEddies="    << currentEddies
          << " currentCore="      << currentCore
          << " currentDrift="     << currentDrift
          << " currentGyreEps="   << currentGyreEps << "\n"
          << "foodPatches="       << foodPatches
          << " foodPatchRadius="  << foodPatchRadius
          << " foodDrift="        << (foodDrift ? "on" : "off") << "\n"
          << "predatorCount="     << predatorCount
          << " predatorPerception=" << predatorPerception
          << " predatorSpeed="    << predatorSpeed
          << " predatorCaptureRadius=" << predatorCaptureRadius
          << " predatorCooldown=" << predatorCooldown << "\n"
          << "predatorEconomy="   << (predatorEconomy ? "on" : "off")
          << " predatorMetabolism=" << predatorMetabolism
          << " predatorMoveCost=" << (predatorMoveCost < 0.0f
                                      ? std::string("reuse(") + std::to_string(moveCost) + ")"
                                      : std::to_string(predatorMoveCost))
          << " predatorReproEnergy=" << predatorReproEnergy
          << " predatorNewbornEnergy=" << predatorNewbornEnergy
          << " predatorMeal="     << (predatorMeal < 0.0f
                                      ? std::string("absorb-reserves")
                                      : std::to_string(predatorMeal))
          << " predatorMaxAge="   << (predatorMaxAge > 0.0f
                                      ? std::to_string(predatorMaxAge)
                                      : std::string("immortal")) << "\n"
          << "predatorMinPopulation=" << (predatorMinPopulation > 0
                                      ? std::to_string(predatorMinPopulation)
                                      : std::string("off (no predator floor)"))
          << " predatorMaxPopulation=" << (predatorMaxPopulation > 0
                                      ? std::to_string(predatorMaxPopulation)
                                      : std::string("unlimited"))
          << " predatorInheritance=" << (predatorInheritance ? "on (heritable speed/budding)" : "off")
          << " predatorTraitMutation=" << predatorTraitMutation << "\n"
          << "reproWindow="       << reproWindow
          << " reproMinCluster="  << reproMinCluster
          << " reproLog="         << (reproLog ? "on" : "off")
          << " reproLogMax="      << reproLogMax;
        // Stage C, only when on: an off run's sidecar reads as 0.26.0's did.
        if (predatorBrain)
            o << "\npredatorBrain=on (neural predators)"
              << " predatorMutation=" << predatorMutation
              << " predatorTurnRate=" << predatorTurnRate
              << " predatorMinSpeed=" << predatorMinSpeed
              << " predatorPrimer="   << (predatorPrimer ? "on" : "off")
              << " predatorFrozen="   << (predatorFrozen ? "on (no deaths, no buds)" : "off")
              << " predatorLog="      << (predatorLog ? "on" : "off");
        return o.str();
    }
};

// The Stage C knobs every frontend and the checkpoint loader refuse, on the
// terms the other mutation knobs are refused (finite and >= 0; negated tests
// because NaN compares false to everything). Checked whatever predatorBrain
// says, so a value is never accepted now and refused once the brain goes on.
// nullptr when the config is fine.
inline const char* predatorBrainConfigError(const SimConfig& c) {
    if (!(c.predatorMutation >= 0.0f) || !std::isfinite(c.predatorMutation))
        return "predatorMutation must be finite and >= 0";
    if (!(c.predatorTurnRate >= 0.0f) || !std::isfinite(c.predatorTurnRate))
        return "predatorTurnRate must be finite and >= 0";
    if (!(c.predatorMinSpeed >= 0.0f) || !std::isfinite(c.predatorMinSpeed))
        return "predatorMinSpeed must be finite and >= 0";
    // With the brain on, a floor above the cruise would silently raise the
    // ceiling (predbrain::topSpeed takes the max): refuse it instead.
    if (c.predatorBrain && c.predatorMinSpeed > c.predatorSpeed)
        return "predatorMinSpeed must not exceed predatorSpeed";
    return nullptr;
}
