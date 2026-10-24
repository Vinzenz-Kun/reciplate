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

from config import ConfigError, load_settings
from copy_template import copy_template, file_hash, tidy_recipe_folder
from fill import IngredientGroup, RecipeDraft, fill_copy, ingredients_body
from language import DE, EN, detect_language, video_note
from names import (
    canonical_recipe_url,
    find_folder_by_url,
    folder_name,
    folder_number,
    move_recipe_folder,
    next_insta_number,
    recipe_url_key,
    rename_stem_files,
    slug,
)
from parse import groups_from_text, parse_caption
from translate import bilingual_drafts

MINI = r"""
\documentclass[12pt,ngerman]{scrartcl}
\graphicspath{ {img/} }
\newenvironment{ingredients}{\begin{tcolorbox}[ingredientsbox,title=Zutaten]}{\end{tcolorbox}}
\newenvironment{directionswide}{\begin{tcolorbox}[directionsbox,title=Zubereitung,width=\DirectionsWidth]}{\end{tcolorbox}\par}
\newcommand{\RecipeTitle}{OLD TITLE}
\newcommand{\RecipeHandle}{OLD HANDLE}
\newcommand{\RecipeURL}{https://example.com/old}
\img[width=\ImageFixedWidth,keepaspectratio]{old.jpg}
\begin{ingredients}
  \begin{itemize}
    \item leftover
  \end{itemize}
\end{ingredients}
\begin{directionswide}
  \begin{enumerate}
    \item leftover step
  \end{enumerate}
\end{directionswide}
\url{\RecipeURL}\fi
"""


