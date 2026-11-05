/* web/types.d.ts: the Ocean page's shared shapes and its window.Evo* globals, for the type check only
 * (tsc --checkJs: tsconfig.json at the repo root; CI's "web types" job).
 *
 * The site has no build step: plain <script> IIFEs, each registering one window.Evo* namespace, in
 * web/ocean.html's order. No page loads this file and nothing here exists at run time. tsc reads it
 * with the files that carry // @ts-check (tsconfig.json lists them), so
 *   - a checked file's namespace is checked against its contract here (an exported member missing,
 *     misspelled or of another shape is an error), and
 *   - a checked file's calls into another namespace are checked against that one's contract.
 * A namespace whose file is not checked yet (EvoOceanScene, EvoOcean, ...) is declared by what the
 * checked files use of it: the seam, not the whole object. Grow these as files are checked.
 *
 * The shared shapes: the engine's exports the front end calls (OceanModule), the per-frame snapshot
 * views (OceanSnapshot), the world file's header (WorldHeader), the gene slot store's records
 * (SlotStore and co.), the profiler the page and the scene drive (Profiler). */

/* ---------------- small helpers ---------------- */

/** a writable list of numbers: a typed array or an array */
interface NumArray { length: number; [index: number]: number }
/** a JSON value as JSON.parse makes it */
type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
/** a flat settings record (a cfg): oc_init's keys, numbers and switches */
type Cfg = Record<string, number | boolean>;

/* ---------------- the engine: web/evo_ocean.{js,wasm} (wasm/ocean_wasm.cpp, EVO_EXPORT) ---------------- */

/** One instance of the Ocean module (createEvoOcean()), as the page, the Turbo worker and the hand-off
 * helpers call it. Pointers are byte offsets into the module's memory (buffer(M), never cached across a
 * call: an allocating export can grow it); a const char* is read with EvoOceanHandoff.cString. Every
 * export of the committed module is listed; the page still feature-tests some (ocean.js has()), from
 * before they all existed. */
interface OceanModule {
  HEAPU8: Uint8Array;
  /** the module's memory (exported: the hand-off grows it with Memory.grow) */
  wasmMemory?: WebAssembly.Memory;
  _malloc(bytes: number): number;
  _free(ptr: number): void;
  /** 1, or 0 with oc_last_error() set (the previous world kept); cfgJson: a C string or 0 */
  _oc_init(seed: number, width: number, height: number, depth: number, population: number, cfgJson: number): number;
  _oc_reset(): number;
  _oc_step(n: number): void;
  /** refresh every exported buffer below from the world (after a step, before any read) */
  _oc_sync(): void;
  _oc_last_error(): number;
  /** a live setting (name: a C string); 1 or 0 with oc_last_error() set */
  _oc_set_param(name: number, value: number): number;
  _oc_creature_count(): number;
  /** float32 x 12 a fish: the spine's six points (x, y) */
  _oc_creature_segments(): number;
  _oc_creature_depth(): number;
  _oc_creature_vz(): number;
  /** float32 x 2 a fish */
  _oc_body_params(): number;
  /** uint8 x 3 a fish (the colour mode's) */
  _oc_creature_colors(): number;
  /** float64 a fish */
  _oc_creature_ids(): number;
  _oc_appearance_abi(): number;
  _oc_appearance_schema(): number;
  _oc_appearance_flags(): number;
  _oc_appearance_broken(): number;
  _oc_appearance_pattern_genes(): number;
  _oc_appearance_morph_genes(): number;
  _oc_appearance_morph_offset(): number;
  _oc_appearance_stride(): number;
  _oc_pattern_law(): number;
  _oc_morphology_law(): number;
  _oc_morphology_chart_law(): number;
  _oc_appearance_count(): number;
  /** float32 x stride a fish, or 0 (no rows) */
  _oc_creature_appearance(): number;
  _oc_food_count(): number;
  _oc_food_xy(): number;
  _oc_food_depth(): number;
  _oc_predator_count(): number;
  /** float32 x 3 a predator */
  _oc_predator_data(): number;
  _oc_predator_depth(): number;
  /** float64 x oc_stats_len(); [1] is the frame */
  _oc_stats(): number;
  _oc_stats_len(): number;
  _oc_width(): number;
  _oc_height(): number;
  _oc_depth_max(): number;
  _oc_light_enabled(): number;
  _oc_light_l0(): number;
  _oc_light_kwater(): number;
  _oc_e1_preset(): number;
  _oc_has_eye(): number;
  _oc_walls_enabled(): number;
  _oc_num_senses(): number;
  _oc_num_actions(): number;
  _oc_num_hidden(): number;
  _oc_sensor_names(): number;
  _oc_action_names(): number;
  _oc_inspect(index: number): number;
  _oc_inspect_info(): number;
  _oc_inspect_len(): number;
  _oc_inspect_sensors(): number;
  _oc_inspect_hidden(): number;
  _oc_inspect_actions(): number;
  _oc_inspect_conn_count(): number;
  _oc_inspect_conns(): number;
  /** allocates */
  _oc_summary(): number;
  _oc_summary_len(): number;
  /** the k biggest family lines (allocates); their count */
  _oc_families(k: number): number;
  _oc_families_data(): number;
  _oc_family_color(lineageId: number): number;
  _oc_wiring(): number;
  _oc_wiring_data(): number;
  _oc_set_colour_mode(mode: number): void;
  _oc_set_capture(on: number): void;
}

