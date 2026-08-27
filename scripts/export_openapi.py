#!/usr/bin/env python3
"""Export the OpenAPI schema JSON from the FastAPI backend application."""

import json
import os
import sys

# Add user site-packages explicitly for Debian/Ubuntu environments
user_site = os.path.expanduser("~/.local/lib/python3.11/site-packages")
if os.path.exists(user_site) and user_site not in sys.path:
    sys.path.insert(0, user_site)

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(root_dir, "backend", "src"))

from app.main import create_app


def export_openapi(output_path: str) -> None:
    app = create_app()
    openapi_schema = app.openapi()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(openapi_schema, f, indent=2)

    print(f"Exported OpenAPI schema to {output_path}")


if __name__ == "__main__":
    output_file = (
        sys.argv[1]
        if len(sys.argv) > 1
        else os.path.join(root_dir, "data", "openapi.json")
    )
    export_openapi(output_file)
