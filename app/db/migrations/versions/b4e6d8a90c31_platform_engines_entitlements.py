"""platform engine registry, billing readiness, and entitlements

Revision ID: b4e6d8a90c31
Revises: 8d1c4b72e0af
Create Date: 2026-09-27
"""
from alembic import op
import json
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b4e6d8a90c31"
down_revision = "8d1c4b72e0af"
branch_labels = None
depends_on = None

ENGINE_ROWS = (
    ("firas", "FIRAS", "Flood Risk Assessment System", "active", True, "1.0", "risk", "/api/v1/firas", "flood", '["flood-risk","screening-atlas"]', True),
    ("wrras", "WRRAS", "Wildfire Risk Assessment System", "planned", False, "0", "risk", "/api/v1/wrras", "wildfire", "[]", False),
    ("lucas", "LUCAS", "Land Use / Land Cover Change Analysis System", "planned", False, "0", "change", "/api/v1/lucas", "land-cover", "[]", False),
    ("hasas", "HASAS", "Habitat Suitability Analysis System", "planned", False, "0", "ecology", "/api/v1/hasas", "habitat", "[]", False),
    ("veras", "VERAS", "Vegetation Recovery Analysis System", "planned", False, "0", "ecology", "/api/v1/veras", "vegetation", "[]", False),
    ("diras", "DIRAS", "Drought Impact / Risk Analysis System", "planned", False, "0", "risk", "/api/v1/diras", "drought", "[]", False),
    ("lstas", "LSTAS", "Land Surface Temperature Analysis System", "planned", False, "0", "climate", "/api/v1/lstas", "temperature", "[]", False),
    ("wqras", "WQRAS", "Water Quality Risk / Analysis System", "planned", False, "0", "water", "/api/v1/wqras", "water-quality", "[]", False),
    ("lras", "LRAS", "Landslide Risk Assessment System", "planned", False, "0", "risk", "/api/v1/lras", "landslide", "[]", False),
    ("megis", "MEGIS", "Mineral Exploration / Geospatial Intelligence System", "planned", False, "0", "exploration", "/api/v1/megis", "mineral", "[]", False),
)


