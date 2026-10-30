"""
Data Handler Module
Supports importing and exporting student attendance datasets across multiple formats:
- CSV
- JSON
- Excel (.xlsx)
- SQLite Database
- Pandas DataFrame
"""

import os
import json
import sqlite3
import pandas as pd

def load_csv(filepath):
    """Loads dataset from a CSV file into a pandas DataFrame."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"CSV file not found at: {filepath}")
    return pd.read_csv(filepath)

def load_json(filepath):
    """Loads dataset from a JSON file into a pandas DataFrame."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"JSON file not found at: {filepath}")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return pd.DataFrame(data)

def load_excel(filepath, sheet_name=0):
    """Loads dataset from an Excel (.xlsx / .xls) file into a pandas DataFrame."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Excel file not found at: {filepath}")
    return pd.read_excel(filepath, sheet_name=sheet_name)

def load_database(db_path, table_name="students"):
    """Loads dataset from a SQLite database table into a pandas DataFrame."""
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found at: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
    finally:
        conn.close()
    return df

def save_csv(df, filepath):
    """Exports a pandas DataFrame to a CSV file."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    df.to_csv(filepath, index=False)
    print(f" Saved CSV to: {filepath}")

def save_json(df, filepath, orient="records", indent=2):
    """Exports a pandas DataFrame to a formatted JSON file."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(json.loads(df.to_json(orient=orient)), f, indent=indent)
    print(f" Saved JSON to: {filepath}")

def save_excel(df, filepath, sheet_name="Attendance Data"):
    """Exports a pandas DataFrame to an Excel (.xlsx) file."""
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    print(f" Saved Excel to: {filepath}")

def save_database(df, db_path, table_name="attendance_predictions", if_exists="replace"):
    """Exports a pandas DataFrame to a SQLite database table."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        print(f" Saved Database table '{table_name}' to: {db_path}")
    finally:
        conn.close()

def load_data(source, format_type=None, **kwargs):
    """
    Unified loader that dynamically imports data based on file extension or explicit format_type.
    """
    if isinstance(source, pd.DataFrame):
        return source.copy()
    
    if not isinstance(source, str):
        raise ValueError("Source must be a file path, database URI, or pandas DataFrame.")

    ext = os.path.splitext(source)[1].lower() if not format_type else f".{format_type.lower().lstrip('.')}"

    if ext == ".csv":
        return load_csv(source)
    elif ext == ".json":
        return load_json(source)
    elif ext in [".xlsx", ".xls"]:
        return load_excel(source, **kwargs)
    elif ext in [".db", ".sqlite", ".sqlite3"]:
        table_name = kwargs.get("table_name", "students")
        return load_database(source, table_name=table_name)
    else:
        raise ValueError(f"Unsupported data format '{ext}'. Supported formats: CSV, JSON, Excel (.xlsx), SQLite (.db).")


COLUMN_ALIASES = {
    'roll_number': ['roll_number', 'roll no', 'roll_no', 'student_id', 'student id'],
    'full_name': ['full_name', 'full name', 'student_name', 'student name', 'name'],
    'email': ['email', 'email_id', 'email id', 'student_email'],
    'department': ['department', 'dept', 'dept_name', 'course', 'programme_dept'],
    'program': ['program', 'programme', 'course', 'course_name'],
    'semester': ['semester', 'sem'],
    'section': ['section', 'section_name', 'class_section'],
    'total_classes': ['total_classes', 'total classes', 'conducted_classes'],
    'classes_attended': ['classes_attended', 'classes attended', 'attended_classes'],
    'classes_missed': ['classes_missed', 'classes missed'],
    'attendance_percentage': ['attendance_percentage', 'attendance percentage', 'attendance_pct'],
    'predicted_status': ['predicted_status', 'predicted status', 'attendance_status'],
    'predicted_risk_tier': ['predicted_risk_tier', 'predicted risk tier', 'risk_tier'],
    'risk_score': ['risk_score', 'risk score'],
    'projected_final_attendance': ['projected_final_attendance', 'projected final attendance'],
    'confidence_score': ['confidence_score', 'confidence score'],
    'prescriptive_action_plan': ['prescriptive_action_plan', 'prescriptive action plan'],
}


def _normalize_col_name(name):
    return str(name).strip().lower().replace('-', '_').replace(' ', '_')


