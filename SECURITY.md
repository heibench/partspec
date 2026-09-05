# Security

## The trust boundary

`partspec` runs what it is pointed at. That is the design, not an oversight:
executing the contract is how the tool learns what you claimed, and executing the
model is how the part gets built. There is no sandbox and none is planned.

Two different mechanisms, worth separating because their consequences differ:

- **In this process, via `exec()`** — the contract module (`target.py`) and a
  build123d or CadQuery model (`engines/pycad.py`). This is ordinary Python with
  the privileges of whoever ran `partspec`. Import-scope statements run before
  any validation, so they run even on a contract the tool then rejects.
- **In the `openscad` binary, as a subprocess** — a `.scad` model, together with
  everything it `include`s or `use`s. partspec does not interpret that file; it
  hands it to a third-party binary that evaluates it, reads whatever
  `include`/`import()`/`surface()` reach on its own search path, and is outside
  partspec's control. Note that partspec's own README describes installing a
  development snapshot for headless rendering, so that binary may be one you
  downloaded rather than one your distribution signed.

`lint` is narrower than the other verbs but not outside this. Tier 1 parses only,
and on a Python source the whole of `lint` is `ast`-based and nothing runs — but
the three `csg-*` tier-2 rules export a `.scad` through the same binary, so
linting an untrusted `.scad` evaluates it and its include chain. `diff` and
`vdiff` execute nothing.

So a contract is code, and so is a `.scad`. Read what you were handed before you
run it, the same as any other source.

`requires` expressions are the one restricted surface, and only in a narrow
sense: they are evaluated against the declared params with no imports, attribute
access or calls (`SPEC-contract.md` §5.1; the implementation rejects indexing
too). That is a *legibility*
boundary, not a security one — it exists so the tool can print an expression's
operands. The contract around it is unrestricted Python.

Reports are data, not code. `report.json`, `render.json` and the lint payload are
consumed by parsing, never by evaluation.

## Reporting a vulnerability

Report privately through GitHub:
<https://github.com/heibench/partspec/security/advisories/new>

Please do not open a public issue for a security report.

Because partspec executes what it is pointed at by design, "a contract can run
arbitrary code" is documented behaviour rather than a vulnerability. What is in
scope is anything that runs code the user did **not** point the tool at, or that
misreports what was read. For example: a path in a report or lint payload that
gets evaluated rather than parsed; the MCP server acting on something the caller
never named; or a closure that does not flag external reads for a render that did
make them — an `include` partspec could not resolve on its own search path may
resolve on the engine's, and the file behind it may hold an `import()` partspec
never saw, so the absence of that flag is not a promise.