class CopyTests(unittest.TestCase):
    def test_copy_then_fill_leaves_master_alone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            master = root / "recipe.tex"
            master.write_text(MINI, encoding="utf-8")
            img = root / "img"
            img.mkdir()
            (img / "sticker-homemade.png").write_bytes(b"png")
            before = file_hash(master)
            dest = root / "out"
            copies = copy_template(master, dest)
            self.assertEqual(set(copies), {DE, EN})
            self.assertFalse((dest / "img").exists())
            self.assertFalse((dest / "sticker-homemade.png").exists())
            self.assertIn((img.resolve().as_posix().rstrip("/") + "/"), copies[DE].read_text(encoding="utf-8"))
            self.assertNotEqual(copies[DE].resolve(), master.resolve())
            german = RecipeDraft(
                title="[3][01] Test",
                handle="Insta: @x",
                url="https://www.instagram.com/reel/abc/",
                image_name="cover.jpg",
                groups=[IngredientGroup("Sauce", ["1 EL Sojasauce"])],
                steps=["Tofu anbraten"],
                language=DE,
                video_language=DE,
            )
            fill_copy(copies[DE], german)
            fill_copy(
                copies[EN],
                RecipeDraft(
                    title="[3][01] Test",
                    handle="Insta: @x",
                    url="https://www.instagram.com/reel/abc/",
                    image_name="cover.jpg",
                    groups=[IngredientGroup("Sauce", ["1 tbsp soy sauce"])],
                    steps=["Fry the tofu"],
                    language=EN,
                    video_language=DE,
                ),
            )
            self.assertEqual(file_hash(master), before)
            self.assertEqual(master.read_text(encoding="utf-8"), MINI)
            filled_de = copies[DE].read_text(encoding="utf-8")
            filled_en = copies[EN].read_text(encoding="utf-8")
            self.assertIn("[3][01] Test", filled_de)
            self.assertIn("1 EL Sojasauce", filled_de)
            self.assertIn("ngerman", filled_de)
            self.assertIn("Video: Deutsch (Original)", filled_de)
            self.assertIn("Fry the tofu", filled_en)
            self.assertIn("english", filled_en)
            self.assertIn("title=Ingredients", filled_en)
            self.assertIn(video_note(EN, DE), filled_en)
            self.assertNotIn("OLD TITLE", filled_de)

    def test_fill_copy_uses_plain_ingredient_lines(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            master = root / "recipe.tex"
            master.write_text(MINI, encoding="utf-8")
            dest = root / "out"
            copies = copy_template(master, dest)
            groups = groups_from_text("Für die Panade\n6 EL Speisestärke\n2 TL Knoblauchpulver")
            fill_copy(
                copies[DE],
                RecipeDraft(
                    title="[3][39] Panierter Tofu",
                    handle="Insta: @x",
                    url="https://www.instagram.com/p/Db8meUcoJX8/",
                    image_name="cover.jpg",
                    groups=groups,
                    steps=["Panade mixen"],
                    language=DE,
                    video_language=DE,
                ),
            )
            text = copies[DE].read_text(encoding="utf-8")
            self.assertIn("6 EL Speisestärke", text)
            self.assertIn("2 TL Knoblauchpulver", text)
            self.assertNotIn("TODO: Zutaten ergänzen", text)
            fill_copy(
                copies[DE],
                RecipeDraft(
                    title="[3][39] Panierter Tofu",
                    handle="Insta: @x",
                    url="https://www.instagram.com/p/Db8meUcoJX8/",
                    image_name="cover.jpg",
                    groups=groups,
                    steps=["Panade mixen"],
                    language=DE,
                    video_language=DE,
                ),
            )
            again = copies[DE].read_text(encoding="utf-8")
            self.assertEqual(again.count(r"\newcommand{\RecipeVideoNote}"), 1)
            self.assertEqual(again.count(r"{\footnotesize \RecipeVideoNote}"), 1)

    def test_latex_url_escapes_hash(self) -> None:
        from fill import latex_url

        self.assertIn(r"\#", latex_url("https://www.instagram.com/reel/abc/?igsh=x#frag"))

    def test_refuses_existing_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            master = root / "recipe.tex"
            master.write_text(MINI, encoding="utf-8")
            (root / "img").mkdir()
            dest = root / "out"
            dest.mkdir()
            with self.assertRaises(FileExistsError):
                copy_template(master, dest)

    def test_numbering(self) -> None:
        self.assertEqual(slug("Kung Pao Tofu"), "kung-pao-tofu")
        self.assertTrue(folder_name(36, "Kung Pao").startswith("[3][36]"))
        self.assertEqual(folder_name(36, "[3][36] Kung Pao"), folder_name(36, "Kung Pao"))
        self.assertIn("豆腐", slug("豆腐のステーキ"))
        self.assertEqual(
            canonical_recipe_url("https://www.instagram.com/reels/AbC123/?igsh=xyz"),
            "https://www.instagram.com/reel/AbC123/",
        )
        self.assertEqual(
            canonical_recipe_url("www.instagram.com/reel/AbC123/?igsh=xyz"),
            "https://www.instagram.com/reel/AbC123/",
        )
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            (parent / "[3][01]a").mkdir()
            (parent / "[3][35]b").mkdir()
            self.assertEqual(next_insta_number(parent), 36)
            cook = parent / "cook"
            bake = parent / "bake"
            cook.mkdir()
            bake.mkdir()
            (cook / "[3][02]x").mkdir()
            (bake / "[3][40]y").mkdir()
            self.assertEqual(next_insta_number([cook, bake]), 41)

    def test_overwrite_refreshes_copies_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            master = root / "recipe.tex"
            master.write_text(MINI, encoding="utf-8")
            (root / "img").mkdir()
            dest = root / "out"
            first = copy_template(master, dest)
            first[DE].write_text("OLD", encoding="utf-8")
            copies = copy_template(master, dest, overwrite=True)
            self.assertTrue((dest / "out.de.tex").is_file())
            self.assertNotEqual(copies[DE].read_text(encoding="utf-8"), "OLD")

    def test_tidy_keeps_only_tex_pdf_video(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "recipe"
            folder.mkdir()
            (folder / "recipe.de.tex").write_text("tex", encoding="utf-8")
            (folder / "recipe.pdf").write_bytes(b"%PDF")
            (folder / "recipe.mp4").write_bytes(b"vid")
            (folder / "recipe.jpg").write_bytes(b"jpg")
            (folder / "recipe.aux").write_text("aux", encoding="utf-8")
            (folder / "__build_de.log").write_text("log", encoding="utf-8")
            (folder / "__build_de.pdf").write_bytes(b"%PDF")
            (folder / "source.json").write_text("{}", encoding="utf-8")
            (folder / "cover.jpg").write_bytes(b"jpg")
            (folder / "sticker-homemade.png").write_bytes(b"png")
            (folder / "source.webp").write_bytes(b"webp")
            img = folder / "img"
            img.mkdir()
            (img / "cover.jpg").write_bytes(b"jpg")
            tidy_recipe_folder(folder)
            names = {path.name for path in folder.iterdir()}
            self.assertEqual(names, {"recipe.de.tex", "recipe.pdf", "recipe.mp4", "recipe.jpg"})

    def test_instagram_url_finds_existing_folder(self) -> None:
        self.assertEqual(
            recipe_url_key("https://www.instagram.com/reel/AbC123/?igsh=xyz"),
            recipe_url_key("https://instagram.com/p/AbC123/"),
        )
        self.assertEqual(recipe_url_key("https://www.instagram.com/reel/AbC123/"), "abc123")
        self.assertEqual(
            canonical_recipe_url("https://www.instagram.com/reel/AbC123/?igsh=xyz"),
            "https://www.instagram.com/reel/AbC123/",
        )
        with tempfile.TemporaryDirectory() as raw:
            cook = Path(raw) / "cook"
            folder = cook / "[3][36]kraut"
            folder.mkdir(parents=True)
            (folder / "source.json").write_text(
                '{"url": "https://www.instagram.com/reel/AbC123/?igsh=old"}\n',
                encoding="utf-8",
            )
            found = find_folder_by_url(
                [cook],
                "https://instagram.com/reel/AbC123/",
            )
            self.assertEqual(found, folder)
            tex_only = cook / "[3][01]from-tex"
            tex_only.mkdir()
            (tex_only / "recipe.de.tex").write_text(
                r"\newcommand{\RecipeURL}{https://www.instagram.com/reel/TeX999/}",
                encoding="utf-8",
            )
            self.assertEqual(
                find_folder_by_url([cook], "https://www.instagram.com/p/TeX999/"),
                tex_only,
            )
            self.assertIsNone(find_folder_by_url([cook], "https://www.instagram.com/reel/missing/"))
            self.assertEqual(folder_number("[3][36]kraut"), 36)

    def test_rename_stem_files_and_move_folder(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw)
            old = parent / "[3][01]old-title"
            old.mkdir()
            (old / "[3][01]old-title.de.tex").write_text("tex", encoding="utf-8")
            (old / "[3][01]old-title.jpg").write_bytes(b"jpg")
            (old / "[3][01]old-title.mp4").write_bytes(b"vid")
            (old / "notes.txt").write_text("keep-name", encoding="utf-8")
            rename_stem_files(old, old.name, "[3][01]new-title")
            names = {path.name for path in old.iterdir()}
            self.assertEqual(
                names,
                {
                    "[3][01]new-title.de.tex",
                    "[3][01]new-title.jpg",
                    "[3][01]new-title.mp4",
                    "notes.txt",
                },
            )
            dest = parent / "cook" / "[3][01]new-title"
            moved = move_recipe_folder(old, dest)
            self.assertEqual(moved, dest)
            self.assertTrue((dest / "[3][01]new-title.mp4").is_file())
            self.assertFalse(old.exists())


class ConfigTests(unittest.TestCase):
    def test_loads_personal_paths_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            recipes = root / "recipes"
            (recipes / "cook").mkdir(parents=True)
            (recipes / "bake").mkdir()
            file = root / "config.json"
            file.write_text(
                """
                {
                  "recipes_root": "%s",
                  "template_tex": "tmpl/recipe.tex",
                  "sticker": "tmpl/img/sticker.png",
                  "sections": {"Kochen": "cook", "Backen": "bake"},
                  "default_section": "Backen",
                  "cookies_from_browser": "firefox",
                  "folder_code": 3
                }
                """
                % recipes.as_posix(),
                encoding="utf-8",
            )
            settings = load_settings(file)
            self.assertEqual(settings.default_section, "Backen")
            self.assertEqual(settings.cookies_from_browser, "firefox")
            self.assertEqual(settings.section_path("Kochen"), (recipes / "cook").resolve())
            self.assertEqual(settings.template_tex, (recipes / "tmpl" / "recipe.tex").resolve())

    def test_missing_config_explains_copy(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            missing = Path(raw) / "nope.json"
            with self.assertRaises(ConfigError) as caught:
                load_settings(missing)
            self.assertIn("config.example.json", str(caught.exception))

    def test_missing_recipes_root_explains(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            file = Path(raw) / "config.json"
            file.write_text('{"sections": {"Kochen": "cook"}}', encoding="utf-8")
            with self.assertRaises(ConfigError) as caught:
                load_settings(file)
            self.assertIn("recipes_root", str(caught.exception))

    def test_invalid_folder_code_explains(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            recipes = Path(raw) / "recipes"
            (recipes / "cook").mkdir(parents=True)
            file = Path(raw) / "config.json"
            file.write_text(
                '{"recipes_root": "%s", "sections": {"Kochen": "cook"}, "folder_code": "x"}'
                % recipes.as_posix(),
                encoding="utf-8",
            )
            with self.assertRaises(ConfigError) as caught:
                load_settings(file)
            self.assertIn("folder_code", str(caught.exception))


class LanguageTests(unittest.TestCase):
    def test_detects_german_and_english(self) -> None:
        self.assertEqual(detect_language("Tofu anbraten und mit Sojasauce mischen"), DE)
        self.assertEqual(detect_language("Mix the tofu with soy sauce until browned"), EN)

    def test_bilingual_pair_translates_once(self) -> None:
        def fake(text: str, source: str, target: str) -> str:
            return f"{text} [{target}]"

        source = RecipeDraft(
            title="[3][01] Tofu",
            handle="Insta: @x",
            url="https://example.com",
            image_name="cover.jpg",
            groups=[IngredientGroup("Sauce", ["Sojasauce"])],
            steps=["Tofu anbraten"],
            language=DE,
            video_language=DE,
        )
        pair = bilingual_drafts(source, translator=fake)
        self.assertEqual(pair[DE].steps, ["Tofu anbraten"])
        self.assertEqual(pair[EN].steps, ["Tofu anbraten [en]"])
        self.assertEqual(pair[EN].title, "[3][01] Tofu [en]")
        self.assertEqual(pair[EN].language, EN)
        self.assertEqual(pair[EN].handle, "Insta: @x")

    def test_pack_unpack_keeps_order(self) -> None:
        from translate import pack_texts, unpack_texts

        texts = ["2 EL Öl", "Tofu anbraten", "Sauce"]
        blob = pack_texts(texts)
        self.assertIn("[[T0]]", blob)
        self.assertEqual(unpack_texts(blob, 3), texts)
        scrambled = "Intro [[T1]] fry tofu [[T0]] 2 tbsp oil [[T2]] sauce"
        self.assertEqual(unpack_texts(scrambled, 3), ["2 tbsp oil", "fry tofu", "sauce"])


class ParseTests(unittest.TestCase):
    def test_headed_german_caption(self) -> None:
        draft = parse_caption(
            "Instagram",
            "@veganewunder",
            "https://example.com",
            """
            Tofu Lachs ✨
            Zutaten
            450g extra fester Tofu
            Marinade:
            2 EL Sojasoße
            1 TL Nori-Flocken
            Zubereitung
            1. Tofu ausdrücken und einschneiden
            2. Marinade verrühren und den Tofu einpinseln
            Tipps
            Nori fein mörsern
            #vegan #tofu
            """,
        )
        self.assertIn("Tofu", draft.title)
        items = [item for group in draft.groups for item in group.items]
        self.assertTrue(any("450g" in item for item in items))
        self.assertTrue(any(group.heading.lower().startswith("marinade") for group in draft.groups))
        self.assertEqual(len(draft.steps), 2)
        self.assertTrue(any("ausdrücken" in step for step in draft.steps))
        self.assertTrue(any("mörsern" in tip for tip in draft.tips))

    def test_unheaded_amounts_then_verbs(self) -> None:
        draft = parse_caption(
            "Kung Pao Tofu",
            "@x",
            "https://example.com",
            """
            Kung Pao Tofu
            200g Tofu
            2 EL Sojasauce
            1 TL Speisestärke
            Tofu würfeln und anbraten. Sauce mischen und 3 min köcheln.
            """,
        )
        items = [item for group in draft.groups for item in group.items]
        self.assertEqual(len(items), 3)
        self.assertGreaterEqual(len(draft.steps), 1)
        self.assertTrue(any("anbraten" in step for step in draft.steps))

    def test_english_headings(self) -> None:
        draft = parse_caption(
            "Video by chef",
            "@x",
            "https://example.com",
            """
            Ingredients
            - 200g tofu
            - 2 tbsp soy sauce
            Instructions
            1. Press and fry the tofu
            2. Mix the sauce and simmer for 3 minutes
            """,
        )
        self.assertEqual(len(draft.groups[0].items), 2)
        self.assertEqual(len(draft.steps), 2)

    def test_grams_inside_instruction_stay_one_step(self) -> None:
        draft = parse_caption(
            "Pfanne",
            "@x",
            "https://example.com",
            """
            200g Tofu
            2 EL Öl
            In der Pfanne 2 EL Öl erhitzen, 200g Tofu 5 min anbraten und mit der Sauce ablöschen.
            """,
        )
        items = [item for group in draft.groups for item in group.items]
        self.assertEqual(items, ["200g Tofu", "2 EL Öl"])
        self.assertEqual(len(draft.steps), 1)
        self.assertIn("200g Tofu 5 min anbraten", draft.steps[0])

    def test_inline_amount_list_then_prose(self) -> None:
        draft = parse_caption(
            "Tofu",
            "@x",
            "https://example.com",
            "450g extra fester Tofu 2 EL Sojasoße 1 TL Nori-Flocken Tofu ausdrücken und einschneiden.",
        )
        items = [item for group in draft.groups for item in group.items]
        self.assertEqual(len(items), 3)
        self.assertTrue(any("450g" in item for item in items))
        self.assertEqual(len(draft.steps), 1)
        self.assertIn("ausdrücken", draft.steps[0])
        self.assertNotIn("ausdrücken", " ".join(items))

    def test_scans_amounts_in_steps_without_duplicating(self) -> None:
        draft = parse_caption(
            "Pfanne",
            "@x",
            "https://example.com",
            """
            Tofu-Pfanne
            In der Pfanne 2 EL Öl erhitzen, 200g Tofu 5 min anbraten und 1 TL Sojasauce dazugeben.
            """,
        )
        items = [item for group in draft.groups for item in group.items]
        joined = " ".join(items).lower()
        self.assertTrue(any("öl" in item.lower() for item in items))
        self.assertTrue(any("200g" in item.replace(" ", "") for item in items))
        self.assertTrue(any("sojasauce" in item.lower() for item in items))
        self.assertEqual(len(draft.steps), 1)
        self.assertIn("200g Tofu 5 min anbraten", draft.steps[0])
        listed_again = parse_caption(
            "Pfanne",
            "@x",
            "https://example.com",
            """
            200g Tofu
            2 EL Öl
            1 TL Sojasauce
            In der Pfanne 2 EL Öl erhitzen, 200g Tofu 5 min anbraten und 1 TL Sojasauce dazugeben.
            """,
        )
        again = [item for group in listed_again.groups for item in group.items]
        self.assertEqual(len(again), 3)

    def test_scan_does_not_duplicate_listed_amounts(self) -> None:
        draft = parse_caption(
            "Pfanne",
            "@x",
            "https://example.com",
            """
            200g extra fester Tofu
            2 EL Öl
            In der Pfanne 2 EL Öl erhitzen und 200g Tofu anbraten.
            """,
        )
        items = [item for group in draft.groups for item in group.items]
        self.assertEqual(len(items), 2)

    def test_groups_from_text_keeps_headings(self) -> None:
        groups = groups_from_text("Marinade:\n- 2 EL Sojasauce\n\n- 200g Tofu")
        self.assertEqual(groups[0].heading, "Marinade")
        self.assertEqual(groups[0].items, ["2 EL Sojasauce"])
        self.assertEqual(groups[1].heading, "")
        self.assertEqual(groups[1].items, ["200g Tofu"])

    def test_groups_from_text_plain_lines_without_dashes(self) -> None:
        groups = groups_from_text(
            """
            (2 Portionen)
            Für die Panade
            60 g Chips, deine Lieblingssorte
            100 g Cornflakes
            6 EL Speisestärke

            Für den Tofu
            400 g Räuchertofu
            Für die Marinade
            8 EL Skyr-Alternative
            2 TL Knoblauchpulver
            """
        )
        by_head = {group.heading: group.items for group in groups}
        self.assertIn("60 g Chips, deine Lieblingssorte", by_head["(2 Portionen) · Für die Panade"])
        self.assertIn("6 EL Speisestärke", by_head["(2 Portionen) · Für die Panade"])
        self.assertEqual(by_head["Für den Tofu"], ["400 g Räuchertofu"])
        self.assertEqual(by_head["Für die Marinade"], ["8 EL Skyr-Alternative", "2 TL Knoblauchpulver"])
        body = ingredients_body(groups)
        self.assertIn("60 g Chips", body)
        self.assertIn("2 TL Knoblauchpulver", body)
        self.assertNotIn("TODO", body)

    def test_google_payload_text(self) -> None:
        from translate import google_payload_text

        self.assertEqual(
            google_payload_text([[["Breaded tofu", "Panierter Tofu", None, None, 10]], None, "de"]),
            "Breaded tofu",
        )


class DownloadTests(unittest.TestCase):
    def test_yt_dlp_library_is_available(self) -> None:
        from yt_dlp import YoutubeDL

        self.assertTrue(callable(YoutubeDL))

    def test_place_photo_uses_folder_name(self) -> None:
        from download import _place_recipe_photo

        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "[3][36]kraut"
            folder.mkdir()
            (folder / "[3][36]kraut.jpeg").write_bytes(b"jpeg-bytes")
            _place_recipe_photo(folder)
            photo = folder / "[3][36]kraut.jpg"
            self.assertTrue(photo.is_file())
            self.assertFalse((folder / "[3][36]kraut.jpeg").exists())


class CompileTests(unittest.TestCase):
    def test_finds_lualatex(self) -> None:
        from latex_build import find_lualatex

        engine = find_lualatex()
        if engine is None:
            self.skipTest("lualatex is not installed")
        self.assertTrue(engine.is_file())

    def test_compiles_bracket_filename_then_tidies(self) -> None:
        from latex_build import compile_tex, find_lualatex
        from copy_template import tidy_recipe_folder

        if find_lualatex() is None:
            self.skipTest("lualatex is not installed")
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "[3][01]test"
            folder.mkdir()
            tex = folder / "[3][01]test.de.tex"
            tex.write_text(
                r"""
\documentclass{article}
\begin{document}
Hello.
\end{document}
""",
                encoding="utf-8",
            )
            pdf = compile_tex(tex, passes=1)
            self.assertTrue(pdf.is_file())
            self.assertEqual(pdf.name, "[3][01]test.de.pdf")
            tidy_recipe_folder(folder)
            names = {path.name for path in folder.iterdir()}
            self.assertEqual(names, {"[3][01]test.de.tex", "[3][01]test.de.pdf"})


class PdfTextTests(unittest.TestCase):
    def test_missing_pdf_explains(self) -> None:
        from pdf_text import PdfTextError, extract_pdf_text

        with self.assertRaises(PdfTextError):
            extract_pdf_text(Path("definitely-missing-recipe.pdf"))


if __name__ == "__main__":
    unittest.main()
