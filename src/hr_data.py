"""Core data validation and SQLite persistence for the HR Data Validation System."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd

REQUIRED_COLUMNS = [
    "employee_id", "first_name", "last_name", "department", "job_profile",
    "manager_id", "location", "employment_status"
]
VALID_STATUSES = {"Active", "On Leave", "Terminated", "Pending"}


def validate_employees(df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per validation issue; does not modify the input frame."""
    issues: list[dict[str, object]] = []
    missing_columns = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_columns:
        for col in missing_columns:
            issues.append({"row_number": None, "employee_id": None, "field": col,
                           "issue": "Missing required column", "value": None})
        return pd.DataFrame(issues, columns=["row_number", "employee_id", "field", "issue", "value"])

    data = df.copy()
    for col in REQUIRED_COLUMNS:
        data[col] = data[col].where(data[col].notna(), "").astype(str).str.strip()

    duplicated = data["employee_id"].ne("") & data["employee_id"].duplicated(keep=False)
    for idx in data.index[duplicated]:
        issues.append({"row_number": int(idx) + 2, "employee_id": data.at[idx, "employee_id"],
                       "field": "employee_id", "issue": "Duplicate employee ID", "value": data.at[idx, "employee_id"]})

    ids = set(data.loc[data["employee_id"].ne(""), "employee_id"])
    for idx, row in data.iterrows():
        row_number = int(idx) + 2
        emp_id = row["employee_id"] or None
        for col in ["employee_id", "first_name", "last_name", "department", "job_profile", "location", "employment_status"]:
            if not row[col]:
                issues.append({"row_number": row_number, "employee_id": emp_id, "field": col,
                               "issue": "Missing required value", "value": row[col]})
        if row["employment_status"] and row["employment_status"] not in VALID_STATUSES:
            issues.append({"row_number": row_number, "employee_id": emp_id, "field": "employment_status",
                           "issue": "Invalid employment status", "value": row["employment_status"]})
        manager = row["manager_id"]
        if manager and manager not in ids:
            issues.append({"row_number": row_number, "employee_id": emp_id, "field": "manager_id",
                           "issue": "Manager ID not found in source data", "value": manager})
        if emp_id and manager and emp_id == manager:
            issues.append({"row_number": row_number, "employee_id": emp_id, "field": "manager_id",
                           "issue": "Employee cannot be their own manager", "value": manager})

    return pd.DataFrame(issues, columns=["row_number", "employee_id", "field", "issue", "value"])


def valid_employee_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Return rows with no row-level validation issues; missing-column issues reject all rows."""
    issues = validate_employees(df)
    if not issues.empty and issues["row_number"].isna().any():
        return df.iloc[0:0].copy()
    invalid_rows = set(issues["row_number"].dropna().astype(int).tolist())
    # CSV data row 1 is displayed as spreadsheet row 2 due to the header.
    return df.loc[[int(i) + 2 not in invalid_rows for i in df.index]].copy()


def initialize_database(db_path: str | Path) -> None:
    """Create the employee table and indexes if they do not already exist."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                department TEXT NOT NULL,
                job_profile TEXT NOT NULL,
                manager_id TEXT,
                location TEXT NOT NULL,
                employment_status TEXT NOT NULL CHECK (employment_status IN ('Active','On Leave','Terminated','Pending')),
                FOREIGN KEY (manager_id) REFERENCES employees(employee_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_department ON employees(department)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_employees_manager ON employees(manager_id)")


def import_valid_employees(df: pd.DataFrame, db_path: str | Path) -> tuple[int, int]:
    """Validate then insert valid rows. Returns (inserted, skipped); existing IDs are skipped."""
    initialize_database(db_path)
    if not set(REQUIRED_COLUMNS).issubset(df.columns):
        return 0, len(df)
    valid = valid_employee_rows(df)
    inserted = 0
    with sqlite3.connect(db_path) as conn:
        for _, row in valid.iterrows():
            values = [str(row[c]).strip() if pd.notna(row[c]) else "" for c in REQUIRED_COLUMNS]
            try:
                conn.execute("""INSERT INTO employees
                    (employee_id, first_name, last_name, department, job_profile, manager_id, location, employment_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", values)
                inserted += 1
            except sqlite3.IntegrityError:
                # Duplicate target IDs or invalid FK/status constraints are safely skipped.
                continue
    return inserted, len(df) - inserted


def fetch_employees(db_path: str | Path) -> pd.DataFrame:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query("SELECT * FROM employees ORDER BY employee_id", conn)


def reconcile_counts(source_df: pd.DataFrame, target_df: pd.DataFrame) -> dict[str, int | bool]:
    """Compare source and target IDs and report record-level reconciliation."""
    source_ids = set(source_df.get("employee_id", pd.Series(dtype=str)).dropna().astype(str).str.strip())
    target_ids = set(target_df.get("employee_id", pd.Series(dtype=str)).dropna().astype(str).str.strip())
    return {
        "source_rows": int(len(source_df)),
        "target_rows": int(len(target_df)),
        "source_unique_ids": int(len(source_ids)),
        "target_unique_ids": int(len(target_ids)),
        "missing_in_target": int(len(source_ids - target_ids)),
        "unexpected_in_target": int(len(target_ids - source_ids)),
        "ids_reconciled": source_ids == target_ids,
    }