/* ---------------- one frame of the world: web/ocean.js snapshot() ---------------- */

/** Views over one oc_sync's buffers (borrowed: valid until the next sync, a new world, or a growth of
 * the memory: ocean.js fresh() cuts them again). Per fish c: segs[12c ..], depth[c], ids[c],
 * body[2c ..], colors[3c ..], app[63c ..]. */
interface OceanSnapshot {
  buf: ArrayBuffer;
  worldEpoch: number;
  n: number;
  fc: number;
  pc: number;
  selIdx: number;
  segs: Float32Array;
  depth: Float32Array;
  ids: Float64Array;
  body: Float32Array;
  colors: Uint8Array;
  food: Float32Array;
  foodDepth: Float32Array;
  preds: Float32Array;
  predDepth: Float32Array;
  stats: Float64Array;
  /** the pitch (the engine's, or the page's estimate; null before it has one) */
  vz: Float32Array | null;
  /** the appearance rows (63 floats a fish), or null when the module has none this layout knows */
  app: Float32Array | null;
  curActive: boolean;
  curGrid: Float32Array | null;
  curCols: number;
  curRows: number;
}

/* ---------------- web/ocean_handoff.js (window.EvoOceanHandoff; node: module.exports) ---------------- */

/** the page's live edits around a Turbo session (ledger()) */
interface LedgerEntry { key: string; num: number; seq: number; from: "acked" | "sent" | "held" }
interface Ledger {
  start(): void;
  hold(key: string, num: number): void;
  sent(key: string, num: number, seq?: number): void;
  answered(key: string, ok: boolean): LedgerEntry | null;
  pending(key: string, afterSeq?: number): boolean;
  latest(key: string): LedgerEntry | null;
  takeHeld(): LedgerEntry[];
  back(lost: boolean): LedgerEntry[];
  held(): Record<string, number>;
  /** [key, num] of each edit in flight */
  inflight(): Array<Array<string | number>>;
}
/** a repeated JSON key's later occurrence (parseFirst) */
interface JsonRepeat { path: Array<string | number>; key: string; value: Json }

/** the world file's image record (header.image) */
interface WorldImage { bytes: number; stored: number; sha256: string; body: "gzip" | "raw"; bodyBytes: number }
/** where a saved world began (header.start) */
interface WorldStart { seed: number; population: number; depth: number; width: number; height: number; cfg: Cfg }
/** the Save setup record a saved world carries (header.setup) */
interface SetupRecord {
  format: "evo_ocean_setup"; version: number; seed: number; population: number; depth: number;
  width: number; height: number; walls: boolean; config: Cfg;
}
/** the fish selected when it was saved */
interface WorldPicked { id: number; follow: boolean; family?: number | null; x?: number; y?: number; d?: number }
/** A world file's header (web/ocean.js worldHeader writes it; EvoOceanHandoff.headerProblem says what it
 * must be): every field of its type and range, no other. image and sha256 are encodeWorld's. */
interface WorldHeader {
  format: "evo_ocean_world";
  version: 1;
  app?: string;
  saved?: string;
  engine: { module: "evo_ocean"; wasmSha256: string; eye: boolean };
  frame: number;
  fish: number;
  food: number;
  predators: number;
  start: WorldStart;
  runCfg: Cfg;
  setup: SetupRecord;
  picked: WorldPicked | null;
  image: WorldImage;
  sha256: string;
}
/** the limits a page opens (and saves) world files under (worldLimits) */
interface WorldLimits { engine: number; format: number; device: number; image: number; header: number; file: number }
/** what readWorld reads from: a Blob's parts, or bytes */
interface WorldSource { size: number; read(from: number, to: number): Promise<Uint8Array> }
/** a world file's image, unpacked and checked: its stored bytes and its whole length */
interface WorldBody { data: Uint8Array; bytes: number }
interface WorldRead {
  header: WorldHeader;
  /** where the body starts */
  at: number;
  /** cancelled(): the read is superseded (stop); turn(): wait for the page's turn first */
  body(cancelled?: () => boolean, turn?: () => Promise<unknown>): Promise<WorldBody>;
}
/** a module's world, read (worldNow), and what a header says it is (worldExpect) */
interface WorldNow { w: number; h: number; d: number; fish: number; food: number; pred: number; walls: boolean; frame: number }
interface WorldExpect extends WorldNow { picked: boolean }
/** headerProblem's rules: the sheet's keys and live keys, the size limits, Save setup's version */
interface HeaderRules {
  keys: Record<string, ConfigKey>;
  live: Record<string, number>;
  lim: SizeLimits;
  setupVersion: number;
}

