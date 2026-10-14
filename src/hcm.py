"""Core HCM learning simulation: supervisory orgs, job profiles, positions, assignments."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import pandas as pd


def init_hcm_db(db_path: str | Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS supervisory_orgs (
            org_id TEXT PRIMARY KEY, org_name TEXT NOT NULL, parent_org_id TEXT,
            manager_employee_id TEXT, location TEXT NOT NULL,
            FOREIGN KEY(parent_org_id) REFERENCES supervisory_orgs(org_id));
        CREATE TABLE IF NOT EXISTS positions (
            position_id TEXT PRIMARY KEY, position_title TEXT NOT NULL, job_profile TEXT NOT NULL,
            department TEXT NOT NULL, location TEXT NOT NULL, org_id TEXT NOT NULL,
            position_status TEXT NOT NULL CHECK(position_status IN ('Open','Filled','Frozen','Closed')),
            FOREIGN KEY(org_id) REFERENCES supervisory_orgs(org_id));
        CREATE TABLE IF NOT EXISTS worker_assignments (
            employee_id TEXT PRIMARY KEY, position_id TEXT NOT NULL, assignment_type TEXT NOT NULL,
            assignment_status TEXT NOT NULL CHECK(assignment_status IN ('Active','Pending','Ended')),
            FOREIGN KEY(employee_id) REFERENCES employees(employee_id),
            FOREIGN KEY(position_id) REFERENCES positions(position_id));
        ''')
        org_count = conn.execute('SELECT COUNT(*) FROM supervisory_orgs').fetchone()[0]
        if org_count == 0:
            conn.executemany('INSERT INTO supervisory_orgs VALUES (?,?,?,?,?)', [
                ('ORG-100','Corporate Services',None,'','Bengaluru'),
                ('ORG-110','People & Culture','ORG-100','E1001','Bengaluru'),
                ('ORG-120','Finance','ORG-100','E1003','Chennai'),
                ('ORG-130','Technology','ORG-100','E1002','Hyderabad'),
            ])
        pos_count = conn.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
        if pos_count == 0:
            conn.executemany('INSERT INTO positions VALUES (?,?,?,?,?,?,?)', [
                ('POS-100','HR Analyst','HR Analyst','Human Resources','Bengaluru','ORG-110','Filled'),
                ('POS-101','HR Associate','HR Associate','Human Resources','Bengaluru','ORG-110','Open'),
                ('POS-200','Finance Analyst','Finance Analyst','Finance','Chennai','ORG-120','Filled'),
                ('POS-300','Software Engineer','Software Engineer','Technology','Hyderabad','ORG-130','Filled'),
                ('POS-301','QA Analyst','QA Analyst','Technology','Bengaluru','ORG-130','Open'),
            ])


def fetch_table(db_path: str | Path, table: str) -> pd.DataFrame:
    allowed = {'supervisory_orgs','positions','worker_assignments'}
    if table not in allowed:
        raise ValueError('Unsupported table')
    init_hcm_db(db_path)
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql_query(f'SELECT * FROM {table} ORDER BY 1', conn)


def validate_orgs(orgs: pd.DataFrame) -> pd.DataFrame:
    issues=[]
    required={'org_id','org_name','parent_org_id','manager_employee_id','location'}
    if not required.issubset(orgs.columns):
        return pd.DataFrame([{'org_id':'','issue':'Missing columns: '+', '.join(sorted(required-set(orgs.columns)))}])
    data=orgs.fillna('').astype(str)
    ids=set(data.org_id.str.strip())
    for _, r in data.iterrows():
        oid=r.org_id.strip(); parent=r.parent_org_id.strip()
        if not oid or not r.org_name.strip() or not r.location.strip():
            issues.append({'org_id':oid,'issue':'Organization ID, name, and location are required'})
        if parent and parent not in ids:
            issues.append({'org_id':oid,'issue':f'Parent organization {parent} does not exist'})
        if parent == oid and parent:
            issues.append({'org_id':oid,'issue':'Organization cannot be its own parent'})
    if data.org_id.duplicated(keep=False).any():
        for oid in data.loc[data.org_id.duplicated(keep=False),'org_id'].unique():
            issues.append({'org_id':oid,'issue':'Duplicate organization ID'})
    # Detect cycles in parent links.
    parents=dict(zip(data.org_id.str.strip(),data.parent_org_id.str.strip()))
    for start in parents:
        seen=set(); node=start
        while node and node in parents:
            if node in seen:
                issues.append({'org_id':start,'issue':'Circular supervisory organization hierarchy detected'})
                break
            seen.add(node); node=parents[node]
    return pd.DataFrame(issues,columns=['org_id','issue'])


def validate_positions(positions: pd.DataFrame, orgs: pd.DataFrame) -> pd.DataFrame:
    issues=[]; required={'position_id','position_title','job_profile','department','location','org_id','position_status'}
    if not required.issubset(positions.columns):
        return pd.DataFrame([{'position_id':'','issue':'Missing columns: '+', '.join(sorted(required-set(positions.columns)))}])
    valid_orgs=set(orgs.get('org_id',pd.Series(dtype=str)).fillna('').astype(str))
    statuses={'Open','Filled','Frozen','Closed'}
    data=positions.fillna('').astype(str)
    if data.position_id.duplicated(keep=False).any():
        for pid in data.loc[data.position_id.duplicated(keep=False),'position_id'].unique():
            issues.append({'position_id':pid,'issue':'Duplicate position ID'})
    for _,r in data.iterrows():
        pid=r.position_id.strip()
        for col in ['position_id','position_title','job_profile','department','location','org_id','position_status']:
            if not r[col].strip(): issues.append({'position_id':pid,'issue':f'Missing required value: {col}'})
        if r.org_id and r.org_id not in valid_orgs: issues.append({'position_id':pid,'issue':f'Organization {r.org_id} does not exist'})
        if r.position_status and r.position_status not in statuses: issues.append({'position_id':pid,'issue':f'Invalid position status: {r.position_status}'})
    return pd.DataFrame(issues,columns=['position_id','issue'])


def validate_manager_hierarchy(employees: pd.DataFrame) -> pd.DataFrame:
    issues=[]
    if not {'employee_id','manager_id'}.issubset(employees.columns):
        return pd.DataFrame([{'employee_id':'','issue':'Employee data must include employee_id and manager_id'}])
    data=employees.fillna('').astype(str)
    ids=set(data.employee_id.str.strip())
    managers=dict(zip(data.employee_id.str.strip(),data.manager_id.str.strip()))
    for emp, manager in managers.items():
        if manager and manager not in ids: issues.append({'employee_id':emp,'issue':f'Manager {manager} does not exist'})
        if manager and manager==emp: issues.append({'employee_id':emp,'issue':'Employee cannot manage themselves'})
        seen={emp}; node=manager
        while node and node in managers:
            if node in seen:
                issues.append({'employee_id':emp,'issue':'Circular manager hierarchy detected'}); break
            seen.add(node); node=managers[node]
    return pd.DataFrame(issues,columns=['employee_id','issue'])


def assign_worker(db_path: str | Path, employee_id: str, position_id: str, assignment_type: str='Primary', assignment_status: str='Active') -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute('INSERT OR REPLACE INTO worker_assignments(employee_id,position_id,assignment_type,assignment_status) VALUES (?,?,?,?)',
                     (employee_id,position_id,assignment_type,assignment_status))
        conn.execute("UPDATE positions SET position_status='Filled' WHERE position_id=?",(position_id,))
