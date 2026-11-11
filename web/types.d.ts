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
  /* the M2a body-plan preview (DIAGNOSTIC; wasm/ocean_wasm.cpp ADDITIONS): versions, strides, rows */
  _oc_physical_schema(): number;
  _oc_physical_founder_law(): number;
  _oc_physical_inheritance_law(): number;
  _oc_physical_stream_law(): number;
  /** the physical alleles a fish (5) */
  _oc_physical_genes(): number;
  _oc_body_geometry_law(): number;
  _oc_body_metrics_abi(): number;
  /** the coefficients a fish (oc_body_metrics_layout's stride) */
  _oc_body_metrics_stride(): number;
  _oc_body_plan_enabled(): number;
  _oc_body_plan_broken(): number;
  /** rows this sync (0 while the preview is off or broken) */
  _oc_body_count(): number;
  /** float32 x 5 a fish, or 0 */
  _oc_creature_physical(): number;
  /** uint32 x 2 a fish (the owner id's low, high word), or 0 */
  _oc_body_owner_ids(): number;
  /** float32 x stride a fish, or 0 */
  _oc_creature_body_metrics(): number;
  /** a C string: the coefficient layout (JSON: BodyLayout) */
  _oc_body_metrics_layout(): number;
  /** the fixture viewer's compile (pointers to 63 and 5 floats); 1 or 0 */
  _oc_body_preview(genes: number, size: number, elong: number, physical: number, gas: number, fuel: number): number;
  _oc_body_preview_metrics(): number;
  _oc_body_preview_points(): number;
  /** the renderer's rest law at the canonical samples, body radii (genes: a pointer to 63 floats) */
  _oc_body_rest(genes: number, lambda: number): number;
  _oc_body_rest_points(): number;
  _oc_body_sample_count(): number;
  _oc_body_tri_count(): number;
  /** float32 x 6 a sample: aT (4), part, side */
  _oc_body_samples(): number;
  /** uint16 x 4 a triangle: three samples, the part */
  _oc_body_tris(): number;
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
  /** the M2a body-plan preview's rows (diagnostic; web/ocean.js bodyView), or null when the world has none or
   * the module's layout is not this page's. Never read by the scene: `body` above is what it draws with. */
  bodyPlan: BodyPlanView | null;
  curActive: boolean;
  curGrid: Float32Array | null;
  curCols: number;
  curRows: number;
}

/** one sync's body-plan rows: genes 5 a fish, owners 2 uint32 words a fish (low, high), metrics `stride` a fish */
interface BodyPlanView { genes: Float32Array; owners: Uint32Array; metrics: Float32Array; stride: number }

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
  /** the owner hooks (render-only caches keyed by slot; none: the store behaves as before). They run inside prepare() and
   * must not throw or call the store: onGrow(capacity) after the storage grew (the old data kept), onReset(epoch) when
   * every owner is forgotten, onRelease(slot) when an owner's slot is freed, onInstall(slot, data, offset, id) after a new
   * owner's row (63 floats and the zero padding) was written at data[offset ..] */
  onGrow?: (capacity: number) => void;
  onReset?: (epoch: unknown) => void;
  onRelease?: (slot: number) => void;
  onInstall?: (slot: number, data: Float32Array, offset: number, id: number) => void;
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
  fishVs(P: FishVariant, more?: string[]): string;
  fishFs(P: FishVariant, more?: string[]): string;
  shadowVs(P: FishVariant, more?: string[]): string;
  /** built on first read (an assembly error then fails the read, not the module): FISH_VS / FISH_FS
   * [plain, full, lite] (lite's fragment stage is the plain one), SHADOW_VS [plain, lite]; SHADOW_FS
   * (every variant's) */
  readonly FISH_VS: string[];
  readonly FISH_FS: string[];
  readonly SHADOW_VS: string[];
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
  /** the appearance fish's programs (P absent: plain; more: other features' ids, for the programs they
   * target); appCore, the vertex stages' common part */
  appearanceShaders(EA: EvoAppearanceApi, P?: FishVariant, more?: string[]): AppearancePrograms;
  appCore(EA: EvoAppearanceApi, P?: FishVariant): string;
  /** the fish programs' named slots (step 4a): the slots' ABI, each slot's contract, the programs with slots */
  ABI: number;
  SLOTS: { readonly [slot: string]: ShaderSlotSpec };
  PROGRAMS: { readonly [program: string]: ShaderProgramSpec };
  /** a named slot in a program's parts (fallback: its text when no enabled feature replaces it; null none) */
  slot(name: string, fallback: string | null): ShaderSlot;
  /** the names a GLSL source declares, scope by scope (the checks' scan) */
  declarations(src: string): ShaderDeclaration[];
  /** the module's own assembler: register a feature; assemble a program, or a vertex stage's common part
   * (core: the slots it has), with the enabled features' ids; the registered ids */
  feature(spec: ShaderFeatureSpec): ShaderFeature;
  program(name: string, parts: ShaderPart[], features?: string[], env?: ShaderEnv): string;
  core(name: string, parts: ShaderPart[], features?: string[], env?: ShaderEnv): string;
  features(): string[];
  /** a registered feature by id (null: none) */
  featureOf(id: string): ShaderFeature | null;
  /** a fresh registry and assembler (no feature registered: the tests') */
  assembler(): ShaderAssembler;
  /** each program's parts (fresh arrays): the legacy fish's, the appearance fish's (EA's GLSL) */
  parts: FishProgramParts;
  /** the swim polish's two features (plain is neither), and its spec in a mode (to register elsewhere) */
  POLISH: { readonly lite: string; readonly full: string };
  polishFeature(mode: "lite" | "full"): ShaderFeatureSpec;
}

