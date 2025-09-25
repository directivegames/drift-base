"""migrate_drift_026_p4

Revision ID: c306a514b84
Revises: af02ef9d604
Create Date: 2025-09-25 10:09:00.595856
"""

# revision identifiers, used by Alembic.
revision = 'c306a514b84'
down_revision = 'af02ef9d604'
branch_labels = None
depends_on = None

from alembic import op


SCHEMA = "public"

UP_MAP = {
    "ck_users": ["create_date", "logon_date", "modify_date"],
    "gs_machine_events": ["create_date", "modify_date"],
    "gs_machinegroups": ["create_date", "modify_date"],
    "gs_machines": ["server_date", "heartbeat_date", "create_date", "modify_date"],
    "gs_matches": ["start_date", "end_date", "status_date", "create_date", "modify_date"],
    "gs_matchevents": ["create_date", "modify_date"],
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


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    upgrade_db()


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    downgrade_db()


def upgrade_db():
    for tbl, cols in UP_MAP.items():
        _alter_to_timestamptz(tbl, cols)


def downgrade_db():
    for tbl, cols in DOWN_MAP.items():
        _alter_to_timestamp(tbl, cols)
