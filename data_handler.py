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
