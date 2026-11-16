#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The reader with the real PDAL: the image's, which is where these run (see .github/workflows/test.yml).

Every cloud is written here, by PDAL itself where the format is binary, so
nothing is downloaded: the dome of 'sample.pcd' as the PCD it is, as a Leica
PTX with colours, as a COPC read back a region at a time, and as LAS with a
classification.
"""

import json
import math
import os
import subprocess

import part_pointcloud
import pdal_cloud
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SAMPLE = os.path.join(ROOT, "sample.pcd")


def volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()


def bounding_box(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    return box.Get()


def request(path=None, **parameters):
    found = {"kind": "part", "name": "/test:cloud", "parameters": parameters, "config": {}}
    if path is not None:
        found["path"] = str(path)
    return found


def translate(pdal, stages, tmp_path):
    pipe = tmp_path / "make.json"
    pipe.write_text(json.dumps({"pipeline": stages}))
    subprocess.run([pdal, "pipeline", str(pipe)], check=True, env=pdal_cloud.environment(pdal))


def sample_points():
    with open(SAMPLE) as f:
        lines = f.read().split("DATA ascii\n", 1)[1].splitlines()
    return [tuple(float(v) for v in line.split()) for line in lines if line.strip()]


def test_the_sample_is_the_solid_the_builtin_type_makes_of_its_points(real_pdal, tmp_path):
    text = tmp_path / "sample.xyz"
    text.write_text("".join("%r %r %r\n" % point for point in sample_points()))

    ours = pdal_cloud.run(request(SAMPLE, unit="m"))
    builtin = part_pointcloud.run(request(text, unit="m"))

    assert "exception" not in ours, ours
    # PCD holds the points as 32-bit floats, so not to the last digit.
    assert volume(ours["shape"]) == pytest.approx(volume(builtin["shape"]), rel=1e-5)
    xmin, ymin, zmin, xmax, ymax, zmax = bounding_box(ours["shape"])
    assert xmax - xmin == pytest.approx(3000.0, rel=0.1) and zmax > 1000.0


def test_a_ptx_scan_in_its_colours(real_pdal, tmp_path):
    points = sample_points()
    side = int(round(math.sqrt(len(points))))
    ptx = tmp_path / "scan.ptx"
    with open(ptx, "w") as f:
        # Columns, rows, the scanner's position and axes, and its transform: none.
        f.write("%d\n%d\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n" % (side, side))
        f.write("1 0 0 0\n0 1 0 0\n0 0 1 0\n0 0 0 1\n")
        for x, y, z in points:
            red, blue = (255, 0) if z < 0.5 else (0, 255)
            f.write("%r %r %r 0.5 %d 0 %d\n" % (x, y, z, red, blue))

    output = pdal_cloud.run(request(ptx, unit="m", cell=250, **{"as": "voxels"}))

    assert "exception" not in output, output
    colours = {tuple(entry["rgba"][:3]) for entry in output["cmf"]["solids"] if entry}
    assert colours == {(255, 0, 0), (0, 0, 255)}


def test_a_copc_survey_is_read_a_region_at_a_time(real_pdal, tmp_path):
    copc = tmp_path / "survey.copc.laz"
    translate(real_pdal, [SAMPLE, {"type": "writers.copc", "filename": str(copc)}], tmp_path)

    whole = pdal_cloud.run(request(copc, unit="m"))
    corner = pdal_cloud.run(request(copc, unit="m", bounds="0 0 1.5 1.5"))

    assert "exception" not in whole, whole
    assert "exception" not in corner, corner
    width = bounding_box(whole["shape"])[3] - bounding_box(whole["shape"])[0]
    part = bounding_box(corner["shape"])[3] - bounding_box(corner["shape"])[0]
    assert part < 0.7 * width


def test_a_lidar_survey_s_ground(real_pdal, tmp_path):
    las = tmp_path / "survey.las"
    translate(
        real_pdal,
        [
            SAMPLE,
            {"type": "filters.assign", "value": ["Classification = 6", "Classification = 2 WHERE Z < 0.001"]},
            {"type": "writers.las", "filename": str(las), "minor_version": 4, "dataformat_id": 6},
        ],
        tmp_path,
    )

    output = pdal_cloud.run(request(las, unit="m", classes=2, base=10))

    assert "exception" not in output, output
    xmin, ymin, zmin, xmax, ymax, zmax = bounding_box(output["shape"])
    assert zmax - zmin == pytest.approx(10.0, abs=1e-3)


def test_what_pdal_cannot_read_is_said_in_its_words(real_pdal, tmp_path):
    bad = tmp_path / "nothing.pcd"
    bad.write_text("not a point cloud\n")

    output = pdal_cloud.run(request(bad))

    assert output["exception"].startswith("nothing.pcd: PDAL could not")
