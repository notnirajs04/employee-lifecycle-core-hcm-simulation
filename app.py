from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st
from src.hr_data import REQUIRED_COLUMNS, fetch_employees, import_valid_employees, initialize_database, reconcile_counts, validate_employees
from src.hcm import init_hcm_db, fetch_table, validate_orgs, validate_positions, validate_manager_hierarchy, assign_worker

ROOT=Path(__file__).parent; DATA=ROOT/'data'; DB=ROOT/'hr_records.db'
SAMPLE=DATA/'sample_employees.csv'
st.set_page_config(page_title='Core HCM Learning Simulation',page_icon='🏢',layout='wide')
initialize_database(DB); init_hcm_db(DB)
st.title('Employee Lifecycle & Core HCM Simulation')
st.caption('Learning simulation of HR data, supervisory organizations, job profiles, positions, and staffing validation. Not connected to Workday.')
tabs=st.tabs(['Overview & employee import','Supervisory organizations','Positions & job profiles','Worker assignments','Business process simulator','UAT & implementation pack','Validation workbench'])

with tabs[0]:
    with st.sidebar:
        st.header('Employee data import')
        uploaded=st.file_uploader('Upload employee CSV',type=['csv'],key='employee_upload')
        if st.button('Load sample employee CSV',use_container_width=True): st.session_state['employee_df']=pd.read_csv(SAMPLE,dtype=str).fillna('')
        if uploaded is not None:
            try: st.session_state['employee_df']=pd.read_csv(uploaded,dtype=str).fillna('')
            except Exception as exc: st.error(f'Could not read CSV: {exc}')
        st.caption('Required columns'); st.code(', '.join(REQUIRED_COLUMNS))
    employees=fetch_employees(DB)
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Employees in target',len(employees)); c2.metric('Active workers',int((employees.employment_status=='Active').sum()) if not employees.empty else 0)
    c3.metric('Supervisory organizations',len(fetch_table(DB,'supervisory_orgs'))); c4.metric('Positions',len(fetch_table(DB,'positions')))
    st.subheader('Employee directory')
    if employees.empty: st.info('Load the sample employee CSV, review validation, then import valid records.')
    else: st.dataframe(employees,use_container_width=True,hide_index=True)
    if 'employee_df' in st.session_state:
        source=st.session_state['employee_df'].copy(); st.subheader('Source data preview'); st.dataframe(source,use_container_width=True,hide_index=True)
        missing=[c for c in REQUIRED_COLUMNS if c not in source.columns]
        if missing: st.error('Missing required columns: '+', '.join(missing))
        else:
            issues=validate_employees(source); badrows=set(issues.row_number.dropna().astype(int)) if not issues.empty else set()
            a,b,c=st.columns(3); a.metric('Source rows',len(source)); b.metric('Rows with issues',len(badrows)); c.metric('Validation issues',len(issues))
            if issues.empty: st.success('No employee data validation issues found.')
            else: st.warning('Rows with issues are excluded from import.'); st.dataframe(issues,use_container_width=True,hide_index=True)
            x,y=st.columns(2)
            with x:
                if st.button('Import valid employee records',type='primary',use_container_width=True):
                    inserted,skipped=import_valid_employees(source,DB); st.session_state['last_import']=(inserted,skipped); st.rerun()
            with y: st.download_button('Download validation report',issues.to_csv(index=False).encode(),file_name='hr_validation_report.csv',mime='text/csv',use_container_width=True)
            if 'last_import' in st.session_state: st.info(f"Last import: {st.session_state['last_import'][0]} inserted; {st.session_state['last_import'][1]} skipped (invalid or already present).")
            rec=reconcile_counts(source,fetch_employees(DB)); st.subheader('Source-to-target reconciliation'); q1,q2,q3=st.columns(3); q1.metric('Source rows',rec['source_rows']); q2.metric('Target rows',rec['target_rows']); q3.metric('Missing source IDs in target',rec['missing_in_target'])

