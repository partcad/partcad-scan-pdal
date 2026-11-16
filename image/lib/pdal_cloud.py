#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Point clouds in every format PDAL reads, as the solids PartCAD's 'pointcloud' part type makes.

PartCAD reads LAS, LAZ, PLY, E57 and text clouds itself (the 'pointcloud' and
'e57' types of //builtin/import). Everything else a scanner, a lidar or a
survey writes is PDAL's: Point Cloud Library's '.pcd', Leica's '.ptx', a
'.bpf', Optech's '.csd', Terrasolid's '.bin', an SLPK, a Draco cloud -- and the
two formats that are read a region at a time, at a resolution, out of a survey
far too large to read whole: Entwine Point Tiles ('ept.json') and Cloud
Optimized Point Clouds ('.copc.laz'), local or over HTTP. USGS 3DEP publishes
the whole United States as EPT.

PDAL is asked, through its command line, to translate the cloud into a binary
PLY of what a part is made of -- X, Y and Z, and the colour and lidar
classification where the cloud has them -- and the points are handed to
PartCAD's own 'part_pointcloud', a copy of which is beside this module (see
'sync-partcad.sh'): binned into a height field or into voxels, by the part's
'as', exactly as the built-in type does it, with the same parameters.

What this adds to those parameters:

  * 'reader' - the PDAL reader, where its guess from the file's name is not
    the one wanted: 'readers.text', or just 'text';
  * 'bounds' - 'west south east north', in the cloud's own reference system:
    the part of it read. An EPT or COPC reader reads only that; any other
    reads the file and crops it;
  * 'resolution' - for an EPT or COPC source, the spacing of the points read,
    in the cloud's units: the coarser, the fewer;
  * 'source' - for the 'stream' type, which has no file: the cloud's URL. It
    is read in 'bounds', at 'resolution', or both - read whole, it would be a
    survey of a state.

'classes' is applied by PDAL as it reads, where the cloud has a
classification, so that a survey's ground is all that is written.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Where the image puts PDAL: a conda-forge environment of its own, beside the
# Python the script runs in rather than in it (see image/Dockerfile).
DEFAULT_PDAL = "/opt/pdal/bin/pdal"

# Readers that take 'bounds' and 'resolution' themselves, reading only what is
# asked for out of an index; any other reads its file whole.
INDEXED = ("readers.ept", "readers.copc")

# The dimensions written, and the PLY types they are written as; the cloud's
# others are not wanted, and some (64-bit integers) a PLY cannot hold at all.
COLOURS = ("Red", "Green", "Blue")
CLASSIFICATION = "Classification"
PLY_TYPES = {"float64": "<f8", "uint16": "<u2", "uint8": "u1"}


def program():
    """The 'pdal' to run: 'PC_PDAL', the image's, or the one on PATH."""
    found = os.environ.get("PC_PDAL") or (DEFAULT_PDAL if os.path.exists(DEFAULT_PDAL) else shutil.which("pdal"))
    if not found:
        raise ValueError(
            "there is no PDAL here: this part type runs in the image its package names, which carries it "
            "(set PC_PDAL to run it elsewhere)"
        )
    return found


def environment(pdal):
    """The environment to run 'pdal' in: its conda environment's plugins and data, which an activation would set."""
    env = dict(os.environ)
    prefix = os.path.dirname(os.path.dirname(os.path.realpath(pdal)))
    for name, relative in (("PDAL_DRIVER_PATH", "lib"), ("PROJ_DATA", "share/proj"), ("GDAL_DATA", "share/gdal")):
        candidate = os.path.join(prefix, relative)
        if name not in env and os.path.isdir(candidate):
            env[name] = candidate
    return env


