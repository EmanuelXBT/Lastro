"""Lastro — collectors package."""
from .hermes_approvals import run as run_approvals
from .hub import run as run_hub

__all__ = ["run_approvals", "run_hub"]
