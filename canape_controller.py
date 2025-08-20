"""
CANape Controller integration for TestPackage

Requirements:
  pip install pywin32 asammdf numpy

What this provides
- Thin wrapper around CANape COM (via win32com) that:
  - opens a CANape project
  - lets you add devices and go online
  - records MF4 directly into this test's tests/<TestCase>/testResults folder
  - after recording, logs and adds a report step with the MF4 path and the recorded signals
  - no charts are added (per request)

Typical usage in a test:
  from TestPackage import canape, open_projection

  # optionally switch/open a project:
  open_projection(r"C:\Path\To\CANapeProject")

  # variables
  v = canape["XCPsim:ampl"]
  print(v.value)
  v.value = 5

  # record (saves MF4 under tests/<TestCase>/testResults)
  with canape.recorder(v, task_name="100ms", sampling_time=100, filename="capture.mf4") as rec:
      # perform actions while recording
      pass

The MF4 file will be saved under:
  <report_root>/<suite_timestamp>/tests/<TestCase>/testResults/<filename>.mf4
"""

import os
import time
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import Dict, List, Optional, Union, Any

try:
    import numpy as np
except Exception:
    np = None  # type: ignore

try:
    import win32com.client  # type: ignore
except Exception:
    win32com = None  # type: ignore

try:
    from asammdf import MDF, Signal  # type: ignore
except Exception:
    MDF = None  # type: ignore
    Signal = None  # type: ignore


# ---------- Internal helpers ----------

def _dispatch_canape():
    if win32com is None:
        raise RuntimeError("pywin32 is required (pip install pywin32) to automate CANape.")
    try:
        return win32com.client.Dispatch("CANape.Application")
    except Exception:
        # some installations expose a legacy/typo ProgID
        return win32com.client.Dispatch("CAMape.Application")


def _ensure_parent_dir(path: str):
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _wait_for_file_stable(path: str, timeout_s: float = 30.0, poll_s: float = 0.25) -> bool:
    end = time.time() + timeout_s
    last = -1
    seen = False
    while time.time() < end:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if seen and size == last and size > 0:
                return True
            last = size
            seen = True
        time.sleep(poll_s)
    return os.path.exists(path)


class _CanapeVariable:
    def __init__(self, app, device_com, device_name: str, varname: str):
        self._app = app
        self._dev = device_com
        self.device_name = device_name
        self.varname = varname
        self.longname = f"{device_name}:{varname}"

    @property
    def value(self):
        self._dev.CalibrationObjects.Add(self.varname)
        obj = self._dev.CalibrationObjects.Item(self.varname)
        obj.Read()
        return obj.Value

    @value.setter
    def value(self, val):
        self._dev.CalibrationObjects.Add(self.varname)
        obj = self._dev.CalibrationObjects.Item(self.varname)
        obj.Value = val
        obj.Write()

    def __repr__(self):
        return f"<CanapeVariable {self.longname}>"


def _get_signal_raw_preferred(mdf: "MDF", name: str) -> "Signal":
    try:
        return mdf.get(name, raw=True)  # asammdf new
    except TypeError:
        return mdf.get(name)
    except Exception:
        return mdf.get(name)


def _maybe_text_to_raw(samples, signal: "Signal"):
    # already numeric
    if hasattr(samples, "dtype") and samples.dtype.kind in ("i", "u", "f", "b"):
        return samples

    conv = getattr(signal, "conversion", None)
    if conv is not None:
        for attr in ("text_2_value", "text2value", "text_to_value", "value_map", "val_map"):
            mapping = getattr(conv, attr, None)
            if mapping:
                out = []
                for s in samples:
                    if s in mapping:
                        out.append(mapping[s]); continue
                    if isinstance(s, (bytes, bytearray)):
                        try:
                            s2 = s.decode(errors="ignore")
                            if s2 in mapping:
                                out.append(mapping[s2]); continue
                        except Exception:
                            pass
                    try:
                        out.append(float(s))
                    except Exception:
                        out.append(float("nan"))
                return np.array(out, dtype=float) if np is not None else out
    try:
        return samples.astype(float)
    except Exception:
        return samples


