"""migrate_drift_026_p1

Revision ID: 100215e640c
Revises: a385fd678407
Create Date: 2025-09-24 12:09:00.595856
"""

# revision identifiers, used by Alembic.
revision = '100215e640c'
down_revision = 'a385fd678407'
branch_labels = None
depends_on = None

from alembic import op


SCHEMA = "public"

UP_MAP = {
    "ck_clients": ["create_date", "heartbeat", "modify_date"],
    "ck_connect_events": ["event_date", "create_date", "modify_date"],
    "ck_counterentries": ["date_time"],
    "ck_counters": ["create_date", "modify_date"],
    "ck_friend_invites": ["expiry_date", "create_date", "modify_date"],
    "ck_friendships": ["create_date", "modify_date"],
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


def _rename_unique_constraint(table, old_name, new_name):
    """
    Metadata-only rename (no index rebuild). Safe & idempotent.
    """
    quoted_tbl = f'"{SCHEMA}"."{table}"'
    sql = f"""
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conname = '{old_name}'
      AND c.conrelid = '{SCHEMA}.{table}'::regclass
  ) AND NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conname = '{new_name}'
      AND c.conrelid = '{SCHEMA}.{table}'::regclass
  ) THEN
    ALTER TABLE {quoted_tbl}
      RENAME CONSTRAINT {old_name} TO {new_name};
  END IF;
END$$;
"""
    op.execute(sql)


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    upgrade_db()


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    downgrade_db()


def upgrade_db():
    for tbl, cols in UP_MAP.items():
        _alter_to_timestamptz(tbl, cols)

    _rename_unique_constraint(
        "ck_counterentries",
        "ck_counterentries_counter_id_player_id_period_date_time_key",
        "uq_ck_counterentries_counter_id_player_id_period_date_time",
    )


def downgrade_db():
    _rename_unique_constraint(
        "ck_counterentries",
        "uq_ck_counterentries_counter_id_player_id_period_date_time",
        "ck_counterentries_counter_id_player_id_period_date_time_key",
    )

    for tbl, cols in DOWN_MAP.items():
        _alter_to_timestamp(tbl, cols)
