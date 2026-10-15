from collections import Counter

from app.main import create_app


def test_every_operation_id_is_unique():
    """A duplicate id makes the generated client silently drop one of the operations."""
    schema = create_app().openapi()
    ids = [
        operation["operationId"]
        for path in schema["paths"].values()
        for operation in path.values()
    ]

    duplicated = [name for name, count in Counter(ids).items() if count > 1]

    assert duplicated == []
