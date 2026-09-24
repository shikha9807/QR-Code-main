from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response, send_file
from models import get_db_connection, init_db
from qr_handler import generate_qr_base64
from datetime import datetime, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import uuid
import secrets
import socket
import csv
import os
import sqlite3
import pandas as pd
import json
import re
from functools import wraps
from io import StringIO, BytesIO
from ai_predictor import AIAttendancePredictor
from leave_manager import (
    LeaveCalculator, LeaveWorkflowManager, SystemSettingsManager,
    NotificationManager, AuditLogger
)
from leave_ai_service import AILeaveExtractor, AILeaveAssistant, AIDocumentOCR

app = Flask(__name__)
# Move SECRET_KEY to environment variable with a fallback
app.secret_key = os.environ.get('SECRET_KEY', 'qr_attendance_secret_key_2026_secure')

# Upload Configuration for Leave Documents
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads', 'leave_documents')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB limit
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Ensure database is initialized
init_db()

# --- Global Context Processor for Notifications & Roles ---
@app.context_processor
def inject_global_data():
    if 'user_id' in session:
        conn = get_db_connection()
        user_id = session['user_id']
        role = session.get('role', 'teacher')
        unread_notifs = NotificationManager.get_unread_count(conn, user_id)
        notifs_list = NotificationManager.get_user_notifications(conn, user_id, limit=5)
        
        pending_leave_count = 0
        if role in ['teacher', 'hod', 'admin']:
            pending_query = "SELECT COUNT(*) as count FROM leave_requests WHERE status IN ('PENDING_FACULTY', 'PENDING_HOD')"
            pending_row = conn.execute(pending_query).fetchone()
            pending_leave_count = pending_row['count'] if pending_row else 0
        elif role == 'student':
            roll_number = session.get('username')
            student_pending = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE roll_number = ? AND status LIKE 'PENDING%'", (roll_number,)).fetchone()
            pending_leave_count = student_pending['count'] if student_pending else 0

        conn.close()
        return {
            'unread_notif_count': unread_notifs,
            'recent_notifications': notifs_list,
            'pending_leave_badge_count': pending_leave_count
        }
    return {'unread_notif_count': 0, 'recent_notifications': [], 'pending_leave_badge_count': 0}

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
@role_required('admin', 'teacher', 'hod', 'student')
def dashboard():
    user_id = session['user_id']
    role = session['role']
    username = session.get('username')

    conn = get_db_connection()

    # If student, redirect or load student portal view
    if role == 'student':
        student = LeaveCalculator.get_student(conn, username)
        att_summary = LeaveCalculator.get_student_attendance_summary(conn, student['roll_number'])
        threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)
        recent_leaves = conn.execute("""
            SELECT lr.*, lt.name as leave_type_name 
            FROM leave_requests lr
            JOIN leave_types lt ON lr.leave_type_id = lt.id
            WHERE lr.roll_number = ?
            ORDER BY lr.created_at DESC LIMIT 5
        """, (student['roll_number'],)).fetchall()
        sim_data = LeaveCalculator.simulate_what_if(conn, student['roll_number'])
        conn.close()

        return render_template('dashboard.html',
                               is_student=True,
                               student=student,
                               att_summary=att_summary,
                               threshold=threshold,
                               recent_leaves=recent_leaves,
                               sim_data=sim_data)

    # If HOD, redirect to dedicated HOD executive dashboard
    if role == 'hod':
        conn.close()
        return redirect(url_for('hod_leave_dashboard'))

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
        # Admin sees everything
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

    # Fetch AI Retention Summary for Proactive Alert Banner
    try:
        _, ai_summary = AIAttendancePredictor.analyze_all_students(
            conn, teacher_id=user_id if role == 'teacher' else None
        )
    except Exception:
        ai_summary = None

    # Fetch Pending Leave Requests count
    pending_leaves = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status IN ('PENDING_FACULTY', 'PENDING_HOD')").fetchone()['count']

    conn.close()

    return render_template('dashboard.html',
                           sessions=sessions_raw,
                           total_sessions=total_sessions,
                           total_attendance=total_attendance,
                           active_sessions=active_sessions,
                           ai_summary=ai_summary,
                           pending_leaves=pending_leaves,
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

# --- AI RISK PREDICTOR & RETENTION ANALYTICS ROUTES ---

@app.route('/ai-risk-analytics')
@role_required('admin', 'teacher')
def ai_risk_analytics():
    search = request.args.get('search', '').strip()
    dept_filter = request.args.get('dept_id', '').strip()
    sect_filter = request.args.get('section_id', '').strip()
    risk_filter = request.args.get('risk', 'ALL').strip()

    conn = get_db_connection()
    teacher_id = session['user_id'] if session.get('role') == 'teacher' else None

    students, summary = AIAttendancePredictor.analyze_all_students(
        conn,
        dept_id=dept_filter if dept_filter else None,
        section_id=sect_filter if sect_filter else None,
        search=search if search else None,
        risk_filter=risk_filter if risk_filter != 'ALL' else None,
        teacher_id=teacher_id
    )

    departments = conn.execute('SELECT * FROM departments ORDER BY name ASC').fetchall()
    sections = conn.execute('SELECT * FROM sections ORDER BY section_name ASC').fetchall()
    conn.close()

    return render_template('ai_risk_analytics.html',
                           students=students,
                           summary=summary,
                           departments=departments,
                           sections=sections,
                           search=search,
                           dept_filter=dept_filter,
                           sect_filter=sect_filter,
                           risk_filter=risk_filter)

@app.route('/api/ai-risk-summary')
@role_required('admin', 'teacher')
def api_ai_risk_summary():
    conn = get_db_connection()
    teacher_id = session['user_id'] if session.get('role') == 'teacher' else None
    _, summary = AIAttendancePredictor.analyze_all_students(conn, teacher_id=teacher_id)
    conn.close()
    return jsonify(summary)

@app.route('/api/ai-student-analysis/<roll_number>')
@role_required('admin', 'teacher')
def api_ai_student_analysis(roll_number):
    conn = get_db_connection()
    teacher_id = session['user_id'] if session.get('role') == 'teacher' else None
    analysis = AIAttendancePredictor.get_student_detail(conn, roll_number, teacher_id=teacher_id)
    conn.close()
    return jsonify(analysis)

@app.route('/api/ai-generate-notice', methods=['POST'])
@role_required('admin', 'teacher')
def api_ai_generate_notice():
    data = request.get_json() or {}
    roll_number = data.get('roll_number', '').strip()
    if not roll_number:
        return jsonify({'error': 'Roll number is required'}), 400

    conn = get_db_connection()
    teacher_id = session['user_id'] if session.get('role') == 'teacher' else None
    analysis = AIAttendancePredictor.get_student_detail(conn, roll_number, teacher_id=teacher_id)
    conn.close()

    notice_text = AIAttendancePredictor.generate_notice_text(analysis)
    return jsonify({'notice': notice_text, 'analysis': analysis})

@app.route('/export-risk-report')
@role_required('admin', 'teacher')
def export_risk_report():
    search = request.args.get('search', '').strip()
    dept_filter = request.args.get('dept_id', '').strip()
    sect_filter = request.args.get('section_id', '').strip()
    risk_filter = request.args.get('risk', 'ALL').strip()

    conn = get_db_connection()
    teacher_id = session['user_id'] if session.get('role') == 'teacher' else None

    students, _ = AIAttendancePredictor.analyze_all_students(
        conn,
        dept_id=dept_filter if dept_filter else None,
        section_id=sect_filter if sect_filter else None,
        search=search if search else None,
        risk_filter=risk_filter if risk_filter != 'ALL' else None,
        teacher_id=teacher_id
    )
    conn.close()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow([
        'Roll Number', 'Full Name', 'Department', 'Section', 'Email',
        'Total Sessions', 'Attended', 'Missed', 'Current Attendance %',
        'AI Projected Semester %', 'Risk Tier', 'Risk Score (0-100)',
        'Momentum Trend', 'Absence Streak', 'AI Prescriptive Recovery Plan', 'Most Missed Day'
    ])

    for st in students:
        cw.writerow([
            st['roll_number'],
            st['full_name'],
            st['department'],
            st['section'],
            st['email'],
            st['total_sessions'],
            st['attended_count'],
            st['missed_count'],
            f"{st['current_pct']}%",
            f"{st['projected_final_pct']}%",
            st['risk_level'],
            st['risk_score'],
            st['trend_label'],
            st['current_absence_streak'],
            st['recovery_message'],
            st['most_missed_day']
        ])

    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=ai_defaulter_risk_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    output.headers["Content-type"] = "text/csv; charset=utf-8"
    return output

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


# ==============================================================================
# AI-BASED LEAVE MANAGEMENT & ATTENDANCE IMPACT PREDICTION MODULE ROUTES
# ==============================================================================

# --- STUDENT LEAVE APPLICATION & NLP EXTRACTION ---

@app.route('/student/leave/apply', methods=['GET', 'POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def apply_leave():
    conn = get_db_connection()
    user_id = session.get('user_id')
    username = session.get('username')
    role = session.get('role')

    # Find student profile
    student = LeaveCalculator.get_student(conn, username)
    roll_number = student['roll_number']

    if request.method == 'POST':
        applied_via = request.form.get('applied_via', 'form').strip()
        leave_type_id = request.form.get('leave_type_id', '').strip()
        start_date = request.form.get('start_date', '').strip()
        end_date = request.form.get('end_date', '').strip()
        reason = request.form.get('reason', '').strip()
        description = request.form.get('description', '').strip()
        override_roll = request.form.get('roll_number', '').strip()

        if override_roll and role in ['admin', 'teacher', 'hod']:
            roll_number = override_roll
            student = LeaveCalculator.get_student(conn, roll_number)

        if not leave_type_id or not start_date or not end_date or not reason:
            flash('Please fill in all mandatory fields (Leave Type, Dates, Reason).', 'danger')
            leave_types = conn.execute("SELECT * FROM leave_types WHERE is_active = 1 ORDER BY name ASC").fetchall()
            att_summary = LeaveCalculator.get_student_attendance_summary(conn, roll_number)
            conn.close()
            return render_template('leave_apply.html', student=student, leave_types=leave_types, att_summary=att_summary)

        # Process file upload if provided
        file_data = None
        if 'document' in request.files:
            file = request.files['document']
            if file and file.filename != '' and allowed_file(file.filename):
                safe_orig_name = secure_filename(file.filename)
                unique_name = f"doc_{uuid.uuid4().hex[:10]}_{safe_orig_name}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
                file.save(file_path)

                file_size = os.path.getsize(file_path)
                file_ext = os.path.splitext(safe_orig_name)[1].lower()

                # Run OCR Assistant
                ocr_result = AIDocumentOCR.extract_document_text(file_path)

                file_data = {
                    'filename': unique_name,
                    'original_filename': safe_orig_name,
                    'file_path': file_path,
                    'file_size': file_size,
                    'file_type': file_ext,
                    'ocr_text': ocr_result.get('text', ''),
                    'ocr_status': ocr_result.get('status', 'PROCESSED')
                }

        ip_address = request.remote_addr or '127.0.0.1'
        success, msg, leave_id = LeaveWorkflowManager.submit_leave_request(
            conn, user_id=user_id, roll_number=roll_number,
            leave_type_id=int(leave_type_id), start_date_str=start_date, end_date_str=end_date,
            reason=reason, description=description, applied_via=applied_via,
            file_data=file_data, ip_address=ip_address
        )
        conn.commit()
        conn.close()

        if success:
            flash(f'Leave application (#LEAVE-{leave_id}) submitted successfully! AI impact calculated.', 'success')
            return redirect(url_for('student_leave_history'))
        else:
            flash(f'Error submitting leave: {msg}', 'danger')
            return redirect(url_for('apply_leave'))

    leave_types = conn.execute("SELECT * FROM leave_types WHERE is_active = 1 ORDER BY name ASC").fetchall()
    att_summary = LeaveCalculator.get_student_attendance_summary(conn, roll_number)
    threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)
    conn.close()

    return render_template('leave_apply.html',
                           student=student,
                           leave_types=leave_types,
                           att_summary=att_summary,
                           threshold=threshold)

@app.route('/api/ai/extract-leave', methods=['POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def api_extract_leave():
    """Extracts structured leave parameters from natural language text using AI NLP."""
    data = request.get_json() or {}
    text = data.get('text', '').strip()
    if not text:
        return jsonify({'success': False, 'error': 'No input text provided.'}), 400

    extracted = AILeaveExtractor.extract_leave_intent(text)

    conn = get_db_connection()
    leave_types = conn.execute("SELECT id, name, code FROM leave_types WHERE is_active = 1").fetchall()
    
    # Map code to leave_type_id
    type_id = None
    for lt in leave_types:
        if lt['code'].upper() == extracted['leave_type_code'].upper():
            type_id = lt['id']
            break
    if not type_id and leave_types:
        type_id = leave_types[0]['id']

    extracted['leave_type_id'] = type_id

    # Compute immediate impact preview
    username = session.get('username')
    student = LeaveCalculator.get_student(conn, username)
    impact = LeaveCalculator.calculate_leave_impact(
        conn, student['roll_number'], extracted['start_date'], extracted['end_date'],
        leave_type_code=extracted['leave_type_code']
    )
    subject_impacts = LeaveCalculator.calculate_subject_wise_impact(
        conn, student['roll_number'], extracted['start_date'], extracted['end_date']
    )
    conn.close()

    return jsonify({
        'success': True,
        'extracted': extracted,
        'impact': impact,
        'subject_impacts': subject_impacts
    })

@app.route('/api/attendance/impact-preview', methods=['POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def api_impact_preview():
    """Calculates live overall and subject-wise impact for selected dates."""
    data = request.get_json() or {}
    roll_number = data.get('roll_number') or session.get('username')
    start_date = data.get('start_date', '').strip()
    end_date = data.get('end_date', '').strip()
    leave_type_id = data.get('leave_type_id')

    if not start_date or not end_date:
        return jsonify({'error': 'Start and End dates are required.'}), 400

    conn = get_db_connection()
    impact = LeaveCalculator.calculate_leave_impact(conn, roll_number, start_date, end_date, leave_type_id=leave_type_id)
    subject_impacts = LeaveCalculator.calculate_subject_wise_impact(conn, roll_number, start_date, end_date)
    conn.close()

    return jsonify({
        'impact': impact,
        'subject_impacts': subject_impacts
    })


# --- WHAT-IF ATTENDANCE SIMULATOR ---

@app.route('/student/leave/simulator')
@role_required('admin', 'student', 'teacher', 'hod')
def student_simulator():
    conn = get_db_connection()
    username = session.get('username')
    student = LeaveCalculator.get_student(conn, username)
    sim_data = LeaveCalculator.simulate_what_if(conn, student['roll_number'])
    conn.close()

    return render_template('leave_simulator.html', student=student, sim=sim_data)

@app.route('/api/attendance/simulate', methods=['POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def api_simulate():
    data = request.get_json() or {}
    roll_number = data.get('roll_number') or session.get('username')
    custom_miss = data.get('custom_miss')

    conn = get_db_connection()
    sim_data = LeaveCalculator.simulate_what_if(conn, roll_number, custom_miss=custom_miss)
    conn.close()

    return jsonify(sim_data)


# --- STUDENT LEAVE HISTORY ---

@app.route('/student/leave/history')
@role_required('admin', 'student', 'teacher', 'hod')
def student_leave_history():
    conn = get_db_connection()
    username = session.get('username')
    student = LeaveCalculator.get_student(conn, username)
    roll_number = student['roll_number']

    status_filter = request.args.get('status', 'ALL')
    type_filter = request.args.get('type', 'ALL')

    query = """
        SELECT lr.*, lt.name as leave_type_name, lt.code as leave_type_code,
               (SELECT original_filename FROM leave_documents WHERE leave_request_id = lr.id LIMIT 1) as doc_name,
               (SELECT id FROM leave_documents WHERE leave_request_id = lr.id LIMIT 1) as doc_id
        FROM leave_requests lr
        JOIN leave_types lt ON lr.leave_type_id = lt.id
        WHERE lr.roll_number = ?
    """
    params = [roll_number]

    if status_filter != 'ALL':
        query += " AND lr.status = ?"
        params.append(status_filter)

    if type_filter != 'ALL':
        query += " AND lr.leave_type_id = ?"
        params.append(type_filter)

    query += " ORDER BY lr.created_at DESC"
    requests_list = conn.execute(query, params).fetchall()
    leave_types = conn.execute("SELECT * FROM leave_types ORDER BY name ASC").fetchall()
    att_summary = LeaveCalculator.get_student_attendance_summary(conn, roll_number)
    conn.close()

    return render_template('leave_history.html',
                           student=student,
                           requests=requests_list,
                           leave_types=leave_types,
                           att_summary=att_summary,
                           status_filter=status_filter,
                           type_filter=type_filter)

@app.route('/api/leave/<int:leave_id>/details')
@role_required('admin', 'student', 'teacher', 'hod')
def api_leave_details(leave_id):
    """Retrieves full leave details, approval timeline history, and subject breakdown."""
    conn = get_db_connection()
    user_role = session.get('role')
    username = session.get('username')

    leave = conn.execute("""
        SELECT lr.*, lt.name as leave_type_name, lt.code as leave_type_code,
               s.full_name as student_name, s.email as student_email,
               d.name as dept_name, sec.section_name
        FROM leave_requests lr
        LEFT JOIN leave_types lt ON lr.leave_type_id = lt.id
        LEFT JOIN students s ON lr.roll_number = s.roll_number
        LEFT JOIN departments d ON s.dept_id = d.id
        LEFT JOIN sections sec ON s.section_id = sec.id
        WHERE lr.id = ?
    """, (leave_id,)).fetchone()

    if not leave:
        conn.close()
        return jsonify({'error': 'Leave request not found.'}), 404

    # Security check for student role
    if user_role == 'student' and leave['roll_number'] != username:
        conn.close()
        return jsonify({'error': 'Unauthorized access.'}), 403

    # Fetch workflow timeline
    timeline = conn.execute("""
        SELECT la.*, u.username as approver_username, u.full_name as approver_fullname
        FROM leave_approvals la
        LEFT JOIN users u ON la.approver_id = u.id
        WHERE la.leave_request_id = ?
        ORDER BY la.timestamp ASC
    """, (leave_id,)).fetchall()

    # Fetch document
    doc = conn.execute("SELECT * FROM leave_documents WHERE leave_request_id = ?", (leave_id,)).fetchone()

    # Calculate subject breakdown
    subjects = LeaveCalculator.calculate_subject_wise_impact(conn, leave['roll_number'], leave['start_date'], leave['end_date'])
    conn.close()

    return jsonify({
        'leave': dict(leave),
        'timeline': [dict(t) for t in timeline],
        'document': dict(doc) if doc else None,
        'subjects': subjects
    })


# --- AI CONVERSATIONAL ASSISTANT ---

@app.route('/student/leave/ai-assistant')
@role_required('admin', 'student', 'teacher', 'hod')
def ai_assistant_view():
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    conn.close()
    return render_template('leave_ai_assistant.html', user=user)

@app.route('/api/ai/chat', methods=['POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def api_ai_chat():
    data = request.get_json() or {}
    query = data.get('query', '').strip()
    if not query:
        return jsonify({'reply': 'Please type a question or request.'}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    reply = AILeaveAssistant.process_query(conn, dict(user), query)
    conn.close()

    return jsonify({'reply': reply})


# --- FACULTY LEAVE MANAGEMENT & APPROVAL PANEL ---

@app.route('/faculty/leave-requests')
@role_required('admin', 'teacher', 'hod')
def faculty_leave_dashboard():
    conn = get_db_connection()
    role = session.get('role')
    user_id = session.get('user_id')

    status_filter = request.args.get('status', 'ALL')
    risk_filter = request.args.get('risk', 'ALL')
    type_filter = request.args.get('type', 'ALL')
    dept_filter = request.args.get('dept_id', 'ALL')
    search = request.args.get('search', '').strip()

    requests_list = LeaveWorkflowManager.get_filtered_leave_requests(
        conn, role=role, user_id=user_id,
        status_filter=status_filter if status_filter != 'ALL' else None,
        risk_filter=risk_filter if risk_filter != 'ALL' else None,
        leave_type_filter=type_filter if type_filter != 'ALL' else None,
        dept_filter=dept_filter if dept_filter != 'ALL' else None,
        search=search if search else None
    )

    leave_types = conn.execute("SELECT * FROM leave_types ORDER BY name ASC").fetchall()
    departments = conn.execute("SELECT * FROM departments ORDER BY name ASC").fetchall()
    
    # Counts
    pending_count = sum(1 for r in requests_list if 'PENDING' in r['status'])
    high_risk_count = sum(1 for r in requests_list if r['risk_level'] == 'HIGH_RISK')
    approved_count = sum(1 for r in requests_list if r['status'] == 'APPROVED')

    conn.close()

    return render_template('leave_faculty_dashboard.html',
                           requests=requests_list,
                           leave_types=leave_types,
                           departments=departments,
                           status_filter=status_filter,
                           risk_filter=risk_filter,
                           type_filter=type_filter,
                           dept_filter=dept_filter,
                           search=search,
                           pending_count=pending_count,
                           high_risk_count=high_risk_count,
                           approved_count=approved_count)

@app.route('/api/leave/<int:leave_id>/action', methods=['POST'])
@role_required('admin', 'teacher', 'hod')
def api_process_leave_action(leave_id):
    """Processes approval actions: APPROVE, REJECT, FORWARD_TO_HOD, REQUEST_CLARIFICATION."""
    data = request.get_json() or {}
    action = data.get('action', '').strip()
    remarks = data.get('remarks', '').strip()

    if not action:
        return jsonify({'error': 'Action is required.'}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (session['user_id'],)).fetchone()
    ip_address = request.remote_addr or '127.0.0.1'

    success, msg = LeaveWorkflowManager.process_approval_action(
        conn, leave_id, dict(user), action=action, remarks=remarks, ip_address=ip_address
    )
    conn.commit()
    conn.close()

    if success:
        return jsonify({'success': True, 'message': msg})
    return jsonify({'success': False, 'error': msg}), 400


# --- HOD EXECUTIVE DASHBOARD & QUEUE ---

@app.route('/hod/leave-dashboard')
@role_required('admin', 'hod')
def hod_leave_dashboard():
    conn = get_db_connection()
    user_id = session.get('user_id')
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    dept_id = user['dept_id'] if user else None

    # HOD KPI Statistics
    total_reqs = conn.execute("SELECT COUNT(*) as count FROM leave_requests").fetchone()['count']
    pending_hod = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'PENDING_HOD'").fetchone()['count']
    pending_faculty = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'PENDING_FACULTY'").fetchone()['count']
    approved_total = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'APPROVED'").fetchone()['count']
    high_risk_total = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE risk_level = 'HIGH_RISK'").fetchone()['count']

    # Escalated queue
    escalated_requests = LeaveWorkflowManager.get_filtered_leave_requests(conn, role='hod', status_filter='PENDING_HOD')

    # Department-wise Breakdown
    dept_stats = conn.execute("""
        SELECT d.name as dept_name,
               COUNT(lr.id) as total_leaves,
               SUM(CASE WHEN lr.status = 'APPROVED' THEN 1 ELSE 0 END) as approved_leaves,
               SUM(CASE WHEN lr.risk_level = 'HIGH_RISK' THEN 1 ELSE 0 END) as high_risk_leaves
        FROM departments d
        LEFT JOIN students s ON d.id = s.dept_id
        LEFT JOIN leave_requests lr ON s.roll_number = lr.roll_number
        GROUP BY d.id
    """).fetchall()

    conn.close()

    return render_template('leave_hod_dashboard.html',
                           total_reqs=total_reqs,
                           pending_hod=pending_hod,
                           pending_faculty=pending_faculty,
                           approved_total=approved_total,
                           high_risk_total=high_risk_total,
                           escalated_requests=escalated_requests,
                           dept_stats=dept_stats)

@app.route('/hod/leave-requests')
@role_required('admin', 'hod')
def hod_leave_requests():
    return redirect(url_for('faculty_leave_dashboard', status='PENDING_HOD'))


# --- ADMIN LEAVE CONFIGURATION, TIMETABLE & CALENDAR ---

@app.route('/admin/leave-settings')
@role_required('admin')
def admin_leave_settings():
    conn = get_db_connection()
    threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)
    hod_threshold = SystemSettingsManager.get_int(conn, 'hod_approval_days_threshold', 3)
    duty_comp = SystemSettingsManager.get_setting(conn, 'duty_leave_counts_as_present', '1')

    leave_types = conn.execute("SELECT * FROM leave_types ORDER BY id ASC").fetchall()
    audit_logs = conn.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 30").fetchall()
    conn.close()

    return render_template('manage_leave_settings.html',
                           threshold=threshold,
                           hod_threshold=hod_threshold,
                           duty_comp=duty_comp,
                           leave_types=leave_types,
                           audit_logs=audit_logs)

@app.route('/admin/leave-settings/update-thresholds', methods=['POST'])
@role_required('admin')
def update_leave_thresholds():
    threshold = request.form.get('attendance_threshold', '75.0').strip()
    hod_days = request.form.get('hod_approval_days_threshold', '3').strip()
    duty_comp = '1' if 'duty_leave_counts_as_present' in request.form else '0'

    conn = get_db_connection()
    SystemSettingsManager.set_setting(conn, 'attendance_threshold', threshold, 'University Minimum Attendance Threshold %')
    SystemSettingsManager.set_setting(conn, 'hod_approval_days_threshold', hod_days, 'Days threshold for mandatory HOD review')
    SystemSettingsManager.set_setting(conn, 'duty_leave_counts_as_present', duty_comp, 'Whether duty leave is compensated as attended')

    AuditLogger.log(conn, session['user_id'], session['username'], 'UPDATE_SETTINGS', 'system_settings', None,
                    f"Updated threshold={threshold}%, hod_days={hod_days}, duty_comp={duty_comp}", request.remote_addr)
    conn.commit()
    conn.close()

    flash('System settings updated successfully!', 'success')
    return redirect(url_for('admin_leave_settings'))

@app.route('/admin/leave-settings/leave-type', methods=['POST'])
@role_required('admin')
def add_leave_type():
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip().upper()
    description = request.form.get('description', '').strip()
    max_days = int(request.form.get('max_days', 10))
    requires_doc = 1 if 'requires_document' in request.form else 0
    requires_hod = 1 if 'requires_hod_approval' in request.form else 0

    if name and code:
        conn = get_db_connection()
        try:
            conn.execute("""
                INSERT INTO leave_types (name, code, description, max_days, requires_document, requires_hod_approval)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, code, description, max_days, requires_doc, requires_hod))
            conn.commit()
            flash('New leave type created successfully!', 'success')
        except sqlite3.IntegrityError:
            flash('Leave type name or code already exists.', 'danger')
        finally:
            conn.close()
    else:
        flash('Name and Code are required.', 'danger')

    return redirect(url_for('admin_leave_settings'))

@app.route('/admin/leave-settings/leave-type/toggle/<int:type_id>', methods=['POST'])
@role_required('admin')
def toggle_leave_type(type_id):
    conn = get_db_connection()
    lt = conn.execute("SELECT is_active FROM leave_types WHERE id = ?", (type_id,)).fetchone()
    if lt:
        new_val = 0 if lt['is_active'] == 1 else 1
        conn.execute("UPDATE leave_types SET is_active = ? WHERE id = ?", (new_val, type_id))
        conn.commit()
        flash('Leave type status updated.', 'info')
    conn.close()
    return redirect(url_for('admin_leave_settings'))

@app.route('/admin/timetable', methods=['GET', 'POST'])
@role_required('admin')
def manage_timetable():
    conn = get_db_connection()
    if request.method == 'POST':
        course_id = request.form.get('course_id')
        section_id = request.form.get('section_id')
        day_of_week = request.form.get('day_of_week')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        room = request.form.get('room')
        teacher_id = request.form.get('teacher_id') or None

        if course_id and section_id and day_of_week and start_time and end_time:
            conn.execute("""
                INSERT INTO timetable (course_id, section_id, day_of_week, start_time, end_time, room, teacher_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (int(course_id), int(section_id), day_of_week, start_time, end_time, room, teacher_id))
            conn.commit()
            flash('Timetable slot added successfully!', 'success')
        else:
            flash('Please complete all required schedule fields.', 'danger')

    timetable_slots = conn.execute("""
        SELECT t.*, c.course_code, c.course_name, s.section_name, u.full_name as teacher_name
        FROM timetable t
        JOIN courses c ON t.course_id = c.id
        JOIN sections s ON t.section_id = s.id
        LEFT JOIN users u ON t.teacher_id = u.id
        ORDER BY CASE t.day_of_week
            WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3
            WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 ELSE 7 END,
            t.start_time ASC
    """).fetchall()

    courses = conn.execute("SELECT * FROM courses ORDER BY course_code ASC").fetchall()
    sections = conn.execute("SELECT * FROM sections ORDER BY section_name ASC").fetchall()
    teachers = conn.execute("SELECT * FROM users WHERE role = 'teacher' ORDER BY username ASC").fetchall()
    conn.close()

    return render_template('manage_leave_settings.html',
                           tab='timetable',
                           timetable=timetable_slots,
                           courses=courses,
                           sections=sections,
                           teachers=teachers)

@app.route('/admin/timetable/delete/<int:slot_id>', methods=['POST'])
@role_required('admin')
def delete_timetable_slot(slot_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM timetable WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()
    flash('Timetable slot removed.', 'info')
    return redirect(url_for('manage_timetable'))

@app.route('/admin/holidays', methods=['GET', 'POST'])
@role_required('admin')
def manage_holidays():
    conn = get_db_connection()
    if request.method == 'POST':
        event_date = request.form.get('event_date', '').strip()
        title = request.form.get('title', '').strip()
        is_holiday = 1 if 'is_holiday' in request.form else 0

        if event_date and title:
            try:
                conn.execute("""
                    INSERT INTO academic_calendar (event_date, title, is_holiday)
                    VALUES (?, ?, ?)
                    ON CONFLICT(event_date) DO UPDATE SET title = excluded.title, is_holiday = excluded.is_holiday
                """, (event_date, title, is_holiday))
                conn.commit()
                flash('Holiday/Event saved to academic calendar!', 'success')
            except Exception as e:
                flash(f'Error saving event: {str(e)}', 'danger')
        else:
            flash('Date and Title are required.', 'danger')

    holidays = conn.execute("SELECT * FROM academic_calendar ORDER BY event_date ASC").fetchall()
    conn.close()

    return render_template('manage_leave_settings.html', tab='holidays', holidays=holidays)

@app.route('/admin/holidays/delete/<int:holiday_id>', methods=['POST'])
@role_required('admin')
def delete_holiday(holiday_id):
    conn = get_db_connection()
    conn.execute("DELETE FROM academic_calendar WHERE id = ?", (holiday_id,))
    conn.commit()
    conn.close()
    flash('Holiday event removed.', 'info')
    return redirect(url_for('manage_holidays'))


# --- LEAVE REPORTS & EXPORT ENGINE ---

@app.route('/leave/reports')
@role_required('admin', 'teacher', 'hod')
def leave_reports():
    conn = get_db_connection()
    dept_filter = request.args.get('dept_id', 'ALL')
    status_filter = request.args.get('status', 'ALL')
    risk_filter = request.args.get('risk', 'ALL')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    requests_list = LeaveWorkflowManager.get_filtered_leave_requests(
        conn, status_filter=status_filter if status_filter != 'ALL' else None,
        risk_filter=risk_filter if risk_filter != 'ALL' else None,
        dept_filter=dept_filter if dept_filter != 'ALL' else None,
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None
    )

    departments = conn.execute("SELECT * FROM departments ORDER BY name ASC").fetchall()
    leave_types = conn.execute("SELECT * FROM leave_types ORDER BY name ASC").fetchall()
    conn.close()

    return render_template('leave_reports.html',
                           requests=requests_list,
                           departments=departments,
                           leave_types=leave_types,
                           dept_filter=dept_filter,
                           status_filter=status_filter,
                           risk_filter=risk_filter,
                           start_date=start_date,
                           end_date=end_date)

@app.route('/leave/export/<string:export_format>')
@role_required('admin', 'teacher', 'hod')
def export_leave_report(export_format):
    conn = get_db_connection()
    requests_list = LeaveWorkflowManager.get_filtered_leave_requests(conn)
    conn.close()

    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    if export_format == 'csv':
        si = StringIO()
        cw = csv.writer(si)
        cw.writerow([
            'Leave ID', 'Roll Number', 'Student Name', 'Department', 'Section',
            'Leave Type', 'Start Date', 'End Date', 'Total Days', 'Affected Classes',
            'Current Attendance %', 'Projected Attendance %', 'Risk Level', 'Status', 'Reason', 'Applied At'
        ])
        for r in requests_list:
            cw.writerow([
                f"#LEAVE-{r['id']}", r['roll_number'], r.get('student_name', ''), r.get('dept_name', ''),
                r.get('section_name', ''), r.get('leave_type_name', ''), r['start_date'], r['end_date'],
                r['total_days'], r['affected_classes'], f"{r['current_attendance_pct']}%",
                f"{r['projected_attendance_pct']}%", r['risk_level'], r['status'], r['reason'], r['created_at']
            ])
        output = make_response(si.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=leave_impact_report_{timestamp_str}.csv"
        output.headers["Content-type"] = "text/csv; charset=utf-8"
        return output

    elif export_format == 'json':
        output = make_response(json.dumps(requests_list, indent=2, default=str))
        output.headers["Content-Disposition"] = f"attachment; filename=leave_impact_report_{timestamp_str}.json"
        output.headers["Content-type"] = "application/json"
        return output

    elif export_format == 'excel':
        df = pd.DataFrame(requests_list)
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Leave_Impact_Report')
        output = make_response(out.getvalue())
        output.headers["Content-Disposition"] = f"attachment; filename=leave_impact_report_{timestamp_str}.xlsx"
        output.headers["Content-type"] = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return output

    flash('Unsupported export format.', 'danger')
    return redirect(url_for('leave_reports'))


# --- IN-APP NOTIFICATIONS & SECURE DOCUMENT VIEWING ---

@app.route('/api/notifications')
@role_required('admin', 'student', 'teacher', 'hod')
def api_get_notifications():
    conn = get_db_connection()
    notifs = NotificationManager.get_user_notifications(conn, session['user_id'], limit=15)
    unread = NotificationManager.get_unread_count(conn, session['user_id'])
    conn.close()
    return jsonify({'notifications': [dict(n) for n in notifs], 'unread_count': unread})

@app.route('/api/notifications/read/<int:notif_id>', methods=['POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def api_mark_notif_read(notif_id):
    conn = get_db_connection()
    NotificationManager.mark_as_read(conn, notif_id, session['user_id'])
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/notifications/read-all', methods=['POST'])
@role_required('admin', 'student', 'teacher', 'hod')
def api_mark_all_notifs_read():
    conn = get_db_connection()
    NotificationManager.mark_all_as_read(conn, session['user_id'])
    conn.commit()
    conn.close()
    return jsonify({'success': True})

@app.route('/leave/document/<int:doc_id>')
@role_required('admin', 'student', 'teacher', 'hod')
def view_leave_document(doc_id):
    """Secure, authenticated document download/view route."""
    conn = get_db_connection()
    doc = conn.execute("SELECT ld.*, lr.roll_number FROM leave_documents ld JOIN leave_requests lr ON ld.leave_request_id = lr.id WHERE ld.id = ?", (doc_id,)).fetchone()
    conn.close()

    if not doc:
        flash('Document not found.', 'danger')
        return redirect(url_for('dashboard'))

    # Security check: Students can only view their own uploaded documents
    if session.get('role') == 'student' and doc['roll_number'] != session.get('username'):
        flash('Unauthorized: You cannot access other students’ documents.', 'danger')
        return redirect(url_for('dashboard'))

    file_path = doc['file_path']
    if not os.path.exists(file_path):
        flash('Document file is missing from storage.', 'danger')
        return redirect(url_for('dashboard'))

    return send_file(file_path, as_attachment=False, download_name=doc['original_filename'])

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"🚀 QR Code Attendance System starting on port {port}...")
    print(f"📡 Local Network Address: http://{get_local_ip()}:{port}")
    print(f"💻 Localhost Address:     http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)
