from typing import List, Dict, Any, Optional, Union
from TestPackage.Controller.Diagnostics.dtcinfo import DTCInfo
from TestPackage.config.config_manager import ConfigManager
from TestPackage.report.test_report_context import add_table, add_step, add_diagnostic_tx_rx_group

# Status constants
STATUS_ALLOWED = "Allowed"
STATUS_MUTED = "Muted"
STATUS_EXPECTED = "Expected"
STATUS_ANY = "any"

def _to_int(value: Union[str, int]) -> Optional[int]:
    """
    Convert hex/bin/decimal string or int to int.
    Returns None for 'any' or wildcard bit-pattern strings.
    """
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip().lower()
        if s == STATUS_ANY:
            return None
        if set(s) <= {"0", "1", "*"}:
            # wildcard bit-pattern string (e.g., '11**01**') - not convertible
            return None
        if s.startswith("0x"):
            return int(s[2:].replace("_", ""), 16)
        if s.startswith("0b"):
            return int(s[2:].replace("_", ""), 2)
        return int(s)
    return int(value)

def format_dtc_code(value: Union[str, int]) -> str:
    """
    Format a DTC code for reporting:
    - Preserve the width (leading zeros) if provided as a hex string.
    - If numeric, default to 5 hex digits (pad with leading zeros) up to 0xFFFFF,
      else use minimal width required by the value.
    Always lower-case with 0x prefix.
    """
    if isinstance(value, str):
        s = value.strip().lower()
        if s == STATUS_ANY:
            return STATUS_ANY
        if s.startswith("0x"):
            # Normalize while preserving provided width and removing separators.
            hex_digits = "".join(ch for ch in s[2:] if ch in "0123456789abcdef")
            return f"0x{hex_digits or '00'}"
        if s.startswith("0b"):
            n = int(s[2:].replace("_", ""), 2)
        else:
            # Accept decimal or bare hex like 'f0f0f'
            try:
                # Try decimal first
                n = int(s)
            except ValueError:
                # Fallback to hex
                n = int(s, 16)
    else:
        n = int(value)

    width = 5 if n <= 0xFFFFF else len(f"{n:x}")
    return f"0x{n:0{width}x}"

def parse_to_int_or_hex(value: Union[str, int]) -> str:
    """
    Converts a value to a hex string for consistent comparison/reporting.
    Special-cases:
      - "any" -> "any"
      - "0b..." -> converted to hex, at least 2 digits
      - Wildcard patterns (e.g., '11**01**') returned as-is
      - Hex strings '0x..' preserved as-is, but ensure at least 2 digits for single-nibble values
      - Integers/decimals -> 2-digit hex minimum
    Note: Use format_dtc_code() for DTC codes to preserve leading zeros/width.
    """
    if isinstance(value, str) and value.lower() == STATUS_ANY:
        return STATUS_ANY
    if isinstance(value, str) and value.lower().startswith("0x"):
        digits = "".join(ch for ch in value[2:].strip().lower() if ch in "0123456789abcdef")
        if len(digits) == 1:
            digits = digits.zfill(2)
        return f"0x{digits or '00'}"
    if isinstance(value, str) and value.lower().startswith("0b"):
        n = int(value[2:].replace("_", ""), 2)
        return f"0x{n:02x}"
    if isinstance(value, str) and set(value) <= {"0", "1", "*"}:
        return value
    n = int(value)
    return f"0x{n:02x}"

class DTCStatus:
    BIT_NAMES = [
        "TestFailed",
        "TestFailedThisOperationCycle",
        "pendingDTC",
        "confirmedDTC",
        "testNotCompletedSinceLastClear",
        "testFailedSinceLastClear",
        "testNotCompletedThisOperationCycle",
        "warningIndicatorRequested",
    ]

    def __init__(self, value):
        # Don't try to parse if value is "any"
        if isinstance(value, str) and value.lower() == "any":
            self.value = "any"
            for name in self.BIT_NAMES:
                setattr(self, name, None)
        else:
            if isinstance(value, str):
                value = int(value, 16) if value.startswith("0x") else int(value)
            self.value = value
            for i, name in enumerate(self.BIT_NAMES):
                setattr(self, name, (value >> i) & 1)

    def __repr__(self):
        if self.value == "any":
            return "any"
        return f"0x{self.value:02X}".lower()

class DTC:
    def __init__(self, code, status):
        self.dtc = self._hexify(code)
        self.status = DTCStatus(status)

    def _hexify(self, val):
        # Use the DTC-specific formatter to keep width
        return format_dtc_code(val)

    def __repr__(self):
        return f"DTC(code={self.dtc}, status={self.status})"

