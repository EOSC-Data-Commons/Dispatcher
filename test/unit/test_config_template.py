"""Config-template drift guard.

The deployed ``app/config.py`` is rendered from
``ansible/templates/config.py.j2`` — a setting that exists on the repo's
Settings class but not in the template becomes an AttributeError at
startup *on the server only* (bit us with ``reap_failure_threshold``:
every local test passed, the deployed app could not boot). This test
fails the moment the two drift apart.
"""

import re
from pathlib import Path

from app.config import Settings

_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "ansible" / "templates" / "config.py.j2"
)


def test_template_declares_every_setting():
    template = _TEMPLATE.read_text()
    declared = set(re.findall(r"^    ([a-z_]+):", template, re.MULTILINE))
    assert declared == set(Settings.model_fields), (
        "ansible config template and app/config.py drifted — missing: "
        f"{set(Settings.model_fields) - declared}, extra: {declared - set(Settings.model_fields)}"
    )
