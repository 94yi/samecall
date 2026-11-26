import json
from pathlib import Path
import tempfile

from binding import METHOD
from check_route import check
from service import DeskV2

with tempfile.TemporaryDirectory() as root:
    print(json.dumps(dict(method=METHOD, **check(DeskV2, METHOD, Path(root)))))
