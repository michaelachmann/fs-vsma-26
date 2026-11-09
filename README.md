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
| [`01_transcribe`](notebooks/01_transcribe.ipynb) | Transcribes videos locally with Whisper on the GPU | `/corpus/raw` | `/corpus/derived/transcripts/`, `transcripts.csv`, `transcripts_errors.csv` |

`01_transcribe` is normally run once for the whole seminar, so check with your instructor before running it yourself. Finished videos are skipped when it runs again.

## How data moves

| Folder | Contents | Access |
|---|---|---|
| `/corpus/incoming/<user>` | Your uploads | You write, everyone reads |
| `/corpus/raw` | Validated originals, copied automatically every 15 minutes | Read-only |
| `/corpus/derived` | Transcripts, features and other results | Everyone reads and writes |

Don't move files into `raw` by hand. Put your own results in a subfolder of `/corpus/derived`, and don't change other people's files.

## Contributing

**This repository must never contain corpus data.** Before committing a notebook, clear its outputs (*Edit → Clear Outputs of All Cells*), because they can contain account names and transcripts. Never commit videos, images, transcripts or passwords.

## Background

Adapted from the preprocessing notebooks in [social-media-lab](https://github.com/michaelachmann/social-media-lab).

## License

Licensed under the [GNU General Public License v3.0](LICENSE). The license covers the code and notebooks in this repository, not the corpus data.
