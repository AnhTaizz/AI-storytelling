# M13 Visual Pipeline Plan V0

Status: **Draft plan — not started.** Initial plan agreed on 2026-11-16. Updated 2026-11-19 with the channel's editing workflow.

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

Build an editable first cut for a Vietnamese recap. The recorded or synthesized
narration sets the pace. The editor can listen to a line, preview a few images
in context, and replace one without rebuilding the episode.

For light novels, retrieve illustrations from the channel's image library. For
manga, illustrate selected moments with individual panels in story order.
Connecting narration can use an original background, a title card, or a hold
on the previous image. The number of panels follows the editorial choice.

## Decisions already made

| Topic | Decision |
|---|---|
| Picture timing | Start around 8–10 s per image. Cut earlier for a reveal or hold across several sentences when the scene stays quiet. |
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
| P4 Shot selection | Suggest up to three candidates for a visual change | text match (manga), tag match (LN) | 0 |
| P5 Colorization (optional) | Colorize only the images selected in P4 | ComfyUI, SD 1.5, ControlNet, IP-Adapter | 0 |
| P6 Shot list | Machine-readable handoff to video assembly (M14) | JSON | 0 |

### P0 — Policy

- Record the source and basis for using each image in a published episode.
  Show chapter, page and panel for manga and credit information where applicable.
  Mark assets with unknown rights as **reference only**. Offer an original or
  licensed alternative and flag any unresolved selection before publication.
  The timing target is an editing preference. Buying a copy, erasing dialogue,
  or displaying a panel briefly does not establish permission.

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

Start from the approved script, the recorded voice and its sentence or beat
timestamps. Link each proposed visual change to the existing `beat_id` and
event references. Snap suggested cuts to a spoken phrase or change of action.
For example, a reveal spoken at 0:11 should first appear at 0:11 even if the
default cut would have been at 0:09.

| Source | Retrieve and rank | Editor choice |
|---|---|---|
| Light novel | Match characters, setting, action and emotion. Prefer the correct costume or story period. Penalize recent repeats. | Preview up to three distinct options, such as a wide shot, reaction or object detail. Allow a hold or a manual import. |
| Manga | Search the reviewed chapter and page range. Follow panel reading order and the point reached in the narration. Use action and visual tags for silent panels, with OCR as an additional signal. | Offer up to three panels for the selected moment, labelled by page and panel. Let the editor inspect neighbours, choose one, or skip. Keep later reveals out of suggestions. |

When illustrating an LN with its manga adaptation, use a reviewed passage-to-page
mapping. If the mapping is uncertain, ask for a page range or use a library image.
A chapter number alone cannot establish the match.

Generate thumbnails, OCR and tags once per asset version. Start with local
metadata filters and text matching over the P3 index. Refresh candidates only
for the selected beat. Decide whether local embeddings are worthwhile from
measured misses. Choosing, replacing and retiming a shot uses no model calls.

### P5 — Colorization (optional, after selection)

Colorize selected assets on demand and cache their derivatives for reuse.

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

P6 exports a versioned shot list for M14. Bundle the voice and caption cues with
the draft, using a common timebase. Keep suggestions separate from the saved
selection so refreshing candidates preserves manual edits.

| Field | Purpose |
|---|---|
| `shot_id`, `beat_id` | Stable shot identity across edits and link back to the script. |
| `start_ms`, `end_ms` | Position against the actual voice recording. A held image can span multiple cues. |
| `asset_id`, `candidate_asset_ids` | Selected visual and alternatives. Resolve source, rights and thumbnails via the asset index. |
| `motion`, `transition`, `style` | Start with a cut, slow zoom or crossfade and the episode's chosen visual style. |
| `selection_state` | Distinguish a suggested placement from an editor-confirmed shot. |

### Editing the draft (M14 handoff)

Import the initial shot list once. The saved editor project owns subsequent
timeline changes. Apply later suggestions by shot ID to the requested scene
or track. Preserve confirmed choices and make each accepted change undoable.

- Start with three tracks: narration, visuals and captions. Preview edits with
  local thumbnails or proxies and render from the originals.
- Drop files into the media bin to import them into project-managed storage.
  Dropping an image on a shot replaces its picture and preserves its timing and
  motion. Dropping between shots shows an insertion marker. Moving a picture
  cut leaves voice and captions in place.
- Re-recording a line can change its duration. Update the affected caption cues
  and shift downstream material together. Let the editor loop the join before
  accepting it. Autosave the project and retain manual choices after reopening.
- First evaluate the stock open-source OpenChatCut editor. If entering shots by
  hand dominates editing time, test a small adapter against a pinned release.
  Consider a fork only after identifying a recurring limitation in the editor
  itself. These are integration experiments for the M14 phase.

## Open questions

1. Source language of manga pages: Japanese raw or translated? This decides the OCR
   engine.
2. Background behind the centered image: blurred copy of the image, solid color, or
   a themed backdrop?
3. Final emotion vocabulary.
4. Who builds and reviews the LN → manga chapter mapping for each series.
5. When to start: before the Script Quality Gate (owner override) or after it.

## First spikes when work starts

1. Once the script gate permits work, use 60–90 seconds of approved chapter 5
   narration from *The Angel Next Door* with a few cleared images. Time the first
   cut and corrections per finished minute. Record how often one of the first
   three suggestions is usable and why the others miss. Replace an image,
   retime a cut, change one voice line and reopen the saved project. Check sync,
   manual selections and the rendered result.
2. Repeat selection on a short reviewed manga passage with a silent reaction
   followed by a reveal. Verify reading order, reveal timing, source labels and
   the option to skip panels. Record any paid calls in both trials.
3. P1 on about 20 Roshidere pages; measure how many pages split correctly.
4. P5 on about 10 panels: plain automatic colorization versus the chosen SD 1.5 +
   ControlNet + IP-Adapter setup, compared side by side for character color
   consistency.
