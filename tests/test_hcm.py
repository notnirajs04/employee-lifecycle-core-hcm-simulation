import pandas as pd
from src.hcm import validate_orgs, validate_positions, validate_manager_hierarchy


def test_valid_org_hierarchy_passes():
    orgs=pd.DataFrame([
        {'org_id':'A','org_name':'Root','parent_org_id':'','manager_employee_id':'','location':'Bengaluru'},
        {'org_id':'B','org_name':'Child','parent_org_id':'A','manager_employee_id':'E1','location':'Chennai'},
    ])
    assert validate_orgs(orgs).empty


def test_org_cycle_is_flagged():
    orgs=pd.DataFrame([
        {'org_id':'A','org_name':'One','parent_org_id':'B','manager_employee_id':'','location':'Bengaluru'},
        {'org_id':'B','org_name':'Two','parent_org_id':'A','manager_employee_id':'','location':'Chennai'},
    ])
    assert validate_orgs(orgs)['issue'].str.contains('Circular').any()


def test_position_with_unknown_org_is_flagged():
    positions=pd.DataFrame([{'position_id':'P1','position_title':'Analyst','job_profile':'Analyst','department':'Finance','location':'Bengaluru','org_id':'NOPE','position_status':'Open'}])
    orgs=pd.DataFrame([{'org_id':'A'}])
    assert validate_positions(positions,orgs)['issue'].str.contains('does not exist').any()


def test_manager_cycle_is_flagged():
    employees=pd.DataFrame([{'employee_id':'E1','manager_id':'E2'},{'employee_id':'E2','manager_id':'E1'}])
    assert validate_manager_hierarchy(employees)['issue'].str.contains('Circular').any()


def test_unknown_manager_is_flagged_in_hierarchy():
    employees=pd.DataFrame([{'employee_id':'E1','manager_id':'E9'}])
    assert validate_manager_hierarchy(employees)['issue'].str.contains('does not exist').any()