interface EvoOceanHandoffApi {
  PAGE: number;
  buffer(M: OceanModule): ArrayBufferLike;
  growTo(M: OceanModule, bytes: number): boolean;
  take(M: OceanModule, src: ArrayBuffer | ArrayBufferView, who?: string, full?: number): void;
  cString(M: OceanModule, ptr: number): string;
  withCString<T>(M: OceanModule, str: string | null | undefined, fn: (ptr: number) => T): T;
  f64(M: OceanModule, ptr: number, len: number): number[];
  f32(M: OceanModule, ptr: number, len: number): number[];
  row(M: OceanModule, famK: number, statsLen: number): { st: number[]; su: number[]; fam: number[] };
  ledger(): Ledger;
  parseFirst(text: string): { value: Json; repeats: JsonRepeat[] };
  cfgJson(cfg: Record<string, Json> | null | undefined, repeats?: Array<{ key: string; value: Json }>): string;
  WORLD: {
    MAGIC: string; FORMAT: string; VERSION: number; EXT: string; PREFIX: number; MAX_HEADER: number; MAX_IMAGE: number;
    MAX_SETUP: number; MAX_DEPTH: number; MAX_VALUES: number; RATIO: number; READ_PART: number; DIGEST: string;
  };
  isWorldFile(head: ArrayBuffer | ArrayBufferView): boolean;
  sha256(data: ArrayBuffer | ArrayBufferView): Promise<string>;
  sha256js(data: ArrayBuffer | ArrayBufferView): string;
  storedLength(image: ArrayBuffer | ArrayBufferView): number;
  canGzip(): boolean;
  encodeWorld(header: object, image: ArrayBuffer | ArrayBufferView, opts?: { raw?: boolean; limits?: WorldLimits }):
    Promise<{ parts: Uint8Array[]; header: WorldHeader; size: number }>;
  worldHeader(file: ArrayBuffer | ArrayBufferView, L?: WorldLimits): { header: WorldHeader; at: number };
  decodeWorld(file: ArrayBuffer | ArrayBufferView, L?: WorldLimits): Promise<{ header: WorldHeader; data: Uint8Array; bytes: number }>;
  wholeImage(w: WorldBody): ArrayBuffer;
  worldLimits(engineBytes?: number, deviceBytes?: number): WorldLimits;
  wasmMemoryMax(bytes: ArrayBuffer | ArrayBufferView): number | null;
  maxBody(stored: number, kind: "gzip" | "raw"): number;
  canon(v: Json): string;
  headerDigest(h: object): Promise<string>;
  sealHeader<T extends object>(h: T): Promise<T & { sha256: string }>;
  readWorld(src: WorldSource, L?: WorldLimits): Promise<WorldRead>;
  blobSource(b: Blob): WorldSource;
  bytesSource(x: ArrayBuffer | ArrayBufferView): WorldSource;
  headerProblem(h: unknown, R: HeaderRules): string;
  worldNow(M: OceanModule): WorldNow;
  worldExpect(h: WorldHeader): WorldExpect;
  worldMismatch(a: WorldNow, e: WorldExpect): string;
  /** ok, and at: the world before its step; or not, and why */
  probeWorld(M: OceanModule, data: ArrayBuffer | ArrayBufferView, bytes: number, expect: WorldExpect): { ok: boolean; at?: WorldNow; why?: string };
  CANCELLED: string;
}

/* ---------------- web/ocean_appearance_slots.js (window.EvoAppearanceSlots; node: module.exports) ---------------- */

interface SlotStoreOptions {
  /** floats a row (the appearance stride, 63) */
  stride?: number;
  /** the barbels' gene in a row, and the value above which a fish has barbels */
  barbelGene?: number;
  barbelMin?: number;
  maxCapacity?: number;
  /** most texSubImage2D ranges in one plan (32) */
  maxRanges?: number;
  initialCapacity?: number;
}
/** prepare()'s answer: one object, reused (copy what you keep) */
interface SlotPrepareResult {
  ok: boolean;
  error: string;
  n: number;
  newRows: number;
  released: number;
  grew: boolean;
  migratedBytes: number;
  changed: boolean;
  hasBarbels: boolean;
}
/** a run of dirty slots, in floats (THREE.DataTexture.addUpdateRange's units) */
interface SlotRange { start: number; count: number }
/** plan(): what to upload, and the write clock acknowledge() compares */
interface SlotUploadPlan {
  full: boolean;
  /** why a full upload: "storage" (new GPU storage), "bytes" or "ranges" (the policy); "" for ranges */
  reason: string;
  ranges: SlotRange[];
  slots: number;
  calls: number;
  bytes: number;
  clock: number;
  capacity: number;
}
/** verify()'s first difference between a slot and its fish's row */
interface SlotMismatch { draw: number; id: number; slot: number; gene: number; stored: number; row: number }
interface SlotStats {
  epoch: unknown; capacity: number; owners: number; nextSlot: number; free: number; dirty: number;
  needFull: boolean; barbels: number; allocs: number; bytes: number;
}
/** One gene slot store (the scene's AppKind owns one; web/ocean_appearance_slots.js says what each does) */
interface SlotStore {
  /** the world's epoch the owners belong to (a new one forgets them all) */
  epoch: unknown;
  capacity: number;
  /** capacity x 64 floats */
  data: Float32Array;
  needFull: boolean;
  dirtyCount: number;
  size: number;
  nextSlot: number;
  allocs: number;
  prepare(epoch: unknown, ids: ArrayLike<number>, rows: ArrayLike<number>, n: number, out?: NumArray | null): SlotPrepareResult;
  ranges(limit: number): SlotRange[];
  plan(): SlotUploadPlan | null;
  verify(ids: ArrayLike<number>, rows: ArrayLike<number>, n: number, k: number): SlotMismatch | null;
  acknowledge(p: SlotUploadPlan | null | undefined): void;
  requireFull(): void;
  resetOwnership(epoch: unknown): void;
  invalidate(): void;
  slotOf(id: number): number;
  isDirty(s: number): boolean;
  stats(): SlotStats;
}
interface EvoAppearanceSlotsApi {
  create(opts?: SlotStoreOptions): SlotStore;
  SLOT_FLOATS: number;
  ROW_SLOTS: number;
  MIN_CAPACITY: number;
  MAX_CAPACITY: number;
}

