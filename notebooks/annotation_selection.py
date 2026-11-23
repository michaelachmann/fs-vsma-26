"""Select corpus items and export a draft for the seminar annotation service."""

from __future__ import annotations

import json
import random
from html import escape
from pathlib import Path

import pandas as pd


SOURCES = {
    "texts": ("Post text", "Text ID", "Text Type"),
    "comments": ("Comments", "Comment ID", None),
    "images": ("Images", "Image ID", "Image Type"),
}
PILOT_TABLES = Path(__file__).resolve().parent / "annotation_pilot"


def read_table(path: Path, columns: set[str]) -> pd.DataFrame:
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = columns.difference(table.columns)
    if missing:
        raise ValueError(f"{path.name} is missing these columns: {', '.join(sorted(missing))}.")
    return table


def select_items(
    items: pd.DataFrame,
    source: str,
    *,
    memberships: pd.DataFrame | None = None,
    collection_label: str = "",
    collection_strategy: str = "",
    item_type: str = "",
    text_contains: str = "",
    only_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
    sample_size: int | None = None,
    seed: int = 42,
) -> tuple[pd.DataFrame, int]:
    """Apply filters and then optionally draw a reproducible sample without replacement."""
    _, key, type_column = SOURCES[source]
    if items[key].str.strip().eq("").any() or items[key].duplicated().any():
        raise ValueError(f"{source}.csv must contain one row per non-empty {key}.")

    selected = items
    if collection_label or collection_strategy:
        if memberships is None:
            raise ValueError("Collection filters require collections.csv.")
        if collection_label:
            memberships = memberships[memberships["label"] == collection_label]
        if collection_strategy:
            memberships = memberships[memberships["strategy"] == collection_strategy]
        selected = selected[selected["Post ID"].isin(memberships["Post ID"])]
    if item_type:
        if type_column is None:
            raise ValueError("Item type is available for post text and images.")
        selected = selected[selected[type_column] == item_type]
    if text_contains:
        if "Text" not in selected:
            raise ValueError("Text search is available for post text and comments.")
        selected = selected[selected["Text"].str.contains(text_contains, case=False, regex=False)]
    if only_ids:
        if len(set(only_ids)) != len(only_ids):
            raise ValueError("List each selected ID only once.")
        missing = set(only_ids).difference(selected[key])
        if missing:
            raise ValueError(f"Requested IDs missing from the filtered rows: {sorted(missing)[:8]}.")
        selected = selected.set_index(key, drop=False).loc[only_ids]
    if exclude_ids:
        selected = selected[~selected[key].isin(exclude_ids)]

    eligible = len(selected)
    if sample_size is not None:
        if not 1 <= sample_size <= eligible:
            raise ValueError(f"Choose a positive sample size no larger than the {eligible} eligible items.")
        # Sorting IDs keeps the draw stable when a corpus table changes row order.
        drawn = random.Random(seed).sample(sorted(selected[key]), sample_size)
        selected = selected.set_index(key, drop=False).loc[drawn]
    return selected.reset_index(drop=True), eligible