with tabs[1]:
    st.subheader('Supervisory organization hierarchy')
    st.write('Organizations group workers under a management structure. Parent organization links create the hierarchy; manager IDs are illustrative references.')
    orgs=fetch_table(DB,'supervisory_orgs'); st.dataframe(orgs,use_container_width=True,hide_index=True)
    org_issues=validate_orgs(orgs)
    if org_issues.empty: st.success('Organization structure checks passed: no duplicate IDs, missing parents, or hierarchy cycles detected.')
    else: st.error('Organization validation issues'); st.dataframe(org_issues,use_container_width=True,hide_index=True)
    with st.expander('Add an organization'):
        with st.form('add_org'):
            oid=st.text_input('Organization ID',placeholder='ORG-140'); oname=st.text_input('Organization name'); parent=st.selectbox('Parent organization',['']+orgs.org_id.tolist()); mgr=st.text_input('Manager employee ID (optional)'); loc=st.text_input('Location',value='Bengaluru'); submit=st.form_submit_button('Add organization')
            if submit:
                if not oid.strip() or not oname.strip() or not loc.strip(): st.error('Organization ID, name, and location are required.')
                elif oid in set(orgs.org_id): st.error('That organization ID already exists.')
                elif parent==oid: st.error('An organization cannot be its own parent.')
                else:
                    with sqlite3.connect(DB) as conn: conn.execute('INSERT INTO supervisory_orgs VALUES (?,?,?,?,?)',(oid.strip(),oname.strip(),parent,mgr.strip(),loc.strip()))
                    st.success('Organization added.'); st.rerun()

with tabs[2]:
    st.subheader('Position management and job profiles')
    st.write('A position represents a seat in the organization; a job profile describes the type of work associated with it.')
    orgs=fetch_table(DB,'supervisory_orgs'); positions=fetch_table(DB,'positions'); st.dataframe(positions,use_container_width=True,hide_index=True)
    issues=validate_positions(positions,orgs)
    if issues.empty: st.success('Position checks passed: required fields, organization references, unique IDs, and status values are valid.')
    else: st.warning('Position validation issues found.'); st.dataframe(issues,use_container_width=True,hide_index=True)
    st.markdown('**Position status guide**')
    st.write('Open = available for staffing · Filled = assigned · Frozen = temporarily unavailable · Closed = no longer available')
    with st.expander('Add a position'):
        with st.form('add_position'):
            pid=st.text_input('Position ID',placeholder='POS-400'); title=st.text_input('Position title'); profile=st.text_input('Job profile'); dept=st.text_input('Department'); loc=st.text_input('Location'); org=st.selectbox('Supervisory organization',orgs.org_id.tolist()); status=st.selectbox('Position status',['Open','Filled','Frozen','Closed']); submit=st.form_submit_button('Add position')
            if submit:
                if not all(v.strip() for v in [pid,title,profile,dept,loc]): st.error('Complete all required fields.')
                elif pid in set(positions.position_id): st.error('Position ID already exists.')
                else:
                    with sqlite3.connect(DB) as conn: conn.execute('INSERT INTO positions VALUES (?,?,?,?,?,?,?)',(pid.strip(),title.strip(),profile.strip(),dept.strip(),loc.strip(),org,status))
                    st.success('Position added.'); st.rerun()