/** A named slot in a fish program's parts (EvoOceanShaders.slot). */
interface ShaderSlot { slot: string; fallback: string | null }
/** A program's part: GLSL, null (none: lines() drops it) or a named slot. */
type ShaderPart = string | null | ShaderSlot;
/** What a program is assembled for: the appearance programs pass the appearance law (EA). */
interface ShaderEnv { EA?: EvoAppearanceApi }
/** A feature's text for a slot: GLSL, or a function of the program's environment giving it ("" adds no
 * line). */
type ShaderText = string | ((env: ShaderEnv) => string);
/** A feature, as registered (EvoOceanShaders.feature): its id (namespaced by its owner, "reef.fish"; registered
 * once, as its script loads); the slots' ABI; the programs it supports; by slot, the text it appends
 * (additive slots) or replaces the fallback with (replacement slots); order: where its appends go among
 * others' in every slot it appends to (then by id; default 0); version: a whole number from 1 (default 1),
 * part of the material binder's key with the id. */
interface ShaderFeatureSpec {
  id: string;
  abi: number;
  targets: string[];
  append?: { [slot: string]: ShaderText };
  replace?: { [slot: string]: ShaderText };
  order?: number;
  version?: number;
}
/** A registered feature (frozen). */
interface ShaderFeature {
  readonly id: string;
  readonly abi: number;
  readonly version: number;
  readonly targets: readonly string[];
  readonly append: { readonly [slot: string]: ShaderText };
  readonly replace: { readonly [slot: string]: ShaderText };
  readonly order: number;
}
/** A slot's contract: kind (append: additive, any number of features in their order; replace: one
 * provider), stage, where it is, what it may read, what it writes; must: what a replacement declares. */
interface ShaderSlotSpec {
  readonly kind: "append" | "replace";
  readonly stage: "vs" | "fs";
  readonly at: string;
  readonly reads: readonly string[];
  readonly writes: readonly string[];
  readonly must: readonly string[];
}
/** A program with slots: its slots in order. */
interface ShaderProgramSpec {
  readonly abi: number;
  readonly stage: "vs" | "fs";
  readonly doc: string;
  readonly slots: readonly string[];
}
/** A declaration the source scan found: its name, scope ("" the globals, else "function#k"), kind
 * (uniform, attribute, varying, const, global, struct, function, local) and the offset of its statement. */
