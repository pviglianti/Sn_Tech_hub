"""Re-run the 7 deterministic preprocessing engines and deterministic feature
grouping against an already-scanned assessment.

Preserves all ScanResult review state — none of the engines, nor
seed_feature_groups, write to: review_status, disposition, recommendation,
assigned_to, is_out_of_scope, is_adjacent, observations, ai_observations.

Usage: python -m scripts.rerun_engines_and_grouping <assessment_id>
"""
import sys
from sqlmodel import Session

from src.database import engine
from src import models  # noqa: F401
from src import models_sn  # noqa: F401
from src.mcp.tools.pipeline.run_engines import handle as run_engines_handle
from src.mcp.tools.pipeline.seed_feature_groups import handle as seed_groups_handle


def main(assessment_id: int) -> int:
    with Session(engine) as session:
        print(f"=== Running 7 preprocessing engines for assessment {assessment_id} ===")
        eng_result = run_engines_handle({"assessment_id": assessment_id}, session)
        print(f"engines success={eng_result.get('success')}  errors={eng_result.get('errors')}")
        for e in eng_result.get("engines_run", []):
            name = e.get("engine")
            ok = e.get("success")
            counts = {k: v for k, v in e.items() if k not in ("engine", "success", "errors", "warnings") and isinstance(v, (int, float))}
            print(f"  - {name}: success={ok} {counts}")

        print(f"\n=== Running deterministic feature grouping (seed_feature_groups) ===")
        grp_result = seed_groups_handle(
            {"assessment_id": assessment_id, "reset_existing": True},
            session,
        )
        print(
            f"grouping: features_created={grp_result.get('features_created')} "
            f"grouped_count={grp_result.get('grouped_count')} "
            f"eligible={grp_result.get('eligible_customized_count')}"
        )
    return 0


if __name__ == "__main__":
    aid = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    sys.exit(main(aid))
