import json
from pathlib import Path

import pytest

from commands import check_openapi_schema, generate_openapi_schema

SCHEMA = {"openapi": "3.1.0", "paths": {}}


@pytest.fixture
def schema_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "openapi.json"
    monkeypatch.setattr(check_openapi_schema, "SCHEMA_FILE", path)
    return path


def fake_generator(schema: dict[str, object]):
    def generate(output_file: Path) -> None:
        output_file.write_text(json.dumps(schema))

    return generate


def test_passes_when_the_committed_schema_does_not_exist(
    schema_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_openapi_schema.main() == 0
    assert "skipping" in capsys.readouterr().out


def test_passes_when_the_committed_schema_is_current(
    schema_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema_file.write_text(json.dumps(SCHEMA))
    monkeypatch.setattr(
        generate_openapi_schema, "generate_openapi_schema", fake_generator(SCHEMA)
    )

    assert check_openapi_schema.main() == 0


def test_fails_when_the_committed_schema_is_stale(
    schema_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    schema_file.write_text(json.dumps({"openapi": "3.0.0", "paths": {}}))
    monkeypatch.setattr(
        generate_openapi_schema, "generate_openapi_schema", fake_generator(SCHEMA)
    )

    assert check_openapi_schema.main() == 1
    assert "out of date" in capsys.readouterr().out
