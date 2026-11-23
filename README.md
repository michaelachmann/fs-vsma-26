# fs-vsma-26

Notebooks for the 2026 research seminar on analysing TikTok data. Together we collect and preprocess a shared corpus, then each team works on its own project with it.

The notebooks are written for the seminar's JupyterHub server, which provides the GPU and the shared corpus. You receive your login from your instructor.

## Getting started

In your workspace, open a terminal (*File → New → Terminal*) and run:

```bash
git clone https://github.com/michaelachmann/fs-vsma-26.git
```

The repository then appears in your home folder. To get updates later:

```bash
cd ~/fs-vsma-26
git pull
```

If `git pull` complains about changes to a notebook, save your version under a new name first, or work on a copy from the start.

## Notebooks

| Notebook | Purpose | Reads | Writes |
|---|---|---|---|
| [`00_collect_apify`](notebooks/00_collect_apify.ipynb) | Manually collects with Apify, prepares metadata/media and stages an explicit corpus submission | Your query/hashtag/post URLs and privately entered token | Private `~/apify-collections/<collection-name>/` exports; optional prepared batch in your incoming folder |
| [`01_transcribe`](notebooks/01_transcribe.ipynb) | Transcribes videos locally with Whisper on the GPU | `/corpus/raw` | `/corpus/derived/transcripts/`, `transcripts_errors.csv` |
| [`02_extract_frames`](notebooks/02_extract_frames.ipynb) | Samples frames with several strategies and compares them | `/corpus/raw` | `/corpus/derived/frames/<strategy>/`, `summary.csv` |
| [`03_ocr`](notebooks/03_ocr.ipynb) | Reads on-screen text in extracted frames with EasyOCR on the GPU, and merges repeated text across time | `/corpus/derived/frames/<strategy>/` | `/corpus/derived/ocr/<strategy>/`, `summary.csv` |
| [`03b_clean_ocr`](notebooks/03b_clean_ocr.ipynb) | Repairs OCR errors with a Gemma 4 model in Ollama and flags results that contain text the OCR never saw | `/corpus/derived/ocr/<strategy>/` | `/corpus/derived/ocr_clean/<strategy>/`, `summary.csv`, `ocr_clean_errors.csv` |
| [`04_build_tables`](notebooks/04_build_tables.ipynb) | Builds the tidy post, text, image, collection and comment tables | `/corpus/raw` and the results above | `/corpus/derived/tables/` |
| [`05_explore_texts`](notebooks/05_explore_texts.ipynb) | Explores topics in post text with BERTopic | Shared corpus tables | `~/explorations/texts/` |
| [`06_explore_covers`](notebooks/06_explore_covers.ipynb) | Explores and clusters video covers using DINOv2 embeddings | Shared corpus tables and covers | `~/explorations/covers/` |
| [`07_select_annotation_items`](notebooks/07_select_annotation_items.ipynb) | Filters and samples text or comment rows for Annotation Studies | Shared corpus tables or bundled synthetic tables | Draft JSON in `~/annotation-drafts/` |
| [`07a_sample_images`](notebooks/07a_sample_images.ipynb) | Samples covers, gallery images or frames with a post limit, stratification and a thumbnail check | Shared corpus tables and image files | Draft JSON in `~/annotation-drafts/` |

`01_transcribe` is normally run once for the whole seminar, so check with your instructor before running it yourself. The same goes for the default strategies in `02_extract_frames`, `03_ocr` and `03b_clean_ocr`. Finished videos are skipped when a notebook runs again.