with tabs[3]:
    st.subheader('Worker-to-position assignments')
    employees=fetch_employees(DB); positions=fetch_table(DB,'positions'); assignments=fetch_table(DB,'worker_assignments')
    if not assignments.empty:
        joined=assignments.merge(employees[['employee_id','first_name','last_name']],on='employee_id',how='left').merge(positions[['position_id','position_title','department','org_id']],on='position_id',how='left')
        st.dataframe(joined,use_container_width=True,hide_index=True)
    else: st.info('No worker assignments yet. Import sample employee data, then create assignments below.')
    available_positions=positions[positions.position_status=='Open']
    with st.form('assign_worker'):
        if employees.empty: st.warning('Import employee records on the Overview tab first.'); emp=''
        else: emp=st.selectbox('Employee',employees.employee_id.tolist(),format_func=lambda x: f"{x} — {employees.loc[employees.employee_id==x,'first_name'].iloc[0]} {employees.loc[employees.employee_id==x,'last_name'].iloc[0]}")
        if available_positions.empty: st.warning('No open positions are available. Add an Open position on the Positions tab.'); pos=''
        else: pos=st.selectbox('Open position',available_positions.position_id.tolist(),format_func=lambda x: f"{x} — {available_positions.loc[available_positions.position_id==x,'position_title'].iloc[0]}")
        atype=st.selectbox('Assignment type',['Primary','Additional','Temporary']); astat=st.selectbox('Assignment status',['Active','Pending','Ended']); submit=st.form_submit_button('Assign worker',disabled=employees.empty or available_positions.empty)
        if submit:
            try: assign_worker(DB,emp,pos,atype,astat); st.success('Assignment saved and position marked Filled.'); st.rerun()
            except sqlite3.IntegrityError as exc: st.error(f'Could not save assignment: {exc}')

with tabs[4]:
    st.subheader('Employee lifecycle business-process simulator')
    st.caption('A learning model of common HR events. It does not execute Workday business processes.')
    employees=fetch_employees(DB)
    if employees.empty:
        st.info('Import sample employees on the Overview tab to try lifecycle scenarios.')
    else:
        with st.form('lifecycle_event'):
            emp_id=st.selectbox('Worker',employees.employee_id.tolist(),format_func=lambda x: f"{x} — {employees.loc[employees.employee_id==x,'first_name'].iloc[0]} {employees.loc[employees.employee_id==x,'last_name'].iloc[0]}")
            event_type=st.selectbox('Business process scenario',['Hire','Transfer','Promotion','Termination'])
            effective_date=st.date_input('Effective date')
            reason=st.text_input('Reason / business justification',placeholder='e.g., approved internal move')
            destination=st.text_input('Destination department / position (for transfer or promotion)')
            manager_approval=st.selectbox('Manager approval',['Pending','Approved','Rejected'])
            hr_approval=st.selectbox('HR approval',['Pending','Approved','Rejected'])
            save_event=st.form_submit_button('Evaluate and log scenario')
        if save_event:
            issues=[]
            if not reason.strip(): issues.append('Business justification is required.')
            if event_type in ['Transfer','Promotion'] and not destination.strip(): issues.append('Destination department or position is required for this scenario.')
            if manager_approval=='Rejected' or hr_approval=='Rejected': issues.append('A required approval was rejected; do not proceed.')
            elif manager_approval!='Approved' or hr_approval!='Approved': issues.append('Scenario is pending until both manager and HR approvals are approved.')
            outcome='Blocked' if any('rejected' in x.lower() or 'required' in x.lower() for x in issues) else ('Pending approval' if issues else 'Ready for review')
            st.session_state.setdefault('lifecycle_log',[]).append({'worker_id':emp_id,'event_type':event_type,'effective_date':str(effective_date),'reason':reason,'destination':destination,'manager_approval':manager_approval,'hr_approval':hr_approval,'outcome':outcome,'validation_notes':' | '.join(issues) if issues else 'Required fields and approvals passed.'})
            if outcome=='Ready for review': st.success('Scenario passed simulated entry checks. This records a scenario only; it does not change the worker record.')
            elif outcome=='Pending approval': st.warning('Scenario remains pending approval.')
            else: st.error('Scenario blocked. Review the validation notes.')
            if issues: st.write('\n'.join('- '+x for x in issues))
    log=pd.DataFrame(st.session_state.get('lifecycle_log',[]))
    st.markdown('**Scenario log**')
    if log.empty: st.info('No lifecycle scenarios logged in this session yet.')
    else:
        st.dataframe(log,use_container_width=True,hide_index=True)
        st.download_button('Download lifecycle scenario log',log.to_csv(index=False).encode(),file_name='lifecycle_scenario_log.csv',mime='text/csv')