class _SignalView:
    def __init__(self, signal: "Signal", display_name: Optional[str] = None, force_raw: bool = False):
        if np is None:
            raise RuntimeError("numpy is required (pip install numpy).")
        self._sig = signal
        self._name = display_name or getattr(signal, "name", "signal")
        xs = signal.timestamps
        ys = signal.samples
        if force_raw or (hasattr(ys, "dtype") and ys.dtype.kind in ("O", "U", "S")):
            ys = _maybe_text_to_raw(ys, signal)
        self._x = np.asarray(xs)
        self._y = np.asarray(ys)

    @property
    def x(self): return self._x
    @property
    def y(self): return self._y
    @property
    def name(self) -> str: return self._name
    @property
    def data(self):
        n = min(len(self._x), len(self._y))
        return tuple((float(self._x[i]), float(self._y[i])) for i in range(n))

    def __repr__(self):
        return f"<SignalView name={self._name!r} len={len(self._x)}>"


class _RecorderResult:
    """
    Finalized AFTER the 'with cc.recorder(...)' block exits.
    Provides:
      - rec.signals -> list of recorded signal long names (order preserved)
      - rec.values() -> list of _SignalView with name/x/y/data
      - dict-like access: rec['Dev:Var'] or rec[CanapeVariable]
      - filepath -> absolute path to the MF4 file
    """
    def __init__(self, app, task_per_device: Dict[str, Any], added_per_device: Dict[str, List[str]], vars_list: List[_CanapeVariable], mdf_path: str):
        self._app = app
        self._tasks = task_per_device
        self._added = added_per_device
        self._vars = vars_list
        self.filepath = os.path.abspath(mdf_path)

        self._mdf: Optional["MDF"] = None
        self._views_by_var: Dict[_CanapeVariable, _SignalView] = {}
        self._views_by_name: Dict[str, _SignalView] = {}
        self._ordered_names: List[str] = []

    def _resolve_signal(self, mdf: "MDF", expected_long: str, tail: str, names: List[str]) -> Optional["Signal"]:
        try:
            return _get_signal_raw_preferred(mdf, expected_long)
        except Exception:
            pass
        try:
            return _get_signal_raw_preferred(mdf, tail)
        except Exception:
            pass
        lower = {n.lower(): n for n in names}
        for cand in (expected_long, tail):
            n = lower.get(cand.lower())
            if n:
                try:
                    return _get_signal_raw_preferred(mdf, n)
                except Exception:
                    pass
        for sep in (":", "."):
            suffix = f"{sep}{tail}"
            matches = [n for n in names if n.endswith(suffix)]
            if len(matches) == 1:
                try:
                    return _get_signal_raw_preferred(mdf, matches[0])
                except Exception:
                    pass
        return None

    def _load_views(self):
        if MDF is None:
            raise RuntimeError("asammdf is required (pip install asammdf) to read MF4 files.")
        self._mdf = MDF(self.filepath)
        try:
            names = list(self._mdf.get_channel_names())
        except Exception:
            names = []

        for v in self._vars:
            sig = self._resolve_signal(self._mdf, v.longname, v.varname, names)
            if sig is not None:
                view = _SignalView(sig, display_name=v.longname)
                self._views_by_var[v] = view
                self._views_by_name[v.longname] = view
                self._ordered_names.append(v.longname)

        # also allow raw MDF names lookup
        for n in names:
            if n not in self._views_by_name:
                try:
                    sig = _get_signal_raw_preferred(self._mdf, n)
                    self._views_by_name[n] = _SignalView(sig, display_name=n)
                except Exception:
                    continue

    def finalize(self):
        try:
            self._app.Measurement.Stop()
        except Exception:
            pass

        for dev, task in self._tasks.items():
            for ch in self._added.get(dev, []):
                try:
                    task.Channels.Remove(ch)
                except Exception:
                    pass

        _wait_for_file_stable(self.filepath, timeout_s=30.0, poll_s=0.25)
        self._load_views()

    def __getitem__(self, key: Union[_CanapeVariable, str]) -> _SignalView:
        if isinstance(key, _CanapeVariable):
            view = self._views_by_var.get(key)
            if view is None:
                raise KeyError(f"No recorded data for {key.longname} in '{self.filepath}'")
            return view
        elif isinstance(key, str):
            if key in self._views_by_name:
                return self._views_by_name[key]
            tail = key.split(":", 1)[-1]
            matches = [n for n in self._views_by_name.keys() if n.endswith(":" + tail) or n.endswith("." + tail) or n == tail]
            if len(matches) == 1:
                return self._views_by_name[matches[0]]
            raise KeyError(f"No recorded data for '{key}' in '{self.filepath}'")
        else:
            raise TypeError("Key must be a CanapeVariable or 'Device:Variable' string.")

    @property
    def signals(self) -> List[str]:
        return list(self._ordered_names)

    def values(self) -> List[_SignalView]:
        out: List[_SignalView] = []
        for name in self._ordered_names:
            view = self._views_by_name.get(name)
            if view is not None:
                out.append(view)
        return out


