from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
for _p in (_ROOT, _ROOT / "lib"):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

from media_overview import list_targets, process_root, render_html, Tile


class OverviewTests(unittest.TestCase):
    def test_list_targets_skips_ignore_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "Kochen").mkdir()
            (root / "Backen").mkdir()
            (root / "ignore").mkdir()
            (root / "images").mkdir()
            (root / "notes.txt").write_text("x", encoding="utf-8")
            self.assertEqual(list_targets(root), ["Backen", "Kochen"])

    def test_render_html_has_recipe_button(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image = root / "cover.jpg"
            image.write_bytes(b"x")
            tile = Tile(
                title="Soup",
                image_path=image,
                folder_uri=root.as_uri(),
                mp4_rel=None,
                preview_html="<p>steps</p>",
                kind="pdf",
            )
            body = render_html("Kochen", [tile], root)
            self.assertIn("Rezept", body)
            self.assertIn("Soup", body)
            self.assertIn("steps", body)

    def test_process_root_writes_section_html(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            recipe = root / "Kochen" / "[3][01]soup"
            recipe.mkdir(parents=True)
            try:
                from PIL import Image

                Image.new("RGB", (8, 8), "orange").save(recipe / "cover.png")
            except ImportError:
                self.skipTest("Pillow is needed to build a gallery thumbnail")
            written = process_root(root, keep_images=True, thumb_sec=1.0, only=["Kochen"])
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0].name, "Kochen.html")
            body = written[0].read_text(encoding="utf-8")
            self.assertIn("Rezept", body)
            self.assertNotIn("Keine Kacheln", body)


if __name__ == "__main__":
    unittest.main()
