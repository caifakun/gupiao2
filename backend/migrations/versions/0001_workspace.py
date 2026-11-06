from alembic import op
import sqlalchemy as sa

revision = "0001_workspace"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    options = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("username", name="uq_users_username"), **options)
    op.create_table("user_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False), **options)
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])
    op.create_table("workspace_meta",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False), **options)
    op.create_table("watchlist_groups",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "name", name="uq_group_name"), **options)
    op.create_table("watchlist_stocks",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("market", sa.String(2), primary_key=True),
        sa.Column("code", sa.String(6), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("group_id", sa.String(80), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id", "group_id"], ["watchlist_groups.user_id", "watchlist_groups.id"], ondelete="CASCADE"), **options)
    op.create_table("user_settings",
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("view", sa.String(8), nullable=False),
        sa.Column("layout", sa.Integer(), nullable=False), **options)


def downgrade():
    for table in ["user_settings", "watchlist_stocks", "watchlist_groups", "workspace_meta", "user_sessions", "users"]:
        op.drop_table(table)
