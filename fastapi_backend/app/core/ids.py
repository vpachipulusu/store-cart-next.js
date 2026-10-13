from cuid2 import Cuid

_generator = Cuid()


def new_id() -> str:
    """The one place primary keys are generated (cuid2, 24 characters).

    Existing Prisma ids (cuid) are plain strings and are copied across unchanged.
    """
    return _generator.generate()