def upgrade() -> None:
    entitlement_status = postgresql.ENUM(
        "ACTIVE", "TRIAL", "SUSPENDED", "EXPIRED", "CANCELED", "PENDING",
        name="entitlementstatus", create_type=False,
    )
    subscription_status = postgresql.ENUM(
        "ACTIVE", "TRIAL", "SUSPENDED", "EXPIRED", "CANCELED", "PENDING",
        name="subscriptionstatus", create_type=False,
    )
    entitlement_status.create(op.get_bind(), checkfirst=True)
    subscription_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "engines",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("route_namespace", sa.String(length=128), nullable=False),
        sa.Column("icon_identifier", sa.String(length=64), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("publicly_available", sa.Boolean(), nullable=False),
        sa.Column("subscription_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
        sa.UniqueConstraint("route_namespace", name="uq_engines_route_namespace"),
    )
    values = []
    for row in ENGINE_ROWS:
        capabilities = json.dumps({"features": json.loads(row[9])}).replace("'", "''")
        escaped = [str(value).replace("'", "''") for value in row[:4]]
        version = row[5].replace("'", "''")
        category = row[6].replace("'", "''")
        route = row[7].replace("'", "''")
        icon = row[8].replace("'", "''")
        values.append(
            "(" + ",".join(
                [
                    f"'{escaped[0]}'", f"'{escaped[1]}'", f"'{escaped[2]}'", f"'{escaped[3]}'",
                    "TRUE" if row[4] else "FALSE", f"'{version}'", f"'{category}'",
                    f"'{route}'", f"'{icon}'", f"'{capabilities}'::jsonb",
                    "TRUE" if row[10] else "FALSE", "TRUE", "now()", "now()",
                ]
            ) + ")"
        )
    op.execute(
        "INSERT INTO engines "
        "(key,name,description,status,enabled,version,category,route_namespace,"
        "icon_identifier,capabilities,publicly_available,subscription_required,created_at,updated_at) VALUES "
        + ",".join(values)
    )

    op.create_table(
        "billing_plans",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "billing_plan_engines",
        sa.Column("plan_key", sa.String(length=64), nullable=False),
        sa.Column("engine_key", sa.String(length=32), nullable=False),
        sa.Column("usage_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["engine_key"], ["engines.key"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_key"], ["billing_plans.key"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("plan_key", "engine_key"),
    )
    op.create_table(
        "organization_subscriptions",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("plan_key", sa.String(length=64), nullable=True),
        sa.Column("status", subscription_status, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("external_provider", sa.String(length=64), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_key"], ["billing_plans.key"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_provider", "external_reference", name="uq_subscription_external_ref"),
    )
    op.create_index("ix_subscriptions_organization_id", "organization_subscriptions", ["organization_id"])
    op.create_table(
        "organization_engine_entitlements",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("engine_key", sa.String(length=32), nullable=False),
        sa.Column("status", entitlement_status, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("subscription_id", sa.UUID(), nullable=True),
        sa.Column("external_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("usage_limits", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("granted_by_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["engine_key"], ["engines.key"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["organization_subscriptions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "engine_key", name="uq_org_engine_entitlement"),
    )
    op.create_index("ix_entitlements_organization_id", "organization_engine_entitlements", ["organization_id"])
    op.create_index("ix_entitlements_engine_key", "organization_engine_entitlements", ["engine_key"])

    op.add_column("projects", sa.Column("engine_key", sa.String(length=32), nullable=True))
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (
            SELECT 1 FROM projects
            WHERE lower(analysis_module) NOT IN
              ('firas','wrras','lucas','hasas','veras','diras','lstas','wqras','lras','megis')
          ) THEN
            RAISE EXCEPTION 'Unknown project analysis_module; register and map it before Phase 0.75';
          END IF;
        END $$;
        """
    )
    op.execute("UPDATE projects SET engine_key = lower(analysis_module)")
    op.alter_column("projects", "engine_key", nullable=False, server_default="firas")
    op.create_foreign_key("fk_projects_engine_key", "projects", "engines", ["engine_key"], ["key"], ondelete="RESTRICT")
    op.create_index("ix_projects_engine_key", "projects", ["engine_key"])

    op.add_column("tasks", sa.Column("engine_key", sa.String(length=32), nullable=True))
    op.execute("UPDATE tasks SET engine_key = projects.engine_key FROM projects WHERE tasks.project_id = projects.id")
    op.alter_column("tasks", "engine_key", nullable=False, server_default="firas")
    op.create_foreign_key("fk_tasks_engine_key", "tasks", "engines", ["engine_key"], ["key"], ondelete="RESTRICT")
    op.create_index("ix_tasks_engine_key", "tasks", ["engine_key"])

    op.add_column("results", sa.Column("engine_key", sa.String(length=32), nullable=True))
    op.execute("UPDATE results SET engine_key = tasks.engine_key FROM tasks WHERE results.task_id = tasks.id")
    op.alter_column("results", "engine_key", nullable=False, server_default="firas")
    op.create_foreign_key("fk_results_engine_key", "results", "engines", ["engine_key"], ["key"], ondelete="RESTRICT")
    op.create_index("ix_results_engine_key", "results", ["engine_key"])

    op.execute(
        """
        INSERT INTO organization_engine_entitlements
          (id, organization_id, engine_key, status, starts_at, source, created_at, updated_at)
        SELECT md5(p.organization_id::text || ':' || p.engine_key)::uuid,
               p.organization_id, p.engine_key, 'ACTIVE', min(p.created_at),
               'legacy_migration', now(), now()
        FROM projects p
        GROUP BY p.organization_id, p.engine_key
        ON CONFLICT (organization_id, engine_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_results_engine_key", table_name="results")
    op.drop_constraint("fk_results_engine_key", "results", type_="foreignkey")
    op.drop_column("results", "engine_key")
    op.drop_index("ix_tasks_engine_key", table_name="tasks")
    op.drop_constraint("fk_tasks_engine_key", "tasks", type_="foreignkey")
    op.drop_column("tasks", "engine_key")
    op.drop_index("ix_projects_engine_key", table_name="projects")
    op.drop_constraint("fk_projects_engine_key", "projects", type_="foreignkey")
    op.drop_column("projects", "engine_key")
    op.drop_index("ix_entitlements_engine_key", table_name="organization_engine_entitlements")
    op.drop_index("ix_entitlements_organization_id", table_name="organization_engine_entitlements")
    op.drop_table("organization_engine_entitlements")
    op.drop_index("ix_subscriptions_organization_id", table_name="organization_subscriptions")
    op.drop_table("organization_subscriptions")
    op.drop_table("billing_plan_engines")
    op.drop_table("billing_plans")
    op.drop_table("engines")
    op.execute("DROP TYPE IF EXISTS entitlementstatus")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