class _CanapeDevice:
    def __init__(self, app, device_com, name: str):
        self.app = app
        self.dev = device_com
        self.name = name


class _CanapeSession:
    def __init__(self, project_path: Optional[str] = None):
        self.app = _dispatch_canape()
        try:
            self.app.Measurement.FifoSize = 2048
            self.app.Measurement.SampleSize = 1024
        except Exception:
            pass

        if project_path is None:
            project_path = r"C:\Users\Public\Documents\Vector\CANape Examples 21.0\XCPDemo"

        self.app.Open2(project_path, 1, 100000, 0, 0, 1)
        time.sleep(2)

        self.devices: Dict[str, _CanapeDevice] = {}
        self._var_cache: Dict[str, _CanapeVariable] = {}

    def add_device(self, name: str, a2l: str, dev_type: str, channel: int) -> _CanapeDevice:
        dev_com = self.app.Devices.Add(name, a2l, dev_type, channel)
        dev = _CanapeDevice(self.app, dev_com, name)
        self.devices[name] = dev
        return dev

    def go_online_all(self, reconnect: bool = False):
        for dev in self.devices.values():
            try:
                dev.dev.GoOnline(reconnect)
            except Exception:
                pass

    def close(self):
        try:
            for dev in self.devices.values():
                try:
                    dev.dev.GoOffline()
                except Exception:
                    pass
        finally:
            try:
                self.app.Quit()
            except Exception:
                pass

    def __getitem__(self, longname: str) -> _CanapeVariable:
        if ":" not in longname:
            raise ValueError('Use "Device:Variable", e.g., "XCPsim:ampl"')
        devname, varname = longname.split(":", 1)
        if devname not in self.devices:
            raise KeyError(f"Device '{devname}' is not added.")
        key = f"{devname}:{varname}"
        if key in self._var_cache:
            return self._var_cache[key]
        var = _CanapeVariable(self.app, self.devices[devname].dev, devname, varname)
        self._var_cache[key] = var
        return var

    @contextmanager
    def recorder(
        self,
        *vars_or_longnames: Union[_CanapeVariable, str],
        task_name: str = "100ms",
        sampling_time: Optional[int] = 100,
        mdf_path: Optional[str] = None
    ):
        if not vars_or_longnames:
            raise TypeError("Provide at least one variable or 'Device:Variable'.")

        vars_list: List[_CanapeVariable] = []
        for item in vars_or_longnames:
            if isinstance(item, _CanapeVariable):
                vars_list.append(item)
            elif isinstance(item, str):
                vars_list.append(self[item])
            else:
                raise TypeError("Items must be CanapeVariable or 'Device:Variable'.")

        by_dev: Dict[str, List[_CanapeVariable]] = {}
        for v in vars_list:
            by_dev.setdefault(v.device_name, []).append(v)

        tasks: Dict[str, Any] = {}
        added: Dict[str, List[str]] = {}

        for devname, dev_vars in by_dev.items():
            dev_com = self.devices[devname].dev
            task = dev_com.Tasks(task_name)
            tasks[devname] = task

            if sampling_time is not None:
                try:
                    task.SamplingTime = int(sampling_time)
                except Exception:
                    pass

            added_names: List[str] = []
            for v in dev_vars:
                try:
                    dev_com.CalibrationObjects.Add(v.varname)
                except Exception:
                    pass
                try:
                    task.Channels.Add(v.varname)
                    try:
                        task.Channels(v.varname).Save2MDF = True
                    except Exception:
                        pass
                    added_names.append(v.varname)
                except Exception:
                    pass
            added[devname] = added_names

        if mdf_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            mdf_path = os.path.abspath(f"canape_recording_{stamp}.mf4")
        _ensure_parent_dir(mdf_path)
        try:
            self.app.Measurement.MDFFilename = mdf_path
        except Exception:
            pass

        try:
            self.app.Measurement.Start()
        except Exception:
            pass

        rec = _RecorderResult(self.app, tasks, added, vars_list, mdf_path)
        try:
            yield rec
        finally:
            rec.finalize()


