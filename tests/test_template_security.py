import os
import unittest


class TemplateSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "templates",
            "index.html",
        )
        with open(template_path, "r", encoding="utf-8") as template_file:
            cls.template = template_file.read()

    def test_preview_cards_are_constructed_without_html_injection_sinks(self):
        start = self.template.index("function renderPreviewCards(items)")
        end = self.template.index("// ---- Force overwrite toggle", start)
        renderer = self.template[start:end]

        self.assertNotIn("innerHTML", renderer)
        self.assertNotIn("escapeHtml", renderer)
        self.assertNotIn("insertAdjacentHTML", renderer)
        self.assertIn("document.createElement", renderer)
        self.assertIn("titleElement.title = titleText", renderer)
        self.assertIn("titleElement.textContent = titleText", renderer)
        self.assertIn("yearElement.textContent", renderer)
        self.assertIn("statusBadge.textContent", renderer)
        self.assertIn("$previewGrid.textContent = ''", renderer)


if __name__ == "__main__":
    unittest.main()
