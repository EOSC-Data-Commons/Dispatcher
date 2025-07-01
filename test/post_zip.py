#!/usr/bin/env python3

import io
import zipfile
import requests
import sys

zip_buffer = io.BytesIO()

with open(sys.argv[2]) as pl:
    payload = pl.read()

with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zfile:
    zfile.writestr("ro-crate-metadata.json", payload)
    for fn in sys.argv[3:]:
        with open(fn) as f:
            data = f.read()
            zfile.writestr(fn,data)


zip_buffer.seek(0)

files = {"zipfile": ("files.zip", zip_buffer, "application/zip")}

try:
    api_path = sys.argv[1]
    response = requests.post(api_path, files=files)
    print("Server response:", response.text)
except IndexError:
    print("You did not specify API endpoint")