def write_draft(directory: Path, filename: str, title: str, source: str, item_ids: list[str]) -> Path:
    name = Path(filename.strip())
    if name.name != filename.strip() or name.suffix != ".json":
        raise ValueError("Enter a filename ending in .json.")
    title = title.strip()
    if not 1 <= len(title) <= 200 or not item_ids:
        raise ValueError("Enter a title of up to 200 characters and preview at least one item.")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / name
    draft = {"version": 1, "title": title, "source": source, "item_ids": item_ids}
    with path.open("x", encoding="utf-8") as output:
        json.dump(draft, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return path


def selection_form(tables_dir: Path, *, output_dir: Path | None = None):
    """Build the notebook form and keep exports tied to the current preview."""
    import ipywidgets as widgets
    from IPython.display import display

    if output_dir is None:
        output_dir = Path.home() / "annotation-drafts"
    style = {"description_width": "initial"}
    datasets = {"Seminar corpus": tables_dir, "Synthetic pilot": PILOT_TABLES}
    dataset = widgets.Dropdown(options=list(datasets), description="Data", style=style)
    if not any((tables_dir / f"{source}.csv").is_file() for source in SOURCES):
        dataset.value = "Synthetic pilot"
    source = widgets.Dropdown(description="Source", style=style)
    label = widgets.Dropdown(description="Collection label", style=style)
    collection = widgets.Dropdown(description="Collection strategy", style=style)
    item_type = widgets.Dropdown(description="Item type", style=style)
    search = widgets.Text(description="Text contains", style=style)
    only_ids = widgets.Textarea(description="Include only these IDs", placeholder="One ID per line", rows=2, style=style)
    exclude_ids = widgets.Textarea(description="Exclude these IDs", placeholder="One ID per line", rows=2, style=style)
    sampling = widgets.Dropdown(
        options=[("All matching items", "all"), ("Simple random sample", "random")],
        value="random",
        description="Sampling",
        style=style,
    )
    size = widgets.IntText(value=2 if dataset.value == "Synthetic pilot" else 20, description="Sample size", style=style)
    seed = widgets.IntText(value=42, description="Seed", style=style)
    title = widgets.Text(description="Working title", style=style)
    filename = widgets.Text(value="study-draft.json", description="Draft filename", style=style)
    preview = widgets.Button(description="Preview selection", button_style="primary")
    export = widgets.Button(description="Export draft", disabled=True)
    status = widgets.HTML()
    output = widgets.Output()
    state = {"items": None, "memberships": None, "ids": None}

    def report(message: str) -> None:
        status.value = f"<p>{escape(message)}</p>"

    def reset_preview(change=None) -> None:
        state["ids"] = None
        export.disabled = True
        output.clear_output()
        report("Preview the current selection to enable export.")

    def options(control, values) -> None:
        control.options = [("All", "")] + [(value, value) for value in sorted(set(values) - {""})]
        control.value = ""
        control.disabled = len(control.options) == 1

    def refresh_catalog(change=None) -> None:
        reset_preview()
        preview.disabled = True
        source_key = source.value
        if source_key is None:
            report("No corpus tables found. Choose the synthetic pilot or build the corpus tables.")
            return
        directory = datasets[dataset.value]
        _, key, type_column = SOURCES[source_key]
        try:
            items = read_table(directory / f"{source_key}.csv", {key, "Post ID"})
            memberships = None
            if (directory / "collections.csv").is_file():
                memberships = read_table(directory / "collections.csv", {"Post ID", "label", "strategy"})
        except (OSError, ValueError) as exc:
            report(str(exc))
            return
        state.update(items=items, memberships=memberships)
        options(label, [] if memberships is None else memberships["label"])
        options(collection, [] if memberships is None else memberships["strategy"])
        options(item_type, items.get(type_column, []))
        search.disabled = "Text" not in items
        if search.disabled:
            search.value = ""
        preview.disabled = False
        message = f"{len(items)} rows available in {dataset.value.lower()}."
        if source_key == "images":
            message += " The Hub pilot currently imports text and comment drafts."
        report(message)

    def refresh_sources(change=None) -> None:
        directory = datasets[dataset.value]
        choices = [(name, key) for key, (name, _, _) in SOURCES.items()
                   if (directory / f"{key}.csv").is_file()]
        keys = [key for _, key in choices]
        previous = source.value
        source.unobserve(refresh_catalog, names="value")
        source.options = choices
        source.value = previous if previous in keys else next(iter(keys), None)
        source.observe(refresh_catalog, names="value")
        size.value = 2 if dataset.value == "Synthetic pilot" else 20
        refresh_catalog()

    def change_sampling(change=None) -> None:
        size.disabled = seed.disabled = sampling.value == "all"
        reset_preview()

    def parse_ids(value: str) -> list[str]:
        return [line.strip() for line in value.splitlines() if line.strip()]

    def preview_selection(_button) -> None:
        reset_preview()
        _, key, type_column = SOURCES[source.value]
        try:
            selected, eligible = select_items(
                state["items"], source.value, memberships=state["memberships"],
                collection_label=label.value, collection_strategy=collection.value,
                item_type=item_type.value, text_contains=search.value,
                only_ids=parse_ids(only_ids.value), exclude_ids=parse_ids(exclude_ids.value),
                sample_size=size.value if sampling.value == "random" else None, seed=seed.value,
            )
        except ValueError as exc:
            report(str(exc))
            return
        if selected.empty:
            report("No items match these filters.")
            return
        state["ids"] = selected[key].tolist()
        export.disabled = False
        message = f"Selected {len(selected)} of {eligible} eligible items. Showing up to 25."
        if sampling.value == "random":
            message += f" Simple random sample without replacement, seed {seed.value}."
        report(message)
        columns = [col for col in (key, "Post ID", type_column, "Strategy", "Text") if col in selected]
        with output:
            display(selected.loc[:, columns].head(25))

    def export_selection(_button) -> None:
        if state["ids"] is None:
            return
        try:
            path = write_draft(output_dir, filename.value, title.value, source.value, state["ids"])
        except FileExistsError:
            report("A draft with that filename already exists. Choose a new filename.")
        except (OSError, ValueError) as exc:
            report(str(exc))
        else:
            report(f"Saved {len(state['ids'])} item IDs to {path}.")

    dataset.observe(refresh_sources, names="value")
    source.observe(refresh_catalog, names="value")
    sampling.observe(change_sampling, names="value")
    for control in (label, collection, item_type, search, only_ids, exclude_ids, size, seed):
        control.observe(reset_preview, names="value")
    preview.on_click(preview_selection)
    export.on_click(export_selection)
    refresh_sources()

    return widgets.VBox([
        title, dataset, source, label, collection, item_type, search, only_ids, exclude_ids,
        sampling, size, seed, preview, output, filename, export, status,
    ])
