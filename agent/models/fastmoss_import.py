from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FastMossSalesMetricScopeEntry(BaseModel):
    file_type_id: str
    metric_name: str
    source_column: str
    metric_scope: str
    truth_status: str
    warning: str | None = None


class FastMossImportFileReport(BaseModel):
    upload_field_key: str
    file_type_id: str | None = None
    label: str | None = None
    original_filename: str
    detected_by: str = "field_key"
    storage_path: str
    extension: str
    sheet_names: list[str] = Field(default_factory=list)
    selected_sheet: str | None = None
    headers: list[str] = Field(default_factory=list)
    row_count: int = 0
    required_columns_present: list[str] = Field(default_factory=list)
    optional_columns_present: list[str] = Field(default_factory=list)
    missing_required_columns: list[str] = Field(default_factory=list)
    unknown_columns: list[str] = Field(default_factory=list)
    parse_status: str = "PENDING"
    parse_warnings: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    sales_metric_scope_report: list[FastMossSalesMetricScopeEntry] = Field(default_factory=list)
    sample_records: list[dict[str, Any]] = Field(default_factory=list)


class FastMossImportBatchReport(BaseModel):
    batch_id: str
    import_status: str
    write_back_status: str = "READ_ONLY_IMPORT_PREVIEW"
    latest_reference_only: bool = True
    growth_analytics_enabled: bool = False
    uploaded_files: int
    recognized_file_types: list[str] = Field(default_factory=list)
    missing_expected_file_types: list[str] = Field(default_factory=list)
    duplicate_file_types: list[str] = Field(default_factory=list)
    row_counts_by_file_type: dict[str, int] = Field(default_factory=dict)
    column_validation_by_file_type: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sales_metric_scope_report: list[FastMossSalesMetricScopeEntry] = Field(default_factory=list)
    product_reference_sample: list[dict[str, Any]] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    ready_for_processing: bool = False
    raw_file_storage_path: str
    provenance: list[str] = Field(default_factory=list)
    files: list[FastMossImportFileReport] = Field(default_factory=list)
