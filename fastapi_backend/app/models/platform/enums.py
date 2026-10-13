import enum

from sqlalchemy import CheckConstraint, Enum

ENUM_LENGTH = 16


def enum_column(enum_class: type[enum.Enum]) -> Enum:
    """Store an enum as short text. Pair it with `enum_check` in `__table_args__`."""
    return Enum(
        enum_class, native_enum=False, create_constraint=False, length=ENUM_LENGTH
    )


def enum_check(column: str, enum_class: type[enum.Enum]) -> CheckConstraint:
    """Database CHECK that only the enum's names are stored (named `ck_<table>_<column>_valid`)."""
    allowed = ", ".join(f"'{member.name}'" for member in enum_class)
    return CheckConstraint(f"{column} IN ({allowed})", name=f"{column}_valid")
