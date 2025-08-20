import os
import shutil
import json
from datetime import datetime
from TestPackage.report.status import get_case_status

def sanitize_name(name):
    """Replace spaces with underscores for safe file/object keys."""
    return name.replace(" ", "_") if isinstance(name, str) else name

def fill_stats(stats, test_cases, suite_start_time, suite_end_time):
    pass_count = sum(1 for t in test_cases if t.get("status", "").upper() == "PASS")
    fail_count = sum(1 for t in test_cases if t.get("status", "").upper() == "FAIL")
    error_count = sum(1 for t in test_cases if t.get("status", "").upper() == "ERROR")
    none_count = sum(1 for t in test_cases if t.get("status", "").upper() == "NONE")
    total = len(test_cases)
    runnable = pass_count + fail_count + error_count

    def fmt_stat(count):
        return f"{count}   {int((count/total*100) if total else 0)}%"

    if error_count > 0:
        overall = "ERROR"
    elif fail_count > 0:
        overall = "FAIL"
    elif pass_count > 0 and pass_count == runnable:
        overall = "PASS"
    elif none_count == total:
        overall = "NONE"
    else:
        overall = "PARTIAL"

    try:
        delta = suite_end_time - suite_start_time
        duration = f"{delta.seconds//3600:02}:{(delta.seconds//60)%60:02}:{delta.seconds%60:02}"
        date = suite_start_time.strftime("%Y-%m-%d")
        end_time = suite_end_time.strftime("%H:%M:%S")
    except Exception:
        duration = "00:00:00"; date = ""; end_time = ""

    stats_filled = {
        "all": fmt_stat(total),
        "pass": fmt_stat(pass_count),
        "fail": fmt_stat(fail_count),
        "error": fmt_stat(error_count),
        "none": none_count,
        "overall": overall,
        "date": date,
        "time": end_time,
        "duration": duration
    }
    return stats_filled