/* ---------------- web/ocean_perf.js (window.EvoOceanPerf; node: module.exports) ---------------- */

/** the CPU spans (EvoOceanPerf.SPANS, in order) */
type SpanName = "step" | "sync" | "snapshot" | "dashboard" | "controller" | "cameraPick" | "fishPack" | "appearanceRows" |
  "geneRanges" | "otherPack" | "submit" | "card" | "hud" | "gpuPoll" | "frameCpu";
/** the per-frame counters (EvoOceanPerf.COUNTERS, in order) */
type CounterName = "epoch" | "turbo" | "paused" | "simN" | "tick" | "stepsReq" | "submitted" | "hidden" | "lost" | "diag" |
  "bodyInst" | "barbelInst" | "shadowInst" | "lod" | "tplVerts" | "tplTris" | "calls" | "triangles" | "points" | "lines" |
  "instBytes" | "instAllocBytes" | "geneSrcBytes" | "genePadBytes" | "geneDirtySlots" | "geneRanges" | "geneUploads" |
  "geneUploadBytes" | "texAllocs" | "texCapacity" | "geneFull" | "geneUploadCalls" | "litInst" | "gpuIssued";
/** the GPU scopes' labels (EvoOceanPerf.LABELS) */
type GpuLabel = "frame" | "fishBody" | "barbels" | "fishShadow" | "predBody" | "predShadow" | "floor" | "surface" | "food" | "snow" | "other";
type TurboPhase = "live" | "entering" | "turbo" | "exiting";

interface ProfilerConfig { cpu?: boolean | "frame"; gpu?: "off" | "frame" | "draws"; sampleEvery?: number }
/** cpu: "off" | "frame" | "spans"; gpu: "off" | "frame" | "draws" */
interface ProfilerConfigNow { cpu: string; gpu: string; sampleEvery: number }
interface ProfilerCapabilities {
  gpuTimer: boolean;
  /** EvoOceanPerf.disabled's (true) */
  disabled?: boolean;
  timerGeneration?: number;
  lost?: boolean;
  maxQueries?: number;
  ringFrames?: number;
  crossOriginIsolated?: boolean | null;
}
/** one GPU measurement's statuses (EvoOceanPerf.STATUS): ok, disjoint, aborted, lost */
interface GpuResults { n: number; frame: Float64Array; label: Uint8Array; ms: Float64Array; status: Uint8Array; generation: Uint32Array }
interface GpuStats {
  attempted: number; issued: number; ok: number; unsupported: number; skippedPool: number; refusedNest: number;
  disjointEvents: number; discardedDisjoint: number; aborted: number; discardedLost: number; resultOverflow: number; droppedEarlier: number;
}
/** a capture, as drain() hands it over (typed arrays, frame-major) */
interface Capture {
  schema: { spans: SpanSpec[]; counters: CounterSpec[]; labels: GpuLabel[]; statuses: string[] };
  config: ProfilerConfigNow;
  capabilities: ProfilerCapabilities;
  frames: number;
  recorded: number;
  overflow: boolean;
  valid: boolean;
  ts: Float64Array;
  raw: Float64Array;
  cpu: Float64Array;
  cnt: Float64Array;
  gpu: {
    results: GpuResults | { n: 0 };
    stats: GpuStats | null;
    pending: number;
    complete: boolean;
    generation: number;
    supported: boolean;
  };
}
type SpanSpec = [SpanName, string, boolean];
type CounterSpec = [CounterName, string];

/** The profiler the page (web/ocean.js) and the scene (web/ocean_scene.js) drive every frame. The page
 * holds EvoOceanPerf.disabled unless ?renderBench=1 / ?perf=1 ask for a real one (create()); the scene,
 * without web/ocean_perf.js, one of its own that records nothing. A span is a token: beginCpu()'s clock
 * reading, 0 when nothing is timed. */
