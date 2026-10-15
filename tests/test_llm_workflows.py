import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import generic_importer
import llm_workflows


VALID_CODE = """import os
from pathlib import Path
import matplotlib.pyplot as plt
project = Path(os.environ["CHART_PROJECT_DIR"])
fig, ax = plt.subplots()
ax.plot([1, 2], [3, 4])
fig.savefig(os.environ["CHART_OUTPUT"])
"""


class WorkflowTests(unittest.TestCase):
    def test_validate_chart_source_blocks_subprocess(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            llm_workflows.validate_chart_source(VALID_CODE.replace("import os", "import os\nimport subprocess"))

    @mock.patch("llm_workflows.llm_client.chat")
    def test_edit_repairs_invalid_model_output(self, chat):
        chat.side_effect = ["print('missing contract')", VALID_CODE]
        with mock.patch.dict(os.environ, {"LLM_MAX_REPAIRS": "1"}):
            result = llm_workflows.edit_chart("make the line red", VALID_CODE, [])
        self.assertEqual(result, VALID_CODE)
        self.assertEqual(chat.call_count, 2)
        self.assertIn("Validator error", chat.call_args.args[0][-1]["content"])

    @mock.patch("llm_workflows.llm_client.chat")
    def test_edit_repairs_render_failure(self, chat):
        chat.side_effect = [VALID_CODE, VALID_CODE.replace("[3, 4]", "[5, 6]")]
        attempts = []

        def validator(code):
            attempts.append(code)
            if len(attempts) == 1:
                raise ValueError("Render failed: bad data shape")

        result = llm_workflows.edit_chart("change values", VALID_CODE, [], validator)
        self.assertIn("[5, 6]", result)
        self.assertEqual(len(attempts), 2)

    @mock.patch("llm_workflows.llm_client.chat")
    def test_split_accepts_fenced_json_and_normalizes_name(self, chat):
        escaped = VALID_CODE.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        chat.return_value = '```json\n{"charts":[{"name":"Figure 1","code":"' + escaped + '"}]}\n```'
        result = llm_workflows.split_chart("source.py", VALID_CODE, [{"file": "data.csv"}])
        self.assertEqual(result[0]["name"], "Figure_1")
        self.assertEqual(result[0]["code"], VALID_CODE)

    def test_generic_importer_keeps_deterministic_fallback_without_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload = root / "upload"
            (upload / "code").mkdir(parents=True)
            (upload / "csv").mkdir()
            (upload / "csv" / "points.csv").write_text("x,y\n1,2\n", encoding="utf-8")
            (upload / "code" / "plot.py").write_text(
                "import matplotlib.pyplot as plt\nplt.plot([1], [2])\nplt.show()\n", encoding="utf-8")
            result = generic_importer.import_generic(root, upload, "demo", "Demo")
            generated = (root / "projects" / "demo" / "charts" / "plot.py").read_text(encoding="utf-8")
        self.assertEqual(result["charts"], ["plot"])
        self.assertIn("CHART_PROJECT_DIR", generated)
        self.assertIn("CHART_OUTPUT", generated)


if __name__ == "__main__":
    unittest.main()