def call(pdal, arguments, doing):
    """Run 'pdal' with 'arguments' and return what it printed; ValueError, in PDAL's words, when it fails."""
    try:
        done = subprocess.run(
            [pdal] + list(arguments),
            env=environment(pdal),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as e:
        raise ValueError("PDAL could not be run to %s: %s" % (doing, e))
    if done.returncode != 0:
        said = [line for line in (done.stderr or done.stdout or "").strip().splitlines() if line.strip()]
        raise ValueError("PDAL could not %s: %s" % (doing, said[-1] if said else "exit %d" % done.returncode))
    return done.stdout


def remote(source):
    return "://" in str(source)


def reader_type(source, parameters):
    """The PDAL reader 'source' is read with: the part's 'reader', the one its name says, or None for PDAL's guess."""
    named = parameters.get("reader")
    if named:
        named = str(named).strip()
        return named if named.startswith("readers.") else "readers." + named
    lower = str(source).lower().split("?")[0]
    if lower.endswith("ept.json"):
        return "readers.ept"
    if lower.endswith(".copc.laz"):
        return "readers.copc"
    return None


def bounds_of(value):
    """'bounds' as [west, south, east, north], or None."""
    if value in (None, "", []):
        return None
    try:
        values = [float(v) for v in (value.replace(",", " ").split() if isinstance(value, str) else value)]
    except (TypeError, ValueError):
        values = []
    if len(values) != 4 or not (values[0] < values[2] and values[1] < values[3]):
        raise ValueError("'bounds' is 'west south east north', west before east and south before north")
    return values


def pdal_bounds(bounds):
    west, south, east, north = bounds
    return "([%r, %r], [%r, %r])" % (west, east, south, north)


def classes_of(value):
    if value in (None, "", []):
        return None
    if isinstance(value, (int, float)):
        return [int(value)]
    if isinstance(value, str):
        return [int(v) for v in value.replace(",", " ").split()]
    return [int(v) for v in value]


def schema(pdal, source, reader):
    """The names of the dimensions 'source' has, as PDAL reads it, without reading its points."""
    arguments = ["info", "--schema"] + (["--driver", reader] if reader else []) + [source]
    said = call(pdal, arguments, "read the schema of %s" % shown(source))
    try:
        dimensions = json.loads(said)["schema"]["dimensions"]
        return [str(dimension["name"]) for dimension in dimensions]
    except (ValueError, KeyError, TypeError):
        raise ValueError("PDAL said nothing about the dimensions of %s" % shown(source))


def count(pdal, source, reader):
    """How many points 'source' holds, where its header says so without reading them; None otherwise."""
    arguments = ["info", "--summary"] + (["--driver", reader] if reader else []) + [source]
    try:
        return int(json.loads(call(pdal, arguments, "count"))["summary"]["num_points"])
    except (ValueError, KeyError, TypeError):
        return None


def shown(source):
    return os.path.basename(str(source).split("?")[0].rstrip("/")) or str(source)


def pipeline(source, reader, dimensions, parameters, output, points=None, limit=None):
    """The PDAL pipeline that reads 'source' as the part asks and writes it to 'output' as a binary PLY."""
    stage = {"filename": source}
    if reader:
        stage["type"] = reader
    stages = [stage]
    bounds = bounds_of(parameters.get("bounds"))
    resolution = parameters.get("resolution")
    if resolution not in (None, ""):
        resolution = float(resolution)
        if not resolution > 0.0:
            raise ValueError("'resolution' is a spacing larger than nothing, not %r" % parameters.get("resolution"))
        if reader not in INDEXED:
            raise ValueError("'resolution' is for an EPT or a COPC source, which are read at one, and this is neither")
        stage["resolution"] = resolution
    if bounds is not None:
        if reader in INDEXED:
            stage["bounds"] = pdal_bounds(bounds)
        else:
            stages.append({"type": "filters.crop", "bounds": pdal_bounds(bounds)})
    # PDAL's dimension names are its own whatever case a format spells them in
    # ('x' in a PCD is X), and are compared here the way PDAL compares them.
    has = {str(name).lower() for name in dimensions}
    classes = classes_of(parameters.get("classes"))
    if classes is not None and CLASSIFICATION.lower() in has:
        limits = ",".join("%s[%d:%d]" % (CLASSIFICATION, c, c) for c in classes)
        stages.append({"type": "filters.range", "limits": limits})
    # Thinned as it is read where the header says how many there are, and no
    # filter above drops an unknown share of them: 'part_pointcloud' thins
    # whatever is left the same way, but only once it is all in memory.
    whole = classes is None and bounds is None and resolution in (None, "")
    if points and limit and points > limit and whole:
        stages.append({"type": "filters.decimation", "step": int(math.ceil(points / float(limit)))})
    written = ["X=float64", "Y=float64", "Z=float64"]
    if all(colour.lower() in has for colour in COLOURS):
        written += ["%s=uint16" % colour for colour in COLOURS]
    if CLASSIFICATION.lower() in has:
        written.append("%s=uint8" % CLASSIFICATION)
    stages.append(
        {"type": "writers.ply", "filename": output, "storage_mode": "little endian", "dims": ",".join(written)}
    )
    return {"pipeline": stages}


def read_ply(path):
    """'(columns, count)' of the binary little-endian PLY 'pipeline' had PDAL write: each column by its name."""
    import numpy

    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("PDAL wrote no PLY")
        properties, vertices = [], 0
        while True:
            line = f.readline()
            if not line:
                raise ValueError("PDAL wrote a PLY with no 'end_header'")
            words = line.decode("ascii", "replace").split()
            if not words:
                continue
            if words[0] == "end_header":
                break
            if words[0] == "format" and words[1] != "binary_little_endian":
                raise ValueError("PDAL wrote a PLY in '%s', and was asked for little endian" % words[1])
            if words[0] == "element" and words[1] == "vertex":
                vertices = int(words[2])
            elif words[0] == "property":
                if words[1] not in PLY_TYPES:
                    raise ValueError("PDAL wrote a '%s' it was not asked for" % words[1])
                properties.append((words[2], PLY_TYPES[words[1]]))
        dtype = numpy.dtype(properties)
        data = numpy.frombuffer(f.read(vertices * dtype.itemsize), dtype=dtype, count=vertices)
    return {name.lower(): data[name] for name, _ in properties}, vertices


def cloud_of(columns, reader_said):
    """The 'part_pointcloud.Cloud' of the columns 'read_ply' read."""
    import numpy
    import part_pointcloud

    xyz = numpy.column_stack([columns["x"], columns["y"], columns["z"]]).astype(float)
    rgb = None
    if all(colour.lower() in columns for colour in COLOURS):
        rgb = numpy.column_stack([columns[colour.lower()] for colour in COLOURS]).astype(float)
        # 16-bit as PDAL holds them, unless the format's were 8-bit (a PCD's, a PTX's).
        rgb = rgb / 257.0 if rgb.size and rgb.max() > 255.0 else rgb
        if not rgb.any():
            rgb = None
    classes = columns[CLASSIFICATION.lower()].astype(int) if CLASSIFICATION.lower() in columns else None
    return part_pointcloud.Cloud(xyz, rgb, classes, what=reader_said)


def read(source, parameters):
    """The cloud the part asks for out of 'source' (a path or a URL), read by PDAL."""
    import part_pointcloud

    pdal = program()
    reader = reader_type(source, parameters)
    if remote(source) and parameters.get("bounds") in (None, "", []) and parameters.get("resolution") in (None, ""):
        raise ValueError(
            "a remote cloud is read in 'bounds', at 'resolution', or both: read whole, it is the whole survey"
        )
    dimensions = schema(pdal, source, reader)
    for axis in ("X", "Y", "Z"):
        if axis.lower() not in {str(name).lower() for name in dimensions}:
            raise ValueError("PDAL reads no %s in it" % axis)
    limit = int(float(parameters.get("maxPoints") or part_pointcloud.DEFAULT_MAX_POINTS))
    points = count(pdal, source, reader)
    scratch = tempfile.mkdtemp(prefix="pc-pdal-")
    try:
        output = os.path.join(scratch, "cloud.ply")
        pipe = os.path.join(scratch, "pipeline.json")
        with open(pipe, "w") as f:
            json.dump(pipeline(source, reader, dimensions, parameters, output, points, limit), f)
        call(pdal, ["pipeline", pipe], "read %s" % shown(source))
        columns, _ = read_ply(output)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return cloud_of(columns, "PDAL, %s" % (reader or "the reader its name says"))


def run(request):
    """The part 'request' asks for, as the 'output' PartCAD's 'wrapper_part_type' reads."""
    import part_pointcloud

    parameters = dict(request.get("parameters") or {})
    source = request.get("path") or parameters.get("source")
    if not request.get("path") and not (source and remote(source)):
        # A file of the package's own is a 'scan' part: it is the file that
        # is sent to the container, and what the part is keyed on.
        return {"exception": "a 'stream' part names its cloud in 'source', as a URL; a file is a 'scan' part"}
    request = dict(request, path=str(source))
    # 'part_pointcloud.run' reads its file by the extension; here PDAL reads
    # it, by its own reader, and what it reads is handed over instead.
    # Put back afterwards, so that nothing else in the process reads by PDAL.
    builtin = part_pointcloud.read
    part_pointcloud.read = lambda path: read(path, parameters)
    try:
        return part_pointcloud.run(request)
    finally:
        part_pointcloud.read = builtin
