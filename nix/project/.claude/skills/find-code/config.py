"""Read addon locations from the generated public project configuration."""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETTINGS = json.loads((PROJECT_ROOT / ".nixodoo/config.json").read_text())
ADDON_DIRECTORIES = ["src/odoo/addons", "src/odoo/odoo/addons"] + [
    f"src/{repo['name']}" for repo in SETTINGS["repositories"]["addons"]
]
OUTPUT_DIRECTORY = ".odoo_inspect"
