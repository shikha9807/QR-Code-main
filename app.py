from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from models import get_db_connection, init_db
from qr_handler import generate_qr_base64
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
import uuid
import secrets
import socket
import csv
import os
import sqlite3
import pandas as pd
import re
from functools import wraps
from io import StringIO, BytesIO

app = Flask(__name__)
# Move SECRET_KEY to environment variable with a fallback
app.secret_key = os.environ.get('SECRET_KEY', 'qr_attendance_secret_key_2026_secure')

# Ensure database is initialized
init_db()

# --- RBAC Decorator ---
def role_required(*roles):
    """Decorator to restrict route access to specific roles."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            if session.get('role') not in roles:
                flash('You do not have permission to access this page.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return wrapped
    return decorator

# Helpers
def get_local_ip():
    """Detect local network IP for network-wide QR code scanning."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def is_logged_in():
    return 'user_id' in session

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, str(email)) is not None

def process_student_import(file, mode, update_existing, admin_id):
    """
    Processes student import file.
    Returns (success_count, failure_count, errors, import_id)
    """
    filename = file.filename
    ext = os.path.splitext(filename)[1].lower()

    try:
        if ext == '.csv':
            df = pd.read_csv(file)
        elif ext in ['.xlsx', '.xls']:
            df = pd.read_excel(file)
        elif ext == '.json':
            df = pd.read_json(file)
        else:
            return 0, 0, ["Unsupported file format"], None
    except Exception as e:
        return 0, 0, [f"File read error: {str(e)}"], None

    required_cols = ['roll_number', 'full_name', 'email', 'department', 'program', 'semester', 'section']
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        return 0, 0, [f"Missing columns: {', '.join(missing_cols)}"], None

    # Pre-fetch valid departments and sections for validation
    conn = get_db_connection()
    depts = {row['name']: row['id'] for row in conn.execute('SELECT id, name FROM departments').fetchall()}
    sects = {row['section_name']: row['id'] for row in conn.execute('SELECT id, section_name FROM sections').fetchall()}
    conn.close()

    valid_records = []
    errors = []
    seen_roll_numbers = set()

    total_rows = len(df)

    for index, row in df.iterrows():
        row_num = index + 2 # 1-based and accounting for header
        row_errors = []

        # Basic presence check
        for col in required_cols:
            if pd.isna(row[col]) or str(row[col]).strip() == '':
                row_errors.append(f"Column '{col}' is blank")

        roll = str(row.get('roll_number', '')).strip()
        name = str(row.get('full_name', '')).strip()
        email = str(row.get('email', '')).strip()
        dept_name = str(row.get('department', '')).strip()
        prog = str(row.get('program', '')).strip()
        sem = row.get('semester')
        sect_name = str(row.get('section', '')).strip()

        # Roll number uniqueness in file
        if roll in seen_roll_numbers:
            row_errors.append(f"Duplicate roll number in file: {roll}")
        seen_roll_numbers.add(roll)

        # Email validation
        if email and not validate_email(email):
            row_errors.append(f"Invalid email format: {email}")

        # Semester validation
        try:
            sem_val = int(sem)
            if sem_val <= 0:
                row_errors.append(f"Semester must be a positive number: {sem}")
        except (ValueError, TypeError):
            row_errors.append(f"Invalid semester value: {sem}")

        # Department and Section existence
        dept_id = depts.get(dept_name)
        if not dept_id:
            row_errors.append(f"Department '{dept_name}' does not exist")

        sect_id = sects.get(sect_name)
        if not sect_id:
            row_errors.append(f"Section '{sect_name}' does not exist")

        if row_errors:
            errors.append({'row': row_num, 'roll': roll, 'reasons': "; ".join(row_errors)})
        else:
            valid_records.append({
                'roll_number': roll,
                'full_name': name,
                'email': email,
                'dept_id': dept_id,
                'program': prog,
                'semester': int(sem),
                'section_id': sect_id
            })

    # Import Logic
    if mode == 'all_or_nothing' and errors:
        return 0, len(errors), errors, None

    # Database Transaction
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        success_count = 0
        for rec in valid_records:
            if update_existing:
                # Update if exists, else insert
                cursor.execute('''
                    INSERT INTO students (roll_number, full_name, email, dept_id, program, semester, section_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(roll_number) DO UPDATE SET
                        full_name=excluded.full_name,
                        email=excluded.email,
                        dept_id=excluded.dept_id,
                        program=excluded.program,
                        semester=excluded.semester,
                        section_id=excluded.section_id
                ''', (rec['roll_number'], rec['full_name'], rec['email'], rec['dept_id'], rec['program'], rec['semester'], rec['section_id']))
            else:
                # Check if exists first to avoid IntegrityError if not updating
                existing = conn.execute('SELECT id FROM students WHERE roll_number = ?', (rec['roll_number'],)).fetchone()
                if existing:
                    errors.append({'row': 'DB', 'roll': rec['roll_number'], 'reasons': 'Roll number already exists in database'})
                    continue

                cursor.execute('''
                    INSERT INTO students (roll_number, full_name, email, dept_id, program, semester, section_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (rec['roll_number'], rec['full_name'], rec['email'], rec['dept_id'], rec['program'], rec['semester'], rec['section_id']))

            success_count += 1

        conn.commit()

        # Log import history
        status = 'Success' if not errors else 'Partial'
        cursor.execute('''
            INSERT INTO student_imports (filename, admin_id, total_rows, success_count, failure_count, status)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (filename, admin_id, total_rows, success_count, len(errors), status))
        import_id = cursor.lastrowid

        # Log individual errors
        for err in errors:
            cursor.execute('''
                INSERT INTO import_errors (import_id, row_num, roll_number, reasons)
                VALUES (?, ?, ?, ?)
            ''', (import_id, err.get('row'), err.get('roll'), err.get('reasons')))

        conn.commit()

        return success_count, len(errors), errors, import_id
    except Exception as e:
        conn.rollback()
        return 0, total_rows, [f"Database Error: {str(e)}"], None
    finally:
        conn.close()

