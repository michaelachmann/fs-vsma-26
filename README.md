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
| [`01_transcribe`](notebooks/01_transcribe.ipynb) | Transcribes videos locally with Whisper on the GPU | `/corpus/raw` | `/corpus/derived/transcripts/`, `transcripts_errors.csv` |

| [`02_extract_frames`](notebooks/02_extract_frames.ipynb) | Samples frames with several strategies and compares them | `/corpus/raw` | `/corpus/derived/frames/<strategy>/`, `summary.csv` |
| [`03_ocr`](notebooks/03_ocr.ipynb) | Reads on-screen text in extracted frames with EasyOCR on the GPU, and merges repeated text across time | `/corpus/derived/frames/<strategy>/` | `/corpus/derived/ocr/<strategy>/`, `summary.csv` |
| [`04_build_tables`](notebooks/04_build_tables.ipynb) | Builds the tidy metadata, text and images tables | `/corpus/raw` and the results above | `/corpus/derived/tables/` |

`01_transcribe` is normally run once for the whole seminar, so check with your instructor before running it yourself. The same goes for the default strategies in `02_extract_frames` and `03_ocr`. Finished videos are skipped when a notebook runs again.

To try your own extraction strategy, add it to `CONFIGS` in `02_extract_frames` under a new name. Results for each strategy stay in their own folder, so strategies can be compared side by side.

## Tidy data

We organise the corpus following the [tidy data principles](https://social-media-lab.net/processing/): each variable is a column, each observation is a row, and each type of observational unit is its own table. `04_build_tables` writes three linked tables to `/corpus/derived/tables/`:

| Table | One row per | Key | Main columns |
|---|---|---|---|
| `posts.csv` (metadata) | TikTok post | `Post ID` | `Username`, `Created`, `Plays`, `Likes`, paths to the video, cover and metadata |
| `texts.csv` | Caption, transcription or OCR text of a post | `Text ID` | `Post ID`, `Text Type`, `Strategy`, `Language`, `Text` |
| `images.csv` | Cover or extracted frame | `Image ID` | `Post ID`, `Image Type`, `Strategy`, `Frame`, `Time`, `Path` |

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
| `/corpus/raw/<tiktok-account>/<post-id>` | Validated originals, copied automatically within a few minutes. Contains no student names | Read-only |
| `/corpus/derived` | Transcripts, features and other results | Everyone reads and writes |

Don't move files into `raw` by hand. Put your own results in a subfolder of `/corpus/derived`, and don't change other people's files.

## Contributing

**This repository must never contain corpus data.** Before committing a notebook, clear its outputs (*Edit → Clear Outputs of All Cells*), because they can contain account names and transcripts. Never commit videos, images, transcripts or passwords.

## Background

Adapted from the preprocessing notebooks in [social-media-lab](https://github.com/michaelachmann/social-media-lab).

## License

Licensed under the [GNU General Public License v3.0](LICENSE). The license covers the code and notebooks in this repository, not the corpus data.
