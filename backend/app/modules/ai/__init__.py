"""AI platform. Import `run` from here; never call a provider SDK anywhere else."""
from app.modules.ai.router import AIResult, AIUnavailable, run, run_or_none

__all__ = ["AIResult", "AIUnavailable", "run", "run_or_none"]
