"""
Master Model Testing & Evaluation Pipeline
Runs the end-to-end AI/ML attendance model evaluation on 2,000 student records.

Usage:
  python3 test_model_pipeline.py --format csv
  python3 test_model_pipeline.py --format json
  python3 test_model_pipeline.py --format excel
  python3 test_model_pipeline.py --format db
  python3 test_model_pipeline.py --generate-data
"""

import os
import sys
import argparse
import pandas as pd
import json

from generate_dataset import generate_and_export_all
from data_handler import load_csv, load_json, load_excel, load_database, save_csv, save_json, save_excel, save_database
from data_validator import validate_and_clean_dataset
from model_evaluator import AttendanceModelEvaluator

def print_header(title):
    print("\n" + "=" * 80)
    print(f" {title.upper()}")
    print("=" * 80)

def display_ascii_confusion_matrix(cm_data):
    """Displays a clean ASCII visualization of the Confusion Matrix."""
    tp = cm_data["true_eligible"]
    fn = cm_data["false_low_attendance"]
    fp = cm_data["false_eligible"]
    tn = cm_data["true_low_attendance"]

    print("\n📊 CONFUSION MATRIX (2x2):")
    print("+" + "-"*40 + "+" + "-"*20 + "+" + "-"*20 + "+")
    print(f"| {'ACTUAL / PREDICTED':<38} | {'PRED: ELIGIBLE':^18} | {'PRED: LOW ATT':^18} |")
    print("+" + "-"*40 + "+" + "-"*20 + "+" + "-"*20 + "+")
    print(f"| {'ACTUAL: ELIGIBLE (>=75%)':<38} | {tp:^18} | {fn:^18} |")
    print(f"| {'ACTUAL: LOW ATTENDANCE (<75%)':<38} | {fp:^18} | {tn:^18} |")
    print("+" + "-"*40 + "+" + "-"*20 + "+" + "-"*20 + "+")
    print(f"  • True Positives  (Correctly Identified Eligible)   : {tp}")
    print(f"  • True Negatives  (Correctly Identified At-Risk)    : {tn}")
    print(f"  • False Positives (At-Risk Missclassified Eligible) : {fp}")
    print(f"  • False Negatives (Eligible Misclassified At-Risk)  : {fn}")

def display_sample_predictions_table(df, num_rows=10):
    """Prints a formatted ASCII preview of prediction results."""
    preview_cols = [
        "Student_ID", "Student_Name", "Course", "Attendance_Percentage", 
        "Attendance_Status", "Predicted_Status", "Predicted_Risk_Tier", "Confidence_Score"
    ]
    sample_df = df[preview_cols].head(num_rows)
    
    print(f"\n📋 SAMPLE PREDICTIONS PREVIEW (First {num_rows} of {len(df)} Students):")
    print("-" * 115)
    print(f"{'ID':<14} | {'Name':<20} | {'Course':<25} | {'Att %':<7} | {'Actual':<14} | {'Predicted':<14} | {'Risk':<10} | {'Conf'}")
    print("-" * 115)
    for _, row in sample_df.iterrows():
        c_short = (row['Course'][:22] + '..') if len(row['Course']) > 25 else row['Course']
        print(f"{row['Student_ID']:<14} | {row['Student_Name']:<20} | {c_short:<25} | {row['Attendance_Percentage']:>5.1f}% | {row['Attendance_Status']:<14} | {row['Predicted_Status']:<14} | {row['Predicted_Risk_Tier']:<10} | {row['Confidence_Score']:>4.2f}")
    print("-" * 115)

