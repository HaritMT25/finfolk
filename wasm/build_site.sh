#!/bin/bash
# build_site.sh — assemble the static demo site in dist/ for Vercel.
#
#   dist/index.html            the landing page: the 3-D Ocean (web/ocean.html:
#                              its own engine web/evo_ocean.{js,wasm},
#                              single-threaded, and Turbo worker; it shares
#                              charts.js, guide.js and the three.js bundle with
#                              Classic). no-cache; references everything below
#                              by hash
#   dist/ocean.html            the same page, for the links from before it
#                              moved to the root
#   dist/classic.html          2-D Classic (web/index.html: the threaded and
#                              single-threaded modules), no-cache, hashed
#                              references. An old Classic link to the root
#                              (/?view=flat, /?threads=0, ...) is sent here by
#                              the Ocean page's head (web/ocean.html says which)
#   dist/assets/NAME.HASH.EXT  every script, wasm and image, content-hashed,
#                              served with a one-year immutable cache
#   dist/vercel.json           headers: COOP/COEP (cross-origin isolation for
#                              Classic's threaded module), wasm MIME, caching
#
# web/ keeps its own names (index.html is Classic, ocean.html the Ocean), so
# wasm/serve.py serves it as before; the 3-D | 2-D switch's links and the
# Ocean's redirect are rewritten here for the site's names.
#
# Static output only: no build step on Vercel, no serverless functions.
# Does NOT compile anything — build the modules first:
#   source ~/emsdk/emsdk_env.sh
#   bash wasm/build_wasm.sh      # Classic: the wasm-st and wasm-mt presets
#   bash wasm/build_ocean.sh     # the Ocean: web/evo_ocean.{js,wasm}
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=${SITE_DIR:-dist}   # SITE_DIR=/tmp/x: build elsewhere (a check), not into dist/
SRC=(web/evo_boids.js web/evo_boids.wasm web/evo_boids_mt.js web/evo_boids_mt.wasm
     web/loader.js web/gl_renderer.js web/randomizer.js web/renderer.js web/guide.js
     web/dash_data.js web/charts.js web/dashboard.js web/scene3d.js web/vendor/three.bundle.min.js
     web/worker.js img/rocks.jpg web/index.html web/vercel.json
     web/evo_ocean.js web/evo_ocean.wasm web/ocean.js web/ocean_scene.js web/ocean.html
     web/ocean_config.js web/ocean_dash.js web/ocean_worker.js web/ocean_appearance.js
     web/ocean_appearance_slots.js web/ocean_handoff.js web/ocean_perf.js web/ocean_shaders.js)
for f in "${SRC[@]}"; do
    [ -f "$f" ] || { echo "missing $f — build the modules first (wasm/build_wasm.sh, wasm/build_ocean.sh)" >&2; exit 1; }
done

# Clear the previous build but keep dist/.vercel: that is the Vercel project
# link (`vercel link --cwd dist`), and losing it would make the next deploy
# set up a new project.
mkdir -p "$OUT"
find "$OUT" -mindepth 1 -maxdepth 1 ! -name .vercel -exec rm -rf {} +
mkdir -p "$OUT/assets"

