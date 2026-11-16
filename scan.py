#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'scan' and 'stream' part types: a point cloud PDAL reads, as a solid.

This runs in the image the types name ('container:' in partcad.yaml), which
carries PDAL and the code that reads with it (image/lib, installed at
/opt/partcad-scan-pdal): this script only hands the request over, so that what
reads a cloud is the image, and a part is keyed on the image's tag.

'PC_SCAN_PDAL_LIBRARY' names another copy of that code, for running it outside
the image (the tests do).
"""

import os
import sys

CACHE_VERSION = 1

LIBRARY = os.environ.get("PC_SCAN_PDAL_LIBRARY") or "/opt/partcad-scan-pdal"

if __name__ == "__partcad_part__":
    if not os.path.isfile(os.path.join(LIBRARY, "pdal_cloud.py")):
        output = {
            "exception": "%s holds no PDAL reader: this part type runs in the image its package names "
            "(partcad-scan-pdal), and this is not it" % LIBRARY
        }
    else:
        sys.path.insert(0, LIBRARY)
        import pdal_cloud

        output = pdal_cloud.run(request)  # noqa: F821
