// tools/ocean_render_perf/lean.mjs: the slice of scene.renderOptimization() a measurement record keeps (the review of PR #85, P3).
// renderOptimization() also hands out the live diagnostics: each draw's instance buffers and fish lists, the decoded cache's CPU
// array and its GPU texture. A record per observation kept them: 426 MB for one 2,000-fish cell, all of it serialized again after every
// block. A record keeps the policy (requested, in effect, failures), the counters (buckets, barbels, the decoded cache's counts and
// byte figures) and each draw's instance count and capacity; the live arrays and textures are for the targeted diagnostics.
// The function is serialized into the page (cycle.mjs: window.__leanOpt), so it stays self-contained.
export function leanOpt(st) {
  if (!st) return null;
  var batches = null, decoded = null, k;
  if (st.batches) {
    batches = {};
    var names = ["coarse", "medium", "barbels"];
    for (var i = 0; i < names.length; i++) if (st.batches[names[i]]) batches[names[i]] = { n: st.batches[names[i]].n, cap: st.batches[names[i]].cap };
  }
  if (st.decoded) {
    decoded = {};
    for (k in st.decoded) { var v = st.decoded[k]; if (v === null || typeof v !== "object") decoded[k] = v; }   /* (the counters; not the texture or its array) */
  }
  return { enabled: st.enabled, requested: st.requested, effective: st.effective, failures: st.failures, buckets: st.buckets, barbels: st.barbels,
           batches: batches, decoded: decoded, features: st.features };
}