class DiagResponse:
    def __init__(self, name, request_did, response_did, expected_did, responsetype, result, reason):
        self.name = name
        self.request = {"did": request_did}
        self.response = {"did": response_did}
        self.expected = {"did": expected_did}
        self.responsetype = responsetype
        self.result = result
        self.reason = reason

    def __repr__(self):
        return (f"DiagResponse(name={self.name}, request={self.request}, "
                f"response={self.response}, expected={self.expected}, "
                f"type={self.responsetype}, result={self.result})")

def get_muted_dtcs() -> List[DTCInfo]:
    """
    Retrieves muted DTCs from the configuration.
    """
    config = ConfigManager().config
    try:
        muted = config.muted_troubles.DTC if config and config.muted_troubles else []
    except AttributeError:
        muted = []
    return [DTCInfo(DTC=format_dtc_code(x), status=STATUS_ANY) for x in (muted or [])]

def dtc_matches_code(dtc: DTCInfo, rule: DTCInfo) -> bool:
    """
    Compares the DTC code of the DUT and the rule for a match.
    """
    try:
        dtc_code = _to_int(dtc.DTC)
        rule_code = _to_int(rule.DTC)
        return dtc_code is not None and rule_code is not None and dtc_code == rule_code
    except Exception as e:
        print(f"Error in dtc_matches_code: {e}")
        return False

def status_matches(dut_status: str, rule_status: str) -> bool:
    """
    Compares the status of the DUT with the rule status.
    Handles "any" status and supports pattern matching with '*'.
    """
    if rule_status == STATUS_ANY:
        return True  # Matches any status

    # Wildcard pattern support: rule_status contains '*'
    if isinstance(rule_status, str) and "*" in rule_status:
        try:
            # Convert both status strings to binary strings
            dut_bin = bin(int(dut_status, 16))[2:]
            rule_pattern = rule_status
            # Align lengths
            maxlen = max(len(rule_pattern), len(dut_bin))
            rule_pattern = rule_pattern.zfill(maxlen)
            dut_bin = dut_bin.zfill(maxlen)
            for db, rp in zip(dut_bin, rule_pattern):
                if rp != '*' and db != rp:
                    return False
            return True
        except Exception:
            return False

    try:
        dut_status_int = _to_int(dut_status)
        rule_status_int = _to_int(rule_status)
        if dut_status_int is None or rule_status_int is None:
            return False
        return dut_status_int == rule_status_int
    except ValueError:
        return False

def build_comprehensive_dtc_results_table(
        dut_dtcs: List[DTCInfo],
        allowed_dtcs: List[DTCInfo],
        muted_dtcs: List[DTCInfo],
        expected_dtcs: List[DTCInfo]
) -> Dict[str, Any]:
    """
    Builds a comprehensive results table for DTC evaluation.
    Handles special cases for "status=any" in expected and muted rules.
    Marks expected DTCs missing from DUT as 'fail', including those with wildcard status.
    Evaluates status patterns like "11**11**".
    """
    table_data = []
    rule_sets = [
        (STATUS_ALLOWED, allowed_dtcs),
        (STATUS_MUTED, muted_dtcs),
        (STATUS_EXPECTED, expected_dtcs),
    ]
    # Track which expected DTCs were found in DUT
    expected_found = [False] * len(expected_dtcs)

    # Evaluate present DUT DTCs
    for dut in dut_dtcs:
        dtc_code = format_dtc_code(dut.DTC)
        dtc_status = parse_to_int_or_hex(dut.status)
        found = False
        for type_name, rules in rule_sets:
            for idx, rule in enumerate(rules):
                if dtc_matches_code(dut, rule):
                    dtc_plus_status = f"{format_dtc_code(rule.DTC)}+{parse_to_int_or_hex(rule.status)}"
                    # ---- Pattern matching for wildcard pattern statuses ----
                    if isinstance(rule.status, str) and "*" in rule.status:
                        if status_matches(dut.status, rule.status):
                            result = "none" if type_name in [STATUS_ALLOWED, STATUS_MUTED] else "pass"
                        else:
                            result = "fail"
                    # ---- Handle "status=any" for specific rule types ----
                    elif rule.status == STATUS_ANY:
                        if type_name == STATUS_EXPECTED:
                            result = "pass"
                        elif type_name in [STATUS_ALLOWED, STATUS_MUTED]:
                            result = "none"
                    else:
                        # Regular status matching logic
                        if status_matches(dut.status, rule.status):
                            result = "none" if type_name in [STATUS_ALLOWED, STATUS_MUTED] else "pass"
                        else:
                            result = "fail"
                    row = [
                        dtc_code,
                        dtc_status,
                        "Present",
                        type_name,
                        dtc_plus_status,
                        result
                    ]
                    table_data.append(row)
                    if type_name == STATUS_EXPECTED:
                        # Mark found for this expected DTC
                        for eidx, ex in enumerate(expected_dtcs):
                            if dtc_matches_code(dut, ex):
                                expected_found[eidx] = True
                    found = True
                    break
            if found:
                break
        if not found:
            # Not matched to any rule, so mark as Unexpected
            row = [
                dtc_code,
                dtc_status,
                "Present",
                "Unexpected",
                "",
                "fail"
            ]
            table_data.append(row)

    # ---- Check for missing expected DTCs (FAIL if missing in DUT; including wildcards) ----
    for idx, ex in enumerate(expected_dtcs):
        if not expected_found[idx]:
            row = [
                format_dtc_code(ex.DTC),
                parse_to_int_or_hex(ex.status),
                "Not Present",
                STATUS_EXPECTED,
                f"{format_dtc_code(ex.DTC)}+{parse_to_int_or_hex(ex.status)}",
                "fail"
            ]
            table_data.append(row)

    return {
        "name": "DTC Comprehensive Evaluation",
        "column_header": ["DTC", "Status", "Present/Not present", "Type", "DTC+Status", "Result"],
        "data": table_data,
        "expanded": True  # keep DTC tables expanded
    }