@app.route('/')
def index():
    if is_logged_in():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if is_logged_in():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not username or not password:
            flash('Please enter both username and password.', 'danger')
            return render_template('login.html')

        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()

        if user:
            stored_password = user['password']
            # SAFE MIGRATION: Check hashed first, then fallback to plaintext
            is_valid = False
            needs_update = False

            if check_password_hash(stored_password, password):
                is_valid = True
            elif stored_password == password:
                is_valid = True
                needs_update = True

            if is_valid:
                if needs_update:
                    # Upgrade plaintext password to hash
                    conn = get_db_connection()
                    conn.execute('UPDATE users SET password = ? WHERE id = ?',
                                (generate_password_hash(password), user['id']))
                    conn.commit()
                    conn.close()

                session['user_id'] = user['id']
                session['username'] = user['username']
                session['role'] = user['role']
                flash(f'Welcome back, {user["username"]}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Invalid username or password!', 'danger')
        else:
            flash('Invalid username or password!', 'danger')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if is_logged_in():
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        role = request.form.get('role', 'teacher').strip()

        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('login.html', register_mode=True)

        hashed_pw = generate_password_hash(password)
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                         (username, hashed_pw, role))
            conn.commit()
            conn.close()
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            conn.close()
            flash('Username already exists. Please choose a different one.', 'danger')
            return render_template('login.html', register_mode=True)

    return render_template('login.html', register_mode=True)

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@role_required('admin', 'teacher', 'student')
def dashboard():
    user_id = session['user_id']
    role = session['role']

    conn = get_db_connection()

    # If teacher, only show their own sessions
    if role == 'teacher':
        sessions_raw = conn.execute('''
            SELECT s.*, COUNT(a.id) as attendee_count
            FROM sessions s
            LEFT JOIN attendance a ON s.id = a.session_id
            WHERE s.teacher_id = ?
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT 10
        ''', (user_id,)).fetchall()

        total_sessions = conn.execute('SELECT COUNT(*) as count FROM sessions WHERE teacher_id = ?', (user_id,)).fetchone()['count']
        total_attendance = conn.execute('''
            SELECT COUNT(a.id) as count
            FROM sessions s
            JOIN attendance a ON s.id = a.session_id
            WHERE s.teacher_id = ?
        ''', (user_id,)).fetchone()['count']
    else:
        # Admin sees everything, Student sees nothing (yet)
        sessions_raw = conn.execute('''
            SELECT s.*, COUNT(a.id) as attendee_count
            FROM sessions s
            LEFT JOIN attendance a ON s.id = a.session_id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT 10
        ''').fetchall()
        total_sessions = conn.execute('SELECT COUNT(*) as count FROM sessions').fetchone()['count']
        total_attendance = conn.execute('SELECT COUNT(*) as count FROM attendance').fetchone()['count']

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if role == 'teacher':
        active_sessions = conn.execute('SELECT COUNT(*) as count FROM sessions WHERE expiry_time > ? AND teacher_id = ?', (now_str, user_id)).fetchone()['count']
    elif role == 'admin':
        active_sessions = conn.execute('SELECT COUNT(*) as count FROM sessions WHERE expiry_time > ?', (now_str,)).fetchone()['count']
    else:
        active_sessions = 0

    conn.close()

    return render_template('dashboard.html',
                           sessions=sessions_raw,
                           total_sessions=total_sessions,
                           total_attendance=total_attendance,
                           active_sessions=active_sessions,
                           now_str=now_str)