`00_collect_apify` runs in a CPU workspace. Follow the notebook for cost limits, private exports and staging. Both manual uploads and notebook batches go through the same corpus form. [Student Manual: Upload collected data](https://github.com/michaelachmann/jupyter-workstation/blob/main/student-manual.md#4-upload-collected-data)

To try your own extraction strategy, add it to `CONFIGS` in `02_extract_frames` under a new name. Results for each strategy stay in their own folder, so strategies can be compared side by side.

## Exploring the corpus

After preprocessing, run `04_build_tables` again, then open:

- [`05_explore_texts`](notebooks/05_explore_texts.ipynb): multilingual BERTopic on captions, transcripts, OCR, or one combined document per post. Choose one OCR strategy; cleaned OCR can fall back to raw OCR. Includes source coverage, topic inspection and an interactive text map.
- [`06_explore_covers`](notebooks/06_explore_covers.ipynb): DINOv2 embeddings of video covers, higher-dimensional UMAP (or PCA) plus HDBSCAN or k-means, and a separate 2D UMAP image canvas. Zoom through on-canvas thumbnails, adjust image size, switch between images and points, select image centres for a gallery, browse all images of a chosen cluster, and compare neighbours in the original embedding space. Also exports `cluster-overview.html`, a simple dropdown-filtered overview grouped by cluster with captions and post links.

Both notebooks default to **CPU** and work without PixPlot. Their first cell installs the exploration packages in your workspace; on the seminar server, both notebooks load administrator-prepared weights directly from the shared read-only `/models/exploration` mount. Each model is stored once for all users, with an exact revision in `seminar-model.json`. No home-folder symlink is needed. Outside the seminar server, models fall back to a private Hugging Face cache. Use a GPU workspace only when preprocessing has released the shared GPU. The visual map is self-contained HTML and needs no additional server or port.

By default results are private to your workspace, under `~/explorations/texts/` and `~/explorations/covers/`. Each notebook caches embeddings with the exact model revision and input selection. Changing clustering parameters reuses those vectors. Keep the shared tables unchanged while a notebook runs, and restart from the import cell after rebuilding them. Result tables retain `Post ID` or `Image ID` so you can link them back to the corpus.

Covers exclude photo posts without a cover. The coverage tables show this selection and the availability of each text source. Clusters are exploratory groupings, not validated frames. Before committing notebooks, clear every output; exported HTML includes corpus text and/or thumbnails and must stay outside this public repository.

## Annotation Studies

Use `07_select_annotation_items` to review and export a sample, then open **Services → Annotation Studies → Create study** in the Hub. The classroom pilot and test rounds use one TikTok caption per item. [Student Manual: Annotation Studies](https://github.com/michaelachmann/jupyter-workstation/blob/main/student-manual.md#10-annotation-studies)

## Tidy data

Each variable is a column, each observation is a row, and each type of observational unit is its own table. `04_build_tables` writes five linked tables to `/corpus/derived/tables/`. [Data preprocessing](https://social-media-lab.net/processing/preprocessing.html) · [Image and frame sampling](https://github.com/michaelachmann/social-media-lab-quarto/blob/main/processing/frame-sampling.qmd)

| Table | One row per | Key | Main columns |
|---|---|---|---|
| `posts.csv` (metadata) | TikTok post | `Post ID` | `Username`, `Created`, `Plays`, `Likes`, paths to the video, cover and metadata |
| `texts.csv` | Caption, transcription or OCR text of a post | `Text ID` | `Post ID`, `Text Type`, `Strategy`, `Language`, `Text` |
| `images.csv` | Cover or extracted frame | `Image ID` | `Post ID`, `Image Type`, `Strategy`, `Frame`, `Time`, `Path` |
| `collections.csv` | Post in one collection submission | `Post ID` + `Batch ID` | `label`, `strategy` (`FYP`, `search`, `hashtag`, `profile`) |
| `comments.csv` | Latest retrieved observation of a TikTok comment | `Comment ID` | `Post ID`, `Parent Comment ID`, `Username`, `Text`, `Likes`, `Run ID`, `Retrieved` |

Comment snapshots remain in raw attachments. The comments table selects the latest retrieval per comment and reports observations excluded because the parent post is not yet imported. Parent comments may be missing because a sample can include replies without their parents. Comments remain separate from captions/transcripts/OCR. Read `Comment ID` and `Parent Comment ID` as strings as well.

`posts.csv` also includes `label` and `strategy` as JSON arrays of distinct values. Use `collections.csv` for filtering by a particular label/strategy pair: a post can occur in several collections while its media is stored once. Collection `strategy` is separate from the OCR/frame extraction `Strategy` column. Uploader IDs remain private and are not included in these tables. Existing posts without a collection submission have empty arrays.

Run it again after each preprocessing step. Merge tables on `Post ID`, and always read IDs as text, because TikTok IDs are too long for number formats:

```python
import pandas as pd

ids = {"Post ID": str, "Text ID": str, "Image ID": str}
posts = pd.read_csv("/corpus/derived/tables/posts.csv", dtype=ids)
texts = pd.read_csv("/corpus/derived/tables/texts.csv", dtype=ids)

transcripts = texts[texts["Text Type"] == "Transcription"].merge(posts, on="Post ID")
```

Don't edit these tables, as they're rebuilt each time. Save your own variables, such as codings or model output, in a separate table in your subfolder of `/corpus/derived`, with the matching `Text ID`, `Image ID` or `Post ID`.

## How data moves

| Folder | Contents | Access |
|---|---|---|
| `/corpus/incoming/<user>` | Your uploads | You write, everyone reads |
| `/corpus/raw/<tiktok-account>/<post-id>` | Validated originals, imported after an explicit form submission. Contains no student names | Read-only |
| `/corpus/derived` | Transcripts, features and other results | Everyone reads and writes |

Don't move files into `raw` by hand. Put your own results in a subfolder of `/corpus/derived`, and don't change other people's files.

Submit uploaded or staged batches through the seminar server's corpus form. [Student Manual: Check and import your folders](https://github.com/michaelachmann/jupyter-workstation/blob/main/student-manual.md#b-check-and-import-your-folders)

## Contributing

**This repository must never contain corpus data.** Before committing a notebook, clear its outputs (*Edit → Clear Outputs of All Cells*), because they can contain account names and transcripts. Never commit videos, images, transcripts or passwords.

## Background

Adapted from the preprocessing notebooks in [social-media-lab](https://github.com/michaelachmann/social-media-lab).

## License

Licensed under the [GNU General Public License v3.0](LICENSE). The license covers the code and notebooks in this repository, not the corpus data.
