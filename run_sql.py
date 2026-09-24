"""Execute every marked master SQL block and export query outputs."""

from pathlib import Path
import re
import sqlite3
import pandas as pd


def run_sql(base: Path) -> pd.DataFrame:
    con = sqlite3.connect(base / "bellabeat.db")
    text = (base / "Bellabeat_Fitbit_Analysis.sql").read_text()
    records = []
    for block in re.split(r"-- QUERY: ", text)[1:]:
        name = block.splitlines()[0].strip()
        statement = block[block.index("\n") + 1 :]
        cur = con.execute(statement)
        if cur.description:
            df = pd.DataFrame(cur.fetchall(), columns=[x[0] for x in cur.description])
            df.to_csv(base / "sql_outputs" / f"{name}.csv", index=False)
            rows = len(df)
        else:
            rows = 0
        records.append({"query": name, "status": "PASS", "output_rows": rows})
        print(name, "PASS", rows, flush=True)
    con.commit()
    con.close()
    result = pd.DataFrame(records)
    result.to_csv(base / "sql_outputs" / "execution_log.csv", index=False)
    return result


if __name__ == "__main__":
    run_sql(Path(__file__).resolve().parent)