interface Profiler {
  enabled: boolean;
  /** a frame is being recorded: the scene's counters are worth computing */
  active: boolean;
  SPAN: Record<SpanName, number>;
  K: Record<CounterName, number>;
  LABEL: Record<GpuLabel, number>;
  configure(c?: ProfilerConfig): ProfilerConfigNow | void;
  config(): ProfilerConfigNow;
  beginFrame(rafTs: number, epoch: number, turbo: TurboPhase | string, paused: boolean): void;
  recordStep(ms: number, steps: number): void;
  beginCpu(): number;
  endCpu(k: number, tok: number): void;
  lap(k: number, tok: number): number;
  count(k: number, v: number): void;
  add(k: number, v: number): void;
  markDiagnostic(): void;
  endFrame(n: number, tick: number, hidden: boolean): void;
  attachGL(gl: WebGL2RenderingContext | WebGLRenderingContext | null): void;
  watch(obj: { onBeforeRender: Function; onAfterRender: Function } | null, label: GpuLabel): void;
  beginSubmission(): void;
  endSubmission(ok: boolean): void;
  suspend<T>(fn: () => T): T;
  capabilities(): ProfilerCapabilities;
  stopSampling(): void;
  pending(): number;
  resetCapture(): void;
  drain(): Capture | null;
}
/** EXT_disjoint_timer_query_webgl2's elapsed queries (EvoOceanPerf.GpuTimer) */
interface GpuTimerOptions { maxQueries?: number; results?: number }

/** the page's hooks for the benchmark (web/ocean.js: EvoOcean.bench = EvoOceanPerf.bench(hooks)) */
interface BenchHooks {
  module: OceanModule;
  scene: OceanScene;
  profiler: Profiler;
  page: OceanPageApi;
  setPaused(on: boolean): void;
  /** the current snapshot; null once the engine stopped (its reader is fenced) */
  last(): OceanSnapshot | null;
  /** oc_step + oc_sync, fenced: false when it could not */
  step(n: number): boolean;
  epoch(): number;
  initArgs(): { seed: number; population: number; depth: number; width: number; height: number; cfg?: Cfg } | null;
  /** the page's own import: "" or why not */
  importWorld(seed: number, population: number, depth: number, cfg: Cfg, ...rest: unknown[]): string;
  setColourMode(mode: string): boolean;
  colourMode(): string;
  dashOpen(): boolean;
}
/** a benchmark case (tests/fixtures/ocean_render_cases.json) as prepare() takes it */
interface BenchCase {
  worldSeed?: number;
  population?: number;
  config?: Cfg;
  world?: [number, number, number];
  tick?: number;
  colourMode?: string;
  quality?: number;
  governor?: boolean;
  camera?: "whole" | "dense" | "follow";
  settleMs?: number;
}
interface BenchSnapshotCopy {
  worldEpoch: number; tick: number; n: number; ids: Float64Array; app: Float32Array | null;
  body: Float32Array; segs: Float32Array; depth: Float32Array;
}
interface RafProbe { frames: number; wallMs: number; rafFps: number | null; raf: Quantiles; over25ms: number | null }
interface Quantiles { n: number; mean: number | null; p50: number | null; p95: number | null; p99: number | null; max: number | null }
interface Bench {
  frames(k: number): Promise<void>;
  wait(ms: number): Promise<void>;
  stepToTick(t: number): Promise<void>;
  snapshotCopy(): BenchSnapshotCopy | null;
  rafProbe(ms: number): Promise<RafProbe>;
  prepare(cd?: BenchCase): Promise<object>;
  live(on: boolean): Promise<void>;
  capture(c?: ProfilerConfig & { durationMs?: number; drainMs?: number; raw?: boolean }): Promise<unknown>;
  textureParity(o?: { expected?: BenchSnapshotCopy | null }): Promise<unknown>;
  info(): object;
}
interface EvoOceanPerfApi {
  SPANS: SpanSpec[];
  COUNTERS: CounterSpec[];
  LABELS: GpuLabel[];
  STATUS: string[];
  SPAN: Record<SpanName, number>;
  K: Record<CounterName, number>;
  LABEL: Record<GpuLabel, number>;
  create(o?: { now?: () => number; frames?: number; maxQueries?: number; timer?: object }): Profiler;
  disabled: Profiler;
  forPage(on: boolean): Profiler;
  GpuTimer: Function;
  summarize(cap: Capture | null): object | null;
  exportCapture(cap: Capture | null): object | null;
  quantiles(values: ArrayLike<number>): Quantiles;
  visualRandom(seed: number): () => number;
  bench(h: BenchHooks): Bench;
}

/* ---------------- web/ocean_config.js (window.EvoOceanConfig) ---------------- */

/** a field's options: a number's step / range / int, a select's options, a bit switch (an int key, 0 / 1) */
interface ConfigKeyOpts { step?: number; min?: number; max?: number; int?: boolean; options?: string[]; bit?: boolean }
/** [default, options]; a boolean default is a switch */
type ConfigKey = [number | boolean, ConfigKeyOpts?];
interface SizeLimits { side: [number, number]; depth: [number, number]; population: [number, number] }
interface ConfigTab { id: string; title: string; groups?: Array<[string, string[]]> }
/** Randomize's range: [min, max, step, source] */
type ConfigRange = [number, number, number, string];
interface BigTank { width: number; height: number; depth: number; population: number; cfg: Cfg }
interface ScenarioMeta { id: string; title: string; blurb: string }
interface ScenarioContext {
  seed: number;
  screen: [number, number];
  walls: boolean;
  e1: Cfg | null;
  rand: () => number;
  tank: { width: number; height: number; depth: number; walls: boolean; sideWallBand: number; sideWallTurnRate: number };
}
interface Scenario {
  id: string; title: string; summary: string; seed: number; population: number; depth: number; width: number; height: number;
  cfg: Cfg; labels: string[];
}
interface EvoOceanConfigApi {
  KEYS: Record<string, ConfigKey>;
  LIVE: Record<string, number>;
  NEG_ON_RESTART: Record<string, number>;
  TABS: ConfigTab[];
  LABELS: Record<string, string>;
  HINTS: Record<string, string>;
  BTN_STEP: Record<string, number>;
  TIPS: Record<string, { d: string; t: string }>;
  RANGES: Record<string, ConfigRange>;
  CHANCE: Record<string, number>;
  draw(rand: () => number, basePop: number, e1: Cfg | null | undefined, size?: number[] | null): { population: number; set: Cfg; labels: string[] };
  FRESH: Cfg;
  BIG_TANK: BigTank;
  SIZE_LIMITS: SizeLimits;
  REFERENCE: { width: number; height: number; depth: number };
  scaleToVolume(set: Cfg, population: number, volume: number, labels: string[]): number;
  SCENARIOS: ScenarioMeta[];
  scenario(id: string, ctx: ScenarioContext): Scenario | null;
  HUNTERS: Cfg;
  CURRENTS: Cfg;
}

