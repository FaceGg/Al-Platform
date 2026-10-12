"""Industrial templates were welding-scenario presets superseded by
project-level workflow templates (Workflow.is_template). The contract types
are kept for compatibility; the registry itself is retired empty."""

from app.templates.contract import (
    IndustrialTemplate,
    TemplateEdge,
    TemplateExpectedOutput,
    TemplateNode,
    TemplateParameter,
)


INDUSTRIAL_TEMPLATES: dict[str, IndustrialTemplate] = {}

__all__ = [
    "INDUSTRIAL_TEMPLATES",
    "IndustrialTemplate",
    "TemplateEdge",
    "TemplateExpectedOutput",
    "TemplateNode",
    "TemplateParameter",
]