interface ShaderDeclaration { name: string; scope: string; kind: string; at: number }
/** A registry of features and the assembler over it. */
interface ShaderAssembler {
  feature(spec: ShaderFeatureSpec): ShaderFeature;
  program(name: string, parts: ShaderPart[], features?: string[], env?: ShaderEnv): string;
  core(name: string, parts: ShaderPart[], features?: string[], env?: ShaderEnv): string;
  features(): string[];
  get(id: string): ShaderFeature | null;
}
/** The fish programs' parts, fresh each call. */
interface FishProgramParts {
  fishCore(): ShaderPart[];
  fishVs(): ShaderPart[];
  fishFs(): ShaderPart[];
  shadowVs(): ShaderPart[];
  /** a pass a look owns on the legacy fish's instances (program "fish.attach.vs"): the common part, the
   * look's declarations, main() with the pose read first, then the look's body (it calls fishWorld()) */
  fishAttach(decl: string, body: string): ShaderPart[];
  appCore(EA: EvoAppearanceApi): ShaderPart[];
  appBodyVs(EA: EvoAppearanceApi): ShaderPart[];
  appBodyFs(EA: EvoAppearanceApi): ShaderPart[];
  appShadowVs(EA: EvoAppearanceApi): ShaderPart[];
}

/* ---------------- web/ocean_materials.js (window.EvoOceanMaterials) ---------------- */

/** A kind's declared attribute layout (EvoOceanMaterials.layout): its template's attributes, its instance attributes
 * component by component as the scene's fills write them, the swim pose's component reserved, the components the scene
 * uses, the spare ones a Look may claim, the claims made. A component is "iX.y", a scalar attribute's its name. */
interface AttributeLayout {
  readonly id: string;
  readonly kind: string;
  readonly template: readonly string[];
  readonly attributes: { readonly [name: string]: readonly string[] };
  readonly reserved: { readonly [component: string]: string };
  readonly used: { readonly [component: string]: string };
  readonly spare: readonly string[];
  readonly claims: { readonly [component: string]: string };
  readonly pose: string;
}
/** A kind the binder draws: its programs' family, its layout's kind, its passes. */
interface MaterialKindSpec {
  readonly family: "app" | "fish" | "attach";
  readonly layout: string;
  readonly passes: readonly string[];
  readonly doc: string;
}
/** What a feature set's features() is asked: a kind's pass's stage in a variant, and the swim polish's ids for it. */
interface MaterialFeatureQuery { kind: string; pass: string; stage: "vs" | "fs"; variant: number; base: string[] }
/** A Look's attached pass on the predators (#47's faces): its declarations and main() body (fish.attach.vs), its own
 * fragment stage, its uniforms (beside the predators'), material options, geometry (for the activation's compile). */
interface MaterialAttach {
  decl: string; body: string; fs: string;
  uniforms?: { [name: string]: { value: any } };
  options?: object;
  geometry?: () => any;
}
/** A feature set (activate): the Look's id, its features by stage, its attached pass, its uniforms and claims by kind. */
interface MaterialSetSpec {
  look: string;
  features?: (q: MaterialFeatureQuery) => string[];
  attach?: { face?: MaterialAttach };
  uniforms?: { [kind: string]: { [name: string]: { value: any } } };
  claims?: { [kind: string]: { [component: string]: string } };
}
/** A feature set, normalized (frozen), with its layouts by kind. */
interface MaterialSet {
  readonly look: string;
  readonly features: ((q: MaterialFeatureQuery) => string[]) | null;
  readonly attach: { face: MaterialAttach } | null;
  readonly uniforms: { [kind: string]: { [name: string]: { value: any } } } | null;
  readonly layouts: { readonly [kind: string]: AttributeLayout };
  /** a digest of the faces' GLSL and options ("" without them): in the faces' key */
  readonly faceDigest: string;
}
/** A kind as the scene defines it: its uniforms by pass (the scene's objects: every variant shares them), the programs'
 * environment (the appearance law). */
interface MaterialKindDef { uniforms: { [pass: string]: object }; env?: ShaderEnv }
/** What a (kind, pass, variant) draws under a set: its features per stage, its layout, its key, and its share key (the key
 * without the kind: the keys whose material would be identical share it). */
