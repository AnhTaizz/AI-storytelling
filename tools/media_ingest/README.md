# Local image collection

Tools that build a private, local image collection for the visual pipeline. Every
image, manifest and index they write lives under `data/sample/<series>/images/` or
`.local/media_ingest/`, and both locations are ignored by Git. Nothing in the
collection is redistributed, and permission to reuse an image in a published video is
not established by collecting it.

Install the dependencies with `pip install -r requirements-media-ingest.txt`
(Pillow, PyYAML). Network access is needed only by the crawlers.

## Your own images

```powershell
.local/m6_venv/Scripts/python.exe tools/media_ingest/ingest_local_images.py --series <series> --incoming <folder> --labels <csv> --apply
```

Omit `--apply` for a dry run. Only file headers are read; files are copied, not
re-encoded, and deduplicated by SHA-256. Labels come from an optional CSV
(`filename,category,characters,emotion,volume,chapter,source,rights_basis,notes`).
The private Roshidere corpus folder is protected: only its `images/` output folder
can be written, so stage incoming files elsewhere.

## Public publisher images

```powershell
.local/m6_venv/Scripts/python.exe tools/media_ingest/crawl_official_images.py --series all          # discover only
.local/m6_venv/Scripts/python.exe tools/media_ingest/crawl_official_images.py --series all --apply  # download and ingest
```

Use `--series roshidere` or `--series otonari_no_tenshi` for one collection. The
crawler fetches only image URLs that the publishers' own public pages supply: the
Roshidere articles listed in the source code and the anime key visuals, and, for Angel
Next Door, cover art and the manga chapters currently readable on Gangan ONLINE title
1480. It uses no login, guessed page numbers or access-control workarounds. It skips
sidebar assets, chapter adverts, expired and app-only chapters, and links to other
series. Original bytes are kept, pixels are decoded to check each image, and HTTP
failures or small images are recorded and skipped. Rerunning deduplicates by SHA-256.

`IMAGES_MANIFEST.yaml` and `IMAGES_INDEX.csv` are written next to the images; the
index is sorted by manga chapter and source page. Downloads, `labels.csv` and
`crawl_report.json` stay under `.local/media_ingest/official/<series>/`.

`official_promo` describes provenance, not a reuse licence. `manga_panel` holds whole
source pages, not cropped panels. Manga chapter numbers are not light novel chapter
numbers; character, emotion and scene labels stay empty until an editor reviews them.

## Publisher light novel artwork

```powershell
.local/m6_venv/Scripts/python.exe tools/media_ingest/crawl_light_novel_art.py --apply
```

Stores public Angel Next Door light novel covers from Yen Press and product-gallery
artwork from Kim Dong as reference assets under
`reference_assets/light_novel_publishers/`, with `category: other` and
`usage_status: reference_only`. Book identity is checked on each page, and volumes come
from the product title or variant label, never from image filenames. These are covers
and product photos, not interior scene illustrations. `LN_REFERENCE_ASSETS_INDEX.csv`
and `LN_REFERENCE_ASSETS_INGEST_REPORT.json` describe the result; existing image
records are preserved.

## Validation

```powershell
.local/m6_venv/Scripts/python.exe -m unittest discover -s tests/media_ingest -t . -p 'test_*.py'
```

Do not run two writers against the same series manifest at the same time.
