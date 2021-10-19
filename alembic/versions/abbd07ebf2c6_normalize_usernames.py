"""Normalize usernames

Revision ID: abbd07ebf2c6
Revises: 3b4283dcb935
Create Date: 2021-10-19 16:48:00.915139

"""

# revision identifiers, used by Alembic.
revision = 'abbd07ebf2c6'
down_revision = '3b4283dcb935'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    # TODO: Replace "username" identities with u+p:username

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    # TODO: Replace "u+p:username" identities with username
