"""
Realistic 2,000 Student Dataset Generator
Generates coherent, statistically correlated academic and attendance records for 2,000 university students.
Exports into:
- students_2000.csv
- students_2000.json
- students_2000.xlsx
- attendance.db (or test_students.db)
"""

import random
import numpy as np
import pandas as pd
from data_handler import save_csv, save_json, save_excel, save_database

FIRST_NAMES_MALE = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
    "Shaurya", "Atharva", "Advik", "Pranav", "Advaith", "Aaryan", "Dhruv", "Kabir", "Rohan", "Vikram",
    "Karan", "Rahul", "Nikhil", "Amit", "Manish", "Siddharth", "Sameer", "Harsh", "Dev", "Aniket"
]

FIRST_NAMES_FEMALE = [
    "Diya", "Saanvi", "Ananya", "Aadhya", "Pari", "Chiara", "Myra", "Avani", "Isha", "Riya",
    "Sneha", "Pooja", "Neha", "Tanvi", "Shreya", "Kavya", "Anushka", "Meera", "Swati", "Nandini",
    "Divya", "Aditi", "Pallavi", "Roshni", "Simran", "Muskan", "Kritika", "Deepika", "Ritika", "Gauri"
]

LAST_NAMES = [
    "Sharma", "Verma", "Patel", "Singh", "Kumar", "Gupta", "Iyer", "Nair", "Reddy", "Rao",
    "Joshi", "Mishra", "Mehta", "Bose", "Das", "Choudhury", "Bhat", "Deshmukh", "Chauhan", "Saxena",
    "Agarwal", "Chatterjee", "Kulkarni", "Pandey", "Kapoor", "Malhotra", "Shetty", "Pillai", "Yadav", "Ghosh"
]

COURSES = [
    "Computer Science & Engineering",
    "Information Technology",
    "Data Science & AI",
    "Electronics & Communication",
    "Mechanical Engineering",
    "Civil Engineering",
    "Electrical Engineering",
    "Biotechnology"
]

