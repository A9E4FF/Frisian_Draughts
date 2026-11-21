The Python analysis interface is copied from the user's modified Scan 3.1
ScanGraphic source tree. Scan is Copyright Fabien Letouzey, GPL version 3;
see COPYING. The interface retains its original board, diagnostics, tactics,
evaluation graph and game navigation. Imports and Hub startup were adapted.

`integrated.IntegratedWindow` adds the shared testbench match panel. It does
not replace the Scan analysis interface. Build using the explicit original
C++/evaluation source tree with `tools.testbench.build_scan_graphic`.