with tabs[5]:
    st.subheader('UAT, requirements traceability, and mock cutover pack')
    st.caption('These are sample implementation artefacts for practice; tailor them to a real client process before using professionally.')
    uat=pd.DataFrame([
      ['UAT-001','Worker data','Import valid worker CSV','Five valid sample records','All valid records appear in target','Pass/Fail','Open'],
      ['UAT-002','Data conversion','Import file with invalid rows','Duplicate ID, missing name, invalid status','Invalid rows excluded and issues reported','Pass/Fail','Open'],
      ['UAT-003','Organization','Create child organization','Existing parent org ID','Child saves and hierarchy remains acyclic','Pass/Fail','Open'],
      ['UAT-004','Position management','Assign worker to open position','Active worker + Open position','Assignment recorded and position becomes Filled','Pass/Fail','Open'],
      ['UAT-005','Approval workflow','Evaluate transfer with pending approval','Manager approval Pending','Scenario remains pending and does not update worker','Pass/Fail','Open'],
      ['UAT-006','Approval workflow','Evaluate promotion with rejected HR approval','HR approval Rejected','Scenario is blocked with validation note','Pass/Fail','Open'],
      ['UAT-007','Reconciliation','Compare source IDs and target IDs','Source and target ID lists','Missing/unexpected IDs are identified for investigation','Pass/Fail','Open'],
    ],columns=['Test ID','Requirement area','Test scenario','Test data','Expected result','Actual result','Defect/status'])
    st.markdown('**UAT test register**')
    st.dataframe(uat,use_container_width=True,hide_index=True)
    st.download_button('Download UAT register CSV',uat.to_csv(index=False).encode(),file_name='uat_test_register.csv',mime='text/csv')
    mapping=pd.DataFrame([
      ['employee_id','Worker ID','Text','Required; unique','Exact ID match','Reject duplicate or blank'],
      ['first_name','Legal/Preferred First Name','Text','Required','Trim whitespace','Reject blank'],
      ['last_name','Legal Last Name','Text','Required','Trim whitespace','Reject blank'],
      ['department','Department / Organization','Text','Required','Map to approved department list','Flag unmapped values'],
      ['manager_id','Manager / Reports To','Text','Optional subject to rule','Map source manager ID to target worker ID','Flag unknown/self/circular manager'],
      ['job_profile','Job Profile','Text','Required for staffing','Map to approved job profile catalog','Flag unmapped values'],
      ['position_id','Position ID','Text','Required for position assignment','Map to target position ID','Reject unknown/non-open positions'],
      ['location','Location','Text','Required','Map to approved location list','Flag unmapped values'],
      ['employment_status','Worker Status','Enumerated','Active/Inactive/On Leave','Normalize approved status values','Reject unsupported values'],
    ],columns=['Source field','Illustrative target concept','Data type','Validation rule','Transformation/mapping','Exception handling'])
    st.markdown('**Source-to-target mapping workbook (CSV)**')
    st.dataframe(mapping,use_container_width=True,hide_index=True)
    st.download_button('Download source-to-target mapping',mapping.to_csv(index=False).encode(),file_name='source_to_target_mapping.csv',mime='text/csv')
    cutover=pd.DataFrame([
      ['C-01','Freeze approved source extract','Data owner','Pending','Confirm extract timestamp and version'],
      ['C-02','Back up source extract and mapping workbook','Technical lead','Pending','Store controlled copy and record checksum'],
      ['C-03','Run pre-load validation','Data migration lead','Pending','Resolve critical errors or approve documented exceptions'],
      ['C-04','Load approved records to target environment','Implementation team','Pending','Follow approved load sequence and access controls'],
      ['C-05','Reconcile counts and key identifiers','Data migration lead','Pending','Compare source, rejected, loaded, and target counts'],
      ['C-06','Execute smoke tests and priority UAT','Business and test leads','Pending','Record evidence and raise defects'],
      ['C-07','Obtain business sign-off','Process owner','Pending','Document approval and outstanding risks'],
      ['C-08','Confirm rollback/contingency readiness','Project lead','Pending','Confirm decision owner and rollback criteria'],
    ],columns=['Step','Activity','Owner role','Status','Evidence / exit criteria'])
    st.markdown('**Mock cutover checklist**')
    st.dataframe(cutover,use_container_width=True,hide_index=True)
    st.download_button('Download mock cutover checklist',cutover.to_csv(index=False).encode(),file_name='mock_cutover_checklist.csv',mime='text/csv')
    st.markdown('**Requirements traceability matrix**')
    trace=pd.DataFrame([
      ['REQ-01','Employee IDs must be unique','Data validation','UAT-001, UAT-002','Validation report'],
      ['REQ-02','Workers must reference valid managers where required','Manager hierarchy','HCM-005','Manager validation results'],
      ['REQ-03','Only Open positions may receive new primary assignment','Position assignment','UAT-004','Assignment table'],
      ['REQ-04','Transfer/promotion requires destination and approvals','Lifecycle simulator','UAT-005, UAT-006','Scenario log'],
      ['REQ-05','Loaded IDs must reconcile to source extract','Reconciliation','UAT-007','Reconciliation summary'],
    ],columns=['Requirement ID','Requirement','Design / feature','Test coverage','Evidence'])
    st.dataframe(trace,use_container_width=True,hide_index=True)
    st.download_button('Download requirements traceability matrix',trace.to_csv(index=False).encode(),file_name='requirements_traceability_matrix.csv',mime='text/csv')

