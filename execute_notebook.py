"""Execute notebook cells sequentially with IPython, without kernel sockets.

Useful in restricted environments. Code runs normally and real stream/rich
outputs are captured; any cell error stops execution. No outputs are fabricated.
"""

from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import io
import os
import nbformat
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from IPython.core.interactiveshell import InteractiveShell
from IPython.utils.capture import capture_output
from IPython.display import Image, display


def execute_notebook(path: Path) -> None:
    path = path.resolve()
    notebook = nbformat.read(path, as_version=4)
    shell = InteractiveShell.instance()
    shell.run_cell('import sys; sys.path.insert(0, "")', store_history=False)
    previous_cwd = Path.cwd()
    old_show = plt.show

    def show_figures(*args, **kwargs):
        for number in plt.get_fignums():
            fig = plt.figure(number)
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", bbox_inches="tight", dpi=130)
            display(Image(data=buffer.getvalue()))

    plt.show = show_figures
    try:
        os.chdir(path.parent)
        for i, cell in enumerate(notebook.cells):
            if cell.cell_type != "code":
                continue
            with capture_output(stdout=True, stderr=True, display=True) as captured:
                result = shell.run_cell(cell.source, store_history=True)
            result.raise_error()
            cell.execution_count = result.execution_count
            outputs = []
            if captured.stdout:
                outputs.append(
                    nbformat.v4.new_output(
                        "stream", name="stdout", text=captured.stdout
                    )
                )
            if captured.stderr:
                outputs.append(
                    nbformat.v4.new_output(
                        "stream", name="stderr", text=captured.stderr
                    )
                )
            outputs.extend(
                nbformat.v4.new_output(
                    "display_data", data=item.data, metadata=item.metadata
                )
                for item in captured.outputs
            )
            cell.outputs = outputs
            print(f"Cell {i}: executed, {len(outputs)} outputs", flush=True)
        notebook.metadata["execution_method"] = (
            "Sequential IPython InteractiveShell; real captured outputs; socket-free runtime"
        )
        nbformat.write(notebook, path)
    finally:
        plt.show = old_show
        os.chdir(previous_cwd)


if __name__ == "__main__":
    execute_notebook(Path(__file__).resolve().parent / "Bellabeat_Fitbit_EDA.ipynb")
