"""Categories, product-category links and product images of the store schema (KAN-71).

Migrates a throwaway store database through ``migrate_store`` (so the real store tree runs)
and exercises the constraints with plain SQL. Skipped when ``TEST_DATABASE_URL`` is unset.
"""

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app.core.ids import new_id
from app.services.media_uploads import ALLOWED_IMAGE_TYPES, MediaUploadService
from app.services.store_migrations import (
    STORE_SCRIPT_LOCATION,
    _alembic_config,
    migrate_store,
)
from tests.pg_scaffold import TEST_DATABASE_URL, url_for
from tests.services.test_store_catalogue_schema_e2e import (
    World,
    assert_rejected,
    insert,
    product,
    violated_constraint,
    violates,
)
from tests.services.test_store_migrations_e2e import (  # noqa: F401  (fixtures)
    baseline,
    server,
    world,
)

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set"
)

HEAD = ScriptDirectory.from_config(
    _alembic_config(STORE_SCRIPT_LOCATION)
).get_current_head()
NEW_TABLES = {"categories", "product_categories", "product_images"}
LINK = text("INSERT INTO product_categories (product_id, category_id) VALUES (:p, :c)")


@pytest.fixture
async def conn(world: World) -> AsyncIterator[AsyncConnection]:  # noqa: F811
    database = await world.store_database("cat2")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


async def category(
    conn: AsyncConnection,
    slug: str,
    parent_id: str | None = None,
    **extra: object,
) -> str:
    return await insert(
        conn,
        "categories",
        {
            "id": new_id(),
            "name": slug.title(),
            "slug": slug,
            "parent_id": parent_id,
            **extra,
        },
    )


async def image(
    conn: AsyncConnection,
    product_id: str,
    position: int,
    key: str | None = None,
    **extra: object,
) -> str:
    image_id = new_id()
    return await insert(
        conn,
        "product_images",
        {
            "id": image_id,
            "product_id": product_id,
            "storage_key": f"stores/s1/{image_id}.png" if key is None else key,
            "position": position,
            **extra,
        },
    )


async def scalar(conn: AsyncConnection, sql: str, **params: object) -> object:
    return (await conn.execute(text(sql), params)).scalar_one()


async def test_migration_creates_the_new_tables(conn: AsyncConnection):
    rows = await conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
    )

    assert NEW_TABLES <= {row[0] for row in rows}


async def test_categories_nest_to_any_depth_and_default_position_to_zero(
    conn: AsyncConnection,
):
    root = await category(conn, "clothing")
    child = await category(conn, "shirts", root)
    grandchild = await category(conn, "tees", child)

    rows = (
        await conn.execute(text("SELECT id, parent_id, position FROM categories"))
    ).all()

    assert {row[0]: (row[1], row[2]) for row in rows} == {
        root: (None, 0),
        child: (root, 0),
        grandchild: (child, 0),
    }


async def test_siblings_are_returned_in_position_order(conn: AsyncConnection):
    root = await category(conn, "root")
    await category(conn, "c", root, position=2)
    await category(conn, "a", root, position=0)
    await category(conn, "b", root, position=1)

    slugs = (
        (
            await conn.execute(
                text(
                    "SELECT slug FROM categories WHERE parent_id = :p "
                    "ORDER BY position, id"
                ),
                {"p": root},
            )
        )
        .scalars()
        .all()
    )

    assert slugs == ["a", "b", "c"]


async def test_category_requires_an_existing_parent(conn: AsyncConnection):
    async with violates(conn, "fk_categories_parent"):
        await category(conn, "orphan", "missing")


async def test_category_cannot_be_its_own_parent(conn: AsyncConnection):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO categories (id, name, slug, parent_id) "
            "VALUES ('self', 'S', 's', 'self')"
        ),
        "ck_categories_not_own_parent",
    )


async def test_deleting_a_category_with_children_is_rejected(conn: AsyncConnection):
    root = await category(conn, "root")
    await category(conn, "kid", root)

    async with violates(conn, "fk_categories_parent"):
        await conn.execute(text("DELETE FROM categories WHERE id = :i"), {"i": root})

    assert await scalar(conn, "SELECT count(*) FROM categories") == 2