/* ---------------- web/ocean_appearance.js (window.EvoAppearance) ---------------- */

interface AppearanceLod {
  rings: number[]; half: number; caud: number; collar: number; dors: number; pec: number; pel: number;
  eyes: number; barb: number; dupEnds: number;
}
/** The appearance law (web/ocean_appearance.js). Its functions' results are the law's own records,
 * untyped here until the scene (their caller) is checked. */
interface EvoAppearanceApi {
  /** the layout and laws this renderer knows (the module's oc_appearance_abi, ...) */
  LAWS: { abi: number; schema: number; patternLaw: number; morphLaw: number; chartLaw: number };
  /** pattern genes; the morphology genes' offset in a row, and their count; a row's floats (63) */
  NG: number;
  MO: number;
  NM: number;
  STRIDE: number;
  PHI_I: number;
  GLSL: { COMMON: string; VARY: string; DECODE: string; SKIN: string; GENES: string; MORPH: string };
  LODS: Record<string, AppearanceLod>;
  buildTemplate(lodName: string): any;
  buildBarbels(lodName: string): any;
  decode(g: ArrayLike<number>, lam: number): any;
  flankAt(D: any, u: number, v: number, out?: number[]): any;
  flankImage(row: ArrayLike<number>, lam: number, W: number, H: number): any;
  lambdaOf(size: number, elong: number): number;
  patternVaryings(g: ArrayLike<number>, lam: number): any;
  morphDecode(g: ArrayLike<number>, lam: number): any;
  morphBuild(M: any, rings: any, a: number, pat: any, time: number, wag: number, minW: number): any;
}

/* ---------------- web/ocean_shaders.js (window.EvoOceanShaders) ---------------- */

/** A fish program's variant (the swim polish): false plain (the fish as before the polish, its GLSL byte
 * for byte), true full, "lite" the roll only. */
type FishVariant = boolean | "lite";
/** The appearance fish's programs, one variant (appearanceShaders): the body's vertex and fragment stages,
 * its shadow's vertex stage, and the checks' and probes' programs (the flank chart, the live texture's raw
 * genes and charts). */
interface AppearancePrograms {
  vs: string; fs: string; shadowVs: string;
  chartVs: string; chartFs: string; probeRawVs: string; probeRawFs: string; probeChartVs: string;
}
/** The scene's GLSL: the chunks its programs share, the environment's programs, and the fish programs in
 * their variants with the functions that build them (web/ocean_shaders.js says what each draws). */
interface EvoOceanShadersApi {
  FOG_FN: string;
  BEAM_FN: string;
  DEPTH_FN: string;
  CLARITY_FN: string;
  FLOOR_VS: string;
  FLOOR_FS: string;
  SURF_FS: string;
  FOOD_VS: string;
  FOOD_FS: string;
  GLOW_VS: string;
  GLOW_FS: string;
  SNOW_VS: string;
  SNOW_FS: string;
  GLASS_VS: string;
  GLASS_FS: string;
  LINE_VS: string;
  LINE_FS: string;
  RING_VS: string;
  RING_FS: string;
  /** a program from its lines (the null ones, a variant's absent lines, left out) */
  lines(a: (string | null)[]): string;
  /** how often sub occurs in s */
  occurrences(s: string, sub: string): number;
  /** the swim pose's GLSL (poseOf: the packed float -> iPose; rollTo, wagAt, causOf) and the polish's light */
  POSE_GLSL: string;
  POLISH_FN: string;
  /** the plain fish's and the predators' programs: the vertex stages' common part, the body's vertex and
   * fragment stages, the shadow's vertex stage */
  fishCore(P: FishVariant): string;
  fishVs(P: FishVariant): string;
  fishFs(P: FishVariant): string;
  shadowVs(P: FishVariant): string;
  /** built once: FISH_VS / FISH_FS [plain, full, lite] (lite's fragment stage is the plain one),
   * SHADOW_VS [plain, lite], SHADOW_FS (every variant's) */
  FISH_VS: string[];
  FISH_FS: string[];
  SHADOW_VS: string[];
  SHADOW_FS: string;
  /** an instance's gene slot, read by every gene-reading program (and the statement it returns) */
  GENE_SLOT_RET: string;
  GENE_SLOT_GLSL: string;
  /** the split: a lit appearance fish's highlight (iBody.z) in the main draw, the line that skips such an
   * instance, and litSkip(vs), a vertex stage (one main) with that line first */
  LIT_SKIP: number;
  LIT_SKIP_GLSL: string;
  litSkip(vs: string): string;
  /** the fetched slot's pattern genes -> the flat pattern varyings */
  DECODE_CALL: string;
  /** a float32 constant as a GLSL float literal */
  glslF(x: number): string;
  /** the appearance fish's programs (P absent: plain); appCore, the vertex stages' common part;
   * appearanceShadersOf, the programs around given common parts (body, shadow) */
  appearanceShaders(EA: EvoAppearanceApi, P?: FishVariant): AppearancePrograms;
  appCore(EA: EvoAppearanceApi, P?: FishVariant): string;
  appearanceShadersOf(EA: EvoAppearanceApi, P: FishVariant | undefined, CORE: string, SCORE: string, F: boolean | undefined): AppearancePrograms;
}

