"""Manual end-to-end verification against real behavior-analysis Plot Bundles."""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from bundle_importer import import_plot_bundle
from server import render


def verify(platform_root: Path, bundle_root: Path, code_root: Path):
    results = {}
    with tempfile.TemporaryDirectory(prefix="graphic-editing-integration-") as tmp:
        studio = Path(tmp)
        (studio / "projects").mkdir()
        for name in ("bundle_runtime.py", "bundle_bindings.py"):
            shutil.copy2(platform_root / name, studio / name)
        for analysis in ("group", "border"):
            source = bundle_root / (analysis + "_plot_bundle")
            imported = import_plot_bundle(
                studio,
                source,
                project_id=analysis + "_integration",
                name=analysis.title() + " integration",
                mode="server_path",
                trusted=True,
                runtime_source=code_root,
            )
            project = studio / "projects" / (analysis + "_integration")
            chart = project / "charts" / (imported["charts"][0] + ".py")
            from local_execution import approve
            approve(project)
            image = render(project, chart.read_text(encoding="utf-8"))
            if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise AssertionError("{} renderer did not return PNG".format(analysis))
            results[analysis] = {
                "plot_count": imported["plot_count"],
                "first_chart": imported["charts"][0],
                "rendered_bytes": len(image),
            }
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--platform-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--code-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            verify(args.platform_root, args.bundle_root, args.code_root),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
