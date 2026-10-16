import pytest
from sqlalchemy.engine import make_url

from tests._worker_db import worker_database_url

BASE = "postgresql+asyncpg://postgres:s3cret@localhost:5433/storecart_test"


def test_worker_gets_its_own_database_with_the_test_suffix() -> None:
    url = worker_database_url(BASE, "gw3")

    assert url.database == "storecart_gw3_test"


def test_driver_credentials_host_and_port_are_kept() -> None:
    url = worker_database_url(BASE, "gw0")

    assert (url.drivername, url.username, url.password) == (
        "postgresql+asyncpg",
        "postgres",
        "s3cret",
    )
    assert (url.host, url.port) == ("localhost", 5433)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_local_hosts_are_accepted(host: str) -> None:
    base = make_url(BASE).set(host=host)

    assert worker_database_url(base.render_as_string(False), "gw1").host == host


def test_two_workers_never_share_a_database() -> None:
    assert worker_database_url(BASE, "gw0").database != (
        worker_database_url(BASE, "gw1").database
    )


def test_rejects_a_database_not_ending_in_test() -> None:
    with pytest.raises(ValueError, match="_test"):
        worker_database_url(BASE.replace("storecart_test", "storecart"), "gw0")


def test_rejects_a_remote_host() -> None:
    with pytest.raises(ValueError, match="local"):
        worker_database_url(BASE.replace("localhost", "db.example.com"), "gw0")