with tabs[6]:
    st.subheader('Core HCM validation workbench')
    st.markdown('**Manager hierarchy validation**')
    employees=fetch_employees(DB); manager_issues=validate_manager_hierarchy(employees)
    if employees.empty: st.info('Import employees to validate manager relationships.')
    elif manager_issues.empty: st.success('No missing managers, self-management, or circular manager chains detected in the target employee data.')
    else: st.warning(f'{len(manager_issues)} manager hierarchy issue(s) detected.'); st.dataframe(manager_issues,use_container_width=True,hide_index=True)
    st.markdown('**Position and organization validation**')
    orgs=fetch_table(DB,'supervisory_orgs'); positions=fetch_table(DB,'positions'); po=validate_positions(positions,orgs)
    if po.empty: st.success('Position-to-organization checks passed.')
    else: st.dataframe(po,use_container_width=True,hide_index=True)
    st.markdown('**Suggested implementation-style test scenarios**')
    tests=pd.DataFrame([
      ['HCM-001','Create organization with valid parent','New organization references an existing parent','Pass when saved and hierarchy has no cycle'],
      ['HCM-002','Reject unknown parent organization','Parent ID is absent from organization list','Validation error; do not save'],
      ['HCM-003','Prevent duplicate position ID','Position ID already exists','Validation error; preserve original position'],
      ['HCM-004','Prevent assignment to closed/frozen position','Position is not Open','Assignment must be blocked'],
      ['HCM-005','Validate manager hierarchy','Manager does not exist or creates a cycle','Flag the relationship for correction'],
      ['HCM-006','Reconcile employee conversion','Compare source IDs with target IDs','Investigate missing and unexpected IDs'],
    ],columns=['Test ID','Scenario','Test input','Expected result'])
    st.dataframe(tests,use_container_width=True,hide_index=True)
    st.download_button('Download test scenario workbook (CSV)',tests.to_csv(index=False).encode(),file_name='core_hcm_test_scenarios.csv',mime='text/csv')

st.divider()
st.caption('Important: this is a fictional learning simulation. It is not Workday software, does not connect to Workday, and does not perform real Workday configuration. Never upload real employee personal information.')
