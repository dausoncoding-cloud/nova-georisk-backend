"""canonical FIRRIS engine and persistent analysis lifecycle

Revision ID: c7f0a8d42e91
Revises: b4e6d8a90c31
Create Date: 2026-09-28
"""
from alembic import op


revision = "c7f0a8d42e91"
down_revision = "b4e6d8a90c31"
branch_labels = None
depends_on = None


def _rename_engine(old_key: str, new_key: str, name: str, description: str) -> None:
    op.execute(
        f"""
        INSERT INTO engines
          (key, name, description, status, enabled, version, category,
           route_namespace, icon_identifier, capabilities, publicly_available,
           subscription_required, created_at, updated_at)
        SELECT '{new_key}', '{name}', '{description}', status, enabled, version,
               category, '/api/v1/analyses', icon_identifier, capabilities,
               publicly_available, subscription_required, created_at, now()
        FROM engines WHERE key = '{old_key}'
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute(
        f"UPDATE billing_plan_engines SET engine_key = '{new_key}' WHERE engine_key = '{old_key}'"
    )
    op.execute(
        f"UPDATE organization_engine_entitlements SET engine_key = '{new_key}' WHERE engine_key = '{old_key}'"
    )
    op.execute(f"UPDATE projects SET engine_key = '{new_key}' WHERE engine_key = '{old_key}'")
    op.execute(f"UPDATE tasks SET engine_key = '{new_key}' WHERE engine_key = '{old_key}'")
    op.execute(f"UPDATE results SET engine_key = '{new_key}' WHERE engine_key = '{old_key}'")
    op.execute(f"DELETE FROM engines WHERE key = '{old_key}'")


def upgrade() -> None:
    op.drop_constraint("uq_engines_route_namespace", "engines", type_="unique")
    _rename_engine(
        "firas",
        "firris",
        "FIRRIS",
        "NOVA flood mapping and risk analysis engine",
    )
    _rename_engine("wrras", "wras", "WRAS", "Wildfire Risk Assessment System")
    op.execute("UPDATE projects SET analysis_module = 'FIRRIS' WHERE upper(analysis_module) = 'FIRAS'")
    op.alter_column("projects", "engine_key", server_default="firris")
    op.alter_column("tasks", "engine_key", server_default="firris")
    op.alter_column("results", "engine_key", server_default="firris")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'CANCELED'")
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'ANALYSIS'")


def downgrade() -> None:
    _rename_engine("firris", "firas", "FIRAS", "Flood Risk Assessment System")
    _rename_engine("wras", "wrras", "WRRAS", "Wildfire Risk Assessment System")
    op.execute("UPDATE projects SET analysis_module = 'FIRAS' WHERE upper(analysis_module) = 'FIRRIS'")
    op.execute("UPDATE engines SET route_namespace = '/api/v1/firas' WHERE key = 'firas'")
    op.execute("UPDATE engines SET route_namespace = '/api/v1/wrras' WHERE key = 'wrras'")
    op.alter_column("projects", "engine_key", server_default="firas")
    op.alter_column("tasks", "engine_key", server_default="firas")
    op.alter_column("results", "engine_key", server_default="firas")
    op.create_unique_constraint("uq_engines_route_namespace", "engines", ["route_namespace"])
    # PostgreSQL enum values are intentionally retained: removing them safely
    # requires rewriting every dependent column and is not needed for rollback.
