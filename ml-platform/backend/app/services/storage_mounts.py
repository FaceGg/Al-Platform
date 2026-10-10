"""Week 16 storage-mount helpers re-exported for the API layer.

The validation/injection contract lives in :mod:`resource_governance` next to
the snapshot services; this module keeps the planned import surface stable.
"""

from app.services.resource_governance import build_mount_injection, validate_binding

__all__ = ["validate_binding", "build_mount_injection"]
