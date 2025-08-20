import os
from datetime import datetime
from TestPackage.report.export.exporter import export_report_with_assets, fill_stats, append_incremental_info
from TestPackage.config.config_manager import ConfigManager
from TestPackage.env_info import build_test_env

# Global variables for managing test suite state and reporting
_completed_tests = []
_suite_start_time = None
_suite_end_time = None
_report_output_dir = None
_current_test_name = None
_current_test_report_path = None
_test_env = None
_last_test_report = None

def set_test_env(env=None):
    """Set the test environment dynamically from the configuration."""
    global _test_env
    if _test_env is None:
        _test_env = build_test_env(user_env=env)
    print(f"[DEBUG] Test environment initialized: {_test_env}")

def get_test_env():
    """Retrieve the global test environment."""
    global _test_env
    if _test_env is None:
        print("[WARNING] Test environment is uninitialized. Attempting fallback initialization.")
        set_test_env()
    print(f"[DEBUG] Test environment fetched: {_test_env}")
    return _test_env

def set_report_output_dir(path):
    """Set the directory for report output."""
    global _report_output_dir
    if not path:
        raise ValueError("[ERROR] Report output directory cannot be None or empty.")
    _report_output_dir = path
    print(f"[DEBUG] Report output directory set to: {_report_output_dir}")

def start_suite():
    """Initialize the test suite and set up the environment."""
    global _suite_start_time, _report_output_dir
    _suite_start_time = datetime.now()
    print(f"[DEBUG] Suite start time: {_suite_start_time}")

    from TestPackage.Test.runner import resolve_path
    config = ConfigManager()
    test_path = config.get("Tests", {}).get("path", ".")
    config_dir = os.path.dirname(config.config_path)
    _report_output_dir = resolve_path("report", config_dir) if test_path else os.getcwd()

    set_test_env()
    print(f"[DEBUG] Test environment during suite initialization: {_test_env}")

def end_suite():
    """Finalize the test suite."""
    global _suite_end_time
    _suite_end_time = datetime.now()
    print(f"[DEBUG] Suite end time: {_suite_end_time}")

def start_test(test_name=None):
    """Initialize a test case."""
    global _current_test_name, _current_test_report_path, _report_output_dir, _suite_start_time

    print("[DEBUG] Starting test...")

    if _report_output_dir is None:
        raise RuntimeError("[ERROR] Report output directory not set. Call set_report_output_dir() before tests.")

    if not test_name:
        from TestPackage.report.test_report_context import get_report
        report = get_report()
        if report:
            test_name = report.name
            print(f"[DEBUG] Test name fetched from report context: {test_name}")
        else:
            raise ValueError("[ERROR] Test name is not provided and no active report is found in context.")

    _current_test_name = test_name
    print(f"[DEBUG] Current test name set to: {_current_test_name}")

    if not _suite_start_time:
        _suite_start_time = datetime.now()

    folder_name = _suite_start_time.strftime("%Y.%m.%d_%H.%M.%S")
    _current_test_report_path = os.path.join(_report_output_dir, folder_name, "tests", test_name, "testResults")
    print(f"[DEBUG] Current test report path set to: {_current_test_report_path}")

def get_test_report_path(test_name=None):
    """Retrieve the path to the test report folder for a specific test case."""
    global _report_output_dir, _current_test_name

    print("[DEBUG] Fetching test report path...")

    if _report_output_dir is None:
        raise RuntimeError("[ERROR] Report output directory not set.")

    if not os.path.exists(_report_output_dir):
        raise RuntimeError("[ERROR] Report output directory does not exist.")

    if not _current_test_name:
        raise RuntimeError("[ERROR] Test name is not set. Ensure start_test() was called correctly.")

    test_name = test_name or _current_test_name
    print(f"[DEBUG] Using test name: {test_name}")

    folder_name = _suite_start_time.strftime("%Y.%m.%d_%H.%M.%S") if _suite_start_time else "default_folder"
    test_report_path = os.path.join(_report_output_dir, folder_name, "tests", test_name, "testResults")
    print(f"[DEBUG] Test report path constructed: {test_report_path}")
    return test_report_path

