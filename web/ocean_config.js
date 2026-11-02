"use strict";
/* evo_boids 3-D Ocean: the settings the page offers (web/ocean.js builds the
 * sheet from these), their explanations, and 🎲 Randomize's ranges.
 *
 * Every key is an oc_init cfg key (SimConfig's checkpoint names, or
 * OceanConfig's: src/ocean/ocean_config.hpp) except seed / population / depth,
 * which are oc_init's own arguments. Defaults are the Ocean's: SimConfig's,
 * then applyOceanDefaults (perceptionRadius 100, interactRadius 36,
 * pickupRadius 24, targetFood 2400), then OceanConfig's. The page sends only
 * keys that differ from these, so an untouched sheet is the tuned world.
 *
 * LIVE is oc_set_param's whitelist (wasm/ocean_wasm.cpp kOcean + kLive):
 * those apply to the running world at once, everything else on Restart.
 * No page code here. */
(function (root) {
  /* key: [default, {step, min, max, int, options, bit}]
   *   boolean default = a switch (JSON true / false); bit = a switch that is
   *   an int key (JSON 0 / 1); options = a select (int value) */
  var KEYS = {
    seed: [42, { step: 1, min: 0, int: true }], population: [300, { step: 1, min: 0, int: true }],
    depth: [240, { step: 10, min: 10, max: 100000 }],
    /* the tank's size across (oc_init's width / height arguments, like depth: not cfg keys) */
    width: [1920, { step: 10, min: 100, max: 100000, int: true }], height: [1080, { step: 10, min: 100, max: 100000, int: true }],
    /* glass walls: the ENGINE's default is off (and so is every link and setup
     * made before walls existed); a fresh page starts with FRESH.walls */
    walls: [false], sideWallBand: [80, { step: 5, min: 0, max: 100000 }], sideWallTurnRate: [6, { step: 0.5, min: 0, max: 1000 }],
    toroidal: [false], bodyModel: [false],
    maxPopulation: [0, { step: 1, min: 0, int: true }], minPopulation: [50, { step: 1, min: 0, int: true }],
    minSpeed: [30], maxSpeed: [150], triangularMotion: [false], maxTurnRate: [4],
    perceptionRadius: [100], interactRadius: [36], maxNeighbors: [0, { step: 1, min: 0, int: true }],
    fastTanh: [false],
    foodPatches: [0, { step: 1, min: 0, int: true }], foodPatchRadius: [120], targetFood: [2400, { step: 1, min: 0, int: true }],
    foodSpawnBase: [3], foodSpawnAmp: [2], foodEnergy: [5], pickupRadius: [24], foodDrift: [false],
    foodLife: [0, { step: 5, min: 0 }],
    foodDepthMode: [0, { options: ["Anywhere in depth", "Each patch at its own depth"] }], foodDepthSpread: [30, { min: 0 }],
    metabolicRate: [1.5], moveCost: [0, { step: 0.00001, min: 0 }], geneCost: [0, { step: 0.001, min: 0 }],
    maxAge: [120], reproEnergy: [20], newbornEnergy: [25],
    mutationMultiplier: [1, { step: 0.1, min: 0 }], genomeInitMin: [24, { int: true }], genomeInitMax: [48, { int: true }],
    genomeMinLength: [16, { int: true }], genomeMaxLength: [80, { int: true }],
    reproMaxDistance: [-1, { step: 0.5 }], reproSoftWidth: [0, { step: 0.5, min: 0 }],
    reproGracePeriod: [0, { step: 10, min: 0 }],
    bodyMutation: [0.1, { step: 0.01, min: 0 }], buoyMutation: [0.05, { step: 0.01, min: 0, max: 1 }],
    predatorCount: [0, { step: 1, min: 0, int: true }], predatorEconomy: [false],
    predatorSpeed: [110], predatorPerception: [150], predatorCaptureRadius: [14],
    predatorCooldown: [3, { step: 0.5, min: 0 }],
    predatorMeal: [-1, { step: 0.5 }], predatorMetabolism: [2], predatorReproEnergy: [60], predatorMaxAge: [0],
    predatorMinPopulation: [0, { step: 1, min: 0, int: true }], predatorMaxPopulation: [0, { step: 1, min: 0, int: true }],
    predatorInheritance: [false], predatorTraitMutation: [0.1, { step: 0.01, min: 0 }],
    kBuoy: [1, { step: 0.1 }], pitchMax: [0.5, { step: 0.05, min: 0.001 }], vDrag: [2, { step: 0.1, min: 0 }],
    wallBand: [12, { step: 1, min: 0 }],
    cHold: [0, { step: 0.01, min: 0, max: 100 }], cPress: [0, { step: 0.01, min: 0, max: 100 }], depthCostScaled: [false],
    currentStrength: [0, { step: 1, min: 0 }],
    currentMode: [0, { options: ["Eddies", "Gyre"] }], currentEddies: [5, { int: true, min: 0 }], currentCore: [150], currentDrift: [1],
    deepCurrent: [false],
    waveSpeed: [0, { step: 0.5, min: 0, max: 100 }], waveBand: [32, { min: 1 }], waveGravity: [20, { min: 0.01 }],
    lightEnabled: [false], L0: [1, { step: 0.1, min: 0, max: 100 }], kWater: [0.006, { step: 0.001, min: 0, max: 1 }],
    sizeDrift: [false], sizeFight: [false], mouthGate: [false], kMouth: [2, { step: 0.1, min: 0.01 }],
    steerFrame: [0, { options: ["World x / y (Classic's)", "The fish's own frame"] }],
    eye: [0, { bit: true }], eyeOnly: [0, { bit: true }], eyeCode: [0, { step: 1, min: 0, max: 31, int: true }],
    appearance: [3, { options: ["Off", "Skin patterns only", "Body shapes only", "Patterns and body shapes"] }],
    patternMutation: [0.025, { step: 0.005, min: 0, max: 0.25 }], patternPhaseMutation: [0.03, { step: 0.005, min: 0, max: 0.25 }],
    patternNovelProbability: [0.05, { step: 0.01, min: 0, max: 0.25 }],
    morphologyMutation: [0.025, { step: 0.005, min: 0, max: 0.25 }], morphologyNovelProbability: [0.05, { step: 0.01, min: 0, max: 0.25 }]
  };

  /* What a FRESH page starts with where it differs from the engine's defaults
   * (a bare address: no seed / size / cfg in it, no setup loaded). A link or a
   * setup without these keys keeps the engine's default, so an old one
   * replays the world it was made with. */
  var FRESH = { walls: true };

  /* The "Big tank" preset (walls_bigtank design): 3840 x 2160 x 240 — four
   * times the standard volume — with 2000 founders, glass walls, four times
   * the food stock (9600: the standard 2400 per standard volume) and supply
   * (12 + 8 sin: ~11.5 items a step, ~3600 energy/s, enough for ~2300 fish at
   * metabolism 1.5), a 2000-fish birth cap, a 200-fish reseed floor (the
   * standard 50, x4), a 48 touch radius (2.4x the encounter volume of 36, for
   * pairing where fish are as sparse as 500 in the standard tank), no
   * predators, and the tuned E1 water (waves, a gentle deep current, light,
   * depth costs) with the walls' flow. Steering in the fish's own frame
   * (steerFrame 1): with world-frame steering a fish whose net outputs a
   * steady STEER_X / STEER_Y is pushed toward one wall like a constant force
   * and held in the glass's turn-away band — 35-40% of the Big tank's fish
   * within 80 units of the glass (11% of its area) over its first ~20k
   * steps, fading as fish evolve; in their own frame a steady steer only
   * turns them, and 14-15% are there. wasm/ocean_parity.sh BIGTANK is this
   * cfg verbatim (its walls_bigtank_s9 case). */
  var BIG_TANK = {
    width: 3840, height: 2160, depth: 240, population: 2000,
    cfg: { walls: true, maxPopulation: 2000, minPopulation: 200, targetFood: 9600, foodSpawnBase: 12, foodSpawnAmp: 8,
           foodEnergy: 5, interactRadius: 48, waveSpeed: 6, deepCurrent: true, currentStrength: 5, foodDrift: true,
           lightEnabled: true, depthCostScaled: true, cHold: 0.05, cPress: 0.03, steerFrame: 1 }
  };
  /* The tank sizes a setup may have (oc_init's own limits) */
  var SIZE_LIMITS = { side: [100, 100000], depth: [10, 100000], population: [0, 100000] };
  /* The standard tank, the reference volume Randomize scales a recipe from */
  var REFERENCE = { width: 1920, height: 1080, depth: 240 };

  /* oc_set_param's whitelist: these apply at once */
  var LIVE = {};
  ["kBuoy", "pitchMax", "vDrag", "wallBand", "buoyMutation", "cHold", "cPress", "foodDepthSpread",
   "waveSpeed", "waveBand", "waveGravity", "deepCurrent", "lightEnabled", "L0", "kWater",
   "depthCostScaled", "sizeDrift", "sizeFight", "mouthGate", "kMouth", "eye", "eyeOnly", "eyeCode",
   "steerFrame", "foodLife",
   "maxPopulation", "minPopulation", "targetFood", "foodSpawnBase", "foodSpawnAmp", "foodEnergy",
   "metabolicRate", "moveCost", "geneCost", "maxAge", "reproEnergy", "newbornEnergy",
   "mutationMultiplier", "minSpeed", "maxSpeed", "predatorMinPopulation", "predatorMaxPopulation",
   "predatorTraitMutation", "patternMutation", "patternPhaseMutation", "patternNovelProbability",
   "morphologyMutation", "morphologyNovelProbability"].forEach(function (k) { LIVE[k] = 1; });
  /* oc_set_param changes a running world only to values >= 0, while a new
   * world (oc_init) takes these live keys below 0 too: kBuoy in [-1000, 1000],
   * foodSpawnBase / foodSpawnAmp in [-1e4, 1e4], the energies and ages any
   * finite value (ocean_config.hpp oceanConfigError / oceanSimConfigError,
   * wasm/ocean_wasm.cpp configOk). The sheet keeps such a value for the next
   * Restart, marked so; a negative value for any other live key is outside its
   * range and the field goes back. */
  var NEG_ON_RESTART = {};
  ["kBuoy", "foodSpawnBase", "foodSpawnAmp", "foodEnergy", "metabolicRate", "maxAge", "reproEnergy",
   "newbornEnergy"].forEach(function (k) { NEG_ON_RESTART[k] = 1; });

  /* The sheet: tabs, then groups of keys. "run" is static HTML in ocean.html. */
  var TABS = [
    { id: "run", title: "Run" },
    { id: "world", title: "World", groups: [
      ["The world", ["seed", "population", "width", "height", "depth", "bodyModel"]],
      ["The tank's sides", ["walls", "sideWallBand", "sideWallTurnRate", "toroidal"]],
      ["Population limits", ["maxPopulation", "minPopulation"]],
      ["Movement", ["minSpeed", "maxSpeed", "triangularMotion", "maxTurnRate"]],
      ["Senses", ["perceptionRadius", "interactRadius", "maxNeighbors"]],
      ["Numerics", ["fastTanh"]]] },
    { id: "food", title: "Food", groups: [
      ["Food", ["foodPatches", "foodPatchRadius", "targetFood", "foodSpawnBase", "foodSpawnAmp", "foodEnergy", "pickupRadius", "foodDrift", "foodLife"]],
      ["Food in depth", ["foodDepthMode", "foodDepthSpread"]]] },
    { id: "life", title: "Life", groups: [
      ["Energy and age", ["metabolicRate", "moveCost", "geneCost", "maxAge", "reproEnergy", "newbornEnergy"]],
      ["Genes", ["mutationMultiplier", "genomeInitMin", "genomeInitMax", "genomeMinLength", "genomeMaxLength"]],
      ["Who can breed", ["reproMaxDistance", "reproSoftWidth", "reproGracePeriod"]],
      ["Bodies", ["bodyMutation", "buoyMutation"]],
      ["Appearance (looks only)", ["appearance", "patternMutation", "patternPhaseMutation", "patternNovelProbability",
                                   "morphologyMutation", "morphologyNovelProbability"]]] },
    { id: "predators", title: "Predators", groups: [
      ["Predators", ["predatorCount", "predatorEconomy"]],
      ["Hunting", ["predatorSpeed", "predatorPerception", "predatorCaptureRadius", "predatorCooldown"]],
      ["Their economy", ["predatorMeal", "predatorMetabolism", "predatorReproEnergy", "predatorMaxAge"]],
      ["Limits and inheritance", ["predatorMinPopulation", "predatorMaxPopulation", "predatorInheritance", "predatorTraitMutation"]]] },
    { id: "depth", title: "Depth", groups: [
      ["Swimming in depth", ["kBuoy", "pitchMax", "vDrag", "wallBand"]],
      ["What depth costs", ["cHold", "cPress", "depthCostScaled"]]] },
    { id: "ocean", title: "Water (E1)", groups: [
      ["Currents", ["currentStrength", "currentMode", "currentEddies", "currentCore", "currentDrift", "deepCurrent"]],
      ["Waves", ["waveSpeed", "waveBand", "waveGravity"]],
      ["Light", ["lightEnabled", "L0", "kWater"]],
      ["Size laws", ["sizeDrift", "sizeFight", "mouthGate", "kMouth"]]] },
    { id: "senses", title: "Steering", groups: [
      ["Steering", ["steerFrame"]],
      ["The compound eye", ["eye", "eyeOnly", "eyeCode"]]] }
  ];

  var LABELS = {
    seed: "Seed", population: "Starting fish", depth: "Sea depth", toroidal: "Senses wrap around the edges",
    width: "Tank width", height: "Tank length", walls: "Glass walls", sideWallBand: "Turn-away distance",
    sideWallTurnRate: "Turn-away rate",
    bodyModel: "Evolving bodies",
    maxPopulation: "Population cap", minPopulation: "Reseed floor",
    minSpeed: "Slowest speed", maxSpeed: "Fastest speed", maxTurnRate: "Turn rate",
    triangularMotion: "Fast swims straight, slow turns",
    perceptionRadius: "Sight radius", interactRadius: "Touch radius", maxNeighbors: "Neighbours watched",
    fastTanh: "Fast tanh",
    foodPatches: "Food patches", foodPatchRadius: "Patch radius", targetFood: "Food target",
    foodSpawnBase: "Food per step", foodSpawnAmp: "Food swing", foodEnergy: "Energy per food",
    pickupRadius: "Eating distance", foodDrift: "Food drifts with the current", foodLife: "Food lifetime (s)",
    foodDepthMode: "Where food appears", foodDepthSpread: "Depth spread per patch",
    metabolicRate: "Energy burned per second", moveCost: "Swimming cost", geneCost: "Cost per gene",
    maxAge: "Lifespan (s)", reproEnergy: "Energy needed to breed", newbornEnergy: "Newborn energy",
    mutationMultiplier: "Mutation rate ×", genomeInitMin: "Starting genes, fewest",
    genomeInitMax: "Starting genes, most", genomeMinLength: "Genes, minimum", genomeMaxLength: "Genes, maximum",
    reproMaxDistance: "Breeding distance limit", reproSoftWidth: "Soft limit width",
    reproGracePeriod: "Founder grace (s)", bodyMutation: "Body mutation", buoyMutation: "Buoyancy mutation",
    predatorCount: "Predators", predatorEconomy: "Predators eat, breed and starve",
    predatorSpeed: "Predator speed", predatorPerception: "Predator sight", predatorCaptureRadius: "Catch distance",
    predatorCooldown: "Digesting time (s)", predatorMeal: "Energy per catch",
    predatorMetabolism: "Predator energy burn", predatorReproEnergy: "Energy to bud a child",
    predatorMaxAge: "Predator lifespan", predatorMinPopulation: "Predator floor",
    predatorMaxPopulation: "Predator cap", predatorInheritance: "Hunters inherit traits",
    predatorTraitMutation: "Trait mutation",
    kBuoy: "Buoyancy pull", pitchMax: "Steepest dive", vDrag: "Vertical drag", wallBand: "Surface and floor cushion",
    cHold: "Cost of leaving neutral depth", cPress: "Cost of pressure", depthCostScaled: "Depth costs scale with metabolism",
    currentStrength: "Current strength", currentMode: "Current shape", currentEddies: "Eddies",
    currentCore: "Eddy radius", currentDrift: "How fast the flow changes", deepCurrent: "A deep current",
    waveSpeed: "Wave strength", waveBand: "Wave taper band", waveGravity: "Wave dispersion",
    lightEnabled: "Light field", L0: "Surface light", kWater: "Light fall-off",
    sizeDrift: "Small fish drift more", sizeFight: "Big fish fight harder", mouthGate: "Mouth size limits food",
    kMouth: "Mouth size ×",
    steerFrame: "Steering frame", eye: "Compound eye", eyeOnly: "See only through the eye", eyeCode: "Eye encoding",
    appearance: "Appearance genes", patternMutation: "Pattern mutation", patternPhaseMutation: "Pattern layout drift",
    patternNovelProbability: "New pattern traits", morphologyMutation: "Shape mutation", morphologyNovelProbability: "New shape traits"
  };
  var HINTS = {
    maxPopulation: "0 = none", minPopulation: "founders added below this",
    maxNeighbors: "0 = everyone in range", reproMaxDistance: "-1 = off",
    reproSoftWidth: "0 = a hard limit", reproGracePeriod: "0 = off", predatorMeal: "-1 = the prey's whole store",
    predatorMaxAge: "0 = until it starves", predatorMinPopulation: "0 = off; put back below this",
    predatorMaxPopulation: "0 = none", currentDrift: "0 = a still pattern", fastTanh: "changes the numbers",
    foodLife: "0 = until eaten", depth: "0 = surface", kBuoy: "per second", waveSpeed: "0 = still",
    width: "100 to 100000", height: "100 to 100000", sideWallBand: "0 = bounce off only", sideWallTurnRate: "rad/s at the glass",
    cHold: "× metabolism when scaled", cPress: "× metabolism when scaled", eyeCode: "bits 1, 2, 4; cloaks 8, 16",
    patternMutation: "± per gene", morphologyMutation: "± per gene", patternPhaseMutation: "± per birth",
    patternNovelProbability: "chance per trait group", morphologyNovelProbability: "chance per trait group"
  };
  /* what one press of − / + changes */
  var BTN_STEP = {
    seed: 1, population: 50, depth: 20, width: 160, height: 90, sideWallBand: 10, sideWallTurnRate: 1, predatorCount: 1, foodPatches: 1, currentStrength: 5,
    targetFood: 100, foodSpawnBase: 1, foodSpawnAmp: 0.5, foodEnergy: 0.5, foodPatchRadius: 10, pickupRadius: 2,
    foodLife: 5, foodDepthSpread: 5,
    patternMutation: 0.005, patternPhaseMutation: 0.005, patternNovelProbability: 0.01, morphologyMutation: 0.005, morphologyNovelProbability: 0.01,
    metabolicRate: 0.1, moveCost: 0.00001, geneCost: 0.001, maxAge: 10, reproEnergy: 1, newbornEnergy: 1,
    maxPopulation: 50, minPopulation: 10, minSpeed: 5, maxSpeed: 5, maxTurnRate: 0.5,
    perceptionRadius: 5, interactRadius: 2, maxNeighbors: 1, mutationMultiplier: 0.1,
    genomeInitMin: 1, genomeInitMax: 1, genomeMinLength: 1, genomeMaxLength: 1,
    reproMaxDistance: 0.5, reproSoftWidth: 0.5, reproGracePeriod: 10, bodyMutation: 0.01, buoyMutation: 0.01,
    predatorSpeed: 5, predatorPerception: 5, predatorCaptureRadius: 1, predatorCooldown: 0.5,
    predatorMeal: 0.5, predatorMetabolism: 0.1, predatorReproEnergy: 5, predatorMaxAge: 10,
    predatorMinPopulation: 1, predatorMaxPopulation: 5, predatorTraitMutation: 0.01,
    kBuoy: 0.1, pitchMax: 0.05, vDrag: 0.1, wallBand: 2, cHold: 0.01, cPress: 0.01,
    currentEddies: 1, currentCore: 10, currentDrift: 0.1,
    waveSpeed: 0.5, waveBand: 4, waveGravity: 2, L0: 0.1, kWater: 0.001, kMouth: 0.1, eyeCode: 1
  };

  /* Hover (or tap) info: d = what it is, t = values to try. The keys Classic
   * has too carry Classic's text (web/renderer.js TIPS), with the Ocean's
   * defaults where they differ. */
  var TIPS = {
    seed: { d: "RNG seed — the same seed and the same settings replay the run step for step.", t: "try: any uint32; keep it to reproduce a run" },
    population: { d: "Starting fish (the world reseeds below the reseed floor).", t: "try: 200-600; more than ~1500 gets slow in a browser" },
    depth: { d: "How deep the sea is, in world units (the tank is 1920 x 1080 across, or the same area on its side on a portrait screen). Fish, food and predators live anywhere from the surface to the floor.", t: "try: 240 (the default); 120 is a shallow sea, 480 a deep one" },
    toroidal: { d: "Without glass walls only: senses wrap across the world's sides, so a fish near one side senses what is near the opposite one — no sensory dead zone at the edges. Depth never wraps: the surface and the floor are real.", t: "try: on in a wrap-around world; glass walls turn it off" },
    walls: { d: "The four sides are glass, like a real tank: fish and predators turn away as they near one and bounce off if they touch it, food stays inside, and the water's waves and currents flow along the glass, never through it. Off, the sides wrap: a fish swimming out of one comes back in through the opposite side. Restart to apply.", t: "try: on (a new page's default); off for the wrap-around world older links show" },
    sideWallBand: { d: "Glass walls: how far from a side a fish (or predator) starts turning away from it; the closer it gets, the harder it turns. 0 = no turning: it only bounces off the glass. Restart to apply.", t: "try: 80 (the default); 30 lets fish hug the glass" },
    sideWallTurnRate: { d: "Glass walls: how fast a fish turns away, in radians per second, right at the glass (less further out). Restart to apply.", t: "try: 6 (the default); 2 for wide arcs" },
    width: { d: "The tank's size along x, in world units (the standard tank is 1920 x 1080). A bigger tank holds more fish at the same crowding; Big tank (on the Run tab) is a whole recipe for one. Restart to apply.", t: "try: 3840 with a length of 2160 (four times the area)" },
    height: { d: "The tank's size along y, in world units (shown front to back in the 3-D view). Restart to apply.", t: "try: 2160 with a width of 3840" },
    bodyModel: { d: "Heritable body size and elongation: bigger = slower and costlier, longer = turns worse. The size laws (the Water (E1) tab) act on the size.", t: "try: on; founders start at 1.0 and bodies drift from births" },
    maxPopulation: { d: "Birth cap: no births while the population is at or above it (0 = none). Applies live.", t: "try: 0, or 600 to keep a big run fast" },
    minPopulation: { d: "Reseed floor: random founders are added when the population falls below it. Applies live.", t: "try: 50 (the default)" },
    minSpeed: { d: "Minimum swim speed. Applies live.", t: "try: 0 when the swimming cost is above 0 (drifting allowed)" },
    maxSpeed: { d: "Maximum swim speed — the sprint ceiling. Applies live.", t: "try: 150; sprinting escapes predators at 110" },
    maxTurnRate: { d: "Turn ceiling (rad/s) at zero drive — triangular motion only.", t: "try: 2-6 around the default 4" },
    triangularMotion: { d: "Couple drive and turn: fast = straight, slow = agile.", t: "try: on for strike-vs-reorient bouts" },
    perceptionRadius: { d: "Sensing radius for neighbours, food and predators, in 3-D. The Ocean's default (100) is larger than Classic's 80: in a sea with depth, a fish meets others less often.", t: "try: 160 = the high-density schooling regime" },
    interactRadius: { d: "Range for social interactions (share / fight / breed), in 3-D. The Ocean's default is 36 (Classic's 20).", t: "try: 24-48" },
    maxNeighbors: { d: "Attend to only the N nearest neighbours; 0 = everyone in range.", t: "try: 7 — starlings track ~6-7" },
    fastTanh: { d: "A ~1.25x faster tanh approximation — changes the numbers.", t: "try: off to reproduce runs" },
    foodPatches: { d: "Cluster food into N patches (0 = scattered evenly).", t: "try: 5-6; patchy food makes currents matter" },
    foodPatchRadius: { d: "Spread of food around each patch centre.", t: "try: 60 tight, 240 loose" },
    targetFood: { d: "Food count the world regrows toward (hard cap 2x). The Ocean's default (2400) is four times Classic's: food is spread through the depth too. Applies live.", t: "try: 1200 scarcity, 4800 abundance" },
    foodSpawnBase: { d: "Mean food items spawned per step. Applies live.", t: "try: 2-12; higher = a richer world" },
    foodSpawnAmp: { d: "Sinusoidal swing of food abundance around the base rate. Applies live.", t: "try: 0 for a steady food supply" },
    foodEnergy: { d: "Energy gained per food item eaten. Applies live.", t: "try: 3-8 around the default 5" },
    pickupRadius: { d: "How close (in 3-D) a fish must come to eat a food item. The Ocean's default is 24 (Classic's 10).", t: "try: 16-32" },
    foodDrift: { d: "Food is carried by the current into drifting filaments.", t: "try: on — pairs well with currents" },
    foodLife: { d: "Every food item disappears this many seconds after it appeared, eaten or not (it sinks out or decays); 0 = it stays until eaten. With a fixed inflow, food nobody finds is lost, so how many fish a world feeds depends on how well they search. Applies live.", t: "try: 30-90" },
    foodDepthMode: { d: "Anywhere: food appears at any depth. Each patch at its own depth: every food patch gets a depth at the start and its food lands near it (needs food patches).", t: "try: patches at their own depth, to make depth worth choosing" },
    foodDepthSpread: { d: "How far above and below its patch's depth food lands. Applies live.", t: "try: 15 tight, 60 loose" },
    metabolicRate: { d: "Fixed energy burned per second by every fish. Applies live.", t: "try: toward 3 for harsher starvation" },
    moveCost: { d: "Kinetic cost: energy/sec = F x speed² — makes thrust expensive. Applies live.", t: "try: 0.00007 -> cruise ~82; 0 = free" },
    geneCost: { d: "Extra energy/sec per gene — parsimony pressure against bloat. Applies live.", t: "try: 0.005 makes big genomes costly" },
    maxAge: { d: "Age in seconds at which a fish dies of old age. Applies live.", t: "try: 60-240 around the default 120" },
    reproEnergy: { d: "Energy a parent needs before it can reproduce. Applies live.", t: "try: 15-40; higher = slower breeding" },
    newbornEnergy: { d: "Starting energy of a newborn. Applies live.", t: "try: 15-35 around the default 25" },
    mutationMultiplier: { d: "Multiplier on the per-birth mutation rate. Applies live.", t: "try: 0.5 conservative, 2 fast drift" },
    genomeInitMin: { d: "Low end of the starting gene-count range.", t: "try: 24-48 inside the bounds 16-80" },
    genomeInitMax: { d: "High end of the starting gene-count range.", t: "try: 24-48 inside the bounds 16-80" },
    genomeMinLength: { d: "Hard lower bound on gene count.", t: "try: 16 (the default)" },
    genomeMaxLength: { d: "Hard upper bound on gene count.", t: "try: 80 (the default)" },
    reproMaxDistance: { d: "Reproductive isolation: parents farther apart than this in wiring space cannot breed (-1 = off).", t: "try: 18 bites gently, 14 hard; below 12 breeding stops" },
    reproSoftWidth: { d: "Softens the isolation gate into a ramp: past the gate breeding fades out over this width (0 = a hard cliff).", t: "try: 4-5 with the gate at 14-16" },
    reproGracePeriod: { d: "Founders ignore the gate while younger than this, so a fresh genome can breed once (0 = off).", t: "try: 60" },
    bodyMutation: { d: "Evolving bodies only: jitter added to each inherited body parameter.", t: "try: 0.1 default; 0 freezes drift, 0.3 explores fast" },
    buoyMutation: { d: "Half-width of a newborn's neutral-depth draw around its parents' (as a fraction of the depth). Neutral depth is where a fish floats without effort; it is inherited, so a population can evolve to live high or low. Applies live.", t: "try: 0.05 (the default); 0 freezes it, 0.2 explores fast" },
    predatorCount: { d: "Number of scripted hunters chasing fish in 3-D (0 = none).", t: "try: 3-4 with the predator economy on" },
    predatorEconomy: { d: "Predators eat, breed and starve instead of being immortal.", t: "try: on with 4 predators, energy per catch 9 and a predator cap of 15" },
    predatorSpeed: { d: "Predator cruise speed.", t: "try: 110 vs the fish's top speed 150 = escapable" },
    predatorPerception: { d: "Predator's prey-detection radius.", t: "try: 150 (the default)" },
    predatorCaptureRadius: { d: "Contact distance at which a fish is caught.", t: "try: 10-20 around the default 14" },
    predatorCooldown: { d: "Seconds a predator digests after a catch before it can catch again — caps its kill rate.", t: "try: 3-5; 5 eases the chase" },
    predatorMeal: { d: "Energy a predator gains per catch (economy on). -1 = it absorbs the prey's whole store, which lets predators explode.", t: "try: 1.2 × break-even = cooldown × (metabolism + swimming cost × 110²); 7 at the defaults" },
    predatorMetabolism: { d: "Predator energy burn per second (economy on); fish burn 1.5.", t: "try: 2-3" },
    predatorReproEnergy: { d: "Energy a predator needs to bud a child (economy on).", t: "try: 40-80" },
    predatorMaxAge: { d: "Predator death age; 0 = immortal until starved.", t: "try: 0, or 120 to age them out" },
    predatorMinPopulation: { d: "Predator floor: fresh hunters are put back whenever fewer than this are alive (economy on; 0 = off). Applies live.", t: "try: 2, with a cap" },
    predatorMaxPopulation: { d: "Predator cap: a well-fed hunter doesn't bud while this many are alive (economy on; 0 = none). Applies live.", t: "try: 15 with the default 3 s digesting time" },
    predatorInheritance: { d: "Each bud inherits its parent's speed and budding threshold (×0.5 to ×2) with a small mutation, so hunters evolve.", t: "try: on with a swimming cost, a predator lifespan and a cap" },
    predatorTraitMutation: { d: "How far a bud's traits can stray from its parent's, per trait per bud. Applies live.", t: "try: 0.1 (the default)" },
    kBuoy: { d: "How hard a fish is pulled back toward its neutral depth, per second. Leaving neutral depth costs steering effort. Applies live from 0 up; a negative pull (it pushes a fish away from its neutral depth) applies on Restart.", t: "try: 1 (the default, tuned); 0.5 lets fish wander in depth, 3 pins them" },
    pitchMax: { d: "The steepest a fish can climb or dive: its vertical speed is at most this × its speed. Applies live.", t: "try: 0.5 (about 27°); 1 = 45°" },
    vDrag: { d: "Vertical drag, per second: how fast a fish's climb or dive dies away when it stops steering in depth. Applies live.", t: "try: 2 (the default); 0.5 glides, 6 stops short" },
    wallBand: { d: "Within this distance of the surface or the floor, a soft push turns a fish back into the water. Applies live.", t: "try: 12 (the default); 0 = hard walls" },
    cHold: { d: "Energy a fish pays for being away from its neutral depth, per unit of distance (as a share of the depth). With depth costs scaled: a multiple of its own metabolism. Applies live.", t: "try: 0.05 scaled (the E1 preset); 0 = free" },
    cPress: { d: "Energy a fish pays for depth itself (pressure), growing toward the floor. With depth costs scaled: a multiple of its own metabolism. Applies live.", t: "try: 0.03 scaled (the E1 preset)" },
    depthCostScaled: { d: "Off: the two depth costs are energy per second. On: they are multiples of each fish's own metabolism (bigger bodies pay more), the E1 physics' rule. Applies live.", t: "try: on with the E1 preset" },
    currentStrength: { d: "Peak ocean-flow speed in world units per second (0 = still water).", t: "try: 5 with a deep current (the E1 preset); 80 for a strong 2-D-style flow" },
    currentMode: { d: "Eddies = moving vortices; gyre = two counter-rotating basins.", t: "try: eddies" },
    currentEddies: { d: "Number of vortices in eddies mode.", t: "try: 3-8 around the default 5" },
    currentCore: { d: "Eddy radius — the distance of peak flow speed.", t: "try: 100-250 around the default 150" },
    currentDrift: { d: "How fast the flow field evolves (0 = static).", t: "try: 0.5-2 around the default 1" },
    deepCurrent: { d: "The current flows at depth only: still at the surface, full strength from mid-depth down, so where a fish swims decides whether it is carried. Applies live.", t: "try: on (the E1 preset)" },
    waveSpeed: { d: "Surface waves: three fixed wave trains move the water in orbits, strongest near the surface, fading toward the floor; fish and food are carried. Their orbital speed in units per second (0 = still). Applies live.", t: "try: 6 (the E1 preset)" },
    waveBand: { d: "How far from the surface and floor the waves taper to nothing. Applies live.", t: "try: 32 (the default)" },
    waveGravity: { d: "The waves' dispersion constant (ω² = g·k): higher = faster orbits. Applies live.", t: "try: 20 (the default)" },
    lightEnabled: { d: "Light that fades with depth, L(d) = L0·exp(−fall-off·d). The tank then shades depth by it. Display only in this version of the physics. Applies live.", t: "try: on (the E1 preset)" },
    L0: { d: "Light at the surface. Applies live.", t: "try: 1 (the default)" },
    kWater: { d: "How fast light fades with depth, per unit (0.006: about half at 115). Applies live.", t: "try: 0.006 (the default); 0.012 for murky water" },
    sizeDrift: { d: "The flow moves a fish by min(1, 1 / size) of itself: small fish are carried more. Applies live.", t: "try: on with evolving bodies and a current or waves" },
    sizeFight: { d: "A fish's fighting strength grows with its size squared. Applies live.", t: "try: on with evolving bodies" },
    mouthGate: { d: "A fish can eat a food item only if the food is no bigger than mouth size × its own size. Applies live.", t: "try: on with evolving bodies" },
    kMouth: { d: "Mouth size, as a multiple of body size (the mouth gate). Applies live.", t: "try: 2 (the default)" },
    appearance: { d: "Every fish carries inherited looks: a skin pattern (colours, stripes, bars, spots, mazes, countershading, an eye bar, a shoulder spot, an eyespot, pale fin edges) and a body shape (depth, width, head, snout, tail, fins, barbels). A child gets each trait group from one parent, the mean of both, or now and then a new trait, plus a little mutation. Nothing in the simulation reads them: they change no fish's life, so the run is the same with them on or off. The body shapes show in every Fish colours mode, the skin patterns with Appearance (the default). Restart to apply.", t: "try: patterns and body shapes (the default), with Appearance in View" },
    patternMutation: { d: "How far each pattern gene of a newborn may move from what it inherited (uniform ±). Applies live, to fish born from now on.", t: "try: 0.025-0.1" },
    patternPhaseMutation: { d: "How far a newborn's pattern layout (where its spots and stripes sit) may drift from its first parent's, so families keep recognisable layouts. Applies live.", t: "try: 0.03" },
    patternNovelProbability: { d: "The chance that a newborn gets a brand-new trait for one group of pattern genes (a colour, the field's balance, orientation, a landmark ...) instead of a parent's. Keeps variety from fading. Applies live.", t: "try: 0.05" },
    morphologyMutation: { d: "How far each body-shape gene of a newborn may move from what it inherited (uniform ±). Applies live.", t: "try: 0.025-0.1" },
    morphologyNovelProbability: { d: "The chance that a newborn gets a brand-new trait for one group of shape genes (body, head, tail, a fin, barbels, eyes) instead of a parent's. Applies live.", t: "try: 0.05" },
    steerFrame: { d: "Which way STEER_X / STEER_Y push: in world x / y (Classic's, and the food senses' frame), or in the fish's own frame (STEER_X turns it right or left, STEER_Y along its heading), so a sense in its own frame can turn it toward what it senses. Fast-swims-straight already turns by STEER_X and ignores this. Applies live.", t: "try: the fish's own frame, for the 3-D senses" },
    eye: { d: "The compound eye: six sectors around the fish (ahead, behind, left, right, up, down), each reporting the nearest thing in it by nearness, apparent size and contrast. Only in the eye build of the module. Applies live.", t: "try: on in the eye build" },
    eyeOnly: { d: "Turn off the labelled senses the eye replaces (food direction, neighbours, the predator bearing, ...): the fish see only through the eye (or, with it off, nothing outside their own body). Eye build only. Applies live.", t: "try: on with the eye, to see what evolves from sight alone" },
    eyeCode: { d: "The eye's encoding, a sum of bits (0 to 31): 1 faded contrast, 2 opponent pairs (left + right and right − left, ...), 4 every object in a sector instead of the nearest; and two cloaks: 8 the eye ignores other fish (it still sees predators), 16 the eye ignores food (the labelled senses still see both). Eye build only. Applies live.", t: "try: 0, then 2; 16 to see whether food-finding needs the eye" },
    governor: { d: "When frames take too long: first run fewer steps per frame, then draw the tank with less detail. Never changes the simulation itself.", t: "try: on; off to see the uncapped run (it may stutter)" },
    colourBrain: { d: "Appearance (the default): each fish's own skin pattern, inherited from its two parents with a little mutation; it is only looks: nothing in the simulation reads it. Family: each family line (every fish descended from the same starting fish) has its own colour, the one it has in the dashboards. Brain: the colour comes from the genome's wiring, so similar brains look alike. In every mode a fish keeps the body shape it inherited; only its colour changes.", t: "try: appearance to watch patterns pass down, family to follow lines, brain to see what their brains converged on" },
    followLight: { d: "While you follow a fish (F), a flashlight shows it and its surroundings in clear light: true colours (those of the Fish colours mode), no depth fade, no water tint. The dock's flashlight button (L) turns it on anywhere. Drawing only: the fish never see it.", t: "try: on (the default)" },
    clarity: { d: "How murky the water is drawn. Clear (the default): about half the fade with depth and a gentler blue shift, so a fish at the floor keeps most of its colour; a lighter teal water above the tank over a deeper teal floor (as in Classic's tank) with softer caustics; fainter marine snow and plankton glow; and a lift of the fish's colours, so they read against the floor. Realistic: light fades and turns blue with depth toward dark water, over bright sand, as the Ocean first looked. Drawing only: nothing in the simulation reads it, and the flashlight and the fish card show true colours either way.", t: "try: clear (the default) to watch the fish; realistic for the deep-sea mood" }
  };

  /* ---- 🎲 Randomize: a whole setup from ranges ----
   * Classic's measured ideas (web/randomizer.js: currents with patchy,
   * drifting food and a thrust cost; predators with a thrust cost, plenty of
   * food and a cap; the economy with a fixed meal, a predator cap and floor;
   * the match gate only with its soft ramp), with the Ocean's food stock (4 x
   * Classic's: food fills the depth too) and sight, plus the Ocean's own: the
   * tuned E1 physics preset, patches at their own depths, own-frame steering.
   * key: [min, max, step, source] */
  var RANGES = {
    popFactor: [0.7, 1.4, 0.05, "around the default 300"],
    targetFood: [2000, 4800, 100, "Classic's 500-1200, x4 (the Ocean's default is 4 x Classic's)"],
    foodSpawnBase: [3, 8, 0.5, "Classic's: try 2-12"],
    foodSpawnAmp: [0, 3, 0.5, "default 2; 0 = steady supply"],
    foodEnergy: [4, 7, 0.5, "try: 3-8 around the default 5"],
    maxAge: [90, 180, 10, "try: 60-240 around the default 120"],
    maxAgeHunted: [120, 180, 10, "with predators, at least the default"],
    reproEnergy: [18, 30, 1, "try: 15-40"],
    newbornEnergy: [20, 30, 1, "try: 15-35"],
    mutationMultiplier: [0.5, 2, 0.1, "try: 0.5 conservative, 2 fast drift"],
    moveCost: [0.00003, 0.00007, 0.00001, "Classic measured: 3e-5 and 7e-5 both give a cruise ~82"],
    geneCost: [0.005, 0.01, 0.001, "try: 0.005"],
    maxNeighbors: [6, 8, 1, "starlings track ~6-7 nearest"],
    perceptionRadius: [100, 180, 10, "the Ocean's 100 up to Classic's schooling regime"],
    maxTurnRate: [3, 5, 0.5, "try: 2-6 around the default 4"],
    hunters: [3, 5, 1, "Classic's arena: 3-5 healthy"],
    economyHunters: [3, 4, 1, "try: 3-4 with the economy on"],
    mealFactor: [1.2, 1.4, 0.05, "meal / break-even (Classic measured)"],
    predatorCapPerCooldown: [8, 8, 1, "cap = this x cooldown (Classic measured)"],
    predatorFloor: [2, 2, 1, "keeps a seed population"],
    predatorMetabolism: [2, 3, 0.5, "try: 2-3"],
    predatorReproEnergy: [50, 70, 5, "try: 40-80"],
    predatorCooldown: [3, 5, 0.5, "default 3; 5 eases the chase"],
    arenaFood: [4800, 8000, 200, "Classic's arena 1200-2000, x4"],
    arenaFoodSpawn: [8, 12, 1, "the arena runs used 12"],
    arenaCap: [300, 450, 50, "Classic's schooling arena capped at 350"],
    economyCap: [400, 600, 50, "the economy runs capped at 600"],
    foodPatches: [5, 6, 1, "try: 5-6"],
    foodPatchRadius: [80, 200, 10, "try: 60 tight, 240 loose"],
    foodDepthSpread: [20, 60, 5, "try: 15 tight, 60 loose"],
    currentFight: [70, 90, 5, "Classic measured: 80 with a thrust cost = fish fight the flow"],
    currentRide: [130, 160, 5, "Classic measured: 150 with a thrust cost = fish ride it"],
    currentEddies: [3, 8, 1, "try: 3-8"],
    currentCore: [100, 250, 10, "try: 100-250"],
    currentDrift: [0.5, 2, 0.1, "try: 0.5-2"],
    reproMaxDistance: [16, 18, 0.5, "16 with the soft ramp clears collapse"],
    reproSoftWidth: [4, 5, 0.5, "width 4 clears collapse at 16"],
    bodyMutation: [0.05, 0.2, 0.01, "try: 0.1 default"],
    buoyMutation: [0.03, 0.12, 0.01, "around the default 0.05"]
  };
  var CHANCE = {
    predatorsScripted: 0.25, predatorsEconomy: 0.3,
    currents: 0.35, patchyFood: 0.25,
    e1: 0.35,              /* the tuned E1 physics preset (waves, deep current, light, depth costs) */
    patchDepths: 0.6,      /* with patches: each patch at its own depth */
    thrustCost: 0.5, toroidal: 0.8, topological: 0.35, triangular: 0.2, widePerception: 0.2,
    geneCost: 0.3, bodyModel: 0.3, matchGate: 0.15, grace: 0.5, ownFrame: 0.25,
    tuneFood: 0.5, tuneLife: 0.4, tuneMutation: 0.4, tuneBuoy: 0.3
  };
  var PREDATOR_SPEED = 110;
  function round(v, step) { return +(Math.round(v / step) * step).toFixed(6); }
  /* Wrap-around senses need every radius under half the world's smaller side
   * (src/ocean/ocean_world.hpp radiusError: the grid's wrapped query), the
   * fish's long probe (30) among them. */
  var TORUS_RADII = ["perceptionRadius", "interactRadius", "pickupRadius", "predatorPerception", "predatorCaptureRadius"];
  var LONG_PROBE_RADIUS = 30;
  function fitTorus(set, labels, side) {
    var lim = side / 2;   /* a radius r fits when 2r < side */
    if (!(LONG_PROBE_RADIUS < lim)) {   /* not even the probe: walls */
      delete set.toroidal;
      labels.splice(labels.indexOf("wrap-around senses"), 1);
      return;
    }
    var cap = Math.ceil(lim) - 1, cut = [];
    TORUS_RADII.forEach(function (k) {
      if ((k in set ? set[k] : KEYS[k][0]) >= lim) { set[k] = cap; cut.push(LABELS[k].toLowerCase()); }
    });
    if (cut.length) labels.push(cut.join(", ") + " cut to " + cap + " to fit the wrap-around");
  }

  /* A drawn recipe for the standard tank, scaled once to a tank of another
   * volume (walls_bigtank design): the fish, the food stock and supply, the
   * reseed floor and caps, and the predators' counts by the volume ratio;
   * distances (sight, touch, eating, patch radius) stay in world units. The
   * engine's limits bound every scaled value. */
  function scaleToVolume(set, population, volume, labels) {
    if (!(volume > 0) || Math.abs(volume - 1) < 1e-9) return population;
    function sc(key, def, lo, hi, isInt) {
      var v = (key in set ? set[key] : def) * volume;
      v = Math.max(lo, Math.min(hi, isInt ? Math.round(v) : round(v, 0.5)));
      set[key] = v;
    }
    sc("targetFood", KEYS.targetFood[0], 0, 1000000, true);
    sc("foodSpawnBase", KEYS.foodSpawnBase[0], -10000, 10000, false);
    sc("foodSpawnAmp", KEYS.foodSpawnAmp[0], -10000, 10000, false);
    sc("minPopulation", KEYS.minPopulation[0], 0, 100000, true);
    if (set.maxPopulation > 0) sc("maxPopulation", 0, 1, 100000, true);
    if (set.predatorCount > 0) sc("predatorCount", 0, 1, 100000, true);
    if (set.predatorMaxPopulation > 0) sc("predatorMaxPopulation", 0, 1, 100000, true);
    if (set.predatorMinPopulation > 0) sc("predatorMinPopulation", 0, 0, 2000, true);
    population = Math.max(1, Math.min(100000, Math.round(population * volume)));
    if (set.maxPopulation > 0) population = Math.min(population, set.maxPopulation);
    labels.push("scaled to this tank's volume (x" + +volume.toFixed(2) + ")");
    return population;
  }

  /* rand: () => [0, 1); e1: the E1 preset as an object; size: [width,
   * height] of the world it will start (radii are kept to what it allows),
   * or [width, height, depth, walls]: the recipe is then drawn for the
   * standard tank and scaled to that volume, and with walls (true) no
   * wrap-around is drawn (Randomize keeps the tank's size and sides).
   * -> { population, set: {key: value}, labels: [...] }; every key left out
   * stays at its default. */
  function draw(rand, basePop, e1, size) {
    var walls = !!(size && size[3]);
    function chance(p) { return rand() < p; }
    function pick(a) { return a[Math.floor(rand() * a.length)]; }
    function range(key) { var r = RANGES[key]; return round(r[0] + (r[1] - r[0]) * rand(), r[2]); }
    var set = {}, labels = [];
    var population = Math.max(50, Math.round(basePop * range("popFactor")));
    var thrust = false;
    var u = rand();
    if (u < CHANCE.predatorsEconomy + CHANCE.predatorsScripted) {
      var economy = u < CHANCE.predatorsEconomy;
      set.predatorCount = range(economy ? "economyHunters" : "hunters");
      set.predatorCooldown = range("predatorCooldown");
      set.targetFood = range("arenaFood");
      set.foodSpawnBase = range("arenaFoodSpawn");
      set.maxPopulation = range(economy ? "economyCap" : "arenaCap");
      set.moveCost = range("moveCost");
      thrust = true;
      if (economy) {
        set.predatorEconomy = true;
        set.predatorMetabolism = range("predatorMetabolism");
        var breakEven = set.predatorCooldown * (set.predatorMetabolism + set.moveCost * PREDATOR_SPEED * PREDATOR_SPEED);
        var f = RANGES.mealFactor;
        set.predatorMeal = Math.min(Math.floor(f[1] * breakEven * 2) / 2,
                                    Math.max(Math.ceil(f[0] * breakEven * 2) / 2, round(range("mealFactor") * breakEven, 0.5)));
        set.predatorReproEnergy = range("predatorReproEnergy");
        set.minPopulation = 20;
        set.predatorMaxPopulation = Math.round(range("predatorCapPerCooldown") * set.predatorCooldown);
        set.predatorMinPopulation = range("predatorFloor");
        labels.push(function () {
          return set.predatorCount + " predators that must eat to breed (meal " + set.predatorMeal + "), kept between " +
                 set.predatorMinPopulation + " and " + set.predatorMaxPopulation;
        });
      } else {
        labels.push(function () { return set.predatorCount + " hunting predators"; });
      }
      labels.push(function () { return "plenty of food, at most " + set.maxPopulation + " fish"; });
      population = Math.min(population, set.maxPopulation);
    } else {
      var e = rand();
      if (e < CHANCE.currents) {
        var ride = chance(0.5);
        set.currentStrength = range(ride ? "currentRide" : "currentFight");
        set.currentMode = pick([0, 1]);
        if (set.currentMode === 0) { set.currentEddies = range("currentEddies"); set.currentCore = range("currentCore"); }
        set.currentDrift = range("currentDrift");
        set.foodPatches = range("foodPatches");
        set.foodPatchRadius = range("foodPatchRadius");
        set.foodDrift = true;
        thrust = true;
        labels.push("ocean current " + set.currentStrength + " (" + (set.currentMode ? "gyre" : "eddies") + ")");
        labels.push(set.foodPatches + " drifting food patches");
      } else if (e < CHANCE.currents + CHANCE.patchyFood) {
        set.foodPatches = range("foodPatches");
        set.foodPatchRadius = range("foodPatchRadius");
        labels.push(set.foodPatches + " food patches");
      }
      if (set.foodPatches && chance(CHANCE.patchDepths)) {
        set.foodDepthMode = 1;
        set.foodDepthSpread = range("foodDepthSpread");
        labels.push("each patch at its own depth");
      }
      if (chance(CHANCE.tuneFood)) {
        set.targetFood = range("targetFood");
        set.foodSpawnBase = range("foodSpawnBase");
        set.foodSpawnAmp = range("foodSpawnAmp");
        set.foodEnergy = range("foodEnergy");
        labels.push(function () { return "food " + set.targetFood + ", " + set.foodSpawnBase + "/step"; });
      }
    }
    /* the E1 physics preset, unless a strong current was drawn (the preset's
     * own current is a gentle deep one) */
    if (e1 && !set.currentStrength && chance(CHANCE.e1)) {
      Object.keys(e1).forEach(function (k) { if (!(k in set)) set[k] = e1[k]; });
      labels.push("E1 physics: waves, a deep current, light, depth costs");
    }
    if (thrust || chance(CHANCE.thrustCost)) {
      if (set.moveCost === undefined) set.moveCost = range("moveCost");
      set.minSpeed = 0;
      labels.push("swimming costs energy");
    }
    if (chance(CHANCE.toroidal) && !walls) { set.toroidal = true; labels.push("wrap-around senses"); }
    if (chance(CHANCE.topological)) { set.maxNeighbors = range("maxNeighbors"); labels.push("each fish follows its " + set.maxNeighbors + " nearest"); }
    if (chance(CHANCE.widePerception)) { set.perceptionRadius = range("perceptionRadius"); labels.push("sight " + set.perceptionRadius); }
    if (chance(CHANCE.triangular)) {
      set.triangularMotion = true; set.maxTurnRate = range("maxTurnRate");
      labels.push("fast = straight, slow = agile");
    } else if (chance(CHANCE.ownFrame)) {
      set.steerFrame = 1; labels.push("steering in the fish's own frame");
    }
    if (chance(CHANCE.tuneLife)) {
      set.maxAge = range(set.predatorCount ? "maxAgeHunted" : "maxAge");
      set.reproEnergy = range("reproEnergy");
      set.newbornEnergy = range("newbornEnergy");
      labels.push("lifespan " + set.maxAge + " s");
    }
    if (chance(CHANCE.tuneMutation)) { set.mutationMultiplier = range("mutationMultiplier"); labels.push("mutation ×" + set.mutationMultiplier); }
    if (chance(CHANCE.tuneBuoy)) { set.buoyMutation = range("buoyMutation"); labels.push("buoyancy mutation " + set.buoyMutation); }
    if (chance(CHANCE.geneCost)) { set.geneCost = range("geneCost"); labels.push("big genomes cost energy"); }
    if (chance(CHANCE.bodyModel)) { set.bodyModel = true; set.bodyMutation = range("bodyMutation"); labels.push("heritable body size"); }
    if (chance(CHANCE.matchGate)) {
      set.reproMaxDistance = range("reproMaxDistance");
      set.reproSoftWidth = range("reproSoftWidth");
      if (chance(CHANCE.grace)) set.reproGracePeriod = 60;
      labels.push("picky partners (match gate " + set.reproMaxDistance + ")");
    }
    if (set.toroidal && size) fitTorus(set, labels, Math.min(size[0], size[1]));
    if (size && size.length > 2)
      population = scaleToVolume(set, population, (size[0] * size[1] * size[2]) / (REFERENCE.width * REFERENCE.height * REFERENCE.depth), labels);
    /* the labels with numbers that scaling changes are written from the final
     * recipe (functions until now): "at most 375 fish" means the cap that runs */
    labels = labels.map(function (l) { return typeof l === "function" ? l() : l; });
    return { population: population, set: set, labels: labels };
  }

  /* ---- Scenarios (UI-3): complete recipes the Setup's "Start from" stages ----
   * Each is a whole world, never an overlay: what a recipe leaves out is
   * Standard's (a new visitor's: the engine's defaults, glass walls, the
   * screen's size), as Randomize always did. scenario(id, ctx) ->
   * {title, summary, seed, population, depth, width, height, cfg};
   * ctx: {seed, screen: [w, h], walls (the module has glass walls), e1 (the
   * module's E1 preset, an object), rand, tank: {width, height, depth,
   * walls, sideWallBand, sideWallTurnRate} (Surprise me keeps the tank as
   * set)}. The summaries are written from the final recipe. Hunters and
   * Currents & patches are fixed recipes from the ranges Randomize draws
   * from (RANGES): UI presets, not new defaults or claims. BIG_TANK is used
   * verbatim (wasm/ocean_parity.sh compares it). */
  var HUNTERS = { predatorCount: 4, predatorCooldown: 4, targetFood: 6400, foodSpawnBase: 10, maxPopulation: 350, minSpeed: 0, moveCost: 0.00005 };
  var CURRENTS = { currentStrength: 80, currentMode: 0, currentEddies: 5, currentCore: 150, currentDrift: 1, foodPatches: 6, foodPatchRadius: 120,
                   foodDepthMode: 1, foodDepthSpread: 30, foodDrift: true, minSpeed: 0, moveCost: 0.00005 };
  var SCENARIOS = [
    { id: "standard", title: "Standard", blurb: "A new visitor's ocean: the default rules, glass walls, sized for this screen" },
    { id: "bigtank", title: "Big tank", blurb: "Four times the volume and the fish, four times the food, the tuned water" },
    { id: "e1", title: "Living water", blurb: "Waves, a deep current, light that fades with depth, depth costs (E1)" },
    { id: "hunters", title: "Hunters", blurb: "Four predators hunt; plenty of food, a cap on the fish, swimming costs energy" },
    { id: "currents", title: "Currents & patches", blurb: "Eddies carry six food patches, each at its own depth; swimming costs energy" },
    { id: "surprise", title: "Surprise me", blurb: "A whole setup drawn from ranges that worked, for the tank as set" }
  ];
  function tankText(w, h, d) { return w + " × " + h + " × " + d; }
  function scenario(id, ctx) {
    var sw = ctx.screen, fresh = ctx.walls ? Object.assign({}, FRESH) : {};
    var r = { id: id, seed: ctx.seed >>> 0, population: KEYS.population[0], depth: KEYS.depth[0], width: sw[0], height: sw[1], cfg: fresh, labels: [] };
    var walls = function (cfg) { return cfg.walls === true ? "glass walls" : "wrapping sides"; };
    if (id === "bigtank") {
      var b = BIG_TANK;
      r.width = b.width; r.height = b.height; r.depth = b.depth; r.population = b.population; r.cfg = Object.assign({}, b.cfg);
      r.labels = ["four times the food", "births stop at " + b.cfg.maxPopulation, "the tuned water"];
    } else if (id === "e1") {
      if (!ctx.e1) return null;
      Object.keys(ctx.e1).forEach(function (k) { r.cfg[k] = ctx.e1[k]; });
      r.labels = ["waves, a deep current, light, depth costs"];
    } else if (id === "hunters") {
      Object.keys(HUNTERS).forEach(function (k) { r.cfg[k] = HUNTERS[k]; });
      r.labels = [r.cfg.predatorCount + " hunting predators", "food " + r.cfg.targetFood + ", " + r.cfg.foodSpawnBase + "/step",
                  "at most " + r.cfg.maxPopulation + " fish", "swimming costs energy"];
    } else if (id === "currents") {
      Object.keys(CURRENTS).forEach(function (k) { r.cfg[k] = CURRENTS[k]; });
      r.labels = ["current " + r.cfg.currentStrength + " in " + r.cfg.currentEddies + " eddies", r.cfg.foodPatches + " drifting food patches, each at its own depth",
                  "swimming costs energy"];
    } else if (id === "surprise") {
      var t = ctx.tank, pick = draw(ctx.rand, KEYS.population[0], ctx.e1, [t.width, t.height, t.depth, t.walls]);
      r.width = t.width; r.height = t.height; r.depth = t.depth; r.population = pick.population;
      r.cfg = { walls: !!t.walls, sideWallBand: t.sideWallBand, sideWallTurnRate: t.sideWallTurnRate };
      Object.keys(pick.set).forEach(function (k) { r.cfg[k] = pick.set[k]; });
      r.labels = pick.labels.length ? pick.labels : ["the default rules"];
    } else if (id !== "standard") return null;
    else r.labels = ["the default rules"];
    var meta = SCENARIOS.filter(function (s) { return s.id === id; })[0];
    r.title = meta.title;
    r.summary = tankText(r.width, r.height, r.depth) + " · " + r.population + " fish · " + walls(r.cfg) + " · " + r.labels.join(" · ");
    return r;
  }

  root.EvoOceanConfig = { KEYS: KEYS, LIVE: LIVE, NEG_ON_RESTART: NEG_ON_RESTART, TABS: TABS, LABELS: LABELS, HINTS: HINTS,
                          BTN_STEP: BTN_STEP, TIPS: TIPS, RANGES: RANGES, CHANCE: CHANCE, draw: draw,
                          FRESH: FRESH, BIG_TANK: BIG_TANK, SIZE_LIMITS: SIZE_LIMITS, REFERENCE: REFERENCE,
                          scaleToVolume: scaleToVolume, SCENARIOS: SCENARIOS, scenario: scenario, HUNTERS: HUNTERS, CURRENTS: CURRENTS };
})(typeof window !== "undefined" ? window : globalThis);
