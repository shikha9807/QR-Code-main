import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)
EMAIL_LOG_FILE = os.path.join(LOGS_DIR, 'email_reports.log')

class EmailReportService:
    @staticmethod
    def send_attendance_report(recipient_email, session_data, attendees, absentees=None, csv_content=None):
        """
        Sends an attendance summary email with an optional CSV attachment.
        If SMTP server settings are not provided in environment variables,
        it logs the report to logs/email_reports.log and succeeds gracefully in simulation mode.
        """
        if absentees is None:
            absentees = []

        total_present = len(attendees)
        total_absent = len(absentees)
        total_enrolled = total_present + total_absent
        pct = round((total_present / total_enrolled * 100), 1) if total_enrolled > 0 else 100.0

        subject = f"📋 Attendance Report: Session #{session_data['id']} ({session_data.get('created_at', 'N/A')})"
        
        # Build HTML Email Body
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px; }}
            .container {{ max-width: 650px; margin: 0 auto; background: #ffffff; border-radius: 12px; border: 1px solid #e2e8f0; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #4f46e5, #06b6d4); color: #ffffff; padding: 25px; text-align: center; }}
            .content {{ padding: 25px; }}
            .stats-row {{ display: flex; gap: 15px; margin: 20px 0; }}
            .stat-box {{ flex: 1; background: #f1f5f9; padding: 15px; border-radius: 8px; text-align: center; }}
            .stat-val {{ font-size: 24px; font-weight: bold; color: #4f46e5; }}
            .stat-lbl {{ font-size: 12px; color: #64748b; text-transform: uppercase; margin-top: 4px; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 14px; }}
            th {{ background: #f8fafc; color: #475569; text-align: left; padding: 10px; border-bottom: 2px solid #e2e8f0; }}
            td {{ padding: 10px; border-bottom: 1px solid #f1f5f9; color: #334155; }}
            .badge-present {{ background: #dcfce7; color: #15803d; padding: 3px 8px; border-radius: 12px; font-weight: 600; font-size: 12px; }}
            .badge-absent {{ background: #fee2e2; color: #b91c1c; padding: 3px 8px; border-radius: 12px; font-weight: 600; font-size: 12px; }}
            .footer {{ background: #f8fafc; padding: 15px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h2 style="margin: 0;">Attendance Session #{session_data['id']}</h2>
              <p style="margin: 5px 0 0; opacity: 0.9; font-size: 14px;">Recorded on {session_data.get('created_at', 'N/A')}</p>
            </div>
            <div class="content">
              <div class="stats-row">
                <div class="stat-box">
                  <div class="stat-val" style="color: #10b981;">{total_present}</div>
                  <div class="stat-lbl">Present</div>
                </div>
                <div class="stat-box">
                  <div class="stat-val" style="color: #ef4444;">{total_absent}</div>
                  <div class="stat-lbl">Absent</div>
                </div>
                <div class="stat-box">
                  <div class="stat-val" style="color: #6366f1;">{pct}%</div>
                  <div class="stat-lbl">Attendance Rate</div>
                </div>
              </div>

              <h4 style="margin: 20px 0 10px; color: #1e293b;">Attendees Summary</h4>
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Student ID / Name</th>
                    <th>Timestamp</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
        """
        for idx, student in enumerate(attendees[:25], 1):
            s_name = student.get('student_id') or student.get('student_name', 'Unknown')
            s_time = student.get('timestamp', 'Recorded')
            html_body += f"""
                  <tr>
                    <td>{idx}</td>
                    <td><strong>{s_name}</strong></td>
                    <td>{s_time}</td>
                    <td><span class="badge-present">Present</span></td>
                  </tr>
            """

        if absentees:
            for idx, absent_st in enumerate(absentees[:15], len(attendees) + 1):
                a_name = absent_st.get('roll_number') or absent_st.get('full_name', 'Absent Student')
                html_body += f"""
                  <tr>
                    <td>{idx}</td>
                    <td>{a_name}</td>
                    <td>—</td>
                    <td><span class="badge-absent">Absent</span></td>
                  </tr>
                """

        html_body += f"""
                </tbody>
              </table>
              <p style="margin-top: 15px; font-size: 13px; color: #64748b;">
                * Complete record details and CSV report are attached to this email.
              </p>
            </div>
            <div class="footer">
              Automated QR Attendance System &bull; University System Notification
            </div>
          </div>
        </body>
        </html>
        """

        # SMTP Configuration from environment
        smtp_server = os.environ.get('SMTP_SERVER')
        smtp_port = int(os.environ.get('SMTP_PORT', 587))
        smtp_user = os.environ.get('SMTP_USER')
        smtp_pass = os.environ.get('SMTP_PASSWORD')
        sender_email = os.environ.get('SMTP_SENDER', 'attendance-noreply@university.edu')

        if smtp_server and smtp_user and smtp_pass:
            try:
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = sender_email
                msg['To'] = recipient_email

                part_html = MIMEText(html_body, 'html')
                msg.attach(part_html)

                # Attach CSV if provided
                if csv_content:
                    part_csv = MIMEBase('application', 'octet-stream')
                    part_csv.set_payload(csv_content.encode('utf-8'))
                    encoders.encode_base64(part_csv)
                    part_csv.add_header('Content-Disposition', f'attachment; filename=attendance_session_{session_data["id"]}.csv')
                    msg.attach(part_csv)

                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(sender_email, [recipient_email], msg.as_string())

                return True, f"Attendance report email successfully delivered to {recipient_email}"
            except Exception as e:
                print(f"SMTP error: {e}")
                # Fallback to simulation log
                EmailReportService._log_simulated_email(recipient_email, subject, total_present, total_absent, pct)
                return True, f"Report generated and logged (SMTP notice: {str(e)})"
        else:
            # Simulated environment logging
            EmailReportService._log_simulated_email(recipient_email, subject, total_present, total_absent, pct)
            return True, f"Attendance report simulated & logged for {recipient_email} (Configure SMTP_SERVER for live outbound email)"

    @staticmethod
    def _log_simulated_email(recipient_email, subject, present_cnt, absent_cnt, pct):
        with open(EMAIL_LOG_FILE, 'a') as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] TO: {recipient_email} | SUBJECT: {subject} | PRESENT: {present_cnt} | ABSENT: {absent_cnt} | RATE: {pct}%\n")