# hashed copy: prints the published path, relative to dist/
publish() {
    local src=$1 base ext h
    base=$(basename "$src"); ext=${base##*.}; base=${base%.*}
    h=$(sha256sum "$src" | cut -c1-12)
    cp "$src" "$OUT/assets/$base.$h.$ext"
    echo "assets/$base.$h.$ext"
}

ST=$(publish web/evo_boids.js);       ST_WASM=$(publish web/evo_boids.wasm)
MT=$(publish web/evo_boids_mt.js);    MT_WASM=$(publish web/evo_boids_mt.wasm)
LOADER=$(publish web/loader.js);      RENDERER=$(publish web/renderer.js)
GLR=$(publish web/gl_renderer.js);    RAND=$(publish web/randomizer.js)
GUIDE=$(publish web/guide.js);        DDATA=$(publish web/dash_data.js)
CHARTS=$(publish web/charts.js);      DASH=$(publish web/dashboard.js)
WORKER=$(publish web/worker.js);      BG=$(publish img/rocks.jpg)
SCENE=$(publish web/scene3d.js);      THREE=$(publish web/vendor/three.bundle.min.js)
# the Ocean page (it shares the three.js bundle, charts.js and guide.js)
OC=$(publish web/evo_ocean.js);       OC_WASM=$(publish web/evo_ocean.wasm)
OCJS=$(publish web/ocean.js);         OCSCENE=$(publish web/ocean_scene.js)
OCCFG=$(publish web/ocean_config.js); OCDASH=$(publish web/ocean_dash.js)
OCWORKER=$(publish web/ocean_worker.js); OCAPP=$(publish web/ocean_appearance.js)
OCHANDOFF=$(publish web/ocean_handoff.js)
OCPERF=$(publish web/ocean_perf.js);  OCSLOTS=$(publish web/ocean_appearance_slots.js)
OCSHADERS=$(publish web/ocean_shaders.js)

# Classic: rewrite the EVO_ASSETS block, the <script src> tags and the
# switch's link to the Ocean (now the root). Fails loudly if web/index.html no
# longer has the shape this expects.
python3 - "$OUT/classic.html" <<PY
import re, sys
src = open("web/index.html").read()
assets = '''window.EVO_ASSETS = {
      st: "$ST", stWasm: "$ST_WASM",
      mt: "$MT", mtWasm: "$MT_WASM",
      worker: "$WORKER",
      background: "$BG",
      three: "$THREE"
    };'''
out, n1 = re.subn(r'window\.EVO_ASSETS = \{.*?\};', lambda m: assets, src, count=1, flags=re.S)
out, n2 = re.subn(r'<script src="loader\.js"></script>', '<script src="$LOADER"></script>', out, count=1)
out, n3 = re.subn(r'<script src="renderer\.js"></script>', '<script src="$RENDERER"></script>', out, count=1)
out, n4 = re.subn(r'<script src="gl_renderer\.js"></script>', '<script src="$GLR"></script>', out, count=1)
out, n5 = re.subn(r'<script src="randomizer\.js"></script>', '<script src="$RAND"></script>', out, count=1)
out, n6 = re.subn(r'<script src="guide\.js"></script>', '<script src="$GUIDE"></script>', out, count=1)
out, n7 = re.subn(r'<script src="dash_data\.js"></script>', '<script src="$DDATA"></script>', out, count=1)
out, n8 = re.subn(r'<script src="charts\.js"></script>', '<script src="$CHARTS"></script>', out, count=1)
out, n9 = re.subn(r'<script src="dashboard\.js"></script>', '<script src="$DASH"></script>', out, count=1)
out, n10 = re.subn(r'<script src="scene3d\.js"></script>', '<script src="$SCENE"></script>', out, count=1)
out, n11 = re.subn(r'id="to3d" href="ocean\.html"', 'id="to3d" href="./"', out, count=1)
counts = (n1, n2, n3, n4, n5, n6, n7, n8, n9, n10, n11)
assert counts == (1,) * 11, ("index.html changed shape", counts)
open(sys.argv[1], "w").write(out)
PY

# The Ocean page: its EVO_ASSETS block, its eleven <script src> tags, and
# Classic's name in the switch and in the old-link redirect. ocean.js loads the
# engine (ocean / oceanWasm) and starts the Turbo worker (worker) from these,
# handing the worker the hand-off helper's name (handoff: it loads it as the
# page does), ocean_scene.js the three bundle. (mock: ?mock=1's stand-in,
# never published.)
python3 - "$OUT/index.html" <<PY
import re, sys
src = open("web/ocean.html").read()
assets = '''window.EVO_ASSETS = {
      ocean: "$OC", oceanWasm: "$OC_WASM",
      worker: "$OCWORKER", handoff: "$OCHANDOFF",
      mock: "ocean_mock.js",
      three: "$THREE"
    };'''
out, n1 = re.subn(r'window\.EVO_ASSETS = \{.*?\};', lambda m: assets, src, count=1, flags=re.S)
out, n2 = re.subn(r'<script src="ocean_scene\.js"></script>', '<script src="$OCSCENE"></script>', out, count=1)
out, n3 = re.subn(r'<script src="ocean\.js"></script>', '<script src="$OCJS"></script>', out, count=1)
out, n4 = re.subn(r'<script src="ocean_config\.js"></script>', '<script src="$OCCFG"></script>', out, count=1)
out, n5 = re.subn(r'<script src="ocean_dash\.js"></script>', '<script src="$OCDASH"></script>', out, count=1)
out, n6 = re.subn(r'<script src="charts\.js"></script>', '<script src="$CHARTS"></script>', out, count=1)
out, n7 = re.subn(r'<script src="guide\.js"></script>', '<script src="$GUIDE"></script>', out, count=1)
out, n8 = re.subn(r'<script src="ocean_appearance\.js"></script>', '<script src="$OCAPP"></script>', out, count=1)
out, n9 = re.subn(r'id="to2d" href="index\.html"', 'id="to2d" href="classic.html"', out, count=1)
out, n10 = re.subn(r'var CLASSIC_PAGE = "index\.html";', 'var CLASSIC_PAGE = "classic.html";', out, count=1)
out, n11 = re.subn(r'<script src="ocean_handoff\.js"></script>', '<script src="$OCHANDOFF"></script>', out, count=1)
out, n12 = re.subn(r'<script src="ocean_perf\.js"></script>', '<script src="$OCPERF"></script>', out, count=1)
out, n13 = re.subn(r'<script src="ocean_appearance_slots\.js"></script>', '<script src="$OCSLOTS"></script>', out, count=1)
out, n14 = re.subn(r'<script src="ocean_shaders\.js"></script>', '<script src="$OCSHADERS"></script>', out, count=1)
counts = (n1, n2, n3, n4, n5, n6, n7, n8, n9, n10, n11, n12, n13, n14)
assert counts == (1,) * 14, ("ocean.html changed shape", counts)
open(sys.argv[1], "w").write(out)
PY
cp "$OUT/index.html" "$OUT/ocean.html"

cp web/vercel.json "$OUT/vercel.json"

echo "built $OUT/:"
(cd "$OUT" && find . -type f | sort | xargs ls -la | awk '{printf "  %9d  %s\n", $5, $9}')
