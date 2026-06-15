"""quant.research — the runner layer that wires a candidate through the harness.

This package owns the *plumbing* between the thin strategy contracts (quant.base)
and the crown-jewel validation harness (tools/nautilus/* + tools/graduation/gate.py).
It contains NO new validation logic: it constructs the schedule with the framework's
own constructor + execution model and hands it to the existing, audited harness
functions, then maps the harness verdict onto a quant.base.ValidationResult.

Nothing here opens real data. The adapter is a PURE function of the data passed in;
the caller (a frozen, committed pre-registration run) owns data loading via
tools.nautilus.u30_data. See README in quant/ and research/prereg/.
"""

from .adapter import run_walkforward

__all__ = ["run_walkforward"]