def get_current_test_status():
    """Retrieve the status of the currently executing test case."""
    global _current_test_name

    print("[DEBUG] Fetching current test status...")

    if not _current_test_name:
        raise RuntimeError("[ERROR] Current test name is not set. Ensure start_test() was called correctly.")

    # Search for the current test name in the completed tests
    for test in _completed_tests:
        if test.get("name") == _current_test_name:
            status = test.get("status", "NONE").upper()
            print(f"[DEBUG] Current test case status for '{_current_test_name}': {status}")
            return status

    raise RuntimeError(f"[ERROR] Test case '{_current_test_name}' not found in completed tests.")

def notify_test_complete(test_report):
    """Notify that a test case has been completed and update the report."""
    global _completed_tests, _report_output_dir, _suite_start_time, _last_test_report

    if not hasattr(test_report, "to_dict"):
        raise TypeError("[ERROR] Test report must have a 'to_dict()' method.")

    test_report_dict = test_report.to_dict()

    if not test_report_dict.get("lines"):
        raise ValueError(f"[ERROR] Steps are missing in the report for {test_report_dict['name']}. Verify step logic.")

    if not _suite_start_time:
        _suite_start_time = datetime.now()

    folder_name = _suite_start_time.strftime("%Y.%m.%d_%H.%M.%S")
    report_dir = os.path.join(_report_output_dir, folder_name)

    if not os.path.exists(report_dir):
        os.makedirs(report_dir)

    test_report_dict["index"] = len(_completed_tests)
    _completed_tests.append(test_report_dict)
    _last_test_report = test_report

    # Resolve the `dut` argument for append_incremental_info
    dut = test_report_dict.get("dut", {})

    append_incremental_info(
        report_dir=report_dir,
        test_name=test_report_dict["name"],
        tc=test_report_dict,
        test_env=get_test_env(),
        dut=dut,  # Pass the resolved `dut` argument
        project_name=ConfigManager().get("project"),
        suite_name="Test Report",
        suite_start_time=_suite_start_time,
        suite_end_time=_suite_end_time or datetime.now()
    )

def export_suite_report():
    """Export the final suite report."""
    global _suite_start_time, _suite_end_time, _completed_tests, _report_output_dir

    if _suite_start_time is None:
        raise RuntimeError("[ERROR] Suite start time not set. Ensure start_suite() was called before exporting the suite report.")

    folder_name = _suite_start_time.strftime("%Y.%m.%d_%H.%M.%S")

    # Resolve the `dut` argument to pass to export_report_with_assets
    dut = _completed_tests[-1].get("dut", {}) if _completed_tests else {}

    export_report_with_assets(
        output_root_dir=_report_output_dir or "output_reports",
        folder_name=folder_name,
        test_env=get_test_env(),
        dut=dut,  # Pass the resolved `dut` argument
        test_cases=_completed_tests.copy(),
        stats=fill_stats({}, _completed_tests, _suite_start_time, _suite_end_time or datetime.now()),
        project_name=ConfigManager().get("project"),
        suite_name="Test Report",
        suite_start_time=_suite_start_time,
        suite_end_time=_suite_end_time or datetime.now()
    )

def get_current_test_name():
    """Retrieve the name of the current test case."""
    return _current_test_name

def get_report_status():
    """Check if the report directory exists."""
    return os.path.exists(_report_output_dir) if _report_output_dir else False

def get_report_path():
    """Retrieve the path to the latest report folder."""
    if not _report_output_dir:
        raise RuntimeError("[ERROR] Report output directory not set.")
    subfolders = [os.path.join(_report_output_dir, d) for d in os.listdir(_report_output_dir)
                  if os.path.isdir(os.path.join(_report_output_dir, d))]
    return max(subfolders, key=os.path.getmtime) if subfolders else None

def get_overall_report_status():
    """Retrieve the overall status of the test suite."""
    statuses = [test.get("status", "NONE").upper() for test in _completed_tests]
    if "ERROR" in statuses:
        return "ERROR"
    elif "FAIL" in statuses:
        return "FAIL"
    elif all(status == "PASS" for status in statuses if status != "NONE"):
        return "PASS"
    elif all(status == "NONE" for status in statuses):
        return "NONE"
    return "PARTIAL"

def get_test_case_status(test_name):
    """Retrieve the status of a specific test case."""
    for test in _completed_tests:
        if test.get("name") == test_name:
            return test.get("status", "NONE").upper()
    return "NOT_FOUND"