def build_dtc_rule_summary_table(
    allowed_dtcs: List[DTCInfo],
    expected_dtcs: List[DTCInfo],
    muted_dtcs: List[DTCInfo]
) -> Dict[str, Any]:
    """
    Builds the rule summary table with DTC codes and statuses formatted in hexadecimal.
    """
    table_data = []
    for rule in allowed_dtcs:
        table_data.append([STATUS_ALLOWED, format_dtc_code(rule.DTC), parse_to_int_or_hex(rule.status)])
    for rule in expected_dtcs:
        table_data.append([STATUS_EXPECTED, format_dtc_code(rule.DTC), parse_to_int_or_hex(rule.status)])
    for rule in muted_dtcs:
        table_data.append([STATUS_MUTED, format_dtc_code(rule.DTC), parse_to_int_or_hex(rule.status)])
    return {
        "name": "DTC Rule Summary",
        "column_header": ["Type", "DTC", "Status"],
        "data": table_data,
        "expanded": True  # keep DTC tables expanded
    }

def evaluate_dtc_block(
    dut_dtcs: List[DTCInfo],
    allowed_dtcs: List[DTCInfo],
    expected_dtcs: List[DTCInfo],
    report: Any = None
) -> List[DTC]:
    """
    Evaluates DTCs based on allowed, expected, and muted rules.
    """
    muted_dtcs = get_muted_dtcs()
    dtc_objs = []

    # Generate summary table for the rules (expanded)
    summary_table = build_dtc_rule_summary_table(allowed_dtcs, expected_dtcs, muted_dtcs)
    add_table(summary_table)

    # If no DTCs are present, return PASS (expanded table, but empty data)
    if not dut_dtcs:
        table = {
            "name": "DTC Comprehensive Evaluation",
            "column_header": ["DTC", "Status", "Present/Not present", "Type", "DTC+Status", "Result"],
            "data": [],
            "expanded": True
        }
        add_table(table)
        add_step("PASS", "DTC evaluation overall status: PASS")
        return dtc_objs

    # Comprehensive evaluation of DTCs (expanded)
    table = build_comprehensive_dtc_results_table(dut_dtcs, allowed_dtcs, muted_dtcs, expected_dtcs)
    results = [row[5] for row in table["data"] if row[5]]
    status = "FAIL" if any(r == "fail" for r in results) else "PASS"
    add_table(table)
    add_step(status, f"DTC evaluation overall status: {status}")

    for dtc in dut_dtcs:
        dtc_objs.append(DTC(format_dtc_code(dtc.DTC), parse_to_int_or_hex(dtc.status)))
    return dtc_objs

