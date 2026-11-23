import json
import sys
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "notebooks"))

from annotation_selection import PILOT_TABLES, read_table, select_items, selection_form, write_draft


class AnnotationSelectionTests(unittest.TestCase):
    def setUp(self):
        self.items = read_table(PILOT_TABLES / "texts.csv", {"Text ID", "Post ID"})
        self.memberships = read_table(PILOT_TABLES / "collections.csv", {"Post ID", "label", "strategy"})

    def test_seed_reproduces_same_draw_after_corpus_rows_reordered(self):
        sample, eligible = select_items(self.items, "texts", sample_size=2, seed=42)
        reordered, _ = select_items(self.items.iloc[::-1], "texts", sample_size=2, seed=42)
        self.assertEqual(eligible, 3)
        self.assertEqual(sample["Text ID"].tolist(), ["0003", "0001"])
        self.assertEqual(reordered["Text ID"].tolist(), sample["Text ID"].tolist())

    def test_selection_filters_and_exclusions_apply_before_sampling(self):
        selected, eligible = select_items(
            self.items, "texts", memberships=self.memberships,
            collection_label="Transport", collection_strategy="search",
            exclude_ids=["0001"], sample_size=1,
        )
        self.assertEqual(eligible, 1)
        self.assertEqual(selected["Text ID"].tolist(), ["0003"])
        empty, _ = select_items(
            self.items, "texts", memberships=self.memberships,
            collection_label="Parks", collection_strategy="search",
        )
        self.assertTrue(empty.empty)

    def test_manual_selection_preserves_order_and_rejects_oversampling(self):
        selected, _ = select_items(self.items, "texts", only_ids=["0002", "0001"])
        self.assertEqual(selected["Text ID"].tolist(), ["0002", "0001"])
        for size in (0, 4):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "3 eligible items"):
                select_items(self.items, "texts", sample_size=size)

    def test_draft_uses_existing_schema_and_preserves_an_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            draft = write_draft(path, "pilot.json", "  Caption pilot ", "texts", ["0003", "0001"])
            with self.assertRaises(FileExistsError):
                write_draft(path, "pilot.json", "Another study", "comments", ["0101"])
            self.assertEqual(json.loads(draft.read_text(encoding="utf-8")), {
                "version": 1, "title": "Caption pilot", "source": "texts", "item_ids": ["0003", "0001"],
            })

    @unittest.skipUnless(find_spec("ipywidgets"), "Requires the Jupyter widget package")
    def test_form_can_preview_the_pilot_and_requires_a_new_preview_after_changes(self):
        with tempfile.TemporaryDirectory() as tmp, patch("IPython.display.display"), patch("ipywidgets.Output.clear_output"):
            form = selection_form(Path(tmp) / "missing-tables", output_dir=Path(tmp))
            controls = {control.description: control for control in form.children
                        if hasattr(control, "description")}
            preview = controls["Preview selection"]
            export = controls["Export draft"]
            self.assertEqual(controls["Data"].value, "Synthetic pilot")
            self.assertEqual(controls["Source"].value, "texts")
            self.assertFalse(preview.disabled)
            self.assertTrue(export.disabled)
            preview.click()
            self.assertFalse(export.disabled)
            controls["Seed"].value = 12
            self.assertTrue(export.disabled)
            form.close()
