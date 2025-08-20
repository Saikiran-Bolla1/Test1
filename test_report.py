from .status import get_case_status
from datetime import datetime
from contextlib import contextmanager
from typing import Any, Dict, List, Tuple, Sequence, Optional
import textwrap

def get_group_status(children):
    priority = {"ERROR": 3, "FAIL": 2, "PASS": 1, "INFO": 0, "NONE": 0}
    group_status = "NONE"
    for child in children:
        status = child.get("status", "NONE")
        if child.get("category") == "GROUP":
            status = get_group_status(child.get("children", []))
            child["status"] = status
        if priority.get(status, 0) > priority.get(group_status, 0):
            group_status = status
    return group_status

def get_table_status(table):
    result_idx = None
    headers = table.get("column_header", [])
    if headers:
        for idx, h in enumerate(headers):
            if h.strip().lower() == "result":
                result_idx = idx
                break
    if result_idx is not None:
        priority = {'FAIL': 0, 'PASS': 1, 'NONE': 2}
        data = table.get("data", [])
        data.sort(key=lambda row: priority.get(str(row[result_idx]).strip().upper(), 3))
        found = False
        has_pass = False
        for row in data:
            if len(row) > result_idx:
                val = row[result_idx]
                found = True
                if isinstance(val, str):
                    v = val.strip().upper()
                    if v == "FAIL":
                        return "FAIL"
                    if v == "PASS":
                        has_pass = True
        if found and has_pass:
            return "PASS"
        if found:
            return "NONE"
        return "NONE"
    found = False
    has_pass = False
    for row in table.get("data", []):
        for cell in row:
            if isinstance(cell, str):
                found = True
                v = cell.strip().upper()
                if v == "FAIL":
                    return "FAIL"
                if v == "PASS":
                    has_pass = True
    if found and has_pass:
        return "PASS"
    if found:
        return "NONE"
    return "NONE"

def _lin_interp(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))

def _series_value_at(xq: float, xs: List[float], ys: List[float]) -> Optional[float]:
    from bisect import bisect_left
    i = bisect_left(xs, xq)
    if i < len(xs) and xs[i] == xq:
        return ys[i]
    left = i - 1
    right = i
    in_left = left >= 0
    in_right = right < len(xs)
    if in_left and in_right:
        return _lin_interp(xq, xs[left], ys[left], xs[right], ys[right])
    return None

