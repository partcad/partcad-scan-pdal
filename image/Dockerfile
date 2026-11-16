# The image the 'scan' and 'stream' part types run in: PartCAD's Python base,
# with OCP (which a part type hands its shapes back in), PDAL, and the code that
# reads with it.
#
# Built FROM PartCAD's own base image, as PartCAD's part type documentation asks
# of an image a 'container:' names ("What the image needs"): it carries the
# Python and the JSON-RPC service PartCAD runs commands through, and its
# 'verify.py' checks that contract at the end of this build.
#
#   docker build -f image/Dockerfile -t partcad-scan-pdal image
#
# A new image is a new tag (VERSION), never a new build under an old one: a
# part is cached against the tag it was built with.

# The PartCAD release whose base image this is built on, and the Python in it.
ARG PARTCAD_VERSION=0.10.26
ARG PYTHON_VERSION=3.12
# Set by BuildKit to the architecture being built ('amd64', 'arm64'): PartCAD
# publishes its base image per architecture.
ARG TARGETARCH

# PDAL is not in Debian's current release, and PyPI has no build of it, so it
# comes from conda-forge -- into an environment of its own, at /opt/pdal, beside
# the image's Python rather than in it: the script runs on that Python (with
# OCP), and starts PDAL's command line.
#
# 'libpdal-core' is PDAL with the readers built into it -- PCD, PTX, BPF, text,
# LAS and LAZ, COPC and EPT (local and over HTTP), SLPK and I3S, and every
# raster GDAL reads -- and two plugins are added for the scanners' formats:
# E57 and Draco. conda-forge builds more (Arrow, HDF, TileDB, NITF), each a
# 'libpdal-<name>' to add here; they are left out because each is a library
# of its own, and 'libpdal', which has them all, is several times the size.
FROM mambaorg/micromamba:2.10.0-debian13-slim AS pdal
ARG PDAL_VERSION=2.10.2
USER root
RUN micromamba create --yes --prefix /opt/pdal --channel conda-forge --override-channels \
      "libpdal-core=${PDAL_VERSION}" "libpdal-e57=${PDAL_VERSION}" "libpdal-draco=${PDAL_VERSION}" \
  && micromamba clean --all --yes \
  && rm -rf /opt/pdal/include \
  && PDAL_DRIVER_PATH=/opt/pdal/lib /opt/pdal/bin/pdal --version


FROM ghcr.io/partcad/partcad-container-python:${PARTCAD_VERSION}-py${PYTHON_VERSION}-${TARGETARCH}
ARG PARTCAD_VERSION
ARG PDAL_VERSION=2.10.2

USER root

# OCP at the version PartCAD's sandboxes have it (sandbox_versions.BUILD123D
# and .OCP), which brings numpy and scipy, which the height field fills its
# empty cells with.
RUN pip install --no-cache-dir "build123d==0.11.1" "cadquery-ocp-novtk==7.9.3.1.1"

COPY --from=pdal /opt/pdal /opt/pdal
# What an activation of that environment would set: where its plugins and its
# reference systems are. 'pdal_cloud' sets them too, for a PDAL found elsewhere.
ENV PDAL_DRIVER_PATH=/opt/pdal/lib \
    PROJ_DATA=/opt/pdal/share/proj \
    GDAL_DATA=/opt/pdal/share/gdal \
    PC_PDAL=/opt/pdal/bin/pdal

COPY lib/ /opt/partcad-scan-pdal/
# The readers this image is for, asked for by name: a PDAL build that moved one
# of them into a plugin is a build that fails here rather than a part that
# fails in a user's container.
RUN python3 -c "import sys; sys.path.insert(0, '/opt/partcad-scan-pdal'); import pdal_cloud, part_pointcloud, heightfield, voxel_solid; import OCP, scipy" \
  && /opt/pdal/bin/pdal --drivers > /tmp/drivers.txt \
  && for reader in pcd ptx bpf text las copc ept slpk e57 draco; do \
       grep -q "readers\.${reader}\b" /tmp/drivers.txt || { echo "PDAL has no readers.${reader}"; exit 1; }; \
     done \
  && rm /tmp/drivers.txt \
  && python3 /pc/verify.py

LABEL partcad.image="1"
LABEL partcad.partcad="${PARTCAD_VERSION}"
LABEL partcad.pdal="${PDAL_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/partcad/partcad-scan-pdal"
LABEL org.opencontainers.image.description="PDAL for PartCAD's 'scan' and 'stream' part types"
LABEL org.opencontainers.image.licenses="Apache-2.0"

USER pc