# ---------- Public Controller ----------

class CanapeController:
    """
    High-level controller that:
      - wraps CANape session/device/recording setup,
      - saves MF4 in the current test's tests/<TestCase>/testResults folder,
      - logs actions via logger,
      - reports the MF4 path (no chart).
    """
    def __init__(
        self,
        report: Optional[Any] = None,      # TestReport object (optional)
        logger: Optional[logging.Logger] = None,
        project_path: Optional[str] = None
    ):
        if np is None:
            raise RuntimeError("numpy is required (pip install numpy).")
        self.report = report
        self.logger = logger or logging.getLogger("TestPackage.CANape")
        self._session = _CanapeSession(project_path=project_path)

    # Allow canape["Device:Variable"] access
    def __getitem__(self, longname: str) -> _CanapeVariable:
        return self._session[longname]

    # Session passthroughs
    def add_device(self, name: str, a2l: str, dev_type: str, channel: int):
        self.logger.info("CANape: adding device '%s' (type=%s, ch=%s, a2l=%s)", name, dev_type, channel, a2l)
        return self._session.add_device(name, a2l, dev_type, channel)

    def go_online_all(self, reconnect: bool = False):
        self.logger.info("CANape: go online (reconnect=%s)", reconnect)
        return self._session.go_online_all(reconnect)

    def close(self):
        self.logger.info("CANape: closing session")
        return self._session.close()

    def _get_test_results_dir(self) -> str:
        """
        Resolve tests/<TestCase>/testResults using reporting_manager.
        If not available, fallback to CWD/report/tmp/<timestamp>/testResults.
        """
        try:
            from TestPackage.report import reporting_manager as rm
            path = rm.get_test_report_path()
            os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            # fallback
            stamp = datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
            fallback = os.path.abspath(os.path.join("report", stamp, "tests", "default", "testResults"))
            os.makedirs(fallback, exist_ok=True)
            self.logger.warning("Reporting manager not ready; using fallback testResults path: %s", fallback)
            return fallback

    @contextmanager
    def recorder(
        self,
        *vars_or_longnames: Union[str, _CanapeVariable],
        task_name: str = "100ms",
        sampling_time: Optional[int] = 100,
        filename: Optional[str] = None,
    ):
        """
        Record specified signals to MF4 in this test's 'testResults' folder and log/report the path.
        No chart is added.
        """
        results_dir = self._get_test_results_dir()
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = filename or f"CANape_{stamp}.mf4"
        mdf_path = os.path.join(results_dir, fname)

        self.logger.info("CANape: start recording -> %s", mdf_path)

        with self._session.recorder(
            *vars_or_longnames,
            task_name=task_name,
            sampling_time=sampling_time,
            mdf_path=mdf_path
        ) as rec:
            yield rec

        # After finalize
        signals = rec.signals
        self.logger.info("CANape: recording complete. %d signals saved to %s", len(signals), rec.filepath)

        # Report via context if explicit report not provided
        try:
            if self.report is not None:
                self.report.add_step("INFO", f"MF4 saved to: {rec.filepath}\nSignals: {', '.join(signals) if signals else '(none)'}")
            else:
                from TestPackage.report.test_report_context import add_step as ctx_add_step
                ctx_add_step("INFO", f"MF4 saved to: {rec.filepath}\nSignals: {', '.join(signals) if signals else '(none)'}")
        except Exception as e:
            self.logger.exception("Failed to add MF4 info to report: %s", e)