def _align_signals_union(
    signals: Sequence[Tuple[List[float], List[float], str]],
    name: str = "Signals",
    xlabel: str = "Time (s)",
    ylabel: str = "Value",
    x_mode: str = "number",
    colors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    xs_union = sorted({float(x) for xs, _, _ in signals for x in xs})
    y_map: Dict[str, List[Optional[float]]] = {}
    legend: List[str] = []
    for xs, ys, leg in signals:
        xs_f = list(map(float, xs))
        ys_f = list(map(float, ys))
        legend.append(leg)
        y_map[leg] = [_series_value_at(xq, xs_f, ys_f) for xq in xs_union]
    chart: Dict[str, Any] = {
        "name": name,
        "legend": legend,
        "x": xs_union,
        "y": y_map,
        "xlabel": xlabel,
        "ylabel": ylabel,
        "xMode": x_mode,
    }
    if colors:
        chart["colors"] = colors
    return chart

def _xs_equal(xs_list: List[List[float]]) -> bool:
    if not xs_list:
        return True
    ref = xs_list[0]
    for xs in xs_list[1:]:
        if len(xs) != len(ref):
            return False
        for a, b in zip(xs, ref):
            if float(a) != float(b):
                return False
    return True

def _normalize_chart_input(input_obj: Any) -> Dict[str, Any]:
    if isinstance(input_obj, dict) and ("x" in input_obj and "y" in input_obj):
        return input_obj
    if isinstance(input_obj, dict) and "signals" in input_obj:
        opts = input_obj
        name = opts.get("name", "Signals")
        xlabel = opts.get("xlabel", "Time (s)")
        ylabel = opts.get("ylabel", "Value")
        x_mode = opts.get("xMode", "number")
        colors = opts.get("colors")
        sigs = opts.get("signals", [])
        parsed: List[Tuple[List[float], List[float], str]] = []
        if isinstance(sigs, (list, tuple)) and sigs:
            if hasattr(sigs[0], "x") and hasattr(sigs[0], "y"):
                xs_list: List[List[float]] = []
                for it in sigs:
                    xs = list(map(float, getattr(it, "x")))
                    ys = list(map(float, getattr(it, "y")))
                    nm = getattr(it, "name", None) or f"Sig{len(parsed)+1}"
                    xs_list.append(xs)
                    parsed.append((xs, ys, nm))
                if _xs_equal(xs_list):
                    legend = [p[2] for p in parsed]
                    x = parsed[0][0]
                    y_map = {p[2]: parsed[i][1] for i, p in enumerate(parsed)}
                    chart = {
                        "name": name,
                        "legend": legend,
                        "x": x,
                        "y": y_map,
                        "xlabel": xlabel,
                        "ylabel": ylabel,
                        "xMode": x_mode,
                    }
                    if colors:
                        chart["colors"] = colors
                    return chart
                return _align_signals_union(parsed, name=name, xlabel=xlabel, ylabel=ylabel, x_mode=x_mode, colors=colors)
            else:
                parsed_pairs: List[Tuple[List[float], List[float], str]] = []
                for idx, series in enumerate(sigs):
                    if isinstance(series, (list, tuple)) and series and isinstance(series[0], (list, tuple)) and len(series[0]) >= 2:
                        xs = [float(p[0]) for p in series]
                        ys = [float(p[1]) for p in series]
                        parsed_pairs.append((xs, ys, f"Sig{idx+1}"))
                if parsed_pairs:
                    xs_list = [p[0] for p in parsed_pairs]
                    if _xs_equal(xs_list):
                        legend = [p[2] for p in parsed_pairs]
                        x = parsed_pairs[0][0]
                        y_map = {p[2]: parsed_pairs[i][1] for i, p in enumerate(parsed_pairs)}
                        chart = {
                            "name": name,
                            "legend": legend,
                            "x": x,
                            "y": y_map,
                            "xlabel": xlabel,
                            "ylabel": ylabel,
                            "xMode": x_mode,
                        }
                        if colors:
                            chart["colors"] = colors
                        return chart
                    return _align_signals_union(parsed_pairs, name=name, xlabel=xlabel, ylabel=ylabel, x_mode=x_mode, colors=colors)
        return {"name": name, "legend": [], "x": [], "y": {}, "xlabel": xlabel, "ylabel": ylabel, "xMode": x_mode}
    if isinstance(input_obj, (list, tuple)):
        items = list(input_obj)
        if not items:
            return {"name": "Signals", "legend": [], "x": [], "y": {}}
        if hasattr(items[0], "x") and hasattr(items[0], "y"):
            views = list(items)
            xs_list: List[List[float]] = [list(map(float, getattr(v, "x"))) for v in views]
            ys_list: List[List[float]] = [list(map(float, getattr(v, "y"))) for v in views]
            names: List[str] = [getattr(v, "name", None) or f"Sig{i+1}" for i, v in enumerate(views)]
            if _xs_equal(xs_list):
                x = xs_list[0]
                legend = names
                y_map: Dict[str, List[float]] = {names[i]: ys_list[i] for i in range(len(views))}
                return {
                    "name": "Signals",
                    "legend": legend,
                    "x": x,
                    "y": y_map,
                    "xlabel": "Time (s)",
                    "ylabel": "Value",
                }
            parsed = list(zip(xs_list, ys_list, names))
            return _align_signals_union(parsed)
        elif isinstance(items[0], (list, tuple)) and items and items[0] and isinstance(items[0][0], (list, tuple)):
            parsed_pairs: List[Tuple[List[float], List[float], str]] = []
            for idx, series in enumerate(items):
                xs = [float(p[0]) for p in series]
                ys = [float(p[1]) for p in series]
                parsed_pairs.append((xs, ys, f"Sig{idx+1}"))
            xs_list = [p[0] for p in parsed_pairs]
            if _xs_equal(xs_list):
                x = parsed_pairs[0][0]
                legend = [p[2] for p in parsed_pairs]
                y_map = {p[2]: parsed_pairs[i][1] for i, p in enumerate(parsed_pairs)}
                return {
                    "name": "Signals",
                    "legend": legend,
                    "x": x,
                    "y": y_map,
                    "xlabel": "Time (s)",
                    "ylabel": "Value",
                }
            return _align_signals_union(parsed_pairs)
    if isinstance(input_obj, dict):
        return input_obj
    return {"name": "Signals", "legend": [], "x": [], "y": {}}

class TestReport:
    project = None

    @classmethod
    def set_project(cls, project_name):
        cls.project = project_name

    def __init__(self, name, goal=None, requirements=None, dut=None):
        self.name = name
        self.goal = goal
        self.requirements = requirements or []
        self.lines: List[Dict[str, Any]] = []
        self.tables: List[Dict[str, Any]] = []
        self.charts: List[Dict[str, Any]] = []
        self.status = get_case_status(self.lines)
        self.project = TestReport.project
        self._group_stack: List[Dict[str, Any]] = []
        self.dut = dut or {}
        self.steps: List[Dict[str, Any]] = []

        # Top-of-report condition fields (avoid method name clash)
        self.top_condition: Optional[str] = None
        self.top_condition_comment: Optional[str] = None
        self.conditions: List[Dict[str, Any]] = []  # history list

    @contextmanager
    def start_group(self, title, comment=None):
        group = {
            "category": "GROUP",
            "title": title,
            "comment": comment,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "children": [],
            "status": "NONE"
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(group)
        else:
            self.lines.append(group)
        self._group_stack.append(group)
        try:
            yield
        finally:
            self._group_stack.pop()
            group["status"] = get_group_status(group["children"])
            self.status = get_case_status(self.lines)

    def add_step(self, status, comment):
        step = {
            "category": "STEP",
            "status": status,
            "comment": comment,
            "timestamp": datetime.now().strftime("%H:%M:%S")
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(step)
        else:
            self.lines.append(step)
        self.status = get_case_status(self.lines)

    def add_text(self, text: str, status: str = "INFO", title: str = None, max_preview_chars: int = 200, render: str = "step_only", table_wrap: int = 120):
        """
        Add multi-line text with a visible status.
        - Always creates a STEP with a one-line preview in 'comment'.
        - Optionally also creates a TABLE with the full text so it is visible even if the UI doesn't render 'details'.
        render:
          - "auto": STEP always; add TABLE if text is long or contains newlines.
          - "step_only": only STEP.
          - "step_and_table": always STEP + TABLE.
          - "table_only": only TABLE (no STEP).
        """
        title_or_preview = (title if title is not None else (text.splitlines()[0] if text else "")).strip() or "(text)"
        preview = title_or_preview[:max_preview_chars] + ("…" if len(title_or_preview) > max_preview_chars else "")

        should_add_table = (render == "step_and_table") or (render == "auto" and (len(text) > max_preview_chars or "\n" in text)) or (render == "table_only")

        # STEP (unless table_only)
        if render != "table_only":
            entry = {
                "category": "STEP",
                "status": status,
                "comment": preview,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "details": text,
                "details_type": "text"
            }
            if self._group_stack:
                self._group_stack[-1]["children"].append(entry)
            else:
                self.lines.append(entry)

        # TABLE with wrapped full text (optional)
        if should_add_table:
            lines: List[str] = []
            for par in (text or "").splitlines() or [""]:
                if par.strip() == "":
                    lines.append("")  # preserve blank line
                else:
                    lines.extend(textwrap.wrap(par, width=table_wrap, drop_whitespace=False) or [""])
            rows = [[ln] for ln in lines] if lines else [[""]]
            self.add_table(
                name=f"{title_or_preview}",
                data=rows,
                column_header=["text"],
            )

        self.status = get_case_status(self.lines)

    def add_table(self, name, data, column_header=None, row_header=None):
        idx = len(self.tables)
        table_dict = {"name": name, "data": data}
        if column_header is not None:
            table_dict["column_header"] = column_header
        if row_header is not None:
            table_dict["row_header"] = row_header
        self.tables.append(table_dict)
        table_status = get_table_status(table_dict)
        table_entry = {
            "category": "TABLE",
            "status": table_status,
            "comment": f"Table: {name or f'Table {idx+1}'}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "table_idx": idx
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(table_entry)
        else:
            self.lines.append(table_entry)
        self.status = get_case_status(self.lines)

    def add_chart(self, chart):
        normalized = _normalize_chart_input(chart)
        idx = len(self.charts)
        self.charts.append(normalized)
        chart_entry = {
            "category": "CHART",
            "status": "NONE",
            "comment": f"Chart: {normalized.get('name', f'Chart {idx+1}')}",
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "chart_idx": idx
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(chart_entry)
        else:
            self.lines.append(chart_entry)
        self.status = get_case_status(self.lines)

    def condition(self, cond: bool, description: str, comment: str = ""):
        """
        Record a condition check as a STEP and update top-of-report fields.
        """
        status = "PASS" if cond else "FAIL"
        now = datetime.now().strftime("%H:%M:%S")

        # 1) timeline step
        msg = description
        if comment:
            msg += f" | Comment: {comment}"
        self.add_step(status, msg)

        # 2) top-of-report (avoid name clash with this method)
        self.top_condition = description
        self.top_condition_comment = comment

        # 3) keep history
        self.conditions.append({
            "timestamp": now,
            "description": description,
            "comment": comment,
            "status": status,
        })

    # Convenience: equality check that formats "name(actual) == expected"
    def expect_equal(self, actual: Any, expected: Any, name: Optional[str] = None, comment: str = ""):
        """
        Example:
          a = 3
          report.expect_equal(a, 4, name="a")
        Produces a step: "a(3) == 4" with PASS/FAIL status.
        Also updates top-of-report condition/comment.
        """
        label = name or "value"
        desc = f"{label}({actual}) == {expected}"
        self.condition(actual == expected, desc, comment)

    def add_diagnostic_tx_rx_group(self, name, tx_bytes, rx_bytes, expected, status):
        now = datetime.now().strftime("%H:%M:%S")
        diagnostic = {
            "category": "DIAGNOSTIC",
            "timestamp": now,
            "tx": {"raw": tx_bytes},
            "rx": {"raw": rx_bytes},
            "expected": {"response": expected},
            "status": status
        }
        group = {
            "category": "GROUP",
            "title": f"send diagnostic request {name}",
            "timestamp": now,
            "status": status,
            "children": [diagnostic]
        }
        if self._group_stack:
            self._group_stack[-1]["children"].append(group)
        else:
            self.lines.append(group)
        self.status = get_case_status(self.lines)

    def to_dict(self):
        self.status = get_case_status(self.lines)
        return {
            "name": self.name,
            "goal": self.goal,
            "requirements": self.requirements,
            "lines": self.lines,
            "tables": self.tables,
            "charts": self.charts,
            "status": self.status,
            "project": self.project,
            "index": getattr(self, "index", None),
            "dut": self.dut,
            # Expose for top-of-report display
            "condition": self.top_condition,
            "conditionComment": self.top_condition_comment,
            "conditions": self.conditions,
        }