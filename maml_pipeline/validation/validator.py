# Purpose: Run all deterministic validation checks and return one machine-readable report.

from __future__ import annotations

from typing import Any

from maml_pipeline.models import SourceInventory, ValidationReport
from maml_pipeline.validation.preservation_validator import validate_preservation
from maml_pipeline.validation.schema_validator import validate_schema


def validate_maml(objects: list[dict[str, Any]], inventory: SourceInventory) -> ValidationReport:
    schema_errors, schema_warnings = validate_schema(objects)
    preservation_errors, preservation_warnings = validate_preservation(objects, inventory)
    errors = schema_errors + preservation_errors
    return ValidationReport(
        valid=not errors,
        errors=errors,
        warnings=schema_warnings + preservation_warnings,
    )