def evaluate_diagnostic_expected_response(
    did: Any,
    actual_response: Any,
    expected_response: Any,
    name: str = None,
    report: Any = None
) -> DiagResponse:
    """
    Evaluate a diagnostic response against the expected response.
    Only DTC tables should be expanded by default; non-DTC tables are collapsed.
    """
    def response_to_bytes(resp):
        if isinstance(resp, (bytes, bytearray)):
            return list(resp)
        if isinstance(resp, str):
            parts = resp.replace(",", " ").split()
            return [int(p, 16) if p.startswith("0x") else int(p) for p in parts]
        if isinstance(resp, list):
            return [int(x, 16) if isinstance(x, str) and x.startswith("0x") else int(x) for x in resp]
        if isinstance(resp, int):
            return [resp]
        return []

    def to_hex_str(val):
        if isinstance(val, (bytes, bytearray)):
            return " ".join(f"0x{b:02X}" for b in val).lower()
        if isinstance(val, list):
            return " ".join(
                f"0x{int(x, 16):02X}" if isinstance(x, str) and x.startswith("0x") else f"0x{int(x):02X}" for x in val
            ).lower()
        if isinstance(val, int):
            return f"0x{val:02X}".lower()
        try:
            v = int(val, 16) if isinstance(val, str) and val.startswith("0x") else int(val)
            return f"0x{v:02X}".lower()
        except ValueError:
            return str(val)

    # Convert inputs into byte representation
    did_bytes = response_to_bytes(did)
    actual_bytes = response_to_bytes(actual_response)
    expected_bytes = response_to_bytes(expected_response) if isinstance(expected_response, list) else None
    main_did = did_bytes[0] if did_bytes else None

    # Initialize evaluation result
    result = "FAIL"
    reason = ""
    responsetype = "unknown"

    # Case: No expected response
    if expected_response == "none":
        responsetype = "none"
        result = "NONE"
        reason = f"Expected no response, received: {to_hex_str(actual_response)}" if actual_response else "Expected no response and none was received"

    # Case: Any other expected response
    elif not actual_response:
        reason = f"Expected response {to_hex_str(expected_response)}, but received no response."
        raise ValueError(reason)

    # Case: Length check for 0x22 with ln(N) format
    elif isinstance(expected_response, str) and expected_response.startswith("ln(") and expected_response.endswith(")"):
        responsetype = "ln"
        try:
            N = int(expected_response[3:-1])
            if main_did == 0x22:
                if actual_bytes and actual_bytes[0] == 0x62 and len(actual_bytes[3:]) == N:
                    result = "PASS"
                else:
                    reason = (f"For DID 0x22, expected response[0]==0x62 and len(response[3:])=={N}, "
                              f"got {to_hex_str(actual_response)}")
            else:
                reason = "ln(N) length check applies only to DID 0x22"
        except ValueError:
            reason = f"Invalid ln(N) format: {expected_response}"

    # Case: Explicit list match
    elif isinstance(expected_response, list):
        responsetype = "explicit"
        if actual_bytes == expected_bytes:
            result = "PASS"
        else:
            reason = f"Expected {to_hex_str(expected_response)} got {to_hex_str(actual_response)}"

    # Case: Positive response expected
    elif expected_response == "positive":
        responsetype = "positive"
        expected_first = (main_did + 0x40) if main_did is not None else None
        if actual_bytes and expected_first is not None and actual_bytes[0] == expected_first:
            result = "PASS"
        else:
            reason = (f"Expected positive response (DID[0] + 0x40 == 0x{(expected_first or 0):02X}), "
                      f"got {to_hex_str(actual_response)}")

    # Case: Negative response expected
    elif expected_response == "negative":
        responsetype = "negative"
        if actual_bytes and actual_bytes[0] == 0x7F:
            result = "PASS"
        else:
            reason = f"Expected negative response (0x7F), got {to_hex_str(actual_response)}"

    # Case: Unknown expected response format
    else:
        reason = f"Unknown expected_response format: {expected_response}"

    # Reporting results (non-DTC table collapsed by default on fallback)
    try:
        name_val = name if name is not None else to_hex_str(did)
        add_diagnostic_tx_rx_group(
            name=name_val,
            tx_bytes=to_hex_str(did_bytes),
            rx_bytes=to_hex_str(actual_bytes),
            expected=to_hex_str(expected_bytes) if expected_bytes is not None else to_hex_str(expected_response),
            status=result
        )
    except Exception:
        table = {
            "name": f"Diagnostic Response Check for DID {to_hex_str(did)}",
            "column_header": ["DID", "Expected", "Actual", "Result", "Reason"],
            "data": [[to_hex_str(did), to_hex_str(expected_response), to_hex_str(actual_response), result, reason]],
            "expanded": False  # collapse non-DTC tables by default
        }
        add_table(table)
        add_step(result, f"Diagnostic response check for {to_hex_str(did)}: {result}")

    return DiagResponse(
        name=name if name is not None else to_hex_str(did),
        request_did=to_hex_str(did_bytes),
        response_did=to_hex_str(actual_bytes),
        expected_did=to_hex_str(expected_bytes) if expected_bytes is not None else to_hex_str(expected_response),
        responsetype=responsetype,
        result=result,
        reason=reason
    )
