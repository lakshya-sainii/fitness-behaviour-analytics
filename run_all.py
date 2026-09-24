"""Rebuild the database, SQL results, executed notebook and document exports."""

from pathlib import Path
import argparse
import os
import nbformat
from nbclient import NotebookClient
from load_csv_to_sqlite import import_files
from export_notebook import export_notebook


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        required=True,
        help="Directory containing the 18 original CSVs, recursively",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Use socket-free sequential IPython execution",
    )
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    os.environ["FITBIT_RAW_DIR"] = str(args.raw_dir.resolve())
    for name in ["processed", "sql_outputs", "charts"]:
        (base / name).mkdir(exist_ok=True)
    import_files(args.raw_dir.resolve(), base / "bellabeat.db")
    path = base / "Bellabeat_Fitbit_EDA.ipynb"
    if args.in_process:
        from execute_notebook import execute_notebook

        execute_notebook(path)
    else:
        notebook = nbformat.read(path, as_version=4)
        NotebookClient(
            notebook,
            timeout=1200,
            kernel_name="python3",
            resources={"metadata": {"path": str(base)}},
        ).execute()
        nbformat.write(notebook, path)
    export_notebook(base)
    print("Complete. Inspect the notebook, export and reconciliation table.")


if __name__ == "__main__":
    main()
