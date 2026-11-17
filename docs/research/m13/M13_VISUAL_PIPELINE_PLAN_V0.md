# M13 Visual Pipeline Plan V0

Status: **Draft plan — not started.** Agreed with the project owner on 2026-11-16.

## Roadmap position

This plan belongs to M13 (Visual Production) and touches M12 (Manga Ingestion).
`docs/DECISIONS.md` gates M10–M14 behind the Script Quality Gate after M9. This
document records the design so it is not lost; building any stage before the gate
is an explicit owner decision, not a default.

Upstream state when this was written: M6 retrieval (DEC-021), M7 Story Brief
(DEC-022) and M8 Narrative Planning (DEC-023) are accepted as baselines; M4 is in
progress; the M9 Script Quality Gate is not evaluated. The script is written one
section per Narrative Plan beat, and each beat cites brief events by chapter
(`c<N>.E<k>`). Shot selection (P4) builds on that link.

## Goal

For every narration segment of a video script, show 1–2 still images on screen,
each for about 10 seconds, at near-zero running cost.

- **Manga-backed stories:** use the manga's own panels for the matching scene,
  with dialogue erased.
- **Light-novel-backed stories:** the LN has too few illustrations, so build a
  character/emotion image library from manga panels and curated outside images
  (e.g. Pinterest), and pick images that match the characters and emotion of the
  scene the script describes.

## Decisions already made

| Topic | Decision |
|---|---|
| Images per segment | 1–2, about 10 s each |
| Dialogue | Erased from panels before use; the original text is read (OCR) first and kept as metadata |
| Video framing | 16:9 canvas, image centered, animated with motion presets (zoom in, zoom out, fly-in, …) |
| Style per video | One style per video: all colorized or all black-and-white, never mixed |
| Colorization method | Local Stable Diffusion 1.5 anime checkpoint + ControlNet lineart + IP-Adapter, run through ComfyUI on a local 4 GB GPU |
| Cost target | No paid APIs in the default path; one-time install of ~6–10 GB of tools and models |

## Pipeline

| Stage | Purpose | Main tools | Cost |
|---|---|---|---|
| P0 Policy | Fix sources, rights rules, emotion list, character color sheets | — | 0 |
| P1 Panel crop + bubble whitening | Split pages into panels; blank out text in white bubbles | Pillow, numpy | 0 |
| P2 Full dialogue removal | Detect text, OCR it, erase it (fill or inpaint) | comic-text-detector, manga-ocr / PaddleOCR, LaMa | torch install |
| P3 Asset library + tagging | Store panels, face crops and outside images with labels | existing `tools/media_ingest`, human review | 0 |
| P4 Shot selection | Pick 1–2 images per script segment | text match (manga), tag match (LN) | 0 |
| P5 Colorization (optional) | Colorize only the images selected in P4 | ComfyUI, SD 1.5, ControlNet, IP-Adapter | 0 |
| P6 Shot list | Machine-readable handoff to video assembly (M14) | JSON | 0 |

### P0 — Policy

- **Sources and rights.** Every asset records its source URL, artist (for outside
  images) and `rights_basis`. The current Roshidere manga pages come from a
  third-party scan site and are `rights_basis=unknown`. Images that will appear in a
  published video should come from purchased copies or official promotion.
  Pinterest is not a rights holder; many images there are reposted fan art.
- **Fair use is not a numeric rule.** Showing few images briefly helps, but it is
  no safe harbor. The video's own commentary and analysis — not the image count —
  carries most of the transformative weight. Colorizing a panel creates a derivative
  work and does not add fair-use weight.
- **Emotion vocabulary.** A fixed list of about 10 labels (proposal: neutral, happy,
  embarrassed, teasing, angry, sad, surprised, worried, determined, tender).
- **Character color sheets.** For each character: hair, eye and outfit colors plus
  1–2 official color reference images (color pages or anime). Used by P3 tagging and
  P5 colorization.

### P1 — Panel crop and bubble whitening (no ML)

- Recursive XY-cut on white gutters, numbered in Japanese reading order (top to
  bottom, right to left).
- Fallback: accept a near-blank gutter (≤ 8 % ink) when it touches a frame line,
  for art that bleeds across the gutter. A prototype handled this case on a
  Roshidere test page.
