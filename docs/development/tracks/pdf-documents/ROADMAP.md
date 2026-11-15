# Track: PDF & documents — roadmap

**Scope:** PDF parsing, splitting/page selection, rotation, merging, PDF safety, DOCX/TXT conversions and format-specific validation/tests. Shared HTTP route contracts belong to API/security.

1. **Inventory** actual PDF/DOCX/TXT modules, current merged behavior, stacked PRs #96–#104 and HTTP PDF merge PR #108. Record missing functionality as Issues, not guessed completion.
2. **Contract parity:** coordinate PDF merge HTTP contract with API/security; test existing bot, Mini App and HTTP behavior, including output naming and cleanup.
3. **Robustness:** malformed/encrypted PDFs, page-count bounds, memory/time limits, document parsing edge cases and regression fixtures.
4. **Performance:** measured benchmarks with real files and bounded worker concurrency; optimize only where evidence shows a bottleneck.
5. **Platform readiness:** publish stable domain contracts, error taxonomy and safe operations to clients through reviewed capability metadata.

Each item requires an Issue, acceptance criteria, independent PR, exact-head tests and a STATUS update. Do not mark a milestone done before merging.
