# Roadmap

Ordered by what to do next: dependency first, then risk, then effort.
Legend: ⬜ not started · ✅ done

1. ⬜ **[D] Labeled real-photo set** — 50–100 photos you take, varied lamp/glare/angle, each labeled with card and print in a CSV. Every tuning decision below is blocked on this.
2. ⬜ **[Dsn] Eval-driven decisions** — run `eval`, then choose ViT-S vs ViT-B, augmented references, patch verification, and the confidence threshold from the score distributions rather than intuition.
3. ⬜ **[I] Uncertainty policy in `identify`** — act on #2: explicit "uncertain" outcome, what confidence is too low to be a match, and whether it still records a pending match.
4. ✅ **[I] CI** — GitHub Actions running `uv sync`, ruff and pytest. Cheap, and the only thing protecting 50 tests from silent rot.
5. ✅ **[I] `matches list`** — list pending/accepted/rejected matches; right now the only way to accept is to remember the id printed by `identify`.
6. ✅ **[I] Batch input over `data/input/`** — run identification over a folder and write one result per photo. The original use case is a set of pictures, not one.
7. ✅ **[D/I] Full catalog coverage** — `catalog sync --all`, promos, Japanese; verify the parser on sets whose print layouts differ (ST, EB, PRB) instead of only OP08.
8. ✅ **[Dsn] Multi-photo grouping** — how several photos of the same card combine before matching: aggregate scores, use the best, front/back, discard blurry duplicates. Currently one photo equals one match.
9. ✅ **[I] Price refresh path** — re-syncing a set already appends prices, but there's no lightweight "refresh all prices" and no cadence.
10. ✅ **[I] Collection ergonomics** — merge quantity on repeat accept, edit/delete owned rows, condition/language defaults, total collection value.
11. ✅ **[I] `db check`** — report owned/matches whose snapshot no longer resolves after a re-sync, orphan images, index drift. Makes the snapshot guard visible instead of silent.
12. ✅ **[I] Schema versioning/migrations** — `PRAGMA user_version` plus real migrations. `CREATE IF NOT EXISTS` cannot evolve `library.db`, which now holds user data.
13. ⬜ **[I] Augmented reference vectors** — perspective/brightness variants per printing. Only if eval shows single references are fragile under angle/light.
14. ✅ **[I] Patch-token verification / ORB tie-break** — for prints that differ only by foil or border, which global DINOv2 conflates. Storage cost already measured (~1 MB/image as patch tokens).
15. ⬜ **[I] Detection robustness** — multiple cards in one photo, partial/occluded cards, and a sensible fallback when corner detection fails (currently the original image is kept).
16. ⬜ **[I] OCR improvements** — Japanese cards, rotation/flip, name-based fallback when the code is unreadable, confidence gating.
17. ⬜ **[I] Test coverage gaps** — real-photo fixture, parser fixtures for more set shapes, CLI end-to-end, an explicit renumbering regression.
18. ⬜ **[Dsn] Recognition interface** — API, folder watcher or UI. Explicitly deferred at the start; this is where "how recognitions are grouped and exposed" resumes.
19. ✅ **[I] Packaging/ops** — `uv tool install` workflow, quickstart, rate-limit/attribution notes for the image source.
20. ✅ **[I] Scale and performance** — index rebuild and `load_index` at full catalog size (~10k printings), DB growth, batching.

21. ✅ **[I] Confirmed-sample feedback loop** — `samples add/list/remove`, user photos stored under their own origin and excluded from matching/eval by default.

Tags: **[D]** data · **[Dsn]** design decision · **[I]** implementation.
