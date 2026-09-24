"""
Data Validator & Cleaning Module
Performs structural validation, missing value imputation, duplicate detection,
data type checking, and boundary constraint verification for student attendance datasets.
"""

import pandas as pd
import numpy as np

REQUIRED_COLUMNS = [
    "Student_ID",
    "Student_Name",
    "Age",
    "Gender",
    "Course",
    "Semester",
    "Total_Classes",
    "Classes_Attended",
    "Classes_Missed",
    "Attendance_Percentage",
    "Late_Count",
    "Leave_Count",
    "Medical_Leave",
    "Assignment_Submission",
    "Internal_Marks",
    "Previous_Attendance",
    "Attendance_Status"
]

NUMERIC_COLUMNS = [
    "Age",
    "Semester",
    "Total_Classes",
    "Classes_Attended",
    "Classes_Missed",
    "Attendance_Percentage",
    "Late_Count",
    "Leave_Count",
    "Medical_Leave",
    "Assignment_Submission",
    "Internal_Marks",
    "Previous_Attendance"
]

def validate_and_clean_dataset(df, handle_missing="impute", allow_duplicates=False):
    """
    Validates and cleans the attendance dataset.
    
    :param df: Input pandas DataFrame
    :param handle_missing: 'impute' (fill with sensible medians/defaults) or 'drop'
    :param allow_duplicates: If False, duplicates are detected and removed/quarantined
    :return: (clean_df, invalid_df, validation_summary)
    """
    total_raw_records = len(df)
    
    # 1. Check Missing Columns
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Dataset is missing required columns: {missing_cols}")

    working_df = df.copy()
    invalid_rows = []
    
    # Track statistics
    missing_values_count = int(working_df[REQUIRED_COLUMNS].isna().sum().sum())
    duplicate_records_count = int(working_df.duplicated(subset=["Student_ID"]).sum())

    # 2. Check for Duplicates
    seen_ids = set()
    valid_indices = []

    for idx, row in working_df.iterrows():
        errors = []
        student_id = str(row.get("Student_ID", "")).strip()

        # Check ID presence and uniqueness
        if not student_id or pd.isna(row.get("Student_ID")):
            errors.append("Student_ID is missing or blank")
        elif not allow_duplicates and student_id in seen_ids:
            errors.append(f"Duplicate Student_ID: '{student_id}'")
        else:
            seen_ids.add(student_id)

        # Check Numeric Conversions & Boundaries
        for num_col in NUMERIC_COLUMNS:
            val = row.get(num_col)
            if pd.isna(val):
                if handle_missing == "drop":
                    errors.append(f"Missing value in numeric column '{num_col}'")
                continue
            try:
                num_val = float(val)
                if num_col == "Attendance_Percentage" and not (0 <= num_val <= 100):
                    errors.append(f"Attendance_Percentage out of bounds [0-100]: {num_val}")
                elif num_col == "Previous_Attendance" and not (0 <= num_val <= 100):
                    errors.append(f"Previous_Attendance out of bounds [0-100]: {num_val}")
                elif num_col == "Assignment_Submission" and not (0 <= num_val <= 100):
                    errors.append(f"Assignment_Submission score out of bounds [0-100]: {num_val}")
                elif num_col == "Internal_Marks" and not (0 <= num_val <= 100):
                    errors.append(f"Internal_Marks out of bounds [0-100]: {num_val}")
                elif num_col in ["Age", "Semester", "Total_Classes", "Classes_Attended", "Classes_Missed", "Late_Count", "Leave_Count", "Medical_Leave"] and num_val < 0:
                    errors.append(f"Negative value in '{num_col}': {num_val}")
            except (ValueError, TypeError):
                errors.append(f"Non-numeric value in '{num_col}': {val}")

        # Consistency Check: Classes_Attended <= Total_Classes
        try:
            tot = float(row.get("Total_Classes", 0))
            att = float(row.get("Classes_Attended", 0))
            if att > tot:
                errors.append(f"Classes_Attended ({att}) exceeds Total_Classes ({tot})")
        except Exception:
            pass

        if errors:
            invalid_record = row.to_dict()
            invalid_record["Error_Reasons"] = "; ".join(errors)
            invalid_record["Original_Row_Index"] = idx + 1
            invalid_rows.append(invalid_record)
        else:
            valid_indices.append(idx)

    # 3. Separate Valid & Invalid
    clean_df = working_df.loc[valid_indices].copy()
    invalid_df = pd.DataFrame(invalid_rows) if invalid_rows else pd.DataFrame(columns=REQUIRED_COLUMNS + ["Error_Reasons", "Original_Row_Index"])

    # 4. Handle Missing Values in Valid Set (if any remaining NaNs)
    if handle_missing == "impute" and len(clean_df) > 0:
        for num_col in NUMERIC_COLUMNS:
            if clean_df[num_col].isna().sum() > 0:
                median_val = clean_df[num_col].median()
                clean_df[num_col] = clean_df[num_col].fillna(median_val)

        # Categorical columns
        categorical_cols = ["Gender", "Course", "Semester", "Attendance_Status"]
        for cat_col in categorical_cols:
            if cat_col in clean_df.columns and clean_df[cat_col].isna().sum() > 0:
                mode_val = clean_df[cat_col].mode()[0] if not clean_df[cat_col].mode().empty else "Unknown"
                clean_df[cat_col] = clean_df[cat_col].fillna(mode_val)

    # Re-cast numeric columns to proper types
    for col in ["Age", "Semester", "Total_Classes", "Classes_Attended", "Classes_Missed", "Late_Count", "Leave_Count", "Medical_Leave"]:
        if col in clean_df.columns:
            clean_df[col] = clean_df[col].astype(int)

    for col in ["Attendance_Percentage", "Assignment_Submission", "Internal_Marks", "Previous_Attendance"]:
        if col in clean_df.columns:
            clean_df[col] = clean_df[col].round(2)

    # 5. Build Comprehensive Validation Summary
    validation_summary = {
        "total_records_ingested": total_raw_records,
        "valid_records_count": len(clean_df),
        "invalid_records_count": len(invalid_df),
        "missing_values_detected": missing_values_count,
        "duplicate_records_detected": duplicate_records_count,
        "validation_status": "PASSED" if len(invalid_df) == 0 else "WARNING (Invalid records quarantined)",
        "accuracy_ready": len(clean_df) > 0
    }

    return clean_df, invalid_df, validation_summary
