class TestStatus:
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    NONE = "NONE"

def get_case_status(lines):
    def collect_statuses(entries):
        statuses = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            category = entry.get("category")
            # If a group has a non-NONE status, use that status!
            if category == "GROUP" and entry.get("status", "NONE") not in ("NONE", None):
                statuses.append(entry.get("status"))
                # Still check for deeper children in case of nested groups
                statuses.extend(collect_statuses(entry.get("children", [])))
            elif category in ("STEP", "TABLE", "CHART"):
                statuses.append(entry.get("status", "NONE"))
        return statuses

    all_statuses = collect_statuses(lines)

    for s in ["ERROR", "FAIL", "PASS"]:
        if s in all_statuses:
            return s
    return "NONE"