"""Add indices for fast match lookup

Revision ID: a4b515b8757c
Revises: 58c1b2a9640f
Create Date: 2024-08-19 14:10:04.813456

"""

# revision identifiers, used by Alembic.
revision = 'a4b515b8757c'
down_revision = '58c1b2a9640f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.create_index('ix_gs_matches_start_date', 'gs_matches', ['start_date'])
    op.alter_column('gs_matches', 'details', type_=postgresql.JSONB)
    op.alter_column('gs_matches', 'match_statistics', type_=postgresql.JSONB)


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.alter_column('gs_matches', 'match_statistics', type_=postgresql.JSON)
    op.alter_column('gs_matches', 'details', type_=postgresql.JSON)
    op.drop_index('ix_gs_matches_start_date')
