"""Chunked, reproducible Fitbit CSV import. Run --help for paths."""

from __future__ import annotations
import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
import pandas as pd

DATE_COLUMNS = {
    "ActivityDate",
    "ActivityDay",
    "ActivityHour",
    "ActivityMinute",
    "SleepDay",
    "Date",
    "Time",
    "date",
}


def source_hash(path: Path) -> str:
    """Hash source bytes in bounded blocks instead of loading a whole file."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def import_files(raw_dir: Path, db_path: Path, chunk_size: int = 100_000) -> None:
    """Read all columns in bounded chunks; preserve raw files and normalize dates."""
    files = sorted(raw_dir.rglob("*.csv"))
    if len(files) != 18:
        raise ValueError(f"Expected 18 CSV files, found {len(files)}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = OFF")  # Rebuildable local analytical database.
    con.execute("PRAGMA synchronous = OFF")
    audit, fields = [], []
    for path in files:
        table = path.stem.replace("_merged", "")
        header = pd.read_csv(path, nrows=0).columns.tolist()
        date_col = next(c for c in header if c in DATE_COLUMNS)
        fmt = "%m/%d/%Y" if table.startswith("daily") else "%m/%d/%Y %I:%M:%S %p"
        types = {
            c: (
                "string"
                if c in DATE_COLUMNS
                else (
                    "int64"
                    if c in ["Id", "LogId", "logId"]
                    else "boolean" if c == "IsManualReport" else "float64"
                )
            )
            for c in header
        }
        sql_types = {
            c: (
                "TEXT"
                if c in DATE_COLUMNS
                else (
                    "INTEGER"
                    if c in ["Id", "LogId", "logId", "IsManualReport"]
                    else "REAL"
                )
            )
            for c in header
        }
        first = True
        total = 0
        for frame in pd.read_csv(
            path, dtype=types, chunksize=chunk_size, usecols=header
        ):
            parsed = pd.to_datetime(frame[date_col], format=fmt, errors="raise")
            frame[date_col] = parsed.dt.strftime(
                "%Y-%m-%d" if table.startswith("daily") else "%Y-%m-%d %H:%M:%S"
            )
            frame.to_sql(
                table,
                con,
                if_exists="replace" if first else "append",
                index=False,
                dtype=sql_types,
                chunksize=5000,
            )
            total += len(frame)
            first = False
        con.execute(
            f'CREATE INDEX IF NOT EXISTS ix_{table}_id_date ON "{table}" (Id,"{date_col}")'
        )
        con.execute(
            f'CREATE INDEX IF NOT EXISTS ix_{table}_date ON "{table}" ("{date_col}")'
        )
        cols = ",".join(f'"{c}"' for c in header)
        dup = con.execute(
            f'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM "{table}" GROUP BY {cols} HAVING COUNT(*)>1)'
        ).fetchone()[0]
        key_cols = f'Id,"{date_col}"' + (",logId" if table == "minuteSleep" else "")
        key_dup = con.execute(
            f'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM "{table}" GROUP BY {key_cols} HAVING COUNT(*)>1)'
        ).fetchone()[0]
        users, start, end = con.execute(
            f'SELECT COUNT(DISTINCT Id),MIN("{date_col}"),MAX("{date_col}") FROM "{table}"'
        ).fetchone()
        for c in header:
            nulls = con.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{c}" IS NULL'
            ).fetchone()[0]
            negatives = (
                con.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{c}"<0').fetchone()[
                    0
                ]
                if sql_types[c] != "TEXT"
                else 0
            )
            fields.append(
                dict(
                    table_name=table,
                    column_name=c,
                    storage_type=sql_types[c],
                    null_rows=nulls,
                    negative_rows=negatives,
                )
            )
        grain = (
            "user-day"
            if table.startswith("daily") or table == "sleepDay"
            else (
                "user-hour with 60 minute columns"
                if "Wide" in table
                else (
                    "user-hour"
                    if table.startswith("hourly")
                    else (
                        "user-timestamp-log"
                        if table == "minuteSleep"
                        else "user-timestamp"
                    )
                )
            )
        )
        audit.append(
            dict(
                table_name=table,
                filename=path.name,
                rows=total,
                columns=len(header),
                users=users,
                date_column=date_col,
                start=start,
                end=end,
                grain=grain,
                duplicate_rows=dup,
                duplicate_keys=key_dup,
                megabytes=round(path.stat().st_size / 1e6, 2),
                sha256=source_hash(path),
            )
        )
        print(
            f"{table}: CSV {total:,} x {len(header)} -> SQLite {total:,} x {len(header)}; {users} users; {dup} duplicates",
            flush=True,
        )
    pd.DataFrame(audit).to_sql(
        "source_inventory", con, if_exists="replace", index=False
    )
    pd.DataFrame(fields).to_sql("column_audit", con, if_exists="replace", index=False)
    con.commit()
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("../raw"))
    parser.add_argument("--db", type=Path, default=Path("bellabeat.db"))
    parser.add_argument("--chunk-size", type=int, default=100_000)
    args = parser.parse_args()
    import_files(args.raw_dir, args.db, args.chunk_size)
