import json
import os
import tempfile
import unittest
from pathlib import Path

from shared_modules import (
    apply_module,
    discover_modules,
    encode_module_id,
    read_module_history,
    resolve_module,
    module_revision_source,
)


class SharedModuleDiscoveryTests(unittest.TestCase):
    def make_project(self, root, metadata):
        project = Path(root) / "project"
        (project / "lib").mkdir(parents=True)
        (project / "project.json").write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        return project

    @staticmethod
    def write_module(project, relative, source="VALUE = 1\n"):
        path = project / "lib" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return path

    def test_group_bundle_exposes_only_group_visualization(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(
                tmp, {"data_source_type": "plot_bundle", "analysis": "group"}
            )
            self.write_module(project, "behavior_analysis/group/visualization.py")
            self.write_module(project, "behavior_analysis/group/processing.py")
            self.write_module(project, "behavior_analysis/single/visualization.py")

            modules = discover_modules(project)

            self.assertEqual(
                ["behavior_analysis/group/visualization.py"],
                [item["path"] for item in modules],
            )

    def test_border_bundle_exposes_non_init_visualization_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(
                tmp, {"data_source_type": "plot_bundle", "analysis": "border"}
            )
            self.write_module(
                project, "behavior_analysis/border/visualization/__init__.py"
            )
            self.write_module(project, "behavior_analysis/border/visualization/counts.py")
            self.write_module(project, "behavior_analysis/border/processing/counts.py")

            modules = discover_modules(project)

            self.assertEqual(
                ["behavior_analysis/border/visualization/counts.py"],
                [item["path"] for item in modules],
            )

    def test_tabular_project_exposes_non_init_python_files_under_lib(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(tmp, {"name": "Table project"})
            self.write_module(project, "theme.py")
            self.write_module(project, "helpers/labels.py")
            self.write_module(project, "helpers/__init__.py")

            modules = discover_modules(project)

            self.assertEqual(
                ["helpers/labels.py", "theme.py"],
                [item["path"] for item in modules],
            )

    def test_processing_module_cannot_be_resolved_from_forged_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(
                tmp, {"data_source_type": "plot_bundle", "analysis": "group"}
            )
            self.write_module(project, "behavior_analysis/group/visualization.py")
            self.write_module(project, "behavior_analysis/group/processing.py")

            forged = encode_module_id("behavior_analysis/group/processing.py")

            with self.assertRaisesRegex(ValueError, "不可编辑"):
                resolve_module(project, forged)

    def test_traversal_and_absolute_module_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(tmp, {"name": "Table project"})
            self.write_module(project, "theme.py")

            for relative in ("../secret.py", "C:/secret.py"):
                with self.subTest(relative=relative):
                    with self.assertRaisesRegex(ValueError, "无效"):
                        resolve_module(project, encode_module_id(relative))

    def test_symlink_outside_project_library_is_not_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(tmp, {"name": "Table project"})
            outside = Path(tmp) / "outside.py"
            outside.write_text("SECRET = True\n", encoding="utf-8")
            link = project / "lib" / "outside_link.py"
            try:
                os.symlink(outside, link)
            except OSError as error:
                self.skipTest("This Windows account cannot create symlinks: {}".format(error))

            self.assertEqual([], discover_modules(project))


if __name__ == "__main__":
    unittest.main()


class SharedModuleApplyTests(unittest.TestCase):
    def make_project(self, root):
        project = Path(root) / "project"
        module = project / "lib" / "theme.py"
        module.parent.mkdir(parents=True)
        (project / "history").mkdir()
        (project / "project.json").write_text(
            json.dumps({"name": "Table project"}), encoding="utf-8"
        )
        module.write_text("COLOR = 'red'\n", encoding="utf-8")
        return project, module, encode_module_id("theme.py")

    def test_failed_render_keeps_source_and_history_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, module, module_id = self.make_project(tmp)

            def fail_render(chart, library):
                self.assertEqual("summary", chart)
                self.assertEqual("COLOR = 'blue'\n", (library / "theme.py").read_text())
                raise ValueError("Render failed: expected test failure")

            with self.assertRaisesRegex(ValueError, "expected test failure"):
                apply_module(
                    project,
                    module_id,
                    "COLOR = 'blue'\n",
                    "summary",
                    fail_render,
                    "change color",
                )

            self.assertEqual("COLOR = 'red'\n", module.read_text(encoding="utf-8"))
            self.assertEqual([], read_module_history(project, module_id))

    def test_successful_validation_saves_source_and_records_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, module, module_id = self.make_project(tmp)

            def render(chart, library):
                self.assertEqual("COLOR = 'blue'\n", (library / "theme.py").read_text())
                return b"image"

            result = apply_module(
                project,
                module_id,
                "COLOR = 'blue'\n",
                "summary",
                render,
                "change color",
            )

            self.assertEqual("COLOR = 'blue'\n", module.read_text(encoding="utf-8"))
            self.assertEqual(b"image", result["preview"])
            history = read_module_history(project, module_id)
            self.assertEqual(2, len(history))
            self.assertEqual("初始版本", history[0]["note"])
            self.assertEqual("change color", history[1]["note"])

    def test_syntax_error_is_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, module, module_id = self.make_project(tmp)
            calls = []

            with self.assertRaises(SyntaxError):
                apply_module(
                    project,
                    module_id,
                    "if:\n",
                    "summary",
                    lambda chart, library: calls.append((chart, library)),
                )

            self.assertEqual([], calls)
            self.assertEqual("COLOR = 'red'\n", module.read_text(encoding="utf-8"))

    def test_realistic_large_visualization_module_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, module, module_id = self.make_project(tmp)
            source = "VALUE = 1\n" * 16000
            self.assertGreater(len(source), 100_000)

            result = apply_module(
                project,
                module_id,
                source,
                "summary",
                lambda chart, library: b"image",
                "large module",
            )

            self.assertTrue(result["changed"])
            self.assertEqual(source, module.read_text(encoding="utf-8"))

    def test_saved_revision_source_can_be_loaded_for_validated_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, module, module_id = self.make_project(tmp)
            result = apply_module(
                project,
                module_id,
                "COLOR = 'blue'\n",
                "summary",
                lambda chart, library: b"image",
                "change color",
            )

            initial_id = result["history"][0]["id"]

            self.assertEqual(
                "COLOR = 'red'\n",
                module_revision_source(project, module_id, initial_id),
            )
