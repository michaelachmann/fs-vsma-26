import json
import tempfile
import unittest
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebooks" / "07a_sample_images.ipynb"
CELLS = {cell["id"]: "".join(cell["source"]) for cell in json.loads(NOTEBOOK.read_text())["cells"]}


@unittest.skipUnless(find_spec("ipywidgets") and find_spec("PIL"), "Requires ipywidgets and Pillow")
class ImageSamplingTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        display_patch = patch("IPython.display.display")
        display_patch.start()
        self.addCleanup(display_patch.stop)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.tables = root / "corpus" / "tables"
        media = root / "corpus" / "raw"
        self.tables.mkdir(parents=True)
        media.mkdir()
        outside = root / "elsewhere.jpg"
        rows = ["Image ID,Post ID,Image Type,Strategy,Frame,Time,Path"]
        for post in ("p1", "p2", "p3"):
            for kind in ("Cover", "Gallery", "Gallery"):
                image_id = f"{post}_{kind.lower()}_{len(rows)}"
                path = media / f"{image_id}.jpg"
                Image.new("RGB", (8, 8)).save(path)
                rows.append(f"{image_id},{post},{kind},,,,{path}")
        Image.new("RGB", (8, 8)).save(outside)
        rows.append(f"gone,p1,Cover,,,,{media / 'gone.jpg'}")
        rows.append(f"escaped,p1,Cover,,,,{outside}")
        (self.tables / "images.csv").write_text("\n".join(rows) + "\n")
        (self.tables / "collections.csv").write_text("Post ID,label,strategy\np1,A,FYP\np2,B,search\n")
        self.namespace = {}
        self.run_cells("sampling-form")
        self.namespace["tables_dir"] = self.tables
        self.namespace["media_roots"] = [media]
        self.fields = self.namespace["selection_fields"]

    def run_cells(self, *cell_ids):
        for cell_id in cell_ids:
            exec(compile(CELLS[cell_id], f"{NOTEBOOK.name}:{cell_id}", "exec"), self.namespace)

    def test_rows_without_a_file_inside_the_media_roots_are_dropped(self):
        self.run_cells("load")
        ids = set(self.namespace["items"]["Image ID"])
        self.assertEqual(len(ids), 9)
        self.assertNotIn("gone", ids)
        self.assertNotIn("escaped", ids)

    def test_seed_reproduces_same_draw_after_rows_reordered(self):
        self.fields["size"].value = 4
        self.run_cells("load", "filter", "sample")
        first = self.namespace["preview_ids"]
        self.namespace["items"] = self.namespace["items"].iloc[::-1]
        self.run_cells("filter", "sample")
        self.assertEqual(self.namespace["preview_ids"], first)
        self.assertEqual(len(set(first)), 4)

    def test_post_limit_and_stratified_sampling(self):
        self.fields["max_per_post"].value = 1
        self.fields["sampling"].value = "all"
        self.run_cells("load", "filter", "sample")
        self.assertEqual(self.namespace["selected"]["Post ID"].nunique(), 3)
        self.assertEqual(len(self.namespace["preview_ids"]), 3)
        self.fields["max_per_post"].value = 0
        self.fields["sampling"].value = "stratified"
        self.fields["size"].value = 4
        with self.assertRaisesRegex(ValueError, "Cover: choose a positive number of at most 3"):
            self.run_cells("load", "filter", "sample")
        self.fields["size"].value = 3
        self.run_cells("load", "filter", "sample")
        selected = self.namespace["selected"]
        self.assertEqual(selected.groupby("Image Type").size().to_dict(), {"Cover": 3, "Gallery": 3})

    def test_collection_filter_and_exclusions_apply_before_sampling(self):
        self.fields["label"].value = "A"
        self.fields["strategy"].value = "FYP"
        self.fields["sampling"].value = "all"
        self.run_cells("load", "filter", "sample")
        self.assertEqual(set(self.namespace["selected"]["Post ID"]), {"p1"})
        self.fields["exclude"].value = self.namespace["preview_ids"][0]
        self.run_cells("load", "filter", "sample")
        self.assertEqual(len(self.namespace["preview_ids"]), 2)

    def test_gallery_renders_and_export_writes_ids_only(self):
        self.namespace["title"].value = "Cover pilot"
        self.fields["size"].value = 3
        self.run_cells("load", "filter", "sample", "gallery")
        with tempfile.TemporaryDirectory() as home, patch.object(Path, "home", return_value=Path(home)):
            self.run_cells("export")
            with self.assertRaises(FileExistsError):
                self.run_cells("export")
            draft = json.loads((Path(home) / "annotation-drafts" / "image-study-draft.json").read_text())
        self.assertEqual(draft, {"version": 1, "title": "Cover pilot", "source": "images",
                                 "item_ids": self.namespace["preview_ids"]})
        self.fields["seed"].value = 7
        with self.assertRaisesRegex(ValueError, "Selection inputs changed"):
            self.run_cells("export")


if __name__ == "__main__":
    unittest.main()
