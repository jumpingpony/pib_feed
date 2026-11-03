#!/usr/bin/env python3
"""FT Opinion: the topper hero leads the item body exactly once."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from feeds import ft

HERO = {
    "id": "11111111-2222-3333-4444-555555555555",
    "url": (
        "https://images.ft.com/v3/image/raw/"
        "https%3A%2F%2Fd1e00ek4ebabms.cloudfront.net%2Fproduction%2Fhero.jpg"
        "?source=ft-app-api&fit=scale-down&quality=highest&width=780"
    ),
    "altText": "An illustration of a prepper",
    "caption": None,
    "credit": "© Kenneth Andersson",
}

PICTURE_REF = {
    "type": "main-image",
    "picture": {
        "fallbackImage": HERO,
        "alt": "A power cut",
        "caption": None,
        "credit": "© Kenneth Andersson",
    },
}


def paragraph(text):
    return {"type": "paragraph", "children": [{"type": "text", "value": text}]}


def main_image_block(index=0):
    return {"type": "main-image", "data": {"referenceIndex": index}}


def article(children, refs=None, main_image=HERO, topper=None):
    return {
        "title": "The age of prepping is here",
        "standfirst": "",
        "body": {
            "structured": {
                "tree": {"type": "body", "children": children},
                "references": refs or [],
            }
        },
        "mainImage": main_image,
        "topper": topper or {},
    }


class TestLeadImage(unittest.TestCase):
    def test_hero_leads_when_body_has_no_image(self):
        # Columns and Big Reads keep the hero in mainImage, not the body tree.
        rendered = ft.render_article(article([paragraph("Text."), paragraph("More.")]))

        self.assertTrue(rendered["body_html"].startswith("<figure>"))
        self.assertIn('alt="An illustration of a prepper"', rendered["body_html"])
        self.assertIn("© Kenneth Andersson", rendered["body_html"])
        self.assertIn("width=1400", rendered["body_html"])
        self.assertEqual(rendered["body_html"].count("<img"), 1)

    def test_hero_is_not_repeated_when_the_body_carries_it(self):
        # Most articles repeat the hero as a main-image block.
        rendered = ft.render_article(
            article(
                [paragraph("Text."), main_image_block()],
                refs=[PICTURE_REF],
            )
        )

        self.assertEqual(rendered["body_html"].count("<img"), 1)
        self.assertIn('alt="A power cut"', rendered["body_html"])

    def test_topper_image_stands_in_for_a_missing_main_image(self):
        rendered = ft.render_article(
            article(
                [paragraph("Text.")],
                main_image=None,
                topper={"images": [HERO], "fallbackImage": None},
            )
        )

        self.assertEqual(rendered["body_html"].count("<img"), 1)
        self.assertIn("hero.jpg", rendered["body_html"])

    def test_letters_without_any_image_stay_imageless(self):
        rendered = ft.render_article(
            article([paragraph("Letter text.")], main_image=None)
        )

        self.assertNotIn("<img", rendered["body_html"])


if __name__ == "__main__":
    unittest.main()