def generate_2000_students_dataset(num_records=2000, seed=42, include_sample_anomalies=True):
    """
    Generates a realistic 2,000 student dataset with statistical correlations.
    """
    random.seed(seed)
    np.random.seed(seed)

    records = []
    
    for i in range(1, num_records + 1):
        student_id = f"STU2026_{i:04d}"
        
        # Gender & Name
        gender = random.choices(["Male", "Female", "Other"], weights=[0.52, 0.46, 0.02])[0]
        if gender == "Male":
            first_name = random.choice(FIRST_NAMES_MALE)
        elif gender == "Female":
            first_name = random.choice(FIRST_NAMES_FEMALE)
        else:
            first_name = random.choice(FIRST_NAMES_MALE + FIRST_NAMES_FEMALE)
            
        last_name = random.choice(LAST_NAMES)
        student_name = f"{first_name} {last_name}"
        
        # Course & Semester
        course = random.choice(COURSES)
        semester = random.randint(1, 8)
        age = 18 + (semester // 2) + random.choice([0, 1])
        
        # Total Classes held in semester (e.g. 48 to 60 lectures)
        total_classes = random.choice([48, 50, 52, 54, 56, 60])
        
        # Realistic attendance distribution:
        # ~68% high attendance (80-98%), ~18% borderline (72-79%), ~14% defaulters (35-71%)
        student_tier = random.choices(["regular", "borderline", "defaulter"], weights=[0.68, 0.18, 0.14])[0]
        
        if student_tier == "regular":
            target_pct = np.random.uniform(80.0, 98.0)
            leave_count = random.randint(0, 3)
            medical_leave = random.randint(0, 2)
            late_count = random.randint(0, 4)
            assign_score = np.random.uniform(75.0, 98.0)
            prev_att = np.random.uniform(78.0, 97.0)
        elif student_tier == "borderline":
            target_pct = np.random.uniform(70.0, 78.0)
            leave_count = random.randint(2, 5)
            medical_leave = random.randint(1, 3)
            late_count = random.randint(2, 6)
            assign_score = np.random.uniform(60.0, 80.0)
            prev_att = np.random.uniform(68.0, 82.0)
        else: # Defaulter
            target_pct = np.random.uniform(32.0, 69.5)
            leave_count = random.randint(4, 9)
            medical_leave = random.randint(0, 4)
            late_count = random.randint(4, 9)
            assign_score = np.random.uniform(35.0, 65.0)
            prev_att = np.random.uniform(40.0, 72.0)

        # Classes attended calculation based on target_pct
        classes_attended = int(round((target_pct / 100.0) * total_classes))
        classes_attended = max(0, min(total_classes, classes_attended))
        classes_missed = total_classes - classes_attended
        actual_att_pct = round((classes_attended / total_classes) * 100.0, 2)
        
        # Internal marks (correlated with attendance & assignments)
        internal_score = (0.55 * actual_att_pct) + (0.45 * assign_score) + np.random.normal(0, 3)
        internal_marks = round(max(15.0, min(100.0, internal_score)), 2)

        # Ground truth status label
        attendance_status = "Eligible" if actual_att_pct >= 75.0 else "Low Attendance"

        records.append({
            "Student_ID": student_id,
            "Student_Name": student_name,
            "Age": int(age),
            "Gender": gender,
            "Course": course,
            "Semester": int(semester),
            "Total_Classes": int(total_classes),
            "Classes_Attended": int(classes_attended),
            "Classes_Missed": int(classes_missed),
            "Attendance_Percentage": float(actual_att_pct),
            "Late_Count": int(late_count),
            "Leave_Count": int(leave_count),
            "Medical_Leave": int(medical_leave),
            "Assignment_Submission": round(float(assign_score), 2),
            "Internal_Marks": float(internal_marks),
            "Previous_Attendance": round(float(prev_att), 2),
            "Attendance_Status": attendance_status
        })

    df = pd.DataFrame(records)

    # Optional: Introduce a tiny controlled edge case set (e.g. 2 duplicates, 2 missing values)
    # to demonstrate that our validator actively detects and reports them cleanly!
    if include_sample_anomalies and len(df) > 50:
        # Row 1999: Duplicate ID of row 1
        df.loc[1998, "Student_ID"] = df.loc[0, "Student_ID"]
        # Row 2000: Out-of-bound attendance percentage
        df.loc[1999, "Attendance_Percentage"] = 145.0
        df.loc[1999, "Classes_Attended"] = df.loc[1999, "Total_Classes"] + 10

    return df

def generate_and_export_all(output_dir="data"):
    """Generates the 2,000 dataset and exports to CSV, JSON, Excel, and SQLite."""
    print("=" * 70)
    print("🎓 GENERATING REALISTIC 2,000 STUDENT ATTENDANCE DATASET")
    print("=" * 70)
    
    df = generate_2000_students_dataset(num_records=2000, include_sample_anomalies=True)
    
    csv_path = f"{output_dir}/students_2000.csv"
    json_path = f"{output_dir}/students_2000.json"
    xlsx_path = f"{output_dir}/students_2000.xlsx"
    db_path = f"{output_dir}/test_students.db"

    # Also save directly in root directory for standard discovery
    save_csv(df, "students_2000.csv")
    save_json(df, "students_2000.json")
    save_excel(df, "students_2000.xlsx")
    save_database(df, db_path, table_name="students")

    # Also in data/ folder
    save_csv(df, csv_path)
    save_json(df, json_path)
    save_excel(df, xlsx_path)

    print(f"\n Successfully generated and exported 2,000 student records across all 4 formats!")
    print(f"• CSV   : students_2000.csv")
    print(f"• JSON  : students_2000.json")
    print(f"• Excel : students_2000.xlsx")
    print(f"• DB    : {db_path} (table: 'students')")
    return df

if __name__ == "__main__":
    generate_and_export_all()