def normalize_student_columns(df):
    """Maps dataset / import columns (Student_ID, Course, ...) onto the university schema names."""
    if df is None or df.empty:
        return df

    rename_map = {}
    normalized_existing = {_normalize_col_name(c): c for c in df.columns}

    for canonical, aliases in COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue
        for alias in aliases:
            alias_key = _normalize_col_name(alias)
            if alias_key in normalized_existing:
                source_col = normalized_existing[alias_key]
                if source_col != canonical and canonical not in rename_map.values():
                    rename_map[source_col] = canonical
                    break

    if rename_map:
        df = df.rename(columns=rename_map)

    # If Course was mapped to department, copy it to program when program is missing
    if 'department' in df.columns and 'program' not in df.columns:
        df['program'] = df['department']
    if 'program' in df.columns and 'department' not in df.columns:
        df['department'] = df['program']

    return df


def _dept_code_from_name(name):
    words = [w for w in str(name).replace('&', ' ').replace('/', ' ').split() if w]
    letters = ''.join(w[0].upper() for w in words if w[0].isalpha())
    code = (letters or str(name)[:4].upper())[:10]
    return code


def ensure_department_course_section(conn, dept_name, section_name='A'):
    """Creates department, a matching course, and section if they do not already exist."""
    dept_name = (dept_name or '').strip() or 'General Academic'
    section_name = (section_name or '').strip() or 'A'

    row = conn.execute('SELECT id FROM departments WHERE name = ?', (dept_name,)).fetchone()
    if row:
        dept_id = row['id'] if isinstance(row, sqlite3.Row) else row[0]
    else:
        code = _dept_code_from_name(dept_name)
        existing_code = conn.execute('SELECT id FROM departments WHERE code = ?', (code,)).fetchone()
        if existing_code:
            code = f"{code}{existing_code['id'] if isinstance(existing_code, sqlite3.Row) else existing_code[0]}"
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO departments (name, code) VALUES (?, ?)', (dept_name, code))
            dept_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            row = conn.execute('SELECT id FROM departments WHERE name = ?', (dept_name,)).fetchone()
            dept_id = row['id'] if isinstance(row, sqlite3.Row) else row[0]

    course = conn.execute(
        'SELECT id FROM courses WHERE dept_id = ? AND course_name = ?',
        (dept_id, dept_name)
    ).fetchone()
    if course:
        course_id = course['id'] if isinstance(course, sqlite3.Row) else course[0]
    else:
        course_code = f"{_dept_code_from_name(dept_name)}101"
        existing = conn.execute('SELECT id FROM courses WHERE course_code = ?', (course_code,)).fetchone()
        if existing:
            course_code = f"{course_code}-{dept_id}"
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES (?, ?, ?, ?)',
            (course_code, dept_name, dept_id, 1)
        )
        course_id = cursor.lastrowid

    section = conn.execute(
        'SELECT id FROM sections WHERE section_name = ? AND course_id = ?',
        (section_name, course_id)
    ).fetchone()
    if section:
        section_id = section['id'] if isinstance(section, sqlite3.Row) else section[0]
    else:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO sections (section_name, course_id) VALUES (?, ?)', (section_name, course_id))
        section_id = cursor.lastrowid

    return dept_id, course_id, section_id


def _safe_int(value, default=None):
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == '':
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=None):
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == '':
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_dataset_paths(base_dir):
    return {
        'students': [
            os.path.join(base_dir, 'data', 'students_2000.json'),
            os.path.join(base_dir, 'students_2000.json'),
            os.path.join(base_dir, 'data', 'students_2000.csv'),
            os.path.join(base_dir, 'students_2000.csv'),
        ],
        'predictions': [
            os.path.join(base_dir, 'attendance_predictions.csv'),
            os.path.join(base_dir, 'attendance_predictions.json'),
            os.path.join(base_dir, 'data', 'attendance_predictions.csv'),
        ],
    }