interface Described {
  key: string; share: string; kind: string; pass: string; variant: number; vs: string[]; fs: string[]; layout: AttributeLayout; set: MaterialSet;
}
/** A material and its state, shared by the keys it draws (refs); reserved: made, its GLSL not assembled yet. */
interface BinderRecord { share: string; material: any; state: "reserved" | "ready" | "failed"; error: string; refs: number }
/** A cached material: its key, what it is, its (shared) record. */
interface BinderEntry {
  key: string; kind: string; pass: string; variant: number; vs: string[]; fs: string[];
  layout: AttributeLayout; set: MaterialSet; rec: BinderRecord;
}
/** What a mesh was last bound to: the variant asked, the one drawn (0 on a fallback), the material's key. */
interface MaterialBound { kind: string; pass: string; variant: number; effective: number; key: string; fallback: boolean }
/** One material an activation compiles. */
interface MaterialCompileItem { key: string; kind: string; pass: string; variant: number; material: any; geometry: (() => any) | null }
/** An activation's outcome (stage: where it failed); keys: every key it covers; materials: the distinct ones compiled. */
interface MaterialActivation { ok: boolean; look: string; stage?: "spec" | "assembly" | "compile"; error?: string; keys?: string[]; materials?: number }
/** A compile's outcome (EvoOceanMaterials.compiler): timeout, it did not finish in its budget (not a failed program). */
interface MaterialCompileResult { ok: boolean; error?: string; timeout?: boolean }
/** The scene's compile for activations and its prewarm (EvoOceanMaterials.compiler): three (Scene, Mesh), its renderer,
 * camera and scene, a kind's geometry, whether the context is lost, the context's generation (one more at each loss and
 * restore: a compile it moved under is refused); the budget (ms, 60 s) and the timers (tests). */
