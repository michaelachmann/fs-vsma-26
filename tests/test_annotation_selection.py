import json
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch


NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "07_select_annotation_items.ipynb"
CELLS = {cell["id"]: "".join(cell["source"]) for cell in json.loads(NOTEBOOK.read_text())["cells"]}


@unittest.skipUnless(find_spec("ipywidgets"), "Requires the Jupyter widget package")
class AnnotationSelectionTests(unittest.TestCase):
    def setUp(self):
        display_patch = patch("IPython.display.display")
        display_patch.start()
        self.addCleanup(display_patch.stop)
        self.namespace = {}
        self.run_cells("sampling-form")
        self.namespace["table_directories"]["Synthetic pilot"] = NOTEBOOK.parent / "annotation_pilot"
        self.fields = self.namespace["selection_fields"]

    def run_cells(self, *cell_ids):
        for cell_id in cell_ids:
            exec(compile(CELLS[cell_id], f"{NOTEBOOK.name}:{cell_id}", "exec"), self.namespace)

    def test_seed_reproduces_same_draw_after_corpus_rows_reordered(self):
        self.run_cells("load", "filter", "sample")
        self.assertEqual(self.namespace["preview_ids"], ["0003", "0001"])
        self.namespace["items"] = self.namespace["items"].iloc[::-1]
        self.run_cells("filter", "sample")
        self.assertEqual(self.namespace["preview_ids"], ["0003", "0001"])

    def test_filters_apply_before_sampling_and_match_the_same_membership(self):
        self.fields["label"].value = "Transport"
        self.fields["strategy"].value = "search"
        self.fields["exclude"].value = "0001"
        self.fields["size"].value = 1
        self.run_cells("load", "filter", "sample")
        self.assertEqual(self.namespace["preview_ids"], ["0003"])
        self.fields["label"].value = "Parks"
        self.run_cells("load", "filter")
        self.assertTrue(self.namespace["eligible"].empty)

    def test_manual_order_is_preserved_and_invalid_sample_sizes_are_rejected(self):
        self.fields["sampling"].value = "all"
        self.fields["include"].value = "0002\n0001"
        self.run_cells("load", "filter", "sample")
        self.assertEqual(self.namespace["preview_ids"], ["0002", "0001"])
        self.fields["sampling"].value = "random"
        for size in (0, 3):
            self.fields["size"].value = size
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "2 eligible items"):
                self.run_cells("load", "filter", "sample")

    def test_export_uses_the_preview_order_and_protects_existing_drafts(self):
        self.namespace["title"].value = "  Caption pilot  "
        self.run_cells("load", "filter", "sample")
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            self.run_cells("export")
            with self.assertRaises(FileExistsError):
                self.run_cells("export")
            path = Path(home) / "annotation-drafts" / "study-draft.json"
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {
                "version": 1, "title": "Caption pilot", "source": "texts", "item_ids": ["0003", "0001"],
            })

    def test_changing_form_values_or_reloading_requires_a_new_preview(self):
        self.run_cells("load", "filter", "sample")
        self.fields["seed"].value = 12
        with self.assertRaisesRegex(ValueError, "Selection inputs changed"):
            self.run_cells("export")
        self.run_cells("load")
        with self.assertRaisesRegex(ValueError, "Run the load, filter, and sample cells"):
            self.run_cells("export")