def sync_dataset_to_sqlite(db_path, base_dir=None):
    """
    Loads the project's student/attendance dataset files into the university SQLite schema.
    Uses real JSON/CSV values (no fabricated attendance). Idempotent via roll_number upsert.
    """
    base_dir = base_dir or os.path.dirname(os.path.abspath(db_path))
    paths = _candidate_dataset_paths(base_dir)

    students_path = next((p for p in paths['students'] if os.path.exists(p)), None)
    if not students_path:
        print("Dataset sync skipped: no students_2000.json/csv found.")
        return {'synced': 0, 'reason': 'no_student_file'}

    df = load_data(students_path)
    df = normalize_student_columns(df)

    pred_path = next((p for p in paths['predictions'] if os.path.exists(p)), None)
    if pred_path:
        pred_df = normalize_student_columns(load_data(pred_path))
        if 'roll_number' in pred_df.columns:
            extra_cols = [c for c in pred_df.columns if c not in df.columns or c == 'roll_number']
            df = df.merge(pred_df[extra_cols], on='roll_number', how='left')

    if 'roll_number' not in df.columns or 'full_name' not in df.columns:
        raise ValueError(
            f"Dataset at {students_path} is missing required identity columns after mapping. "
            f"Found: {list(df.columns)}"
        )

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        synced = 0
        for _, row in df.iterrows():
            roll = str(row.get('roll_number', '')).strip()
            name = str(row.get('full_name', '')).strip()
            if not roll or not name or roll.lower() == 'nan':
                continue

            dept_name = str(row.get('department') or row.get('program') or 'General Academic').strip()
            program = str(row.get('program') or dept_name).strip()
            section_name = str(row.get('section') or 'A').strip()
            if section_name.lower() in ('nan', 'none', ''):
                section_name = 'A'

            email = str(row.get('email') or '').strip()
            if not email or email.lower() in ('nan', 'none'):
                email = f"{roll.lower().replace(' ', '.')}@university.edu"

            semester = _safe_int(row.get('semester'), 1)
            total_classes = _safe_int(row.get('total_classes'))
            classes_attended = _safe_int(row.get('classes_attended'))
            classes_missed = _safe_int(row.get('classes_missed'))
            if classes_missed is None and total_classes is not None and classes_attended is not None:
                classes_missed = max(0, total_classes - classes_attended)
            attendance_percentage = _safe_float(row.get('attendance_percentage'))
            if attendance_percentage is None and total_classes:
                attendance_percentage = round((classes_attended or 0) / total_classes * 100.0, 2)

            dept_id, course_id, section_id = ensure_department_course_section(conn, dept_name, section_name)

            conn.execute('''
                INSERT INTO students (
                    roll_number, full_name, email, dept_id, program, semester, section_id,
                    total_classes, classes_attended, classes_missed, attendance_percentage,
                    predicted_status, predicted_risk_tier, risk_score,
                    projected_final_attendance, confidence_score, prescriptive_action_plan
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(roll_number) DO UPDATE SET
                    full_name=excluded.full_name,
                    email=excluded.email,
                    dept_id=excluded.dept_id,
                    program=excluded.program,
                    semester=excluded.semester,
                    section_id=excluded.section_id,
                    total_classes=excluded.total_classes,
                    classes_attended=excluded.classes_attended,
                    classes_missed=excluded.classes_missed,
                    attendance_percentage=excluded.attendance_percentage,
                    predicted_status=excluded.predicted_status,
                    predicted_risk_tier=excluded.predicted_risk_tier,
                    risk_score=excluded.risk_score,
                    projected_final_attendance=excluded.projected_final_attendance,
                    confidence_score=excluded.confidence_score,
                    prescriptive_action_plan=excluded.prescriptive_action_plan
            ''', (
                roll, name, email, dept_id, program, semester, section_id,
                total_classes, classes_attended, classes_missed, attendance_percentage,
                None if pd.isna(row.get('predicted_status')) else str(row.get('predicted_status')) if row.get('predicted_status') is not None else None,
                None if pd.isna(row.get('predicted_risk_tier')) else str(row.get('predicted_risk_tier')) if row.get('predicted_risk_tier') is not None else None,
                _safe_float(row.get('risk_score')),
                _safe_float(row.get('projected_final_attendance')),
                _safe_float(row.get('confidence_score')),
                None if pd.isna(row.get('prescriptive_action_plan')) else str(row.get('prescriptive_action_plan')) if row.get('prescriptive_action_plan') is not None else None,
            ))

            student_row = conn.execute('SELECT id FROM students WHERE roll_number = ?', (roll,)).fetchone()
            if student_row:
                student_id = student_row['id']
                conn.execute('''
                    INSERT OR IGNORE INTO enrollments (student_id, course_id, section_id)
                    VALUES (?, ?, ?)
                ''', (student_id, course_id, section_id))
            synced += 1

        conn.commit()
        print(f"Dataset sync complete: {synced} students from {os.path.basename(students_path)}")
        return {'synced': synced, 'source': students_path, 'predictions': pred_path}
    finally:
        conn.close()