async def test_a_whole_subtree_can_be_deleted_in_one_statement(conn: AsyncConnection):
    root = await category(conn, "root")
    child = await category(conn, "kid", root)
    await category(conn, "grandkid", child)

    await conn.execute(text("DELETE FROM categories"))

    assert await scalar(conn, "SELECT count(*) FROM categories") == 0


async def test_a_leaf_category_can_be_deleted(conn: AsyncConnection):
    root = await category(conn, "root")
    leaf = await category(conn, "leaf", root)

    await conn.execute(text("DELETE FROM categories WHERE id = :i"), {"i": leaf})

    assert await scalar(conn, "SELECT count(*) FROM categories") == 1


async def test_category_slug_is_unique_per_store(conn: AsyncConnection):
    await category(conn, "shirts")

    await assert_rejected(
        conn,
        text("INSERT INTO categories (id, name, slug) VALUES ('y', 'S', 'shirts')"),
        "uq_categories_slug",
    )


@pytest.mark.parametrize(
    "slug", ["Tee", "a b", "-a", "a-", "a--b", "", "a_b", "abc\n", "x" * 201]
)
async def test_bad_category_slug_is_rejected(conn: AsyncConnection, slug: str):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO categories (id, name, slug) VALUES ('z', 'N', :s)"
        ).bindparams(s=slug),
        "ck_categories_slug_format",
    )


@pytest.mark.parametrize("name", ["", "  ", "\t\n", "x" * 256])
async def test_blank_or_oversized_category_name_is_rejected(
    conn: AsyncConnection, name: str
):
    await assert_rejected(
        conn,
        text(
            "INSERT INTO categories (id, name, slug) VALUES ('n', :n, 'ok')"
        ).bindparams(n=name),
        "ck_categories_name",
    )


async def test_negative_category_position_is_rejected(conn: AsyncConnection):
    async with violates(conn, "ck_categories_position"):
        await category(conn, "neg", position=-1)


async def test_a_product_belongs_to_many_categories_once(conn: AsyncConnection):
    pid = await product(conn)
    first, second = await category(conn, "a"), await category(conn, "b")

    await conn.execute(LINK, {"p": pid, "c": first})
    await conn.execute(LINK, {"p": pid, "c": second})

    await assert_rejected(
        conn, LINK.bindparams(p=pid, c=first), "product_categories_pkey"
    )
    assert await scalar(conn, "SELECT count(*) FROM product_categories") == 2


async def test_link_requires_an_existing_product_and_category(conn: AsyncConnection):
    pid = await product(conn)

    await assert_rejected(
        conn, LINK.bindparams(p=pid, c="missing"), "fk_product_categories_category"
    )
    await assert_rejected(
        conn,
        LINK.bindparams(p="missing", c=await category(conn, "a")),
        "fk_product_categories_product",
    )


async def test_deleting_a_product_or_a_category_removes_only_the_links(
    conn: AsyncConnection,
):
    first, second = await product(conn, "p1"), await product(conn, "p2")
    shared, other = await category(conn, "shared"), await category(conn, "other")
    for pid, cid in ((first, shared), (second, shared), (second, other)):
        await conn.execute(LINK, {"p": pid, "c": cid})

    await conn.execute(text("DELETE FROM products WHERE id = :i"), {"i": first})
    assert await scalar(conn, "SELECT count(*) FROM product_categories") == 2

    await conn.execute(text("DELETE FROM categories WHERE id = :i"), {"i": shared})
    assert await scalar(conn, "SELECT count(*) FROM product_categories") == 1
    assert await scalar(conn, "SELECT count(*) FROM products") == 1


async def test_product_images_keep_their_order(conn: AsyncConnection):
    pid = await product(conn)
    third = await image(conn, pid, 2)
    first = await image(conn, pid, 0, alt_text="Front")
    second = await image(conn, pid, 1)

    ordered = (
        (
            await conn.execute(
                text(
                    "SELECT id FROM product_images WHERE product_id = :p "
                    "ORDER BY position"
                ),
                {"p": pid},
            )
        )
        .scalars()
        .all()
    )

    assert ordered == [first, second, third]