- Known limits of the heuristic: borderless panels, captions that cross frame
  edges, and inset panels. Replace with a learned detector (Magi) if these
  dominate.
- Bubble whitening: find closed white regions containing small dark components and
  fill the text pixels white.
- Always emit a debug overlay (boxes and order numbers) for quick review.

### P2 — Full dialogue removal

1. Detect text on the **whole page**, before cropping, because bubbles often cross
   panel frames.
2. OCR the text and keep it with the panel. Manga mode uses it for matching.
3. Erase: white fill for text inside white bubbles; LaMa inpainting for text over
   artwork (SFX, captions on art).
4. Crop panels from the cleaned page.

### P3 — Asset library and tagging

Extend the existing image index (`data/sample/<series>/images/IMAGES_INDEX.csv`)
rather than creating a parallel store. Proposed additional fields:

| Field | Meaning |
|---|---|
| `parent_id` | Source page or image this asset was derived from |
| `derived_kind` | `page`, `cleaned_page`, `panel`, `face_crop`, `colorized` |
| `bbox` | Position inside the parent |
| `reading_order` | Panel order within the page |
| `characters`, `emotion` | Already in the ingest schema; machine-suggested, human-confirmed |
| `shot_size` | `close_up`, `medium`, `wide` |
| `original_dialogue` | OCR text (local-only; never committed or quoted) |
| `artist`, `source_url` | Required for outside images |
| `review_status` | `suggested`, `approved`, `rejected` |

All derived images and OCR text stay in Git-ignored local paths, like the
existing corpus.

### P4 — Shot selection

The unit is the **Narrative Plan beat**: the script has one section per beat, and
each beat cites the brief events it tells (`c<N>.E<k>`), with their characters and
verbatim evidence.

- **Manga mode:** beat → cited events → their chapter → the manga pages for that
  chapter → panels whose original dialogue best matches the events' evidence →
  choose 1–2.
- **LN mode:** beat → cited events → characters present, emotion, setting → query
  the library by character + emotion. Prefer assets from the nearest story point
  (appearance and outfits change over the story) and avoid recent repeats.
- **Chapter mapping.** LN chapters and manga chapters are numbered differently, and
  the current image index states that the correspondence is unverified. P4 needs a
  reviewed LN-chapter → manga-chapter/page mapping per series; without it, manga
  mode can only search by dialogue text.

### P5 — Colorization (optional, after selection)

Only the 1–2 images chosen per segment are colorized, so the cost scales with the
video, not with the library.

1. Soften the screentone (descreen) on the cleaned panel.
2. Generate with ControlNet lineart (high strength), a fixed per-character prompt
   (e.g. "silver hair, blue eyes"), the character's color reference through
   IP-Adapter, and a fixed seed and sampler settings.
3. Multiply the original line art over the result, so the model contributes color
   only and the lines and composition stay identical to the source.
4. Save as a new `colorized` asset that points to its parent; human review before
   use.

Fallback for key shots that need higher quality: a reference-based manga
colorization model on rented GPU time.

### P6 — Shot list (handoff to M14)

One JSON entry per shot:

| Field | Example |
|---|---|
| `beat_id` | Narrative Plan beat (script section) the shot illustrates |
| `asset_id` | Image to show |
| `duration_s` | ~10 |
| `motion` | `zoom_in`, `zoom_out`, `fly_in_left`, `fly_in_right`, … |
| `transition` | e.g. `crossfade` |
| `style` | `color` or `bw` (must be the same across the whole video) |

The image is centered on a 16:9 canvas. A contact sheet of all selected shots is
generated for review before assembly.

## Open questions

1. Source language of manga pages: Japanese raw or translated? This decides the OCR
   engine.
2. Background behind the centered image: blurred copy of the image, solid color, or
   a themed backdrop?
3. Final emotion vocabulary.
4. Who builds and reviews the LN → manga chapter mapping for each series.
5. When to start: before the Script Quality Gate (owner override) or after it.

## First spikes when work starts

1. P1 on about 20 Roshidere pages; measure how many pages split correctly.
2. P5 on about 10 panels: plain automatic colorization versus the chosen SD 1.5 +
   ControlNet + IP-Adapter setup, compared side by side for character color
   consistency.
