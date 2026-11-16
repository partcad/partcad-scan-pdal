#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What the reader asks PDAL, and what it makes of PDAL's answer -- with a stand-in PDAL (fake_pdal.py).

The point of reading through PDAL here rather than writing a reader of our own
is that the part is the solid PartCAD's 'pointcloud' type makes: so the
central test reads one cloud both ways and compares the solids.
"""

import json
import math
import os
import runpy

import part_pointcloud
import pdal_cloud
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


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


def dome(step=0.1):
    """A dome 1 m in radius on a 3 m square of ground, as lists of X, Y and Z."""
    xs, ys, zs = [], [], []
    count = int(round(3.0 / step)) + 1
    for i in range(count):
        for j in range(count):
            x, y = -1.5 + i * step, -1.5 + j * step
            r2 = x * x + y * y
            xs.append(x)
            ys.append(y)
            zs.append(math.sqrt(1.0 - r2) if r2 < 1.0 else 0.0)
    return xs, ys, zs


def write_cloud(path, **dimensions):
    with open(path, "w") as f:
        json.dump(dimensions, f)
    return str(path)


def asked(log):
    return [json.loads(line) for line in log.read_text().splitlines()]


def pipeline_asked(log):
    return [entry["pipeline"] for entry in asked(log) if "pipeline" in entry][-1]


def request(path=None, **parameters):
    found = {"kind": "part", "name": "/test:cloud", "parameters": parameters, "config": {}}
    if path is not None:
        found["path"] = str(path)
    return found


# -- The part --------------------------------------------------------------------------------------------------


def test_a_cloud_read_through_pdal_is_the_solid_the_builtin_type_makes(fake_pdal, tmp_path):
    xs, ys, zs = dome()
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)
    text = tmp_path / "dome.xyz"
    text.write_text("".join("%r %r %r\n" % point for point in zip(xs, ys, zs)))

    ours = pdal_cloud.run(request(source))
    builtin = part_pointcloud.run(request(text))

    assert "exception" not in ours, ours
    assert "exception" not in builtin, builtin
    assert volume(ours["shape"]) == pytest.approx(volume(builtin["shape"]), rel=1e-9)
    assert bounding_box(ours["shape"]) == pytest.approx(bounding_box(builtin["shape"]), abs=1e-6)
    # A dome 1 m high on its base, in millimetres, over the origin.
    xmin, ymin, zmin, xmax, ymax, zmax = bounding_box(ours["shape"])
    assert xmax - xmin == pytest.approx(3000.0, rel=0.05)
    assert zmin == pytest.approx(0.0, abs=1e-6)
    assert zmax > 1000.0


def test_what_pdal_is_asked_for_a_plain_file(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.25)
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)

    assert "exception" not in pdal_cloud.run(request(source))

    infos = [entry for entry in asked(fake_pdal) if "info" in entry]
    assert [entry["info"] for entry in infos] == [["--schema"], ["--summary"]]
    assert all(entry["driver"] is None and entry["source"] == source for entry in infos)
    stages = pipeline_asked(fake_pdal)
    assert stages[0] == {"filename": source}
    assert stages[-1]["type"] == "writers.ply"
    assert stages[-1]["storage_mode"] == "little endian"
    # Only what a part is made of: no colour or classification it does not have.
    assert stages[-1]["dims"] == "X=float64,Y=float64,Z=float64"
    assert len(stages) == 2


def test_colours_are_written_and_make_coloured_voxels(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.2)
    # 16-bit, as PDAL holds colour: red low, blue high.
    reds = [65535 if z < 0.5 else 0 for z in zs]
    blues = [0 if z < 0.5 else 65535 for z in zs]
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs, Red=reds, Green=[0] * len(xs), Blue=blues)

    output = pdal_cloud.run(request(source, **{"as": "voxels", "cell": 250}))

    assert "exception" not in output, output
    assert pipeline_asked(fake_pdal)[-1]["dims"] == "X=float64,Y=float64,Z=float64,Red=uint16,Green=uint16,Blue=uint16"
    colours = {tuple(entry["rgba"]) for entry in output["cmf"]["solids"] if entry}
    assert colours == {(255, 0, 0, 1.0), (0, 0, 255, 1.0)}


def test_classes_are_read_by_pdal_and_the_ground_is_what_is_left(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.2)
    classes = [2 if z == 0.0 else 6 for z in zs]
    source = write_cloud(tmp_path / "survey.json", X=xs, Y=ys, Z=zs, Classification=classes)

    output = pdal_cloud.run(request(source, classes="2", base=10))

    assert "exception" not in output, output
    stages = pipeline_asked(fake_pdal)
    assert {"type": "filters.range", "limits": "Classification[2:2]"} in stages
    assert stages[-1]["dims"].endswith(",Classification=uint8")
    xmin, ymin, zmin, xmax, ymax, zmax = bounding_box(output["shape"])
    # The ground alone: flat, on its base.
    assert zmax - zmin == pytest.approx(10.0, abs=1e-6)


def test_classes_of_a_cloud_without_them_are_refused_as_the_builtin_type_refuses_them(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.5)
    source = write_cloud(tmp_path / "plain.json", X=xs, Y=ys, Z=zs)

    output = pdal_cloud.run(request(source, classes=2))

    assert "this file has none" in output["exception"]
    assert not any(stage.get("type") == "filters.range" for stage in pipeline_asked(fake_pdal))


def test_bounds_crop_a_file_and_are_asked_of_an_indexed_reader(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.1)
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)

    output = pdal_cloud.run(request(source, bounds="0 0 1.5 1.5"))
    assert "exception" not in output, output
    assert {"type": "filters.crop", "bounds": "([0.0, 1.5], [0.0, 1.5])"} in pipeline_asked(fake_pdal)
    xmin, ymin, zmin, xmax, ymax, zmax = bounding_box(output["shape"])
    # A quarter of the dome's square, to a cell or so.
    assert 1500.0 <= xmax - xmin < 2000.0

    copc = tmp_path / "survey.copc.laz"
    copc.write_text(json.dumps({"X": xs, "Y": ys, "Z": zs}))
    output = pdal_cloud.run(request(copc, bounds=[0, 0, 1.5, 1.5], resolution=0.2))
    assert "exception" not in output, output
    stages = pipeline_asked(fake_pdal)
    assert stages[0] == {
        "filename": str(copc),
        "type": "readers.copc",
        "resolution": 0.2,
        "bounds": "([0.0, 1.5], [0.0, 1.5])",
    }
    assert not any(stage.get("type") == "filters.crop" for stage in stages)


def test_a_large_cloud_is_thinned_as_pdal_reads_it(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.1)
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)

    output = pdal_cloud.run(request(source, maxPoints=100))

    assert "exception" not in output, output
    assert {"type": "filters.decimation", "step": math.ceil(len(xs) / 100.0)} in pipeline_asked(fake_pdal)


def test_a_cloud_whose_count_pdal_cannot_say_is_thinned_after(fake_pdal, tmp_path, monkeypatch):
    monkeypatch.setenv("PC_FAKE_PDAL_NO_SUMMARY", "1")
    xs, ys, zs = dome(0.1)
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)

    output = pdal_cloud.run(request(source, maxPoints=100))

    assert "exception" not in output, output
    assert not any(stage.get("type") == "filters.decimation" for stage in pipeline_asked(fake_pdal))


def test_what_pdal_says_when_it_cannot_read_is_the_failure(fake_pdal, tmp_path):
    source = write_cloud(tmp_path / "broken.json", X=[0], Y=[0], Z=[0])

    output = pdal_cloud.run(request(source))

    assert output["exception"].startswith("broken.json: PDAL could not read the schema of broken.json: ")
    assert "Unable to open stream" in output["exception"]


def test_with_no_pdal_the_failure_says_where_it_is(tmp_path, monkeypatch):
    monkeypatch.delenv("PC_PDAL", raising=False)
    monkeypatch.setattr(pdal_cloud, "DEFAULT_PDAL", str(tmp_path / "none"))
    monkeypatch.setenv("PATH", str(tmp_path))

    output = pdal_cloud.run(request(tmp_path / "a.pcd"))

    assert "there is no PDAL here" in output["exception"]


def test_the_builtin_reader_is_put_back(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.5)
    pdal_cloud.run(request(write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)))

    assert part_pointcloud.read.__module__ == "part_pointcloud"


# -- 'stream' ----------------------------------------------------------------------------------------------------


def test_a_stream_reads_a_region_of_a_remote_survey(fake_pdal, tmp_path, monkeypatch):
    xs, ys, zs = dome(0.1)
    monkeypatch.setenv("PC_FAKE_PDAL_REMOTE", write_cloud(tmp_path / "remote.json", X=xs, Y=ys, Z=zs))
    url = "https://example.com/usgs/survey/ept.json"

    output = pdal_cloud.run(request(source=url, bounds="-1 -1 1 1", resolution=0.5))

    assert "exception" not in output, output
    reader = pipeline_asked(fake_pdal)[0]
    assert reader["type"] == "readers.ept" and reader["filename"] == url
    assert reader["bounds"] == "([-1.0, 1.0], [-1.0, 1.0])" and reader["resolution"] == 0.5


def test_a_stream_is_never_read_whole(fake_pdal):
    output = pdal_cloud.run(request(source="https://example.com/survey/ept.json"))

    assert "read in 'bounds', at 'resolution', or both" in output["exception"]
    assert not fake_pdal.exists()


def test_a_stream_names_a_url_and_a_file_is_a_scan(fake_pdal):
    assert "names its cloud in 'source'" in pdal_cloud.run(request())["exception"]
    assert "a file is a 'scan' part" in pdal_cloud.run(request(source="survey/ept.json"))["exception"]


# -- The parameters ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source, parameters, reader",
    [
        ("a.pcd", {}, None),
        ("survey/ept.json", {}, "readers.ept"),
        ("https://host/x/ept.json?token=1", {}, "readers.ept"),
        ("tile.copc.laz", {}, "readers.copc"),
        ("points.dat", {"reader": "text"}, "readers.text"),
        ("points.dat", {"reader": "readers.text"}, "readers.text"),
    ],
)
def test_the_reader(source, parameters, reader):
    assert pdal_cloud.reader_type(source, parameters) == reader


@pytest.mark.parametrize("bounds", ["1 2 3", "3 0 1 1", "0 3 1 1", [0, 0, 0, 1], "a b c d"])
def test_bounds_that_bound_nothing_are_refused(bounds):
    with pytest.raises(ValueError, match="west south east north"):
        pdal_cloud.bounds_of(bounds)


def test_resolution_is_for_an_indexed_source():
    with pytest.raises(ValueError, match="EPT or a COPC"):
        pdal_cloud.pipeline("a.pcd", None, ["X", "Y", "Z"], {"resolution": 1}, "out.ply")
    with pytest.raises(ValueError, match="larger than nothing"):
        pdal_cloud.pipeline("a.copc.laz", "readers.copc", ["X", "Y", "Z"], {"resolution": 0}, "out.ply")


def test_dimension_names_are_compared_as_pdal_compares_them():
    stages = pdal_cloud.pipeline(
        "a.pcd", None, ["x", "y", "z", "red", "green", "blue", "classification"], {"classes": [2, 9]}, "out.ply"
    )["pipeline"]

    assert {"type": "filters.range", "limits": "Classification[2:2],Classification[9:9]"} in stages
    assert stages[-1]["dims"].count("=") == 7


def test_the_environment_pdal_runs_in_is_its_conda_environment(tmp_path, monkeypatch):
    prefix = tmp_path / "pdal"
    for relative in ("bin", "lib", "share/proj", "share/gdal"):
        (prefix / relative).mkdir(parents=True)
    program = prefix / "bin" / "pdal"
    program.write_text("")
    # The image sets all three: what is not set is what is worked out.
    monkeypatch.delenv("PDAL_DRIVER_PATH", raising=False)
    monkeypatch.delenv("GDAL_DATA", raising=False)
    monkeypatch.setenv("PROJ_DATA", "/somewhere/else")

    env = pdal_cloud.environment(str(program))

    assert env["PDAL_DRIVER_PATH"] == str(prefix / "lib")
    assert env["GDAL_DATA"] == str(prefix / "share" / "gdal")
    # What is set already is the caller's to set.
    assert env["PROJ_DATA"] == "/somewhere/else"


# -- The script --------------------------------------------------------------------------------------------------


def test_the_package_script_hands_the_request_to_the_library(fake_pdal, tmp_path):
    xs, ys, zs = dome(0.25)
    source = write_cloud(tmp_path / "dome.json", X=xs, Y=ys, Z=zs)

    found = runpy.run_path(
        os.path.join(ROOT, "scan.py"), init_globals={"request": request(source)}, run_name="__partcad_part__"
    )

    assert "exception" not in found["output"], found["output"]
    assert volume(found["output"]["shape"]) > 0


def test_the_package_script_outside_the_image_says_so(tmp_path, monkeypatch):
    monkeypatch.setenv("PC_SCAN_PDAL_LIBRARY", str(tmp_path))

    found = runpy.run_path(
        os.path.join(ROOT, "scan.py"), init_globals={"request": request("a.pcd")}, run_name="__partcad_part__"
    )

    assert "runs in the image its package names" in found["output"]["exception"]
