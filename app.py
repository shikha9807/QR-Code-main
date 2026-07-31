from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response
from models import get_db_connection
from qr_handler import generate_qr_base64
from datetime import datetime, timedelta
import uuid
import secrets
import socket
import csv
from io import StringIO
from flask import make_response

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# Middlewares/Helpers
def get_local_ip():
    try:
        # Connect to an external server to determine the local IP used for internet
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

def is_logged_in():
    return 'user_id' in session

@app.route('/')
def index():
    if is_logged_in():
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', 
                            (username, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials!')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
def dashboard():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    sessions = conn.execute('SELECT * FROM sessions ORDER BY created_at DESC LIMIT 5').fetchall()
    conn.close()
    
    return render_template('dashboard.html', sessions=sessions)

@app.route('/start-session', methods=['POST'])
def start_session():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    token = str(uuid.uuid4())
    # Session valid for 10 minutes
    expiry = (datetime.now() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO sessions (teacher_id, expiry_time, token) VALUES (?, ?, ?)',
                 (session['user_id'], expiry, token))
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return redirect(url_for('view_session', session_id=session_id))

@app.route('/session/<int:session_id>')
def view_session(session_id):
    if not is_logged_in():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    
    if not sess:
        conn.close()
        return "Session not found", 404
        
    # Generate full URL for student scan
    # In a real scenario, this would be the actual domain
    # Use local IP for network accessibility
    local_ip = get_local_ip()
    port = 5000 # Assuming default port
    # scan_url = request.host_url + url_for('mark_attendance', token=sess['token'])[1:]
    scan_url = f"http://{local_ip}:{port}" + url_for('mark_attendance', token=sess['token'])
    qr_code = generate_qr_base64(scan_url)
    
    # Get attendance count
    stats = conn.execute('SELECT COUNT(*) as count FROM attendance WHERE session_id = ?', (session_id,)).fetchone()
    conn.close()
    
    return render_template('session.html', session=sess, qr_code=qr_code, count=stats['count'])

@app.route('/api/session-stats/<int:session_id>')
def session_stats(session_id):
    if not is_logged_in():
        return jsonify({'error': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    count = conn.execute('SELECT COUNT(*) as count FROM attendance WHERE session_id = ?', (session_id,)).fetchone()['count']
    conn.close()
    
    return jsonify({'count': count})

@app.route('/mark-attendance/<token>', methods=['GET', 'POST'])
def mark_attendance(token):
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE token = ?', (token,)).fetchone()
    
    if not sess:
        conn.close()
        return render_template('feedback.html', status='error', message='Invalid QR Code!')

    # Check expiry
    expiry_time = datetime.strptime(sess['expiry_time'], '%Y-%m-%d %H:%M:%S')
    if datetime.now() > expiry_time:
        conn.close()
        return render_template('feedback.html', status='error', message='QR Code has expired!')

    # DEVICE CHECK: Prevent multiple marks from same browser
    if request.cookies.get(f'attended_{sess["id"]}'):
         conn.close()
         return render_template('feedback.html', status='error', message='Device limit reached: Attendance already marked from this device!')

    if request.method == 'POST':
        student_name = request.form.get('student_name')
        
        if not student_name:
             conn.close()
             return render_template('feedback.html', status='error', message='Name/Roll No cannot be empty!')
             
        student_name = student_name.strip()
        
        if not student_name:
             conn.close()
             return render_template('feedback.html', status='error', message='Name/Roll No cannot be empty!')
        
        print(f"Received attendance request for: {student_name} in Session {sess['id']}")

        try:
            conn.execute('INSERT INTO attendance (session_id, student_id) VALUES (?, ?)',
                        (sess['id'], student_name))
            conn.commit()
            conn.close()
            
            print(f"Successfully marked attendance for {student_name}")
            
            # Set cookie to bind this device
            resp = make_response(render_template('feedback.html', status='success', message=f'Attendance marked for {student_name}!'))
            resp.set_cookie(f'attended_{sess["id"]}', 'true', max_age=60*60*24) # 1 day expiry
            return resp
            
        except sqlite3.IntegrityError:
            print(f"Duplicate attendance attempted for {student_name}")
            try:
                conn.close()
            except:
                pass
            return render_template('feedback.html', status='error', message='Attendance already marked for this Name/Roll No!')
            
        except Exception as e:
            print(f"CRITICAL ERROR in mark_attendance: {e}")
            try:
                conn.close()
            except:
                pass
            return render_template('feedback.html', status='error', message=f'System Error: {str(e)}')
    
    conn.close()
    return render_template('student_form.html', token=token)

@app.route('/reports')
def reports():
    if not is_logged_in():
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    
    # Get all sessions ordered by date
    sessions_db = conn.execute('SELECT * FROM sessions ORDER BY created_at DESC').fetchall()
    
    report_data = []
    
    for sess in sessions_db:
        attendees = conn.execute('''
            SELECT student_id, timestamp 
            FROM attendance 
            WHERE session_id = ? 
            ORDER BY timestamp ASC
        ''', (sess['id'],)).fetchall()
        
        report_data.append({
            'session_id': sess['id'],
            'date': sess['created_at'],
            'expiry': sess['expiry_time'],
            'students': attendees
        })
        
    conn.close()
    
    return render_template('reports.html', reports=report_data)

@app.route('/export/<int:session_id>')
def export_session(session_id):
    if not is_logged_in():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    sess = conn.execute('SELECT * FROM sessions WHERE id = ?', (session_id,)).fetchone()
    if not sess:
        conn.close()
        return "Session not found", 404
        
    attendees = conn.execute('''
        SELECT student_id, timestamp 
        FROM attendance 
        WHERE session_id = ? 
        ORDER BY timestamp ASC
    ''', (session_id,)).fetchall()
    conn.close()
    
    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['Student Name/Roll No', 'Timestamp', 'Session ID', 'Session Date'])
    
    for student in attendees:
        cw.writerow([student['student_id'], student['timestamp'], session_id, sess['created_at']])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=attendance_session_{session_id}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/delete-attendance/<int:session_id>/<string:student_id>', methods=['POST'])
def delete_attendance(session_id, student_id):
    if not is_logged_in():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    conn.execute('DELETE FROM attendance WHERE session_id = ? AND student_id = ?', 
                 (session_id, student_id))
    conn.commit()
    conn.close()
    
    flash('Attendance record deleted successfully.')
    return redirect(url_for('reports'))

@app.route('/delete-session/<int:session_id>', methods=['POST'])
def delete_session(session_id):
    if not is_logged_in():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    # First delete all attendance records for this session
    conn.execute('DELETE FROM attendance WHERE session_id = ?', (session_id,))
    # Then delete the session itself
    conn.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
    conn.commit()
    conn.close()
    
    flash('Session and all associated records deleted successfully.')
    return redirect(url_for('reports'))

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
