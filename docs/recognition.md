# Recognition

How a user photo of a One Piece TCG card becomes an identified printing.

## The constraint that shapes everything

Alternate arts and alternate rarities often share a card code (`OP01-001`), while
their prices can differ by orders of magnitude. Matching a code is therefore not the
goal: recognition must return a **printing** (code + art variant + rarity), and a
variant that cannot be told apart must be reported as uncertain rather than guessed.

## Inputs

- **Reference images** — clean product images from
  <https://onepiece.limitlesstcg.com/cards>, possibly watermarked.
- **Query images** — photos taken by a user: arbitrary background, angle, perspective,
  a room lamp, glare and reflectance off the card or its sleeve.

The gap between those two is the whole problem. It is closed in preprocessing, not by
hoping the model is invariant.

## Pipeline

1. **Detect corners** — on a downscaled copy (full-resolution phone photos fragment
   the edges), find a quadrilateral with card-like aspect ratio.
2. **Rectify** — homography warp to a canonical portrait rectangle. A sideways card is
   turned upright by mapping its long edge to the height; if OCR then finds no code,
   the crop is tried upside down before embedding.
3. **Normalize** — exposure and white balance against the lamp, so two photos of the
   same card under different light produce comparable vectors.
4. **OCR (soft signal)** — read the code from the rectified card with EasyOCR
   (stylized small text is beyond stock Tesseract, and PaddleOCR has no Python 3.14
   wheel), then scan the detections for a code. A successful read narrows
   the candidate set to one `card`. An unreadable code must fall back to searching the
   whole catalog, never to a hard failure.
5. **Embed** — DINOv2 (`ViT-S/14`, 518 px to start) over the rectified card, global
   descriptor plus patch tokens.
6. **Rank** — cosine kNN over stored reference vectors; scores are aggregated per
   printing across its augmented references.
7. **Verify** — when candidates fall within a small score margin of the top-1,
   compare pooled patch tokens cell by cell and order that group by patch
   similarity. A group with a missing patch vector is left untouched. ORB +
   homography inliers remain an optional tie-breaker if evaluation shows it helps.
8. **Report** — the printing key `(card_code, print_index)`, confidence, and method.
   The match becomes `owned` only after the user confirms it.

## Reference data

Vectors belong to `card_images` rows, so one printing can hold several references:
the rectified product image, and later, if evaluation asks for them, augmented
variants (mild perspective, brightness shifts) for lighting conditions the product
image does not show. Every vector carries its model name and dimension, so changing
models is delete-and-recompute rather than a migration.

Patch tokens are average-pooled to an 8×8 grid, L2-normalized per cell and stored
alongside the global descriptor: about 49 KB per image as float16, roughly 500 MB
over a full catalog. They are only read for the top candidates.

## Why DINOv2

It is instance-oriented rather than purely semantic. CLIP-style models happily call two
different arts of the same character "the same card"; DINOv2 distinguishes printings,
is robust to partial occlusion, and its patch tokens give a local similarity check
without adding a second matching stack. CPU inference at this scale is fine, so no GPU
is required.

## Known limits

- **Foil/border-only variants** — same art, different treatment. Expect near-identical
  vectors even at patch level. Report low confidence and require confirmation.
- **Heavy glare or damage** covering a large part of the card.
- **Watermarks** on references can contribute spurious matching signal; mask them
  during preprocessing if evaluation shows an effect.
- **Foil/etched cards** change appearance drastically with viewing angle; a reference
  image is one sample of a surface that looks different from every direction.

## Evaluation

Before model or threshold choices are locked in, build a labeled set of real photos:
50–100 images, deliberately varied in lamp, glare and angle, each labeled with its
correct printing. Track:

- top-1 printing accuracy,
- top-5 recall,
- card-code OCR accuracy,
- how often an uncertain-but-correct answer was reported as uncertain.

`ViT-S` vs `ViT-B`, the augmentation count, and the patch-token threshold are all
decided by these numbers, not by intuition.

## Open decisions

- Model size and export path (PyTorch vs. ONNX Runtime).
- Patch margin (currently a hardcoded 0.05) and whether patch agreement should feed
  the reported confidence.
- OCR engine, and whether a failed OCR should ever block a match.
- Whether the augmented reference set is generated at import time or on demand.