interface MaterialCompilerOptions {
  THREE: any; renderer: any; camera: any; scene: any;
  geometry: (item: MaterialCompileItem) => any;
  lost?: () => boolean;
  generation?: () => number;
  budgetMs?: number;
  timers?: { set: (f: () => void, ms: number) => any; clear: (t: any) => void };
}
/** The binder's needs: three (ShaderMaterial, DoubleSide, LessDepth), the activation's compile, the console. */
interface MaterialBinderDeps {
  THREE: any;
  compile?: (items: MaterialCompileItem[]) => Promise<{ ok: boolean; error?: string }> | { ok: boolean; error?: string };
  warn?: (m: string) => void;
}
interface MaterialBinderState {
  look: string; version: number; pending: boolean; kinds: string[]; covered: string[]; materials: number;
  entries: { key: string; state: string; error: string }[]; failed: string[];
}
/** The scene's material binder (EvoOceanMaterials.create): web/ocean_materials.js says what each does. */
interface MaterialBinder {
  define(kind: string, def: MaterialKindDef): void;
  prepare(kinds: string[]): void;
  material(kind: string, pass: string, variant: number): any;
  /** its own programs assemble (no fallback): the split asks before it skips the lit fish in the main draw */
  has(kind: string, pass: string, variant: number): boolean;
  bind(mesh: { material: any }, kind: string, pass: string, variant: number): number;
  bound(mesh: object): MaterialBound | null;
  variantOf(mesh: object): number;
  warm(kinds: string[]): any[];
  key(kind: string, pass: string, variant: number): string;
  programs(kind: string, pass: string, variant: number): { key: string; own: boolean; vs: string; fs: string; material: any };
  activate(spec: MaterialSetSpec | null): Promise<MaterialActivation>;
  state(): MaterialBinderState;
}
interface EvoOceanMaterialsApi {
  KINDS: { readonly [kind: string]: MaterialKindSpec };
  PASSES: readonly string[];
  VARIANTS: readonly number[];
  LAYOUTS: { readonly [kind: string]: AttributeLayout };
  LAYOUT_ABI: number;
  /** the lit fish's split, a feature (app.pose, order -1) */
  LIT_SKIP_FEATURE: string;
  layout(kind: string, claims?: { [component: string]: string }): AttributeLayout;
  create(deps: MaterialBinderDeps): MaterialBinder;
  compiler(o: MaterialCompilerOptions): (items: MaterialCompileItem[]) => Promise<MaterialCompileResult>;
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
  /** the render optimization's body buckets (1 coarse, 2 medium), their thresholds (CSS px of body radius: up to
   * medium from ENTER, back to coarse at EXIT or below) and the barbels' (gene above BARBEL_GENE_MIN, px) */
  LOD_COARSE: number;
  LOD_MEDIUM: number;
  LOD_MEDIUM_ENTER_CSS: number;
  LOD_MEDIUM_EXIT_CSS: number;
  BARBEL_GENE_MIN: number;
  BARBEL_ENTER_CSS: number;
  BARBEL_EXIT_CSS: number;
  /** a fish's body bucket from its projected radius, its last bucket (0 new), the detail and whether it is selected / hovered */
  bodyLod(px: number, previous: number, quality: number, pinned: boolean): number;
  /** whether a fish draws its barbels (gene bD, projected radius, drew them last frame, detail, its body bucket) */
  barbelVisible(bD: number, px: number, previous: boolean, quality: number, lod: number): boolean;
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
/** What the probes use of the scene's three.js renderer (its WebGL2 context untyped here, as the checks'
 * gl): their own render targets, three's state restored after, the shader-error hook. */
interface ParityRenderer {
  getContext(): any;
  resetState(): void;
  getRenderTarget(): unknown;
  setRenderTarget(rt: unknown): void;
  autoClear: boolean;
  debug: { onShaderError: ((gl: any, prog: any, vs: any, fs: any) => void) | null };
  state: { buffers: { color: { setMask(on: boolean): void } }; setScissorTest(on: boolean): void };
  render(scene: unknown, camera: unknown): void;
}
/** What the probes read of the appearance fish's kind (the scene's AppKind) as the frame drew it: its
 * draw's fish (n) and capacity (cap), the instance attributes' names (inst) and three attributes by name
 * (attrs; iGeneSlot each draw's gene slot), the live gene texture (tex: three's DataTexture), its slots
 * (capacity, stats), its programs (shaders: the probes' raw / chart stages), the fish material's uGenes
 * uniform (bound by the probes, so three's uploader is what they test) and whether its mesh is shown. */
interface ParityAppKind {
  n: number;
  cap: number;
  inst: string[];
  attrs: Record<string, any>;
  tex: any;
  slots: { capacity: number; stats(): unknown };
  shaders: AppearancePrograms;
  mat: { uniforms: { uGenes: unknown } };
  mesh: { visible: boolean };
}
/** The scene's port for the probes (attach, once a scene): fixed parts and live getters, read at each
 * probe, never copied (web/ocean_scene_parity.js attach says what each is). */
interface ParityProbePort {
  THREE: any;
  renderer: ParityRenderer;
  profiler: { suspend<T>(fn: () => T): T };
  geneIO: { uploads: number };
  bodyScale(size: number): number;
  ea(): EvoAppearanceApi | null;
  status(): string;
  appKind(): ParityAppKind | null;
  drawn(): boolean;
}
/** The probes on a live scene and their queue: runProbes(s) right after a production draw (s the snapshot
 * drawn), failProbes(why) when there is none; testFaults.holdGeneUploads leaves the scene's gene upload out
 * (a stale texture must then fail appearanceTextureParity). */
interface ParityProbes {
  testFaults: { holdGeneUploads: boolean };
  probes: unknown[];
  failProbes(why: string): void;
  runProbes(s: OceanSnapshot): void;
  appearanceParity(rows: ArrayLike<number>[], lams: number[], cellW?: number, cellH?: number): object;
  appearanceTextureParity(expected?: BenchSnapshotCopy | null, o?: { mutate?: string; pendingUpload?: boolean; charts?: number; rawWords?: boolean }): Promise<any>;
}
/** The appearance fish's GPU == CPU checks (web/ocean_scene_parity.js says what each checks): on any
 * WebGL2 context, a Promise of the report (.error: it did not run; .ok: it passed). EA: EvoAppearance;
 * rows / lams: fish added to the fixed fixture. And the probes on a live scene (attach). */
interface EvoOceanSceneParityApi {
  /** the scene's layout and water (once, as web/ocean_scene.js loads; before it a check throws) */
  bind(scene: ParityScene): void;
  appearancePathCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, rows?: ArrayLike<number>[] | null, lams?: number[] | null, opts?: ParityCheckOptions): Promise<any>;
  appearanceVertexCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, rows: ArrayLike<number>[], lams: number[], opts?: ParityCheckOptions): Promise<any>;
  appearanceFragmentCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, opts?: ParityCheckOptions): Promise<any>;
  /** the probes on a live scene (web/ocean_scene.js create(), once a scene) */
  attach(port: ParityProbePort): ParityProbes;
  /** the M2a body plan: the renderer's rest GLSL at the canonical samples against the C++ law's rest points */
  bodyPlanVertexCheck(gl: WebGL2RenderingContext, EA: EvoAppearanceApi, fixture: BodyPlanFixture, opts?: { slotMap?: "identity" | "permuted" | "sparse"; mutate?: string }): Promise<any>;
  /** its locked tolerance (body radii) and its planted faults' names */
  BODY_TOL: { geo: number };
  BODY_MUT: string[];
}
/** bodyPlanVertexCheck's input: the canonical samples ([a0, a1, a2, a3, part, side] each) and the bodies (63
 * genes, lambda, the C++ rest points: 3 floats a sample) */