def run_pipeline(input_format="csv", input_file=None, force_generate=False, output_dir="."):
    """Executes the complete model testing pipeline."""
    print_header("AI/ML ATTENDANCE MANAGEMENT SYSTEM — MODEL TESTING PIPELINE")

    # Step 1: Data Ingestion / Generation
    if force_generate or not os.path.exists("students_2000.csv"):
        print("\n⚙️ Step 1: Generating standard 2,000 student benchmark dataset...")
        generate_and_export_all(output_dir="data")

    # Select Loader function based on format
    print(f"\n⚙️ Step 2: Loading dataset using selected format: [{input_format.upper()}]...")
    
    if input_format == "csv":
        filepath = input_file or "students_2000.csv"
        raw_df = load_csv(filepath)
    elif input_format == "json":
        filepath = input_file or "students_2000.json"
        raw_df = load_json(filepath)
    elif input_format in ["excel", "xlsx"]:
        filepath = input_file or "students_2000.xlsx"
        raw_df = load_excel(filepath)
    elif input_format in ["db", "sqlite"]:
        filepath = input_file or "data/test_students.db"
        if not os.path.exists(filepath):
            filepath = "attendance.db"
        raw_df = load_database(filepath, table_name="students")
    else:
        raise ValueError(f"Unknown format '{input_format}'. Use: csv, json, excel, db")

    print(f" Ingested {len(raw_df)} total records from: {filepath}")

    # Step 2: Data Cleaning & Validation
    print("\n⚙️ Step 3: Validating schema, data types, missing values, and business constraints...")
    clean_df, invalid_df, val_summary = validate_and_clean_dataset(raw_df, handle_missing="impute", allow_duplicates=False)

    print(f" Validation Complete: {val_summary['validation_status']}")
    print(f"  • Valid Records for Model Testing : {val_summary['valid_records_count']}")
    print(f"  • Quarantined Invalid Records     : {val_summary['invalid_records_count']}")
    print(f"  • Missing Values Handled/Imputed  : {val_summary['missing_values_detected']}")
    print(f"  • Duplicate Records Quarantined   : {val_summary['duplicate_records_detected']}")

    if len(invalid_df) > 0:
        print("\n⚠️ Quarantined Invalid Records Sample:")
        for _, inv_row in invalid_df.head(5).iterrows():
            print(f"   - Row #{inv_row.get('Original_Row_Index')}: Student {inv_row.get('Student_ID')} -> Error: {inv_row.get('Error_Reasons')}")

    # Step 3: Feature Preprocessing
    print("\n⚙️ Step 4: Performing feature preprocessing & vectorization...")
    X_features = AttendanceModelEvaluator.preprocess_features(clean_df)
    print(f" Processed feature matrix shape: {X_features.shape} ({X_features.shape[1]} features extracted)")

    # Step 4: Model Inference
    print("\n⚙️ Step 5: Generating model predictions and prescriptive recovery plans...")
    pred_df = AttendanceModelEvaluator.predict_attendance_outcomes(clean_df)
    print(f" Model inference generated for all {len(pred_df)} valid student records.")

    # Step 5: Model Evaluation & Metric Calculation
    print("\n⚙️ Step 6: Calculating evaluation metrics & comparing with ground truth...")
    metrics = AttendanceModelEvaluator.evaluate_model(pred_df, actual_col="Attendance_Status", pred_col="Predicted_Status")

    # Step 6: Display Predictions & Evaluation Report
    display_sample_predictions_table(pred_df, num_rows=10)

    print_header("MODEL PERFORMANCE EVALUATION REPORT")
    print(f" Accuracy Score             : {metrics['accuracy']}%")
    print(f" Macro Precision            : {metrics['precision_macro']}%")
    print(f" Macro Recall               : {metrics['recall_macro']}%")
    print(f" Macro F1-Score             : {metrics['f1_macro']}%")
    print(f" Low Attendance F1-Score    : {metrics['f1_low_attendance']}%")
    
    display_ascii_confusion_matrix(metrics["confusion_matrix"])

    # Step 7: Export Required Output Files
    print_header("SAVING REQUIRED OUTPUT FILES")
    
    pred_csv_path = os.path.join(output_dir, "attendance_predictions.csv")
    pred_json_path = os.path.join(output_dir, "attendance_predictions.json")
    report_txt_path = os.path.join(output_dir, "model_evaluation_report.txt")

    save_csv(pred_df, pred_csv_path)
    save_json(pred_df, pred_json_path)

    # Executive Summary Compilation
    exec_summary = AttendanceModelEvaluator.generate_evaluation_summary(pred_df, val_summary, metrics)

    # Write text evaluation report
    report_text = f"""================================================================================
AI/ML ATTENDANCE MANAGEMENT SYSTEM — MODEL EVALUATION REPORT
================================================================================

1. DATASET & INGESTION SUMMARY:
--------------------------------------------------------------------------------
• Total Students Ingested         : {val_summary['total_records_ingested']}
• Clean & Validated Records       : {val_summary['valid_records_count']}
• Quarantined Invalid Records     : {val_summary['invalid_records_count']}
• Missing Values Detected/Imputed : {val_summary['missing_values_detected']}
• Duplicate Records Filtered      : {val_summary['duplicate_records_detected']}
• Average Dataset Attendance      : {exec_summary['average_attendance']}%

2. MODEL PREDICTION SUMMARY:
--------------------------------------------------------------------------------
• Predicted Eligible Students     : {exec_summary['predicted_eligible']} (>=75%)
• Predicted Low Attendance / Risk : {exec_summary['predicted_low_attendance']} (<75%)
• Critical Defaulter Tier         : {exec_summary['risk_distribution']['critical_defaulters']}
• Moderate Warning Tier           : {exec_summary['risk_distribution']['moderate_warning']}
• Good Standing Tier              : {exec_summary['risk_distribution']['good_standing']}

3. EVALUATION METRICS:
--------------------------------------------------------------------------------
• Model Accuracy                  : {metrics['accuracy']}%
• Macro Precision                 : {metrics['precision_macro']}%
• Macro Recall                    : {metrics['recall_macro']}%
• Macro F1-Score                  : {metrics['f1_macro']}%
• Defaulter Recall (Detection)    : {metrics['recall_low_attendance']}%

4. DETAILED CLASSIFICATION REPORT:
--------------------------------------------------------------------------------
{metrics['classification_report']}

5. CONFUSION MATRIX:
--------------------------------------------------------------------------------
True Positives (Eligible)         : {metrics['confusion_matrix']['true_eligible']}
True Negatives (Low Attendance)   : {metrics['confusion_matrix']['true_low_attendance']}
False Positives                   : {metrics['confusion_matrix']['false_eligible']}
False Negatives                   : {metrics['confusion_matrix']['false_low_attendance']}

================================================================================
Report Generated Successfully.
================================================================================
"""
    with open(report_txt_path, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f" Saved Evaluation Report to : {report_txt_path}")

    # Final Terminal Executive Summary
    print_header("EXECUTIVE PIPELINE SUMMARY")
    print(f"  Total Students Ingested       : {val_summary['total_records_ingested']}")
    print(f"  Valid Processed Records       : {val_summary['valid_records_count']}")
    print(f"  Predicted Eligible Students   : {exec_summary['predicted_eligible']}")
    print(f"  Predicted Low-Attendance      : {exec_summary['predicted_low_attendance']}")
    print(f"  Average Attendance Rate       : {exec_summary['average_attendance']}%")
    print(f"  Number of Invalid Records     : {val_summary['invalid_records_count']}")
    print(f"  Number of Missing Values      : {val_summary['missing_values_detected']}")
    print(f"  Number of Duplicate Records   : {val_summary['duplicate_records_detected']}")
    print(f"  Overall Model Accuracy        : {metrics['accuracy']}%\n")
    print("=" * 80)

    return exec_summary, pred_df

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test AI/ML Attendance Model on 2,000 Student Dataset")
    parser.add_argument("--format", choices=["csv", "json", "excel", "xlsx", "db"], default="csv", help="Input file format to load")
    parser.add_argument("--input", type=str, default=None, help="Custom input dataset file path")
    parser.add_argument("--generate-data", action="store_true", help="Force regenerate 2,000 student dataset across all formats")
    parser.add_argument("--output-dir", type=str, default=".", help="Directory to save output files")

    args = parser.parse_args()
    run_pipeline(
        input_format=args.format,
        input_file=args.input,
        force_generate=args.generate_data,
        output_dir=args.output_dir
    )
