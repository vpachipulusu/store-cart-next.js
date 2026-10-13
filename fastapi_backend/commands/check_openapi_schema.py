"""Pre-commit check: is nextjs-frontend/openapi.json up to date with the backend?

Regenerates the OpenAPI schema into a temporary file and compares it with the
committed copy. Exits 1 (with a hint) when they differ.

TODO(KAN-33): the frontend has no committed openapi.json / generated TypeScript
client yet. Until KAN-33 adds them, this check is a placeholder that passes when
the committed schema file does not exist. Once KAN-33 lands, also run the
frontend client generator here (see the vintasoftware template's
`generate-frontend-client` hook).
"""

import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCHEMA_FILE = BACKEND_DIR.parent / "nextjs-frontend" / "openapi.json"

# Importing the app requires these settings (app/core/config.py). Schema generation
# never connects to the database or signs tokens, so harmless placeholders are
# enough; values already set in the environment still take precedence.
PLACEHOLDER_SETTINGS = {
    "DATABASE_URL": "postgresql+asyncpg://openapi:openapi@localhost:5432/openapi",
    "CORS_ORIGINS": "[]",
}


def main() -> int:
    if not SCHEMA_FILE.exists():
        print(
            f"openapi-schema-check: {SCHEMA_FILE.name} not found in nextjs-frontend/; "
            "skipping (placeholder until KAN-33 adds the generated client)."
        )
        return 0

    for key, value in PLACEHOLDER_SETTINGS.items():
        os.environ.setdefault(key, value)

    from commands import generate_openapi_schema as generator

    generate_openapi_schema: Callable[[Path], None] = generator.generate_openapi_schema

    with tempfile.TemporaryDirectory() as tmp_dir:
        fresh_file = Path(tmp_dir) / "openapi.json"
        generate_openapi_schema(fresh_file)
        fresh = json.loads(fresh_file.read_text())

    committed = json.loads(SCHEMA_FILE.read_text())
    if fresh != committed:
        print(
            "openapi-schema-check: nextjs-frontend/openapi.json is out of date.\n"
            "Regenerate it from fastapi_backend/ with:\n"
            "  OPENAPI_OUTPUT_FILE=../nextjs-frontend/openapi.json "
            "uv run python -m commands.generate_openapi_schema"
        )
        return 1

    print("openapi-schema-check: nextjs-frontend/openapi.json is up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
