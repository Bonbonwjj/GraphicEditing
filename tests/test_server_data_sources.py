import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server
from shared_modules import encode_module_id


class SharedRootConfigurationTests(unittest.TestCase):
    def test_shared_roots_are_read_from_platform_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "one"
            second = Path(tmp) / "two"
            first.mkdir()
            second.mkdir()
            environ = {
                "CHART_STUDIO_SHARED_ROOTS": os.pathsep.join(
                    [str(first), str(second)]
                )
            }

            roots = server.shared_roots_from_env(environ)

            self.assertEqual([first.resolve(), second.resolve()], roots)

    def test_server_source_outside_configured_roots_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            allowed = Path(tmp) / "allowed"
            outside = Path(tmp) / "outside"
            allowed.mkdir()
            outside.mkdir()
            environ = {"CHART_STUDIO_SHARED_ROOTS": str(allowed)}

            with self.assertRaisesRegex(ValueError, "允许的共享目录"):
                server.resolve_server_path(outside, environ)


class DataPreviewTests(unittest.TestCase):
    def test_preview_supports_csv_tsv_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            data = project / "data"
            data.mkdir()
            (data / "values.csv").write_text("x,y\n1,2\n", encoding="utf-8")
            (data / "values.tsv").write_text("a\tb\n3\t4\n", encoding="utf-8")
            (data / "values.json").write_text(
                json.dumps([{"m": 5, "n": 6}]), encoding="utf-8"
            )

            preview = server.data_preview(project)

            by_name = {item["file"]: item for item in preview}
            self.assertEqual(["x", "y"], by_name["values.csv"]["columns"])
            self.assertEqual(["a", "b"], by_name["values.tsv"]["columns"])
            self.assertEqual(["m", "n"], by_name["values.json"]["columns"])
            self.assertEqual([[5, 6]], by_name["values.json"]["sample"])

    def test_single_file_validation_accepts_tsv_and_json(self):
        self.assertEqual(1, server.validate_tabular_content("values.tsv", "x\ty\n1\t2\n"))
        self.assertEqual(
            1,
            server.validate_tabular_content(
                "values.json", json.dumps([{"x": 1, "y": 2}])
            ),
        )


