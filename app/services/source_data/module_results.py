"""Assemble existing six-module maps without resampling or weakening their gates."""
from dataclasses import dataclass
from pathlib import Path
from contextvars import ContextVar
import hashlib

from app.core.artifact_storage import artifact_root
from app.models.result import Result
from app.models.task import Task, TaskStatus
from app.schemas.source_bindings import SourceBoundAnalysisRequest
from app.services.source_data.readiness import SourceNotReady
from app.services.tasks.execution import fingerprint, validate_source_snapshots

_STACK = ContextVar('module_result_stack', default=())


@dataclass(frozen=True)
class ReadyModuleResult:
    result: Result
    artifacts: dict
    state: str

    def lineage(self):
        return {'result_id': str(self.result.id), 'version': self.result.version,
                'task_id': str(self.result.task_id), 'result_type': self.result.result_type,
                'result_state_sha256': self.state,
                'artifact_checksums': {key: hashlib.sha256(data).hexdigest() for key, (_, data) in self.artifacts.items()}}


def load_module_result(db, result_id, request, role, aoi_geometry, *, root=None):
    stack = _STACK.get()
    if result_id in stack or len(stack) >= 12:
        raise SourceNotReady('Cyclic or excessive upstream map dependency')
    token = _STACK.set((*stack, result_id))
    try:
        result = db.get(Result, result_id)
        if (result is None or result.project_id != request.project_id or result.aoi_id != request.aoi_id
                or result.engine_key != 'firris' or result.result_type != 'source_bound_'+role):
            raise SourceNotReady('Six-module map is unavailable in this project and AOI')
        task = db.get(Task, result.task_id)
        if (task is None or task.status != TaskStatus.COMPLETED or task.project_id != request.project_id
                or task.aoi_id != request.aoi_id or task.engine_key != 'firris'):
            raise SourceNotReady('Six-module map task is not completed')
        original = SourceBoundAnalysisRequest.model_validate(task.input_params['source_binding'])
        if (original.module != role or original.project_id != request.project_id or original.aoi_id != request.aoi_id
                or original.period.start > request.period.start or original.period.end < request.period.end):
            raise SourceNotReady('Six-module map identity or period is incompatible')
        from app.services.source_data.bindings import resolve_bindings
        resolved = resolve_bindings(db, original, root=root, aoi_geometry=aoi_geometry)
        validate_source_snapshots(resolved, task.input_params)
        if ((result.provenance or {}).get('module') != role
                or (result.provenance or {}).get('source_bindings', {}) != resolved.lineage()
                or (result.provenance or {}).get('analysis_readiness_rechecked_at_execution') is not True):
            raise SourceNotReady('Six-module map provenance is incompatible')
        expected_formula = {'flood_duration':'sum(valid inundated interval-start states) × verified temporal resolution in hours','hazard':'compute_hazard_index','exposure':'compute_exposure_index','vulnerability':'compute_fvi','insecurity':'compute_fii','risk':'compute_fri','resilience':'compute_cri'}[role]
        if ((result.provenance or {}).get('formula_implementation') != (expected_formula if role=='flood_duration' else 'app.services.firas.'+role+'.'+expected_formula)
                or (result.provenance or {}).get('upstream_results', {}) != {key: ready.lineage() for key,ready in resolved.upstream.items()}):
            raise SourceNotReady('Six-module formula or upstream lineage differs from reviewed execution')
        artifacts = {}
        storage = (root or artifact_root()).resolve()
        for key, entry in (result.output_files or {}).items():
            if entry.get('role') != 'product' or entry.get('artifact_type') not in {'raster', 'vector'}:
                continue
            if entry.get('result_version') != result.version or not entry.get('gis_metadata', {}).get('crs'):
                raise SourceNotReady('Six-module map version or CRS metadata is missing')
            path = (storage / entry['path']).resolve(strict=True)
            path.relative_to(storage)
            if not path.is_file() or path.stat().st_size > 250*1024*1024:
                raise SourceNotReady('Six-module map exceeds protected artifact capacity')
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != entry.get('checksum_sha256'):
                raise SourceNotReady('Six-module map bytes changed')
            artifacts[key] = (entry, data)
        if not artifacts:
            raise SourceNotReady('Six-module map has no protected spatial products')
        return ReadyModuleResult(result, artifacts, fingerprint({'summary': result.summary, 'provenance': result.provenance, 'outputs': result.output_files}))
    except SourceNotReady:
        raise
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise SourceNotReady('Six-module map or its source approval cannot be revalidated') from exc
    finally:
        _STACK.reset(token)
