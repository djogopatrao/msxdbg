"""Rebuild the committed debugger fixture with an MSXgl 1.5.0 archive."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


HERE = Path(__file__).resolve().parent
ARTIFACTS = ("debug_fixture.rom", "debug_fixture.cdb",
             "debug_fixture.map", "debug_fixture.lst")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path,
                        help="MSXgl-1.5.0 .zip or .tar.gz distribution")
    options = parser.parse_args()
    archive = options.archive.resolve()
    if not archive.is_file():
        parser.error(f"archive does not exist: {archive}")

    with tempfile.TemporaryDirectory(prefix="msxdbg-msxgl-") as directory:
        temporary = Path(directory)
        shutil.unpack_archive(str(archive), temporary)
        roots = tuple(temporary.glob("MSXgl-1.5.0"))
        if len(roots) != 1:
            raise SystemExit("archive must contain one MSXgl-1.5.0 directory")
        root = roots[0]
        project = root / "projects" / "debug_fixture"
        project.mkdir()
        shutil.copy2(HERE / "debug_fixture.c", project / "debug_fixture.c")
        shutil.copy2(HERE / "project_config.js", project / "project_config.js")

        bundled_node = root / "tools" / "build" / "Node" / "node"
        node = shutil.which("node") or str(bundled_node)
        subprocess.run(
            (node, str(root / "engine" / "script" / "js" / "build.js")),
            cwd=project, check=True,
        )

        output = HERE / "out"
        output.mkdir(exist_ok=True)
        for name in ARTIFACTS:
            shutil.copy2(project / "out" / name, output / name)
        # SDCC records absolute object paths in the MAP footer.  Normalize that
        # build-only prefix so rebuilding in another checkout is byte-stable.
        map_path = output / "debug_fixture.map"
        normalized = map_path.read_text(encoding="utf-8").replace(
            str(root), "MSXgl-1.5.0")
        map_path.write_text(normalized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