def append_incremental_info(
    report_dir, test_name, tc, test_env, dut, project_name, suite_name, suite_start_time, suite_end_time
):
    """
    Ensure test steps are properly reflected in reportData.js.
    """
    print(f"Debug: test_env before updating info.js: {test_env}")
    # Make sure muted troubles structure exists instead of hard failing
    if "muted troubles" not in test_env:
        test_env["muted troubles"] = {"DTC": [], "comment": ""}
    viewer_dist_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'viewer', 'dist'))
    if not os.path.exists(report_dir):
        os.makedirs(report_dir, exist_ok=True)
        shutil.copytree(viewer_dist_dir, report_dir, dirs_exist_ok=True)
    else:
        if not os.path.exists(os.path.join(report_dir, "index.html")):
            shutil.copytree(viewer_dist_dir, report_dir, dirs_exist_ok=True)

    js_dir = os.path.join(report_dir, "js")
    tests_dir = os.path.join(report_dir, "tests")
    os.makedirs(js_dir, exist_ok=True)
    os.makedirs(tests_dir, exist_ok=True)

    # Sanitize test name before using as key or folder
    sanitized_test_name = sanitize_name(test_name)

    # Debug: Validate steps added to the report object
    if not tc.get("lines"):
        raise ValueError(f"'lines' array is empty for test case {sanitized_test_name}. Verify step logic.")

    # Write this test's reportData.js
    tc_folder = os.path.join(tests_dir, sanitized_test_name, "testResults")
    os.makedirs(tc_folder, exist_ok=True)
    tc["status"] = tc.get("status") or get_case_status(tc.get("lines", []))
    with open(os.path.join(tc_folder, "reportData.js"), "w", encoding="utf-8") as f:
        f.write("window.reportData = ")
        json.dump(tc, f, indent=2)
        f.write(";")

    # Update info.js incrementally
    info_js = os.path.join(js_dir, "info.js")
    if not os.path.exists(info_js):
        info = {
            "projectName": project_name, "testSuiteName": suite_name,
            "testEnvironment": test_env, "deviceUnderTest": dut,
            "statistics": {},
            "testNames": [],
            "reportData": {},
            "reportIsComplete": False,
            "framework": {
                "version": "", "stubModeActive": "",
                "config": {"diagnostics": {"mutedDtcs": [], "mutedNtcs": [], "mutedTroublesComment": ""}}
            }
        }
    else:
        with open(info_js, encoding="utf-8") as f:
            content = f.read()
        prefix = "window.myreport ="
        if content.startswith(prefix):
            content = content[len(prefix):].strip().rstrip(";")
        try:
            info = json.loads(content)
        except Exception:
            info = {
                "projectName": project_name, "testSuiteName": suite_name,
                "testEnvironment": test_env, "deviceUnderTest": dut,
                "statistics": {},
                "testNames": [],
                "reportData": {},
                "reportIsComplete": False,
                "framework": {
                    "version": "", "stubModeActive": "",
                    "config": {"diagnostics": {"mutedDtcs": [], "mutedNtcs": [], "mutedTroublesComment": ""}}
                }
            }

    # --- PATCH: Ensure TestPreparation is always the first entry, TestDeinitialization always last ---
    test_name_lower = sanitized_test_name.lower()
    if sanitized_test_name in info["testNames"]:
        info["testNames"].remove(sanitized_test_name)
    if test_name_lower == "testpreparation":
        info["testNames"].insert(0, sanitized_test_name)
    elif test_name_lower == "testdeinitialization":
        info["testNames"].append(sanitized_test_name)
    else:
        if "TestPreparation" in info["testNames"]:
            idx = info["testNames"].index("TestPreparation") + 1
            info["testNames"].insert(idx, sanitized_test_name)
        else:
            info["testNames"].append(sanitized_test_name)
    # --- END PATCH ---

    info["reportData"][sanitized_test_name] = {
        "name": sanitized_test_name,
        "status": tc["status"],
        "goal": tc.get("goal", ""),
        "requirements": tc.get("requirements", [])
    }

    all_cases = []
    for tname in info["testNames"]:
        report_js = os.path.join(tests_dir, tname, "testResults", "reportData.js")
        if os.path.isfile(report_js):
            with open(report_js, encoding="utf-8") as f:
                content = f.read()
            prefix = "window.reportData ="
            if content.startswith(prefix):
                content = content[len(prefix):].strip().rstrip(";")
            try:
                tcase = json.loads(content)
                all_cases.append(tcase)
            except Exception:
                pass

    info["statistics"] = fill_stats({}, all_cases, suite_start_time, suite_end_time)

    with open(info_js, "w", encoding="utf-8") as f:
        f.write("window.myreport = ")
        json.dump(info, f, indent=2)
        f.write(";")

def export_report_with_assets(
        output_root_dir, folder_name, test_env, dut, test_cases, stats,
        project_name, suite_name, suite_start_time, suite_end_time
):
    viewer_dist_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'viewer', 'dist'))

    if not suite_start_time:
        suite_start_time = datetime.now()
    folder_name = suite_start_time.strftime("%Y.%m.%d_%H.%M.%S")
    report_dir = os.path.join(output_root_dir, folder_name)

    if not os.path.exists(report_dir):
        os.makedirs(report_dir, exist_ok=True)
        shutil.copytree(viewer_dist_dir, report_dir, dirs_exist_ok=True)

    tests_dir = os.path.join(report_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)

    # --- PATCH: Reorder test cases for output ---
    def reorder_cases(test_cases):
        prep = [tc for tc in test_cases if tc.get("name", "").lower() == "testpreparation"]
        deinit = [tc for tc in test_cases if tc.get("name", "").lower() == "testdeinitialization"]
        main = [tc for tc in test_cases if tc.get("name", "").lower() not in ("testpreparation", "testdeinitialization")]
        return prep + main + deinit

    test_cases = reorder_cases(test_cases)
    # --- END PATCH ---

    for tc in test_cases:
        test_name = tc.get("name")
        if not test_name:
            continue
        sanitized_test_name = sanitize_name(test_name)
        tc_folder = os.path.join(tests_dir, sanitized_test_name, "testResults")
        os.makedirs(tc_folder, exist_ok=True)
        tc["status"] = tc.get("status") or get_case_status(tc.get("lines", []))
        with open(os.path.join(tc_folder, "reportData.js"), "w", encoding="utf-8") as f:
            f.write("window.reportData = ")
            json.dump(tc, f, indent=2)
            f.write(";")