async def test_image_positions_are_unique_per_product_but_not_across(
    conn: AsyncConnection,
):
    one, two = await product(conn, "p1"), await product(conn, "p2")
    await image(conn, one, 0)
    await image(conn, two, 0)

    async with violates(conn, "uq_product_images_product_position"):
        await image(conn, one, 0)


async def test_images_can_swap_positions_with_a_temporary_duplicate(
    conn: AsyncConnection,
):
    pid = await product(conn)
    a, b = await image(conn, pid, 0), await image(conn, pid, 1)
    move = text("UPDATE product_images SET position = :n WHERE id = :i")

    # The first statement leaves two images at position 1; only a deferred check allows it.
    await conn.execute(move, {"n": 1, "i": a})
    await conn.execute(move, {"n": 0, "i": b})
    await conn.commit()

    rows = (await conn.execute(text("SELECT id, position FROM product_images"))).all()
    assert {row[0]: row[1] for row in rows} == {a: 1, b: 0}


async def test_a_duplicate_image_position_is_reported_at_commit_not_at_the_statement(
    conn: AsyncConnection,
):
    pid = await product(conn)
    await image(conn, pid, 0)
    await conn.commit()

    await image(conn, pid, 0)  # no error yet
    with pytest.raises(IntegrityError) as caught:
        await conn.commit()
    await conn.rollback()

    assert violated_constraint(caught.value) == "uq_product_images_product_position"


async def test_storage_key_is_unique_across_the_store(conn: AsyncConnection):
    first, second = await product(conn, "p1"), await product(conn, "p2")
    await image(conn, first, 0, key="stores/s1/abc.png")

    async with violates(conn, "uq_product_images_storage_key"):
        await image(conn, second, 0, key="stores/s1/abc.png")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "abc.png",
        "stores/abc.png",
        "stores//abc.png",
        "stores/s1/",
        "stores/s1/a/b.png",
        "stores/s1/../x.png",
        "other/s1/abc.png",
        "stores/s1/abc.png\n",
        "stores/s1/a b.png",
        "https://cdn.example/stores/s1/abc.png",
        "stores/s1/" + "x" * 300 + ".png",
    ],
)
async def test_storage_key_must_be_a_store_scoped_object_key(
    conn: AsyncConnection, key: str
):
    pid = await product(conn)

    async with violates(conn, "ck_product_images_storage_key"):
        await image(conn, pid, 0, key=key)


async def test_images_carry_both_timestamps(conn: AsyncConnection):
    pid = await product(conn)
    iid = await image(conn, pid, 0)

    row = (
        await conn.execute(
            text("SELECT created_at, updated_at FROM product_images WHERE id = :i"),
            {"i": iid},
        )
    ).one()

    assert row[0] is not None and row[1] is not None


@pytest.mark.parametrize(
    "key",
    [
        "stores/s1/a.jpg",
        "stores/s_1-x/a_b-c.webp",
        "stores/s1/" + "x" * 241 + ".png",  # exactly 255 characters
    ],
)
async def test_valid_storage_keys_are_accepted(conn: AsyncConnection, key: str):
    pid = await product(conn)

    await image(conn, pid, 0, key=key)

    assert await scalar(conn, "SELECT count(*) FROM product_images") == 1


@pytest.mark.parametrize("key", ["stores/s1/a.gif", "stores/s1/a.PNG"])
async def test_other_extensions_are_rejected(conn: AsyncConnection, key: str):
    pid = await product(conn)

    async with violates(conn, "ck_product_images_storage_key"):
        await image(conn, pid, 0, key=key)


async def test_boundary_slug_name_and_alt_text_are_accepted(conn: AsyncConnection):
    pid = await product(conn)

    await category(conn, "a-b", name="n" * 255)
    await category(conn, "s" * 200)
    await image(conn, pid, 0, alt_text="a" * 500)

    assert await scalar(conn, "SELECT count(*) FROM categories") == 2