/* ---------------- web/ocean_pose.js (window.EvoOceanPose) ---------------- */

/** How far a kind's geometry reaches past its spine (reachRadius): forward of the head at most
 * min(uf, sn + kf / lambda) body lengths, behind the tail at most min(ub, tb + kb / lambda), and pad body
 * radii off the spine. */
interface PoseReach { sn: number; kf: number; uf: number; tb: number; kb: number; ub: number; pad: number }
/** The swim pose's camera for one frame (the scene's poseCamera()). */
interface PoseCamera {
  /** false: every fish weighs 1 (the measurements' ungated reference) */
  gate: boolean;
  /** true: every weight 0 (the plain programs' reference) */
  zero: boolean;
  /** the view matrix (world -> camera), column-major, 16 */
  view: ArrayLike<number>;
  /** the frustum's four side planes in camera space: (x or y, depth) unit normals, + outside, 8 */
  planes: ArrayLike<number>;
  /** the focal length in CSS px (the projection's, with the zoom and the panels' view offset) */
  focal: number;
  /** the near plane's distance */
  near: number;
  /** half the tank's width and height (the sim -> three offset) */
  halfW: number;
  halfH: number;
}
/** The swim pose on the CPU: a fish's size weight, its pose packed in one float, the reach. xs, ys: its
 * spine as uploaded (six sim points, head first, unwrapped); R its body radius, y its height (three Y), vz
 * its pitch, lam its lambda (the legacy kinds 1); v its swimming speed / 150 (0: no fold); qw a weight in
 * 7 bits (1 .. 127). */
interface EvoOceanPoseApi {
  /** the appearance fish's reach; the tail beat's largest offset (body radii); the unlit pose */
  REACH_APP: PoseReach;
  WAG_MAX: number;
  POSE0: number;
  /** a legacy template's reach (its positions, 3 a vertex) */
  reachOfTemplate(pos: ArrayLike<number>): PoseReach;
  /** the radius about the head-tail centre that holds everything drawn for the fish */
  reachRadius(xs: ArrayLike<number>, ys: ArrayLike<number>, R: number, vz: number, lam: number, K: PoseReach): number;
  /** the body radius in CSS px at its nearest depth */
  posePx(xs: ArrayLike<number>, ys: ArrayLike<number>, R: number, y: number, G: PoseCamera): number;
  /** the size weight in 7 bits, 0 for a fish whose whole reach is out of view (px: posePx's, over 6) */
  poseVisibleQ(xs: ArrayLike<number>, ys: ArrayLike<number>, R: number, y: number, G: PoseCamera, vz: number, lam: number, K: PoseReach, px: number): number;
  /** the size weight in 7 bits (G.gate false: 127; G.zero: 0; K absent: REACH_APP) */
  poseQ(xs: ArrayLike<number>, ys: ArrayLike<number>, R: number, y: number, G: PoseCamera, vz?: number, lam?: number, K?: PoseReach): number;
  /** the roll and the fold of a lit fish, packed (packPose's layout) */
  posePack(xs: ArrayLike<number>, ys: ArrayLike<number>, v: number, qw: number): number;
  /** one fish's swim pose, packed: posePack if it is lit, else POSE0 */
  swimPose(xs: ArrayLike<number>, ys: ArrayLike<number>, R: number, y: number, v: number, G: PoseCamera, vz?: number, lam?: number, K?: PoseReach): number;
  /** the float's layout: sin(roll), fold, weight -> an integer below 2^24, and back to [sin, cos, fold, weight] */
  packPose(s: number, tuck: number, w: number): number;
  unpackPose(p: number): number[];
  /** GLSL's smoothstep */
  smoothCPU(a: number, b: number, x: number): number;
}

/* ---------------- web/ocean_scene_parity.js (window.EvoOceanSceneParity) ---------------- */

/** The water's clarity (the scene's CLARITY): each entry [realistic, clear]; the fragment check sets the
 * realistic column's uniforms. Declared by what the checks read. */
