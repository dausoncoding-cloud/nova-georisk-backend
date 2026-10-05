"""phase0 security and frontend contracts

Revision ID: 7f3d2a91c4be
Revises: eb3a25ef583f
Create Date: 2026-09-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "7f3d2a91c4be"
down_revision = "eb3a25ef583f"
branch_labels = None
depends_on = None

LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.execute(
        "INSERT INTO organizations (id, name, slug, created_at, updated_at) "
        f"VALUES ('{LEGACY_ORGANIZATION_ID}'::uuid, 'Legacy organization', 'legacy', now(), now())"
    )

    op.create_table(
        "users",
        sa.Column("issuer", sa.String(length=512), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
    )
    membership_role = sa.Enum("OWNER", "ADMIN", "ANALYST", "VIEWER", name="membershiprole")
    op.create_table(
        "organization_memberships",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", membership_role, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("organization_id", "user_id"),
    )

    op.add_column("projects", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_projects_organization_id", "projects", "organizations", ["organization_id"], ["id"]
    )
    op.execute(
        f"UPDATE projects SET organization_id = '{LEGACY_ORGANIZATION_ID}'::uuid "
        "WHERE organization_id IS NULL"
    )
    op.alter_column("projects", "organization_id", nullable=False)
    op.create_index("ix_projects_organization_id", "projects", ["organization_id"])

    op.add_column("tasks", sa.Column("aoi_id", sa.UUID(), nullable=True))
    op.add_column("tasks", sa.Column("error_summary", sa.String(length=500), nullable=True))
    op.add_column("tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_tasks_aoi_id", "tasks", "aois", ["aoi_id"], ["id"])
    op.execute(
        """
        UPDATE tasks
        SET aoi_id = (input_params->>'aoi_id')::uuid
        WHERE aoi_id IS NULL
          AND input_params ? 'aoi_id'
          AND (input_params->>'aoi_id') ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
          AND EXISTS (
              SELECT 1 FROM aois
              WHERE aois.id = (tasks.input_params->>'aoi_id')::uuid
                AND aois.project_id = tasks.project_id
          )
        """
    )
    op.execute(
        "UPDATE tasks SET started_at = created_at "
        "WHERE started_at IS NULL AND status IN ('RUNNING', 'COMPLETED', 'FAILED')"
    )
    op.execute(
        "UPDATE tasks SET completed_at = updated_at "
        "WHERE completed_at IS NULL AND status IN ('COMPLETED', 'FAILED')"
    )
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_aoi_id", "tasks", ["aoi_id"])
    op.create_index("ix_tasks_status", "tasks", ["status"])

    op.add_column("results", sa.Column("project_id", sa.UUID(), nullable=True))
    op.add_column("results", sa.Column("aoi_id", sa.UUID(), nullable=True))
    op.add_column("results", sa.Column("version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("results", sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_foreign_key("fk_results_project_id", "results", "projects", ["project_id"], ["id"])
    op.create_foreign_key("fk_results_aoi_id", "results", "aois", ["aoi_id"], ["id"])
    op.execute(
        "UPDATE results SET project_id = tasks.project_id FROM tasks "
        "WHERE results.task_id = tasks.id AND results.project_id IS NULL"
    )
    op.create_index("ix_results_project_aoi", "results", ["project_id", "aoi_id"])
    op.create_unique_constraint(
        "uq_result_version", "results", ["project_id", "aoi_id", "result_type", "version"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_result_version", "results", type_="unique")
    op.drop_index("ix_results_project_aoi", table_name="results")
    op.drop_constraint("fk_results_aoi_id", "results", type_="foreignkey")
    op.drop_constraint("fk_results_project_id", "results", type_="foreignkey")
    op.drop_column("results", "provenance")
    op.drop_column("results", "version")
    op.drop_column("results", "aoi_id")
    op.drop_column("results", "project_id")

    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_aoi_id", table_name="tasks")
    op.drop_index("ix_tasks_project_id", table_name="tasks")
    op.drop_constraint("fk_tasks_aoi_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "started_at")
    op.drop_column("tasks", "error_summary")
    op.drop_column("tasks", "aoi_id")

    op.drop_index("ix_projects_organization_id", table_name="projects")
    op.drop_constraint("fk_projects_organization_id", "projects", type_="foreignkey")
    op.drop_column("projects", "organization_id")
    op.drop_table("organization_memberships")
    op.drop_table("users")
    op.drop_table("organizations")
    op.execute("DROP TYPE IF EXISTS membershiprole")