interface BodyPlanFixture {
  samples: number[][];
  bodies: Array<{ name?: string; genes: ArrayLike<number>; lambda: number; rest?: ArrayLike<number> }>;
}

/* ---------------- web/ocean_bodyplan.js (window.EvoBodyPlanViewer) ---------------- */

/** The fixture viewer (web/ocean_bodyplan.html): start (once, as it loads), the GPU check (a Promise of
 * the report it also leaves in window.__bodyPlanCheck), the fixture driver's digest, a redraw. */
interface EvoBodyPlanViewerApi {
  start(): Promise<unknown>;
  gpuCheck(): Promise<any>;
  digest(f32: Float32Array): string;
  redraw(): void;
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
interface EvoAssets { ocean?: string; oceanWasm?: string; worker?: string; handoff?: string; mock?: string; three?: string; bodyplan?: string; fixture?: string; [name: string]: string | undefined }

declare var EvoOceanHandoff: EvoOceanHandoffApi;
declare var EvoAppearanceSlots: EvoAppearanceSlotsApi;
declare var EvoOceanPerf: EvoOceanPerfApi;
declare var EvoOceanConfig: EvoOceanConfigApi;
declare var EvoAppearance: EvoAppearanceApi;
/** the scripts web/ocean_scene.js needs: undefined when the file did not load, null when it threw as it
 * loaded (each sets its namespace null first and registers at the end) */
declare var EvoOceanShaders: EvoOceanShadersApi | null | undefined;
declare var EvoOceanPose: EvoOceanPoseApi | null | undefined;
declare var EvoOceanMaterials: EvoOceanMaterialsApi | null | undefined;
declare var EvoOceanSceneParity: EvoOceanSceneParityApi | null | undefined;
declare var EvoBodyPlanViewer: EvoBodyPlanViewerApi | null | undefined;
/** the fixture viewer's last GPU check (web/ocean_bodyplan.js; the headless test reads it) */
declare var __bodyPlanCheck: any;
declare var EvoOceanScene: EvoOceanSceneApi;
/** set by web/ocean_scene.js when a script it needs did not load or failed to run, in words: "<files>
 * missing", "<files> failed to run" or both, "; " between ("ocean_shaders.js", "ocean_pose.js",
 * "ocean_materials.js", "ocean_scene_parity.js", " and " between): the page's "could not start" says it (else "ocean_scene.js
 * missing", the scene itself) */
declare var EvoOceanSceneMissing: string | undefined;
declare var EvoOcean: OceanPageApi;
declare var EVO_ASSETS: EvoAssets;
