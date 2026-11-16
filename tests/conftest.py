#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the tests find what the part type runs with.

* The reader: the image's copy where these tests run in the image
  (/opt/partcad-scan-pdal), which is the copy a user's parts are built with;
  this checkout's image/lib anywhere else.
* PartCAD's wrappers directory, which is on the path when PartCAD runs the
  script, for 'ocp_serialize' (the voxel builder compounds its solids with it):
  from an installed PartCAD, which needs none of its dependencies for that.
* PDAL: a stand-in (fake_pdal.py) for the tests of what this code does with
  what PDAL says, and the real one -- the image's -- for 'test_live.py', which
  is skipped where there is none.
"""

import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGE_LIBRARY = "/opt/partcad-scan-pdal"
LIBRARY = (
    IMAGE_LIBRARY
    if os.path.isfile(os.path.join(IMAGE_LIBRARY, "pdal_cloud.py"))
    else os.path.join(ROOT, "image", "lib")
)
REAL_PDAL = os.environ.get("PC_PDAL_REAL") or ("/opt/pdal/bin/pdal" if os.path.exists("/opt/pdal/bin/pdal") else None)

os.environ["PC_SCAN_PDAL_LIBRARY"] = LIBRARY
sys.path.insert(0, LIBRARY)

spec = importlib.util.find_spec("partcad")
if spec is not None and spec.submodule_search_locations:
    sys.path.append(os.path.join(list(spec.submodule_search_locations)[0], "wrappers"))


@pytest.fixture
def fake_pdal(tmp_path, monkeypatch):
    """The stand-in PDAL, and the file it logs what it is asked into."""
    program = os.path.join(HERE, "fake_pdal.py")
    os.chmod(program, 0o755)
    log = tmp_path / "pdal.log"
    monkeypatch.setenv("PC_PDAL", program)
    monkeypatch.setenv("PC_FAKE_PDAL_LOG", str(log))
    return log


@pytest.fixture
def real_pdal(monkeypatch):
    if not REAL_PDAL:
        pytest.skip("there is no PDAL here: these run in the image (see .github/workflows/test.yml)")
    monkeypatch.setenv("PC_PDAL", REAL_PDAL)
    return REAL_PDAL
