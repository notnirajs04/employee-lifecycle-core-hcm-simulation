import pandas as pd

from src.hr_data import validate_employees, valid_employee_rows, reconcile_counts


def valid_frame():
    return pd.DataFrame([
        {"employee_id":"E001","first_name":"Asha","last_name":"Rao","department":"Engineering","job_profile":"Analyst","manager_id":"","location":"Bengaluru","employment_status":"Active"},
        {"employee_id":"E002","first_name":"Ravi","last_name":"Kumar","department":"Engineering","job_profile":"Associate","manager_id":"E001","location":"Bengaluru","employment_status":"Active"},
    ])


def test_valid_records_have_no_issues():
    assert validate_employees(valid_frame()).empty


def test_duplicate_employee_ids_are_flagged():
    df = pd.concat([valid_frame(), valid_frame().iloc[[0]]], ignore_index=True)
    issues = validate_employees(df)
    assert "Duplicate employee ID" in set(issues["issue"])


def test_missing_required_value_is_flagged():
    df = valid_frame()
    df.loc[0, "first_name"] = ""
    issues = validate_employees(df)
    assert ((issues["field"] == "first_name") & (issues["issue"] == "Missing required value")).any()


def test_unknown_manager_is_flagged():
    df = valid_frame()
    df.loc[1, "manager_id"] = "E999"
    issues = validate_employees(df)
    assert "Manager ID not found in source data" in set(issues["issue"])


def test_invalid_status_is_flagged():
    df = valid_frame()
    df.loc[0, "employment_status"] = "Working"
    issues = validate_employees(df)
    assert "Invalid employment status" in set(issues["issue"])


def test_valid_rows_exclude_rows_with_issues():
    df = valid_frame()
    df.loc[1, "department"] = ""
    result = valid_employee_rows(df)
    assert result["employee_id"].tolist() == ["E001"]


def test_reconciliation_reports_missing_ids():
    source = valid_frame()
    target = source.iloc[[0]].copy()
    result = reconcile_counts(source, target)
    assert result["missing_in_target"] == 1
    assert result["ids_reconciled"] is False
