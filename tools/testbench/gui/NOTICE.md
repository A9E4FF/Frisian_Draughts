# Attribution

`board.py` is adapted from `gui/board_widget.py` in the user-supplied
ScanGraphic / Scan 3.1 project. Original rendering and board interaction code
is retained, with changes for unambiguous legal move selection and setup mode.
The containing Scan distribution credits Fabien Letouzey for Scan 3.1.

The integration, protocol/session code, rules bridge and test runner are
distributed under this repository's GPL-3.0-only license. Engine executables,
evaluation weights, books and bitbases are not bundled with the testbench.
No code from the legacy match script with unidentified separate licensing is
copied; its scheduling workflows informed the new headless implementation.