interface WaterClarity {
  fog: [number[], number[]]; deepTint: [number[], number[]]; deepDim: [number, number]; deepAdd: [number[], number[]];
  lKeep: [number, number]; floorMin: [number, number]; back: [number, number];
  ambLo: [number[], number[]]; ambHi: [number[], number[]]; vivid: [number[], number[]];
}
/** What the checks take from the scene (bind, as it loads): the gene texture's layout as the renderer lays
 * it out (GENES_W texels a row, genesRows(capacity) rows, packGenes(T, R, r, slot, ST): row r of R into
 * slot's 16 texels of T) and its capacities (capFor(n): 256 up, powers of two); the water's constants the
 * fragment check sets (CLARITY, C.select). */
interface ParityScene {
  GENES_W: number;
  genesRows(cap: number): number;
  packGenes(T: Float32Array, R: Float32Array, r: number, slot: number, ST: number): void;
  capFor(n: number): number;
  CLARITY: WaterClarity;
  C: { select: number[] };
}
/** a check's options: colourBy 0 appearance / 1 recolour; polish the variant; mutate / fsMutate a planted
 * fault (vertex: row0, nextRow, slot, partW, drawIndex; fragment: swapRB, branch); slotMap the fish's gene
 * slots; injectSweep NaN / +-Inf into each captured component */
interface ParityCheckOptions {
  colourBy?: number; polish?: FishVariant; mutate?: string; fsMutate?: string;
  slotMap?: "identity" | "permuted" | "sparse"; injectSweep?: boolean;
}
/** The appearance fish's GPU == CPU checks (web/ocean_scene_parity.js says what each checks): on any
 * WebGL2 context, a Promise of the report (.error: it did not run; .ok: it passed). EA: EvoAppearance;
 * rows / lams: fish added to the fixed fixture. */
interface EvoOceanSceneParityApi {
  /** the scene's layout and water (once, as web/ocean_scene.js loads; before it a check throws) */
  bind(scene: ParityScene): void;
  /** resolves null once the GPU passed sync, else why not (lost, failed, ms) */
  fenceDone(gl: WebGL2RenderingContext, sync: WebGLSync, ms: number): Promise<string | null>;
  appearancePathCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, rows?: ArrayLike<number>[] | null, lams?: number[] | null, opts?: ParityCheckOptions): Promise<any>;
  appearanceVertexCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, rows: ArrayLike<number>[], lams: number[], opts?: ParityCheckOptions): Promise<any>;
  appearanceFragmentCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, opts?: ParityCheckOptions): Promise<any>;
}

/* ---------------- not checked yet: declared by what checked files use ---------------- */

/** the scene (web/ocean_scene.js create()): what the benchmark and the page's API use of it */
interface OceanScene {
  setQuality(q: number): void;
  quality(): number;
  appearance(): { want: boolean; skin: boolean; shapes: boolean; drawing: boolean; status?: string; lod?: string; verts?: number; barbels?: boolean };
  appearanceTextureParity(expected: BenchSnapshotCopy | null, o?: object): Promise<unknown>;
  contextInfo?(): object;
  clarity?(): number;
  lookFrom(pos: number[], target: number[]): void;
}
interface EvoOceanSceneApi {
  load(): Promise<unknown>;
  create(canvas: HTMLCanvasElement, opts?: object): OceanScene | null;
}
/** the page's state (EvoOcean.state()): what the benchmark reads */
interface OceanPageState {
  n: number; fc: number; pc: number; W: number; H: number; D: number; paused: boolean; frame: number; seed: number | null;
  walls: boolean; view: unknown; flashlightLevel: number; following: boolean; selectedId: number | null; [more: string]: unknown;
}
/** window.EvoOcean (web/ocean.js): what the benchmark uses of it */
interface OceanPageApi {
  module: OceanModule;
  scene: OceanScene;
  /** null: no snapshot (the engine stopped, or is restarting) */
  state(): OceanPageState | null;
  select(idx: number): void;
  follow(on?: boolean): void;
  bench?: Bench;
  perf?: Profiler;
}
/** the published asset names (ocean.html's EVO_ASSETS; build_site.sh rewrites them to content-hashed ones) */
interface EvoAssets { ocean?: string; oceanWasm?: string; worker?: string; handoff?: string; mock?: string; three?: string; [name: string]: string | undefined }

declare var EvoOceanHandoff: EvoOceanHandoffApi;
declare var EvoAppearanceSlots: EvoAppearanceSlotsApi;
declare var EvoOceanPerf: EvoOceanPerfApi;
declare var EvoOceanConfig: EvoOceanConfigApi;
declare var EvoAppearance: EvoAppearanceApi;
declare var EvoOceanShaders: EvoOceanShadersApi;
declare var EvoOceanPose: EvoOceanPoseApi;
declare var EvoOceanSceneParity: EvoOceanSceneParityApi;
declare var EvoOceanScene: EvoOceanSceneApi;
/** set by web/ocean_scene.js when a script it needs did not load ("ocean_shaders.js", "ocean_pose.js",
 * "ocean_scene_parity.js", " and " between): the page's "could not start" names it (else "ocean_scene.js",
 * the scene itself) */
declare var EvoOceanSceneMissing: string | undefined;
declare var EvoOcean: OceanPageApi;
declare var EVO_ASSETS: EvoAssets;
