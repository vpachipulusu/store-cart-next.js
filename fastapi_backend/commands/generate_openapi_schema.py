import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.main import app

load_dotenv()

OUTPUT_FILE = os.getenv("OPENAPI_OUTPUT_FILE")


def generate_openapi_schema(output_file: str | Path) -> None:
    schema = app.openapi()
    output_path = Path(output_file)

    updated_schema = remove_operation_id_tag(schema)

    output_path.write_text(json.dumps(updated_schema, indent=2))
    print(f"OpenAPI schema saved to {output_file}")


def remove_operation_id_tag(schema: dict[str, Any]) -> dict[str, Any]:
    """
    Removes the tag prefix from the operation IDs in the OpenAPI schema.

    This cleans up the OpenAPI operation IDs that are used by the frontend
    client generator to create the names of the functions. The modified
    schema is then returned.
    """
    for path_data in schema["paths"].values():
        for operation in path_data.values():
            tag = operation["tags"][0]
            operation_id = operation["operationId"]
            to_remove = f"{tag}-"
            new_operation_id = operation_id[len(to_remove) :]
            operation["operationId"] = new_operation_id
    return schema


if __name__ == "__main__":
    if OUTPUT_FILE is None:
        raise SystemExit("Set OPENAPI_OUTPUT_FILE to the schema output path.")
    generate_openapi_schema(OUTPUT_FILE)
