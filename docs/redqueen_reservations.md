# Reservation input grammar

The file is UTF-8, read once in full. It is either nonblank ASCII decimal integer lines,
one complete JSON value, or JSONL (one complete JSON value per nonblank line). Blank
lines are separators. Duplicate JSON keys, invalid JSON, empty files, and any refused
record refuse the whole file, with file and document/line/record context. Sets deduplicate
only after each record independently succeeds; every record must yield at least one seed.

The following contexts are distinct: documents and explicit inventory records allow
flat maps; metadata traversal never infers them; historical seed containers and
archive provenance follow their own rules below. A document/record is one of:

* A nonnegative JSON integer (not a bool), reserved directly. Structural integers have
  no uint32 limit; negative values are refused.
* A nonempty array of records, recursively parsed with the same grammar. An array
  containing a recognized seed argv flag is explicitly an engine argument vector
  and follows the argv rule below; it is not also a scalar-record array.
* A nonempty flat label-to-nonnegative-JSON-integer object. Arbitrary inventory labels,
  including `w01_seed`, `reseed`, `sample`, `ages`, and `transplant`, do not change the
  meaning of siblings. Reserved record fields (`seed`, `seeds`, `founder_seed`, `seed_rederived`,
  `transplant_seed`, `reseed_after_load`, case insensitive) identify structural records
  instead. The case-insensitive names `steps`, `attempt`, `replicate`, `frame`,
  `index`, `worlds`, `reserved`, `reservations`, `records`, and `inventory` cannot
  be flat inventory labels. An integer-only map containing any of these names
  must satisfy the structural rules or is refused; neither `{"worlds":102}` nor
  `{"w01":101,"worlds":102}` is a flat inventory, at any record depth.
  The exact key `schema` is also a discriminator, never a flat label; in a
  document/record it must hold a string, otherwise the record is refused.
  After the complete flat-map shape has been excluded, a scalar-only structural
  object without a schema that mixes seed-bearing fields with unknown non-seed
  fields is ambiguous and refused; recognized scalar record metadata
  is `steps`, `attempt`, `replicate`, `frame`, and `index`. This avoids guessing that an
  unknown sibling is metadata or a seed. Scalar-only noninteger flat maps are refused.
* A structural object or wrapper. Seed-bearing fields are keys containing `seed`, case
  insensitive. Their nonnegative integer leaves are reserved recursively, including
  integer metadata under these containers, preserving the old conservative policy.
  Seed-value leaves must be JSON integers or null; strings/bools/floats are refused.
  Historical metadata names containing `scheme`, `namespace`, `sha256`, `hash`, `rule`,
  `note`, or `path`, and the `groups` / `seed_slot` label subtrees permit noninteger
  metadata leaves, unless an ancestor already requires seed-value leaves. The old
  integer-under-seed-container policy still applies.
  Outside seed containers, primitive metadata leaves/vectors do not reserve integers.
  Object/nested-array collections validate EVERY element independently, including
  those inside dictionary wrappers at any depth. Outside explicit inventory contexts
  their records must be structural objects/wrappers (not scalar seeds or inferred flat
  maps); ambiguous metadata collections are refused instead of promoting integers.
  Documents and their record arrays accept integer records and flat maps. The known
  inventory fields `worlds`, `reserved`, `reservations`, `records`, `inventory` also
  accept those records, and dictionary collections whose values are independent
  records (or a single structural/flat inventory object). Each named inventory field
  must hold an array or object: a bare scalar is ambiguous with metadata counts and
  is refused, before flat-map classification. Under an already established historical
  seed container, group-label subtree or archive provenance subtree, traversal instead
  retains that context; these subtrees are not independent flat-inventory records.
  In such a dictionary inventory,
  the exact key `schema` or a case-insensitive exact reserved record field identifies
  a structural object. Otherwise an all-integer dictionary is classified as a single
  record (with the exclusions above); a noninteger dictionary is a collection of
  independently validated values. A `seed`
  substring in an arbitrary collection label never disables sibling validation.
  Empty inventory arrays and unsupported siblings are refused. Metadata objects are
  traversed for seed fields and argv, without interpreting their ordinary integers as
  flat inventories. A structural document/wrapper with no extracted seeds is refused.
* An object with exact schema `finfolk.invasion.archived-seeds/1`: requires a nonempty
  `all` object whose keys are ASCII decimal seeds. These keys are reserved. `all` values
  are source provenance, not inventory records; they still receive the historical
  seed-key/argv traversal. Other seed-bearing fields are processed normally.

Every array is scanned for the exact separate-token flags `--seed`, `--transplant-seed`,
and `--reseed-after-load`. Values are nonnegative JSON integers or ASCII decimal strings
in 0..4294967295, including leading zeroes. Missing, signed, fractional, boolean, null,
nondecimal, equals-form, overflow, or truncating values are refused. This matches the
unsigned seed stored after `strtoul(...,10)` in src/app/main.cpp (lines 256, 283, 351),
refusing spellings/ranges the engine could interpret differently. Non-seed argv tokens
are metadata outside seed containers; unconsumed leaves within a seed container
still obey its rules. All unconsumed nested objects/arrays are traversed/validated.

JSONL uses exactly this record grammar, not a union-level validity check. No unsupported
record can be rescued by a valid sibling or an already-seen seed. Receipts hash the
complete input bytes and count the distinct validated seed set.

The public entry points `worlds.read_avoid`, `plan.avoid_seeds`, and
`noisebank.avoid_seeds` raise `WorldsError`, `DesignError`, and `NoiseBankError`,
respectively, for refused reservations. Each preserves the loader's message,
including the input file, document or JSONL line, nested record path, and reason.
`rqlib.load_reservations` itself raises `ReservationError`.
