from app.core.ids import new_id


def test_new_id_is_a_lowercase_alphanumeric_string():
    value = new_id()

    assert isinstance(value, str)
    assert value.isalnum()
    assert value == value.lower()


def test_new_id_is_unique_across_many_calls():
    values = {new_id() for _ in range(1000)}

    assert len(values) == 1000