class ProjectListingTests(unittest.TestCase):
    def test_entry_level_warning_without_figure_id_does_not_break_listing(self):
        import project_preparation as prep
        with tempfile.TemporaryDirectory() as tmp:
            projects=Path(tmp);project=projects/'demo'
            (project/'charts').mkdir(parents=True)
            (project/'data').mkdir()
            (project/'charts/a.py').write_text('pass')
            prep.write_json(project/'project.json',{'name':'Demo'})
            prep.save_state(project,{'status':'ready','validation':{'state':'passed','checks':[
                {'entry_path':'pipeline.py','render':'warning','reason':'output limit reached'},
                {'entry_path':'another.py','render':'failed','reason':'missing dependency'}]}})
            with patch.object(server,'PROJECTS',projects):
                listing=server.list_projects()
            self.assertEqual(listing[0]['charts'],['a'])
            self.assertEqual(listing[0]['chart_warnings'],{})
            self.assertEqual(listing[0]['chart_diagnostic_previews'],[])

    def test_project_listing_includes_all_data_files_and_source_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp)
            project = projects / "demo"
            (project / "charts").mkdir(parents=True)
            (project / "data").mkdir()
            (project / "project.json").write_text(
                json.dumps({"name": "Demo", "description": ""}), encoding="utf-8"
            )
            (project / "data_sources.json").write_text(
                json.dumps({"version": 1, "sources": [{"kind": "tabular"}]}),
                encoding="utf-8",
            )
            (project / "charts" / "plot.py").write_text("", encoding="utf-8")
            (project / "data" / "a.tsv").write_text("x\n1\n", encoding="utf-8")

            with patch.object(server, "PROJECTS", projects):
                listing = server.list_projects()

            self.assertEqual(["a.tsv"], listing[0]["data"])
            self.assertEqual("tabular", listing[0]["data_sources"][0]["kind"])

    def test_project_listing_includes_editable_shared_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp)
            project = projects / "demo"
            (project / "charts").mkdir(parents=True)
            (project / "data").mkdir()
            module = project / "lib" / "behavior_analysis" / "group" / "visualization.py"
            (project / "charts" / "plot.py").write_text("# existing split figure\n", encoding="utf-8")
            module.parent.mkdir(parents=True)
            module.write_text("COLOR = 'red'\n", encoding="utf-8")
            (project / "project.json").write_text(
                json.dumps(
                    {
                        "name": "Demo",
                        "data_source_type": "plot_bundle",
                        "analysis": "group",
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(server, "PROJECTS", projects):
                listing = server.list_projects()

            self.assertEqual(
                "behavior_analysis/group/visualization.py",
                listing[0]["modules"][0]["path"],
            )


class RenderPathTests(unittest.TestCase):
    def test_render_can_import_project_local_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            library = project / "lib"
            library.mkdir()
            (library / "helper_module.py").write_text(
                "from pathlib import Path\n"
                "def write(path): Path(path).write_bytes(b'project-lib')\n",
                encoding="utf-8",
            )
            source = (
                "import os\n"
                "from helper_module import write\n"
                "write(os.environ['CHART_OUTPUT'])\n"
            )

            from local_execution import approve
            approve(project)
            output = server.render(project, source)

            self.assertEqual(b"project-lib", output)

    def test_render_can_prioritize_a_validation_library_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project_library = project / "lib"
            candidate_library = Path(tmp) / "candidate"
            project_library.mkdir(parents=True)
            candidate_library.mkdir()
            (project_library / "helper_module.py").write_text(
                "from pathlib import Path\n"
                "def write(path): Path(path).write_bytes(b'working')\n",
                encoding="utf-8",
            )
            (candidate_library / "helper_module.py").write_text(
                "from pathlib import Path\n"
                "def write(path): Path(path).write_bytes(b'candidate')\n",
                encoding="utf-8",
            )
            source = (
                "import os\n"
                "from helper_module import write\n"
                "write(os.environ['CHART_OUTPUT'])\n"
            )

            from local_execution import approve
            approve(project)
            output = server.render(project, source, library_path=candidate_library)

            self.assertEqual(b"candidate", output)


class LlmPromptTests(unittest.TestCase):
    def test_module_instruction_describes_shared_visualization_code(self):
        instruction = server.llm_instruction("module")

        self.assertIn("shared visualization module", instruction)
        self.assertNotIn("one Python Matplotlib chart script", instruction)


class SharedModuleServerTests(unittest.TestCase):
    def make_project(self, root):
        projects = Path(root) / "projects"
        project = projects / "demo"
        (project / "charts").mkdir(parents=True)
        (project / "data").mkdir()
        module = project / "lib" / "theme.py"
        module.parent.mkdir()
        module.write_text("COLOR = 'red'\n", encoding="utf-8")
        (project / "charts" / "summary.py").write_text(
            "from theme import COLOR\n", encoding="utf-8"
        )
        (project / "project.json").write_text(
            json.dumps({"name": "Demo"}), encoding="utf-8"
        )
        return projects, project, module, encode_module_id("theme.py")

    def test_module_detail_returns_code_history_and_relative_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects, project, module, module_id = self.make_project(tmp)

            detail = server.shared_module_detail(project, module_id)

            self.assertEqual("COLOR = 'red'\n", detail["code"])
            self.assertEqual([], detail["history"])
            self.assertEqual("theme.py", detail["module"]["path"])

    def test_apply_shared_module_uses_candidate_library_then_saves(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects, project, module, module_id = self.make_project(tmp)
            rendered = []

            def fake_render(p, source, suffix=".png", library_path=None):
                rendered.append((p, source, suffix, library_path))
                self.assertEqual(
                    "COLOR = 'blue'\n",
                    (Path(library_path) / "theme.py").read_text(encoding="utf-8"),
                )
                return b"png"

            with patch.object(server, "PROJECTS", projects), patch.object(
                server, "render", side_effect=fake_render
            ):
                result = server.save_shared_module(
                    "demo", module_id, "COLOR = 'blue'\n", "summary", "change"
                )

            self.assertEqual(1, len(rendered))
            self.assertEqual("COLOR = 'blue'\n", module.read_text(encoding="utf-8"))
            self.assertTrue(result["changed"])
            self.assertIn("revision", result)


if __name__ == "__main__":
    unittest.main()
