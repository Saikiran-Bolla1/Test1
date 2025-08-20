from contextlib import contextmanager

from TestPackage.report.test_report import TestReport

# Global variable to store the current active TestReport instance.
_current_report = None

def set_report(report: TestReport):
    """Set the current active report context."""
    global _current_report
    _current_report = report

def get_report() -> TestReport:
    """Get the current active report context."""
    return _current_report

def add_step(status, comment):
    """Add a step to the current report."""
    report = get_report()
    if report is None:
        raise RuntimeError("No active report has been set.")
    report.add_step(status, comment)

def add_table(table=None, name=None, data=None, column_header=None, row_header=None):
    """
    Add a table to the current report.
    Supports both dict-style and keyword arguments.

    Examples:
        add_table(name="My Table", data=[...], column_header=[...], row_header=[...])
        add_table({"name": ..., "data": ..., "column_header": ..., "row_header": ...})
    Only 'name' and 'data' are required, others are optional.
    """
    report = get_report()
    if report is None:
        raise RuntimeError("No active report has been set.")

    # Accept legacy dict input for backward compatibility
    if table is not None and isinstance(table, dict):
        name = table.get("name")
        data = table.get("data")
        column_header = table.get("column_header", None)
        row_header = table.get("row_header", None)

    if name is None or data is None:
        raise ValueError("add_table requires at minimum 'name' and 'data' arguments.")

    report.add_table(name=name, data=data, column_header=column_header, row_header=row_header)

def add_diagnostic_tx_rx_group(*args, **kwargs):
    """Add a diagnostic tx/rx group to the current report."""
    report = get_report()
    if report is None:
        raise RuntimeError("No active report has been set.")
    report.add_diagnostic_tx_rx_group(*args, **kwargs)

def condition(cond: bool, description: str, comment: str = ""):
    """Add a condition to the current report."""
    report = get_report()
    if report is None:
        raise RuntimeError("No active report has been set.")
    report.condition(cond, description, comment)

@contextmanager
def start_group(title, comment=None):
    """
    Start a new group in the current report.
    This function uses a context manager for easy management of group hierarchy.
    """
    report = get_report()
    if report is None:
        raise RuntimeError("No active report has been set.")
    with report.start_group(title, comment):
        yield

def add_chart(chart):
    """Add a chart to the current report."""
    report = get_report()
    if report is None:
        raise RuntimeError("No active report has been set.")
    report.add_chart(chart)