async def test_negative_image_position_is_rejected(conn: AsyncConnection):
    pid = await product(conn)

    async with violates(conn, "ck_product_images_position"):
        await image(conn, pid, -1)


async def test_oversized_alt_text_is_rejected(conn: AsyncConnection):
    pid = await product(conn)

    async with violates(conn, "ck_product_images_alt_text"):
        await image(conn, pid, 0, alt_text="x" * 501)


async def test_image_requires_an_existing_product(conn: AsyncConnection):
    async with violates(conn, "fk_product_images_product"):
        await image(conn, "missing", 0)


async def test_deleting_a_product_removes_its_images(conn: AsyncConnection):
    pid = await product(conn)
    await image(conn, pid, 0)

    await conn.execute(text("DELETE FROM products WHERE id = :p"), {"p": pid})

    assert await scalar(conn, "SELECT count(*) FROM product_images") == 0


async def test_foreign_keys_have_covering_indexes(conn: AsyncConnection):
    rows = await conn.execute(
        text(
            "SELECT indexname, regexp_replace(indexdef, '^.*USING btree ', '') "
            "FROM pg_indexes WHERE schemaname = 'public'"
        )
    )

    definitions = {row[0]: row[1] for row in rows}

    assert definitions["ix_categories_parent_position"] == '(parent_id, "position")'
    assert definitions["ix_product_categories_category_id"] == "(category_id)"


async def test_downgrade_to_0002_drops_only_the_new_tables(conn: AsyncConnection):
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def run(connection: Connection, action: str, target: str) -> None:
        config.attributes["connection"] = connection
        getattr(command, action)(config, target)

    await conn.run_sync(run, "downgrade", "0002")
    gone = [
        await scalar(conn, f"SELECT to_regclass('{name}')")
        for name in sorted(NEW_TABLES)
    ]
    kept = await scalar(conn, "SELECT to_regclass('products')")
    stamped = await scalar(conn, "SELECT version_num FROM store_alembic_version")
    await conn.run_sync(run, "upgrade", "head")
    back = await scalar(conn, "SELECT to_regclass('product_images')")

    assert gone == [None, None, None]
    assert kept is not None
    assert stamped == "0002"
    assert back is not None


async def test_a_store_at_0002_with_data_reaches_0003_through_the_migrate_path(
    world: World,  # noqa: F811
):
    database = await world.store_database("old2")
    store_id = await world.add_store(url_for(database))
    await migrate_store(store_id, world.provider)
    engine = create_async_engine(url_for(database))
    config = _alembic_config(STORE_SCRIPT_LOCATION)

    def downgrade(connection: Connection) -> None:
        config.attributes["connection"] = connection
        command.downgrade(config, "0002")

    try:
        async with engine.begin() as connection:
            await connection.run_sync(downgrade)
            await connection.execute(
                text("INSERT INTO products (id, title, slug) VALUES ('p', 'T', 'tee')")
            )
        assert await world.stamped_revision(database) == "0002"

        await migrate_store(store_id, world.provider)

        async with engine.connect() as connection:
            products = await scalar(connection, "SELECT count(*) FROM products")
            images = await scalar(connection, "SELECT to_regclass('product_images')")
        assert await world.stamped_revision(database) == HEAD
        assert products == 1
        assert images is not None
    finally:
        await engine.dispose()


@pytest.mark.parametrize("extension", sorted(ALLOWED_IMAGE_TYPES.values()))
async def test_every_allowed_upload_extension_satisfies_the_storage_key_check(
    conn: AsyncConnection, extension: str
):
    pid = await product(conn)
    signer = SimpleNamespace(presign_put=lambda **_: "https://upload.invalid")
    content_type = next(k for k, v in ALLOWED_IMAGE_TYPES.items() if v == extension)
    key = (
        MediaUploadService(signer, "https://cdn.invalid")
        .presign_image(  # type: ignore[arg-type]
            new_id(), content_type, 1024
        )
        .key
    )

    await image(conn, pid, 0, key=key)

    assert await scalar(conn, "SELECT count(*) FROM product_images") == 1
