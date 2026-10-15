from sqlalchemy.exc import OperationalError

from app.core.db_errors import DATABASE_UNAVAILABLE_ERRORS, root_cause_name


def test_root_cause_name_of_an_unchained_error_is_its_own_type() -> None:
    assert root_cause_name(TimeoutError()) == "TimeoutError"


def test_root_cause_name_follows_the_cause_chain_to_the_driver_error() -> None:
    driver = ConnectionRefusedError(111, "refused")
    middle = RuntimeError("adapter")
    middle.__cause__ = driver
    outer = OperationalError("SELECT 1", {}, middle)
    outer.__cause__ = middle

    assert root_cause_name(outer) == "ConnectionRefusedError"


def test_root_cause_name_stops_on_a_cause_cycle() -> None:
    first = ValueError("a")
    second = KeyError("b")
    first.__cause__ = second
    second.__cause__ = first

    assert root_cause_name(first) in {"ValueError", "KeyError"}


def test_unavailable_errors_cover_connect_failures() -> None:
    assert issubclass(ConnectionRefusedError, DATABASE_UNAVAILABLE_ERRORS)
    assert issubclass(TimeoutError, DATABASE_UNAVAILABLE_ERRORS)
    assert not issubclass(RuntimeError, DATABASE_UNAVAILABLE_ERRORS)