@app.route('/start-session', methods=['POST'])
@role_required('admin', 'teacher')
def start_session():
    # Teachers can only start sessions if they are registered (we assume they are logged in)
    token = str(uuid.uuid4())
    now = datetime.now()
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')
    expiry = (now + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO sessions (teacher_id, created_at, expiry_time, token, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (session['user_id'], now_str, expiry, token, 'active'))
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()

    flash('New attendance session started! QR Code is live.', 'success')
    return redirect(url_for('view_session', session_id=session_id))

@app.route('/session/<int:session_id>')
@role_required('admin', 'teacher')
def view_session(session_id):
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()

    if not sess:
        conn.close()
        flash('Session not found.', 'danger')
        return redirect(url_for('dashboard'))

    # OWNERSHIP CHECK: Only admin or the session creator can view this session
    if session['role'] != 'admin' and sess['teacher_id'] != session['user_id']:
        conn.close()
        flash('You do not have permission to view this session.', 'danger')
        return redirect(url_for('dashboard'))

    host_parts = request.host.split(':')
    port = host_parts[1] if len(host_parts) > 1 else '5001'
    local_ip = get_local_ip()

    scan_url = f"http://{local_ip}:{port}" + url_for('mark_attendance', token=sess['token'])
    local_scan_url = f"http://127.0.0.1:{port}" + url_for('mark_attendance', token=sess['token'])

    qr_code = generate_qr_base64(scan_url)

    stats = conn.execute('SELECT COUNT(*) as count FROM attendance WHERE session_id = ?', (session_id,)).fetchone()
    attendees = conn.execute('SELECT * FROM attendance WHERE session_id = ? ORDER BY timestamp DESC', (session_id,)).fetchall()
    conn.close()

    expiry_time = datetime.strptime(sess['expiry_time'], '%Y-%m-%d %H:%M:%S')
    is_expired = datetime.now() > expiry_time
    remaining_seconds = max(0, int((expiry_time - datetime.now()).total_seconds()))

    return render_template('session.html',
                           current_session=sess,
                           qr_code=qr_code,
                           count=stats['count'],
                           attendees=attendees,
                           scan_url=scan_url,
                           local_scan_url=local_scan_url,
                           is_expired=is_expired,
                           remaining_seconds=remaining_seconds)

@app.route('/api/session-stats/<int:session_id>')
def session_stats(session_id):
    # This is an API endpoint used by JS on the session page, usually the teacher is the one viewing.
    # In a real system, we'd verify the session here too.
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not sess:
        conn.close()
        return jsonify({'error': 'Session not found'}), 404

    attendees_rows = conn.execute('SELECT student_id, timestamp FROM attendance WHERE session_id = ? ORDER BY timestamp DESC', (session_id,)).fetchall()
    conn.close()

    expiry_time = datetime.strptime(sess['expiry_time'], '%Y-%m-%d %H:%M:%S')
    is_expired = datetime.now() > expiry_time
    remaining_seconds = max(0, int((expiry_time - datetime.now()).total_seconds()))

    attendees = [{'student_id': row['student_id'], 'timestamp': row['timestamp']} for row in attendees_rows]

    return jsonify({
        'count': len(attendees),
        'students': attendees,
        'is_expired': is_expired,
        'remaining_seconds': remaining_seconds
    })

@app.route('/mark-attendance/<token>', methods=['GET', 'POST'])
def mark_attendance(token):
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE token = ?', (token,)).fetchone()

    if not sess:
        conn.close()
        return render_template('feedback.html', status='error', message='Invalid QR Code! Session does not exist.')

    expiry_time = datetime.strptime(sess['expiry_time'], '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expiry_time:
        conn.close()
        return render_template('feedback.html', status='error', message='This QR Code session has expired!')

    cookie_name = f'attended_sess_{sess["id"]}'
    if request.cookies.get(cookie_name):
        conn.close()
        return render_template('feedback.html', status='error', message='Device limit reached: Attendance has already been recorded from this device for this session.')

    if request.method == 'POST':
        student_id = request.form.get('student_name', '').strip() # Using existing field name for compatibility

        if not student_id:
            conn.close()
            return render_template('feedback.html', status='error', message='Student Name / Roll No cannot be blank!')

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            conn.execute('INSERT INTO attendance (session_id, student_id, timestamp) VALUES (?, ?, ?)',
                         (sess['id'], student_id, now_str))
            conn.commit()
            conn.close()

            resp = make_response(render_template('feedback.html',
                                                 status='success',
                                                 message=f'Attendance successfully recorded for {student_id}!',
                                                 student_name=student_id,
                                                 timestamp=now_str))
            resp.set_cookie(cookie_name, student_id, max_age=86400, httponly=True)
            return resp

        except sqlite3.IntegrityError:
            try:
                conn.close()
            except Exception:
                pass
            return render_template('feedback.html', status='error', message=f'Attendance already marked for "{student_id}" in this session!')

        except Exception as e:
            try:
                conn.close()
            except Exception:
                pass
            return render_template('feedback.html', status='error', message=f'System Error: {str(e)}')

    conn.close()
    return render_template('student_form.html', token=token, current_session=sess)

@app.route('/reports')
@role_required('admin', 'teacher')
def reports():
    user_id = session['user_id']
    role = session['role']

    conn = get_db_connection()
    if role == 'teacher':
        sessions_db = conn.execute('SELECT * FROM sessions WHERE teacher_id = ? ORDER BY created_at DESC', (user_id,)).fetchall()
    else:
        sessions_db = conn.execute('SELECT * FROM sessions ORDER BY created_at DESC').fetchall()

    report_data = []
    total_scans = 0

    for sess in sessions_db:
        attendees = conn.execute('''
            SELECT id, student_id, timestamp
            FROM attendance
            WHERE session_id = ?
            ORDER BY timestamp ASC
        ''', (sess['id'],)).fetchall()

        total_scans += len(attendees)
        report_data.append({
            'session_id': sess['id'],
            'created_at': sess['created_at'],
            'expiry_time': sess['expiry_time'],
            'token': sess['token'],
            'students': attendees,
            'count': len(attendees)
        })
    conn.close()

    return render_template('reports.html', reports=report_data, total_scans=total_scans, total_sessions=len(report_data))

@app.route('/export/<int:session_id>')
@role_required('admin', 'teacher')
def export_session(session_id):
    # OWNERSHIP CHECK: Only admin or the session creator can export this session
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not sess:
        conn.close()
        flash('Session not found.', 'danger')
        return redirect(url_for('reports'))

    if session['role'] != 'admin' and sess['teacher_id'] != session['user_id']:
        conn.close()
        flash('You do not have permission to export this session.', 'danger')
        return redirect(url_for('reports'))

    attendees = conn.execute('''
        SELECT student_id, timestamp
        FROM attendance
        WHERE session_id = ?
        ORDER BY timestamp ASC
    ''', (session_id,)).fetchall()
    conn.close()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Index', 'Student Name / Roll No', 'Timestamp', 'Session ID', 'Session Created At'])

    for idx, student in enumerate(attendees, 1):
        cw.writerow([idx, student['student_id'], student['timestamp'], session_id, sess['created_at']])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=attendance_session_{session_id}_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

@app.route('/delete-attendance/<int:session_id>/<int:attendance_id>', methods=['POST'])
@role_required('admin', 'teacher')
def delete_attendance(session_id, attendance_id):
    # OWNERSHIP CHECK
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not sess or (session['role'] != 'admin' and sess['teacher_id'] != session['user_id']):
        conn.close()
        flash('Permission denied.', 'danger')
        return redirect(url_for('reports'))

    conn.execute('DELETE FROM attendance WHERE id = ? AND session_id = ?', (attendance_id, session_id))
    conn.commit()
    conn.close()

    flash('Attendance record removed.', 'success')
    return redirect(url_for('reports'))

@app.route('/delete-session/<int:session_id>', methods=['POST'])
@role_required('admin', 'teacher')
def delete_session(session_id):
    # OWNERSHIP CHECK
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not sess or (session['role'] != 'admin' and sess['teacher_id'] != session['user_id']):
        conn.close()
        flash('Permission denied.', 'danger')
        return redirect(url_for('reports'))

    conn.execute('DELETE FROM attendance WHERE session_id = ?', (session_id,))
    conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
    conn.commit()
    conn.close()

    flash('Session and all associated attendance records deleted.', 'success')
    return redirect(url_for('reports'))

# --- ADMIN MANAGEMENT ROUTES ---

@app.route('/admin')
@role_required('admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')

@app.route('/admin/import-students', methods=['GET', 'POST'])
@role_required('admin')
def import_students():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file uploaded.', 'danger')
            return redirect(url_for('import_students'))

        file = request.files['file']
        if file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('import_students'))

        mode = request.form.get('mode', 'skip_invalid')
        update_existing = 'update' in request.form

        success, failures, errors, import_id = process_student_import(
            file, mode, update_existing, session['user_id']
        )

        if errors and success == 0 and import_id is None:
            # Critical failure or "All or Nothing" failed
            flash('Import failed. Please check the errors.', 'danger')
            # Pass errors to the template
            return render_template('import_students.html', errors=errors, summary=None)

        # Success or Partial success
        summary = {
            'total': success + (failures if failures else 0),
            'success': success,
            'failures': failures,
            'import_id': import_id
        }
        return render_template('import_summary.html', summary=summary, errors=errors)

    return render_template('import_students.html')

@app.route('/admin/import-students/template/<ext>')
@role_required('admin')
def import_template(ext):
    # Create sample data
    data = {
        'roll_number': ['2024CS01', '2024CS02'],
        'full_name': ['Alice Smith', 'Bob Jones'],
        'email': ['alice@university.edu', 'bob@university.edu'],
        'department': ['Computer Science', 'Computer Science'],
        'program': ['B.Tech', 'B.Tech'],
        'semester': [1, 1],
        'section': ['Section A', 'Section A']
    }
    df = pd.DataFrame(data)

    if ext == 'csv':
        si = StringIO()
        df.to_csv(si, index=False)
        resp = make_response(si.getvalue())
        resp.headers["Content-Disposition"] = "attachment; filename=student_template.csv"
        resp.headers["Content-type"] = "text/csv"
    elif ext == 'xlsx':
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Students')
        resp = make_response(out.getvalue())
        resp.headers["Content-Disposition"] = "attachment; filename=student_template.xlsx"
        resp.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        return "Unsupported format", 400

    return resp

@app.route('/admin/import-students/report/<int:import_id>')
@role_required('admin')
def import_report(import_id):
    conn = get_db_connection()
    errors = conn.execute('''
        SELECT row_num, roll_number, reasons
        FROM import_errors
        WHERE import_id = ?
    ''', (import_id,)).fetchall()
    conn.close()

    if not errors:
        return "No errors found for this import.", 404

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Row Number', 'Roll Number', 'Error Reasons'])
    for err in errors:
        cw.writerow([err['row_num'], err['roll_number'], err['reasons']])

    resp = make_response(si.getvalue())
    resp.headers["Content-Disposition"] = f"attachment; filename=import_errors_{import_id}.csv"
    resp.headers["Content-type"] = "text/csv"
    return resp

@app.route('/admin/departments', methods=['GET', 'POST'])
@role_required('admin')
def manage_departments():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        code = request.form.get('code', '').strip()
        if name and code:
            conn = get_db_connection()
            try:
                conn.execute('INSERT INTO departments (name, code) VALUES (?, ?)', (name, code))
                conn.commit()
                flash('Department added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Department name or code already exists.', 'danger')
            finally:
                conn.close()
        else:
            flash('All fields are required.', 'danger')

    conn = get_db_connection()
    depts = conn.execute('SELECT * FROM departments').fetchall()
    conn.close()
    return render_template('manage_departments.html', departments=depts)

@app.route('/admin/courses', methods=['GET', 'POST'])
@role_required('admin')
def manage_courses():
    if request.method == 'POST':
        code = request.form.get('course_code', '').strip()
        name = request.form.get('course_name', '').strip()
        dept_id = request.form.get('dept_id', '').strip()
        semester = request.form.get('semester', '').strip()
        if code and name and dept_id and semester:
            conn = get_db_connection()
            try:
                conn.execute('INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES (?, ?, ?, ?)',
                             (code, name, int(dept_id), int(semester)))
                conn.commit()
                flash('Course added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Course code already exists.', 'danger')
            finally:
                conn.close()
        else:
            flash('All fields are required.', 'danger')

    conn = get_db_connection()
    courses = conn.execute('''
        SELECT c.*, d.name as dept_name
        FROM courses c
        JOIN departments d ON c.dept_id = d.id
    ''').fetchall()
    depts = conn.execute('SELECT * FROM departments').fetchall()
    conn.close()
    return render_template('manage_courses.html', courses=courses, departments=depts)

@app.route('/admin/sections', methods=['GET', 'POST'])
@role_required('admin')
def manage_sections():
    if request.method == 'POST':
        name = request.form.get('section_name', '').strip()
        course_id = request.form.get('course_id', '').strip()
        if name and course_id:
            conn = get_db_connection()
            try:
                conn.execute('INSERT INTO sections (section_name, course_id) VALUES (?, ?)', (name, int(course_id)))
                conn.commit()
                flash('Section added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Section already exists.', 'danger')
            finally:
                conn.close()
        else:
            flash('All fields are required.', 'danger')

    conn = get_db_connection()
    sections = conn.execute('''
        SELECT s.*, c.course_name
        FROM sections s
        JOIN courses c ON s.course_id = c.id
    ''').fetchall()
    courses = conn.execute('SELECT * FROM courses').fetchall()
    conn.close()
    return render_template('manage_sections.html', sections=sections, courses=courses)

@app.route('/admin/students', methods=['GET', 'POST'])
@role_required('admin')
def manage_students():
    search = request.args.get('search', '').strip()
    dept_filter = request.args.get('dept_id', '').strip()
    sect_filter = request.args.get('section_id', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page

    if request.method == 'POST':
        roll = request.form.get('roll_number', '').strip()
        name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        dept_id = request.form.get('dept_id', '').strip()
        prog = request.form.get('program', '').strip()
        sem = request.form.get('semester', '').strip()
        sect_id = request.form.get('section_id', '').strip()

        if all([roll, name, email, dept_id, prog, sem, sect_id]):
            conn = get_db_connection()
            try:
                conn.execute('''
                    INSERT INTO students (roll_number, full_name, email, dept_id, program, semester, section_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (roll, name, email, int(dept_id), prog, int(sem), int(sect_id)))
                conn.commit()
                flash('Student added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Roll number or Email already exists.', 'danger')
            finally:
                conn.close()
        else:
            flash('All fields are required.', 'danger')

    conn = get_db_connection()

    # Build query for students
    query = "SELECT s.*, d.name as dept_name, sec.section_name FROM students s JOIN departments d ON s.dept_id = d.id JOIN sections sec ON s.section_id = sec.id"
    params = []
    where_clauses = []

    if search:
        where_clauses.append("(s.roll_number LIKE ? OR s.full_name LIKE ?)")
        params.extend([f'%{search}%', f'%{search}%'])
    if dept_filter:
        where_clauses.append("s.dept_id = ?")
        params.append(dept_filter)
    if sect_filter:
        where_clauses.append("s.section_id = ?")
        params.append(sect_filter)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    # Get total count for pagination
    count_query = f"SELECT COUNT(*) as count FROM students s JOIN departments d ON s.dept_id = d.id JOIN sections sec ON s.section_id = sec.id"
    if where_clauses:
        count_query += " WHERE " + " AND ".join(where_clauses)
    total_students = conn.execute(count_query, params).fetchone()['count']

    # Get paginated results
    paginated_query = query + f" ORDER BY s.roll_number LIMIT {per_page} OFFSET {offset}"
    students = conn.execute(paginated_query, params).fetchall()

    depts = conn.execute('SELECT * FROM departments').fetchall()
    sections = conn.execute('SELECT * FROM sections').fetchall()
    conn.close()

    return render_template('manage_students.html',
                           students=students,
                           departments=depts,
                           sections=sections,
                           search=search,
                           dept_filter=dept_filter,
                           sect_filter=sect_filter,
                           page=page,
                           total_pages=(total_students + per_page - 1) // per_page,
                           total_students=total_students)

@app.route('/admin/teachers', methods=['GET', 'POST'])
@role_required('admin')
def manage_teachers():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username and password:
            hashed_pw = generate_password_hash(password)
            conn = get_db_connection()
            try:
                conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)', (username, hashed_pw, 'teacher'))
                conn.commit()
                flash('Teacher account created successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Username already exists.', 'danger')
            finally:
                conn.close()
        else:
            flash('All fields are required.', 'danger')

    conn = get_db_connection()
    teachers = conn.execute("SELECT * FROM users WHERE role = 'teacher'").fetchall()
    conn.close()
    return render_template('manage_teachers.html', teachers=teachers)

@app.route('/admin/assign-teacher', methods=['POST'])
@role_required('admin')
def assign_teacher():
    teacher_id = request.form.get('teacher_id', '').strip()
    course_id = request.form.get('course_id', '').strip()
    section_id = request.form.get('section_id', '').strip()
    if teacher_id and course_id and section_id:
        conn = get_db_connection()
        try:
            conn.execute('INSERT INTO teacher_assignments (teacher_id, course_id, section_id) VALUES (?, ?, ?)',
                         (int(teacher_id), int(course_id), int(section_id)))
            conn.commit()
            flash('Assignment successful!', 'success')
        except sqlite3.IntegrityError:
            flash('This assignment already exists.', 'danger')
        finally:
            conn.close()
    else:
        flash('All fields are required.', 'danger')
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"🚀 QR Code Attendance System starting on port {port}...")
    print(f"📡 Local Network Address: http://{get_local_ip()}:{port}")
    print(f"💻 Localhost Address:     http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
