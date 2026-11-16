# partcad-scan-pdal

Point clouds in every format [PDAL](https://pdal.io) reads, as [PartCAD](https://github.com/partcad/partcad)
parts: what a laser scanner, a lidar or a survey measured, made the solid it describes.

PartCAD reads LAS, LAZ, PLY, E57 and text clouds itself (`pointcloud` and `e57`). This package is for the rest:

| | Read from |
|---|---|
| `scan` | a file: Point Cloud Library's `.pcd`, Leica's `.ptx`, `.bpf`, Optech's `.csd`, an SLPK, a Draco cloud, an E57 scan, a local Entwine Point Tiles (`ept.json`) or Cloud Optimized Point Cloud (`.copc.laz`) -- anything PDAL reads |
| `stream` | a URL: a region of an EPT or COPC survey far too large to read whole, read in `bounds`, at `resolution` -- [USGS 3DEP](https://www.usgs.gov/3d-elevation-program) publishes the United States as EPT |

A cloud is made a solid exactly as PartCAD's `pointcloud` makes one, by the same code: a height field of the
points binned on the plan (`as: heightfield`, the default), or the voxels they fall in (`as: voxels`), in their
colours.

## What it needs

A container runtime -- Docker, running -- and nothing else. Both types run in
`ghcr.io/partcad/partcad-scan-pdal`, which carries PDAL (conda-forge's build, with its E57 and Draco plugins),
OCP, and the reader; PartCAD pulls it the first time a part needs it. A machine with no container runtime cannot
build these parts, and says so, naming the image.

Requires PartCAD 0.10.24 or later, the first to run a part type in a `container:`.

## Using it

```yaml
dependencies:
  pdal:
    type: git
    url: https://github.com/partcad/partcad-scan-pdal

parts:
  workshop:
    type: pdal:scan
    path: scans/workshop.ptx
    parameters:
      as: voxels
      cell: 50          # mm a side
  site:
    type: pdal:stream
    parameters:
      source: https://s3-us-west-2.amazonaws.com/usgs-lidar-public/CA_SanFrancisco_1_B23/ept.json
      # West south east north, in the survey's reference system: USGS's is
      # Web Mercator (EPSG:3857), in metres. 500 m of San Francisco.
      bounds: "-13627000 4547000 -13626500 4547500"
      resolution: 1     # in its units: a point a metre
      classes: 2        # the ground
```

## Parameters

Everything PartCAD's `pointcloud` takes -- `as`, `cell`, `statistic`, `classes`, `unit`, `origin`, `base`,
`exaggeration`, `minPoints`, `maxPoints`, `maxBoxes`, `maxPoles`: see "Height maps, point clouds and voxels" in
PartCAD's part documentation -- and:

| | |
|---|---|
| `reader` | the PDAL reader, where its guess from the file's name is not the one wanted: `readers.text`, or `text` |
| `bounds` | `west south east north`, in the cloud's reference system: the part of it read. EPT and COPC read only that; any other format is read and cropped |
| `resolution` | EPT and COPC only: the spacing of the points read, in the cloud's units |
| `source` | `stream` only: the cloud's URL. Read in `bounds`, at `resolution`, or both -- never whole |

`classes` is applied by PDAL as it reads, where the cloud is classified, so that a survey's ground is all that is
written. `maxPoints` is applied as it reads too, where the header says how many points there are and nothing else
drops some.

## How it works

`scan.py`, the script both types name, hands the request to the reader the image installed at
`/opt/partcad-scan-pdal` (`image/lib`). The reader asks PDAL's command line for the cloud's dimensions, then has it
translate the cloud -- with any `bounds`, `resolution`, `classes` and thinning -- into a binary PLY of X, Y, Z,
colour and classification, and hands the points to `part_pointcloud`: a copy of PartCAD's own, beside it.

The copies of PartCAD's `part_pointcloud.py`, `heightfield.py` and `voxel_solid.py` are kept by
`image/sync-partcad.sh`, which records where they came from in `image/lib/PARTCAD.sha256`; a test fails when a copy
differs from what was copied. They are in the image rather than taken from the PartCAD that runs the part, because a
part is cached against the image's tag: whatever builds it has to be in the image.

## Developing

```bash
pip install pytest "build123d==0.11.1" "cadquery-ocp-novtk==7.9.3.1.1"
pip install --no-deps "partcad @ git+https://github.com/partcad/partcad@devel"   # its wrappers, for 'ocp_serialize'
pytest                                                                           # with a stand-in PDAL

docker build -t ghcr.io/partcad/partcad-scan-pdal:$(cat VERSION) image          # the image, tagged as partcad.yaml names it
docker run --rm --user root -v "$PWD:/src" -w /src ghcr.io/partcad/partcad-scan-pdal:$(cat VERSION) \
  sh -c 'pip install pytest && pip install --no-deps "partcad @ git+https://github.com/partcad/partcad@devel" && python3 -m pytest'
pc info :sample                                                                  # built by PartCAD, in that image
```

The tests in `tests/test_live.py` run only where the real PDAL is -- in the image -- and write every cloud they read
with PDAL itself.

**A change to the image is a new `VERSION`**, and the same tag in `partcad.yaml` (a test holds the two together).
CI publishes the image for amd64 and arm64 when `main` moves to a version that is not published yet, and never
rebuilds a published one: parts are cached against the tag, so a rebuilt tag is a change nobody's cache notices.

## License

Apache 2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE).
