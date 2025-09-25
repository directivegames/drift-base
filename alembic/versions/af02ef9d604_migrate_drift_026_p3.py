"""migrate_drift_026_p3

Revision ID: af02ef9d604
Revises: 2c4a42b6d71
Create Date: 2025-09-25 10:09:00.595856
"""

# revision identifiers, used by Alembic.
revision = 'af02ef9d604'
down_revision = '2c4a42b6d71'
branch_labels = None
depends_on = None

from alembic import op


SCHEMA = "public"

UP_MAP = {
    "ck_playerjournal": ["timestamp", "create_date", "modify_date"],
    "ck_players": ["create_date", "logon_date", "modify_date"],
    "ck_tickets": ["used_date", "create_date", "modify_date"],
    "ck_user_events": ["event_date", "create_date", "modify_date"],
    "ck_user_identities": ["logon_date", "create_date", "modify_date"],
    "ck_userroles": ["create_date", "modify_date"],
}

DOWN_MAP = UP_MAP


def _alter_to_timestamptz(table, cols):
    """
    Build 1 ALTER TABLE per table, including only columns that are still 'timestamp' (naive).
    Rerunnable/idempotent; performs a single rewrite per table.
    """
    quoted_tbl = f'"{SCHEMA}"."{table}"'
    parts = []
    for col in cols:
        qcol = f'"{col}"'
        parts.append(f"""
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='{SCHEMA}'
      AND table_name='{table}'
      AND column_name='{col}'
      AND udt_name='timestamp'
  ) THEN
    cmd := cmd || sep || 'ALTER COLUMN {qcol} TYPE timestamptz USING ({qcol} AT TIME ZONE ''UTC'')';
    sep := ', ';
  END IF;""")

    sql = f"""
DO $$
DECLARE
  cmd text := '';
  sep text := '';
BEGIN
{''.join(parts)}

  IF cmd <> '' THEN
    EXECUTE 'ALTER TABLE {quoted_tbl} ' || cmd;
  END IF;
END$$;
"""
    op.execute(sql)


def _alter_to_timestamp(table, cols):
    """
    Reverse of above: convert 'timestamptz' -> 'timestamp' (UTC wall-clock).
    Rerunnable/idempotent; single rewrite per table.
    """
    quoted_tbl = f'"{SCHEMA}"."{table}"'
    parts = []
    for col in cols:
        qcol = f'"{col}"'
        parts.append(f"""
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema='{SCHEMA}'
      AND table_name='{table}'
      AND column_name='{col}'
      AND udt_name='timestamptz'
  ) THEN
    cmd := cmd || sep || 'ALTER COLUMN {qcol} TYPE timestamp USING ({qcol} AT TIME ZONE ''UTC'')';
    sep := ', ';
  END IF;""")

    sql = f"""
DO $$
DECLARE
  cmd text := '';
  sep text := '';
BEGIN
{''.join(parts)}

  IF cmd <> '' THEN
    EXECUTE 'ALTER TABLE {quoted_tbl} ' || cmd;
  END IF;
END$$;
"""
    op.execute(sql)


def _create_index_concurrently_if_missing(idx_name, table, cols):
    """
    Build an index concurrently outside the main transaction if it's missing.
    """
    col_list = ", ".join(cols)
    with op.get_context().autocommit_block():
        op.execute(
            f'CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name} ON "{SCHEMA}"."{table}" ({col_list})'
        )


def _drop_index_concurrently_if_exists(idx_name):
    with op.get_context().autocommit_block():
        # Note: syntax order is DROP INDEX CONCURRENTLY IF EXISTS
        op.execute(f'DROP INDEX CONCURRENTLY IF EXISTS {idx_name}')


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    upgrade_db()


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    downgrade_db()


def upgrade_db():
    for tbl, cols in UP_MAP.items():
        _alter_to_timestamptz(tbl, cols)

    # 3) Build index concurrently (outside txn)
    _create_index_concurrently_if_missing(
        idx_name="ix_ck_players_player_uuid",
        table="ck_players",
        cols=["player_uuid"],
    )


def downgrade_db():
    _drop_index_concurrently_if_exists("ix_ck_players_player_uuid")

    for tbl, cols in DOWN_MAP.items():
        _alter_to_timestamp(tbl, cols)
