// --- Vue and Utility Setup (existing code) ---
const { createApp, ref, reactive, computed, nextTick, h } = Vue;

// Utility: format time for axis and legend
function formatTime(ts, mode) {
  if (mode === "datetime") {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + ' ' + d.toLocaleDateString();
  }
  if (typeof ts === "number") {
    return ts.toFixed(2);
  }
  return ts;
}

createApp({
  setup() {
    const myreport = reactive(window.myreport ?? {});
    const filter = ref('all');
    const currentTestName = ref(null);
    const loading = ref(false);
    const testcaseDetails = ref(null);
    const openGroups = ref(new Set());
    const openDiags = ref(new Set());
    const openTables = ref(new Set());
    const openCharts = ref(new Set());
    const openTexts = ref(new Set());
    const chartViewWindow = ref({});
    const chartSignalVisible = ref({});
    const chartCursorValues = ref({});
    const chartCursorX = ref({});

    const filteredTestNames = computed(() => {
      if (!myreport.testNames) return [];
      if (filter.value === "all") return myreport.testNames;
      return myreport.testNames.filter(name => {
        const status = (myreport.reportData?.[name]?.status || 'NONE').toLowerCase();
        return filter.value === status;
      });
    });

    const stats = computed(() => {
      if (
        testcaseDetails.value &&
        testcaseDetails.value.charts &&
        Object.keys(chartViewWindow.value).length > 0
      ) {
        const chartIdx = Object.keys(chartViewWindow.value)[0];
        const chart = testcaseDetails.value.charts[chartIdx];
        if (chart && chart.x && chart.y) {
          const { min, max } = chartViewWindow.value[chartIdx];
          const filteredIndices = chart.x
            .map((x, idx) => (x >= min && x <= max ? idx : -1))
            .filter(idx => idx !== -1);
          let yArrays = Array.isArray(chart.y) ? [chart.y] : Object.values(chart.y);
          let filteredStats = yArrays.map(arr => {
            const vals = filteredIndices.map(idx => arr[idx]).filter(v => typeof v === 'number');
            if (vals.length === 0) return { min: null, max: null, avg: null };
            const min = Math.min(...vals);
            const max = Math.max(...vals);
            const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
            return { min, max, avg };
          });
          return { ...filteredStats[0], window: `[${min.toFixed(2)} - ${max.toFixed(2)}]` };
        }
      }
      const testNames = myreport.testNames || [];
      let s = { pass: 0, fail: 0, error: 0, none: 0, all: testNames.length };
      let totalRunnable = 0;
      for (const name of testNames) {
        const status = (myreport.reportData?.[name]?.status || 'NONE').toUpperCase();
        if (status === 'PASS') { s.pass += 1; totalRunnable += 1; }
        else if (status === 'FAIL') { s.fail += 1; totalRunnable += 1; }
        else if (status === 'ERROR') { s.error += 1; totalRunnable += 1; }
        else { s.none += 1; }
      }
      if (s.error > 0) s.overall = 'ERROR';
      else if (s.fail > 0) s.overall = 'FAIL';
      else if (s.pass > 0 && s.pass === totalRunnable) s.overall = 'PASS';
      else if (s.none === s.all) s.overall = 'NONE';
      else s.overall = 'PARTIAL';
      s.date = myreport.statistics?.date || '';
      s.time = myreport.statistics?.time || '';
      s.duration = myreport.statistics?.duration || '';
      return s;
    });

    function showHome() {
      currentTestName.value = null;
      testcaseDetails.value = null;
      openGroups.value.clear();
      openDiags.value.clear();
      openTables.value.clear();
      openCharts.value.clear();
      openTexts.value.clear();
    }
    function selectTest(name) {
      currentTestName.value = name;
      testcaseDetails.value = null;
      loading.value = true;
      openGroups.value.clear();
      openDiags.value.clear();
      openTables.value.clear();
      openCharts.value.clear();
      openTexts.value.clear();
      if (window.reportData) delete window.reportData;
      const script = document.createElement('script');
      script.src = `tests/${name}/testResults/reportData.js`;
      script.onload = () => {
        loading.value = false;
        if (window.reportData && window.reportData.name === name) {
          testcaseDetails.value = window.reportData;
        } else {
          testcaseDetails.value = null;
        }
        script.remove();
      };
      script.onerror = () => {
        loading.value = false;
        testcaseDetails.value = null;
        script.remove();
      };
      document.body.appendChild(script);
    }
    function toggleGroup(idxPath) {
      openGroups.value.has(idxPath) ? openGroups.value.delete(idxPath) : openGroups.value.add(idxPath);
    }
    function toggleDiag(idxPath) {
      openDiags.value.has(idxPath) ? openDiags.value.delete(idxPath) : openDiags.value.add(idxPath);
    }
    function toggleTable(idxPath) {
      openTables.value.has(idxPath) ? openTables.value.delete(idxPath) : openTables.value.add(idxPath);
    }
    function toggleChart(idxPath) {
      openCharts.value.has(idxPath) ? openCharts.value.delete(idxPath) : openCharts.value.add(idxPath);
      if (openCharts.value.has(idxPath)) {
        nextTick(() => {
          const [chartIdx, chartId] = idxPath.split('|');
          renderUPlot(testcaseDetails.value.charts[Number(chartIdx)], chartId, Number(chartIdx));
        });
      }
    }
    function toggleText(idxPath) {
      openTexts.value.has(idxPath) ? openTexts.value.delete(idxPath) : openTexts.value.add(idxPath);
    }

    function renderTable(table) {
      let html = '<table class="custom-table">';
      if (table.column_header) {
        html += "<tr>";
        if (table.row_header) html += "<th></th>";
        table.column_header.forEach(h => html += `<th>${h}</th>`);
        html += "</tr>";
      }
      for (let i = 0; i < table.data.length; ++i) {
        html += "<tr>";
        if (table.row_header) html += `<th>${table.row_header[i]}</th>`;
        table.data[i].forEach(cell => html += `<td>${cell}</td>`);
        html += "</tr>";
      }
      html += "</table>";
      return html;
    }

    // Minimal chart rendering with below-readout that also filters signals
    function renderUPlot(chart, elId, chartIdx) {
      const el = document.getElementById(elId);
      if (!el) return;
      el.innerHTML = "";

      let legend, yArrays, colors;
      if (Array.isArray(chart.y)) {
        legend = chart.legend || ["Signal"];
        yArrays = [chart.y];
      } else {
        legend = chart.legend || Object.keys(chart.y);
        yArrays = legend.map(k => chart.y[k]);
      }
      colors = chart.colors || ["#1e88e5", "#e53935", "#43a047", "#8e24aa", "#00897b", "#5d4037"];

      // init visibility
      if (!chartSignalVisible.value[chartIdx]) {
        chartSignalVisible.value[chartIdx] = {};
        legend.forEach(k => { chartSignalVisible.value[chartIdx][k] = true; });
      }
      const visible = chartSignalVisible.value[chartIdx];

      // init cursor values storage
      if (!chartCursorValues.value[chartIdx]) {
        chartCursorValues.value[chartIdx] = {};
        legend.forEach(k => { chartCursorValues.value[chartIdx][k] = "--"; });
      }
      if (!chartCursorX.value[chartIdx]) chartCursorX.value[chartIdx] = "--";

      // container
      const chartWrap = document.createElement("div");
      chartWrap.className = "chart-wrap-minimal";
      el.appendChild(chartWrap);

      // main area
      const mainDiv = document.createElement("div");
      chartWrap.appendChild(mainDiv);

      // series (no fill palette; just lines)
      const series = [
        { label: chart.xlabel || "x" },
        ...legend.map((sig, i) => ({
          label: sig,
          stroke: colors[i % colors.length],
          width: 2,
          points: { show: false },
          show: visible[sig]
        }))
      ];
      let data = [chart.x || []];
      yArrays.forEach((arr, i) => {
        const sig = legend[i];
        data.push(visible[sig] ? arr : arr.map(() => null));
      });

      const mainOpts = {
        width: 980,
        height: 420,
        title: chart.name || "",
        series,
        axes: [
          {
            label: chart.xlabel || "Time (s)",
            values: (u, ticks) => ticks.map(t => formatTime(t, chart.xMode || "number")),
            grid: { show: true, stroke: "#eee", width: 1 },
            ticks: { show: true, stroke: "#ddd" },
            space: 50,
            labelSize: 12,
            valuesSize: 11
          },
          {
            label: chart.ylabel || "Value",
            grid: { show: true, stroke: "#eee", width: 1 },
            ticks: { show: true, stroke: "#ddd" },
            space: 60,                 // extra left gutter
            labelSize: 12,
            valuesSize: 11
          }
        ],
        legend: { show: false },
        cursor: {
          show: true,
          drag: { setScale: true, x: true, y: false }
        },
        scales: { x: { time: chart.xMode === "datetime" } }
      };

      const u = new uPlot(mainOpts, data, mainDiv);

      // Track initial window
      if (chartIdx !== undefined && (!chartViewWindow.value[chartIdx] || !chartViewWindow.value[chartIdx].min)) {
        chartViewWindow.value[chartIdx] = {
          min: data[0][0],
          max: data[0][data[0].length - 1]
        };
      }

      // Below-chart readout that doubles as a filter UI
      const readout = document.createElement("div");
      readout.className = "chart-readout";

      // X value line
      const xWrap = document.createElement("div");
      xWrap.className = "readout-x";
      const xLabel = document.createElement("span");
      xLabel.className = "label";
      xLabel.textContent = "x:";
      const xVal = document.createElement("span");
      xVal.className = "value";
      xVal.textContent = chartCursorX.value[chartIdx] || "--";
      xWrap.appendChild(xLabel);
      xWrap.appendChild(xVal);
      readout.appendChild(xWrap);

      // Signal items (click to toggle visibility)
      const items = [];
      legend.forEach((sig, i) => {
        const item = document.createElement("div");
        item.className = "readout-item" + (visible[sig] ? " active" : " inactive");
        item.title = "Click to toggle visibility";

        item.onclick = () => {
          chartSignalVisible.value[chartIdx][sig] = !chartSignalVisible.value[chartIdx][sig];
          nextTick(() => renderUPlot(chart, elId, chartIdx));
        };

        const lab = document.createElement("span");
        lab.className = "label";
        lab.textContent = sig;

        const val = document.createElement("span");
        val.className = "value";
        val.textContent = chartCursorValues.value[chartIdx][sig] ?? "--";

        item.appendChild(lab);
        item.appendChild(val);
        readout.appendChild(item);
        items.push({ val, item });
      });

      chartWrap.appendChild(readout);

      // Update cursor readouts
      mainDiv.onmousemove = (e) => {
        const bbox = u.over.getBoundingClientRect();
        const x = e.clientX - bbox.left;
        let idx = u.posToIdx(x);
        if (!Number.isFinite(idx) || idx < 0 || idx >= data[0].length) return;
        const xv = data[0][idx];
        chartCursorX.value[chartIdx] = formatTime(xv, chart.xMode || "number");
        xVal.textContent = chartCursorX.value[chartIdx];
        legend.forEach((sig, i) => {
          let v = data[i + 1][idx];
          const txt = (typeof v === "number") ? v.toLocaleString(undefined, { maximumFractionDigits: 3 }) : "--";
          chartCursorValues.value[chartIdx][sig] = txt;
          items[i].val.textContent = txt;
        });
      };
      mainDiv.onmouseleave = () => {
        xVal.textContent = "--";
        legend.forEach((sig, i) => {
          chartCursorValues.value[chartIdx][sig] = "--";
          items[i].val.textContent = "--";
        });
      };
    }

    // Replace your StepTree(...) function with this version (only change is we STOP adding "active" class)
function StepTree({ lines, indent = 0, parentIdx = "" }) {
  return lines.map((l, idx) => {
    const status = (l.status || "none").toLowerCase();
    const idxPath = parentIdx ? `${parentIdx}-${idx}` : `${idx}`;

    // DIAGNOSTIC GROUP
    if (
      l.category === "GROUP" &&
      typeof l.title === "string" &&
      /^\s*send\s+diagnostic\s+request\s+\S+/i.test(l.title) &&
      Array.isArray(l.children) &&
      l.children.length >= 1 &&
      l.children[0].category === "DIAGNOSTIC"
    ) {
      const d = l.children[0];
      const isOpen = openDiags.value.has(idxPath);
      return [
        h("div", { class: `teststep-row with-tree ${status} ${isOpen ? "expanded" : ""}`, style: { marginLeft: indent * 20 + "px" } }, [
          h("span", { class: "teststep-timestamp" }, l.timestamp || ""),
          h("div", { class: `tree-line ${status}` }),
          h("span", { class: "teststep-index" }, idx + 1),
          h("span", {
            class: "teststep-desc table-step-desc",  // removed "active" here
            role: "button",
            tabindex: 0,
            onClick: () => {
              openDiags.value.has(idxPath) ? openDiags.value.delete(idxPath) : openDiags.value.add(idxPath);
            }
          }, [
            h("span", { class: "table-arrow" }, isOpen ? "▼" : "▶"),
            h("span", l.title)
          ])
        ]),
        isOpen && h("div", {
          class: "custom-table-container-inline",
          style: { display: "block", marginLeft: (indent * 20 + 110) + "px" }
        }, [
          h("div", { class: "diagnostic-block-section" }, [
            h("div", { class: "diagnostic-label" }, "request"),
            h("div", { class: "diagnostic-kv-row" }, [
              h("span", { class: "diagnostic-kv-label" }, "raw bytes"),
              h("span", { class: "diagnostic-kv-value" }, (d.tx && d.tx.raw) || "")
            ]),
            d.tx?.parameters && h("div", { class: "diagnostic-kv-row" }, [
              h("span", { class: "diagnostic-kv-label" }, "parameters"),
              h("span", { class: "diagnostic-kv-value" }, d.tx.parameters)
            ])
          ]),
          h("div", { class: "diagnostic-block-section" }, [
            h("div", { class: "diagnostic-label" }, "response"),
            h("div", { class: "diagnostic-kv-row" }, [
              h("span", { class: "diagnostic-kv-label" }, "raw bytes"),
              h("span", { class: "diagnostic-kv-value" }, (d.rx && d.rx.raw) || "")
            ]),
            d.rx?.parameters && h("div", { class: "diagnostic-kv-row" }, [
              h("span", { class: "diagnostic-kv-label" }, "parameters"),
              h("span", { class: "diagnostic-kv-value" }, d.rx.parameters)
            ])
          ]),
          h("div", { class: "diagnostic-block-section" }, [
            h("div", { class: "diagnostic-label" }, "expected"),
            h("div", { class: "diagnostic-kv-row" }, [
              h("span", { class: "diagnostic-kv-label" }, "expected response"),
              h("span", { class: "diagnostic-kv-value" }, (d.expected && d.expected.response) || "")
            ])
          ])
        ])
      ];
    }

    // Generic group
    if (l.category === "GROUP") {
      const isOpen = openGroups.value.has(idxPath);
      return [
        h("div", { class: `teststep-row with-tree ${status} ${isOpen ? "expanded" : ""}`, style: { marginLeft: indent * 20 + "px" } }, [
          h("span", { class: "teststep-timestamp" }, l.timestamp || ""),
          h("div", { class: `tree-line ${status}` }),
          h("span", { class: "teststep-index" }),
          h("span", {
            class: "teststep-desc group-step-desc",  // removed "active"
            role: "button",
            tabindex: 0,
            onClick: () => {
              openGroups.value.has(idxPath) ? openGroups.value.delete(idxPath) : openGroups.value.add(idxPath);
            }
          }, [
            h("span", { class: "table-arrow" }, isOpen ? "▼" : "▶"),
            h("span", (l.title || "") + (l.comment ? " - " + l.comment : ""))
          ])
        ]),
        isOpen && h("div", { class: "group-children", style: { display: "block" } },
          StepTree({ lines: l.children, indent: indent + 1, parentIdx: idxPath }))
      ];
    }

    // TABLE
    if (l.category === "TABLE" && l.table_idx !== undefined && testcaseDetails.value && testcaseDetails.value.tables) {
      const table = testcaseDetails.value.tables[l.table_idx];
      const tableKey = idxPath;
      const isOpen = openTables.value.has(tableKey);
      return [
        h("div", { class: `teststep-row with-tree ${status} ${isOpen ? "expanded" : ""}`, style: { marginLeft: indent * 20 + "px" } }, [
          h("span", { class: "teststep-timestamp" }, l.timestamp || ""),
          h("div", { class: `tree-line ${status}` }),
          h("span", { class: "teststep-index" }, idx + 1),
          h("span", {
            class: "teststep-desc table-step-desc",  // removed "active"
            role: "button",
            tabindex: 0,
            onClick: () => {
              openTables.value.has(tableKey) ? openTables.value.delete(tableKey) : openTables.value.add(tableKey);
            }
          }, [
            h("span", { class: "table-arrow" }, isOpen ? "▼" : "▶"),
            h("span", "Table: " + (table.name || l.comment || "Table"))
          ])
        ]),
        isOpen && h("div", {
          class: "custom-table-container-inline",
          style: { display: "block", marginLeft: (indent * 20 + 110) + "px" },
          innerHTML: renderTable(table)
        })
      ];
    }

    // CHART
    if (l.category === "CHART" && l.chart_idx !== undefined && testcaseDetails.value && testcaseDetails.value.charts) {
      const chart = testcaseDetails.value.charts[l.chart_idx];
      const chartKey = `${l.chart_idx}|uplot-chart-${parentIdx}-${idx}-${l.chart_idx}`;
      const chartId = `uplot-chart-${parentIdx}-${idx}-${l.chart_idx}`;
      const isOpen = openCharts.value.has(chartKey);
      return [
        h("div", { class: `teststep-row with-tree ${status} ${isOpen ? "expanded" : ""}`, style: { marginLeft: indent * 20 + "px" } }, [
          h("span", { class: "teststep-timestamp" }, l.timestamp || ""),
          h("div", { class: `tree-line ${status}` }),
          h("span", { class: "teststep-index" }, idx + 1),
          h("span", {
            class: "teststep-desc chart-step-desc",  // removed "active"
            role: "button",
            tabindex: 0,
            onClick: () => {
              openCharts.value.has(chartKey) ? openCharts.value.delete(chartKey) : openCharts.value.add(chartKey);
            }
          }, [
            h("span", { class: "table-arrow" }, isOpen ? "▼" : "▶"),
            h("span", l.comment || "Chart")
          ])
        ]),
        isOpen && h("div", {
          class: "custom-chart-inner",
          style: { display: "block", marginLeft: (indent * 20 + 110) + "px" }
        }, [
          h("div", { id: chartId }),
          (() => { nextTick(() => renderUPlot(chart, chartId, l.chart_idx)); return null; })()
        ])
      ];
    }

    // STEP with text details
    const hasTextDetails = l.details_type === "text" && typeof l.details === "string" && l.details.length > 0;
    const textKey = idxPath;
    if (hasTextDetails) {
      const isOpen = openTexts.value.has(textKey);
      return [
        h("div", { class: `teststep-row with-tree ${status} ${isOpen ? "expanded" : ""}`, style: { marginLeft: indent * 20 + "px" } }, [
          h("span", { class: "teststep-timestamp" }, l.timestamp || ""),
          h("div", { class: `tree-line ${status}` }),
          h("span", { class: "teststep-index" }, idx + 1),
          h("span", {
            class: "teststep-desc text-step-desc",  // removed "active"
            role: "button",
            tabindex: 0,
            onClick: () => {
              openTexts.value.has(textKey) ? openTexts.value.delete(textKey) : openTexts.value.add(textKey);
            }
          }, [
            h("span", { class: "table-arrow" }, isOpen ? "▼" : "▶"),
            h("span", l.comment || "")
          ])
        ]),
        isOpen && h("div", {
          class: "text-details-container",
          style: { display: "block", marginLeft: (indent * 20 + 110) + "px" }
        }, [
          h("pre", { class: "text-details-pre" }, l.details)
        ])
      ];
    }

    // Plain step/comment
    return h("div", { class: `teststep-row with-tree ${status}`, style: { marginLeft: indent * 20 + "px" } }, [
      h("span", { class: "teststep-timestamp" }, l.timestamp || ""),
      h("div", { class: `tree-line ${status}` }),
      h("span", { class: "teststep-index" }, idx + 1),
      h("span", { class: "teststep-desc" }, l.comment || "")
    ]);
  }).flat();
}
    function renderEnvTable(env) {
      let tr = "";
      for (const [k, v] of Object.entries(env)) {
        if (k === "muted troubles") {
          if (typeof v === "object" && v !== null) {
            tr += `<tr>
              <td style="vertical-align: top;">${k}</td>
              <td>
                <table class="env-muted-inner-table">
                  <tr>
                    <td class="env-muted-label">DTC</td>
                    <td class="env-muted-dtc-list">
                      ${(v.DTC || []).map(dtc => `<div>0x${Number(dtc).toString(16).toUpperCase().padStart(6, "0")}</div>`).join("")}
                    </td>
                  </tr>
                  <tr>
                    <td class="env-muted-label">comment</td>
                    <td class="env-muted-comment env-muted-dtc-comment">${v.comment || ""}</td>
                  </tr>
                </table>
              </td>
            </tr>`;
          }
        } else {
          tr += `<tr><td>${k}</td><td>${v}</td></tr>`;
        }
      }
      return `<table>${tr}</table>`;
    }

    function renderDutTable(dut) {
      function renderObj(obj) {
        let tr = "";
        for (const [k, v] of Object.entries(obj || {})) {
          if (v && typeof v === "object" && !Array.isArray(v)) {
            tr += `<tr><td>${k}</td><td><table>${renderObj(v)}</table></td></tr>`;
          } else if (Array.isArray(v)) {
            tr += `<tr><td>${k}</td><td>[${v.map(item => typeof item === "object" && item !== null ? `<table>${renderObj(item)}</table>` : item).join(", ")}]</td></tr>`;
          } else {
            tr += `<tr><td>${k}</td><td>${v}</td></tr>`;
          }
        }
        return tr;
      }
      if (!dut || Object.keys(dut).length === 0) {
        return "<em>No DUT information.</em>";
      }
      return `<table>${renderObj(dut)}</table>`;
    }

    function renderStatsTable(stats) {
  if ('min' in stats && 'max' in stats && 'avg' in stats) {
    // chart stats mode
    return `<table>
      <tr><td>window</td><td>${stats.window ?? ''}</td></tr>
      <tr><td>min</td><td>${stats.min ?? ''}</td></tr>
      <tr><td>max</td><td>${stats.max ?? ''}</td></tr>
      <tr><td>avg</td><td>${stats.avg ? stats.avg.toFixed(2) : ''}</td></tr>
    </table>`;
  }

  const statKeys = ["all", "pass", "fail", "error", "none"];
  let tr = "";
  const total = stats.all || 0;

  for (const k of statKeys) {
    const val = (stats[k] !== undefined && stats[k] !== null) ? stats[k] : 0;
    const percent = total > 0 ? ((val / total) * 100).toFixed(1) + "%" : "";
    tr += `<tr><td>${k}</td><td>${val}${percent ? " (" + percent + ")" : ""}</td></tr>`;
  }

  // Keep overall + date/time/duration
  tr += `<tr><td>overall</td><td>${stats.overall || ""}</td></tr>`;
  tr += `<tr><td>date</td><td>${stats.date || ""}</td></tr>`;
  tr += `<tr><td>time</td><td>${stats.time || ""}</td></tr>`;
  tr += `<tr><td>duration</td><td>${stats.duration || ""}</td></tr>`;

  return `<table>${tr}</table>`;
}


    return {
      myreport, filter, currentTestName, loading, testcaseDetails, filteredTestNames, stats,
      showHome, selectTest, renderTable, StepTree, renderEnvTable, renderDutTable, renderStatsTable
    };
  },
  render() {
    const h = Vue.h;
    return h("div", [
      // Sidebar
      h("div", { class: "sidebar" }, [
        h("div", { class: "sidebar-header", onClick: this.showHome }, "HOME"),
        h("div", { class: "sidebar-filters" }, [
          ...["all", "pass", "fail", "error"].map(f =>
            h("button", { class: { "filter-btn": 1, active: this.filter === f }, onClick: () => { this.filter = f; } }, f)
          )
        ]),
        h("ul", { id: "testcase-list" },
          (this.filteredTestNames || []).map((name, idx) =>
            h("li", {
              key: name,
              class: [
                "testcase-item",
                "status-" + (this.myreport.reportData?.[name]?.status || 'none').toLowerCase(),
                { selected: this.currentTestName === name }
              ],
              onClick: () => this.selectTest(name)
            }, [
              h("span", { class: "case-index-badge" }, idx + 1 + ""),
              h("span", " " + name)
            ])
          )
        )
      ]),
      // Main Content
      h("div", { class: "main", id: "main-content" }, [
        !this.currentTestName ? [
          h("div", { class: "status-badge " + (this.stats.overall || 'none').toLowerCase() }, this.stats.overall),
          h("div", { class: "title compact" }, "Test Report"),
          h("div", { class: "project-name-row" }, [
            h("span", { class: "project-name-label" }, "Project Name:"),
            h("span", { class: "project-name-value" }, this.myreport.projectName)
          ]),
          h("div", { class: "summary-row" }, [
            h("div", { class: "summary-col" }, [
              h("div", { class: "summary-title" }, "TEST ENVIRONMENT"),
              h("div", { class: "summary-section", innerHTML: this.renderEnvTable(this.myreport.testEnvironment || {}) })
            ]),
            h("div", { class: "summary-col" }, [
              h("div", { class: "summary-title" }, "DEVICE UNDER TEST"),
              h("div", { class: "summary-section", innerHTML: this.renderDutTable(this.myreport.deviceUnderTest || {}) })
            ]),
            h("div", { class: "summary-col" }, [
              h("div", { class: "summary-title" }, "STATISTICS"),
              h("div", { class: "summary-section", innerHTML: this.renderStatsTable(this.stats) })
            ])
          ]),
          h("div", { class: "testcases-section" }, [
            h("div", { class: "testcases-title" }, "TEST CASES (" + (this.filteredTestNames?.length || 0) + ")"),
            h("table", { id: "testcases-table" }, [
              h("thead", [ h("tr", [h("th", "#"), h("th", "Name"), h("th", "Status")]) ]),
              h("tbody", (this.filteredTestNames || []).map((name, idx) =>
                h("tr", [ h("td", idx + 1 + ""), h("td", name), h("td", this.myreport.reportData?.[name]?.status) ])
              ))
            ])
          ])
        ] : [
          this.loading
            ? h("div", "Loading test case details...")
            : !this.testcaseDetails
              ? h("div", "Test case data could not be loaded.")
              : [
                h("div", { class: "title subtle" }, this.testcaseDetails.name),
                h("div", { class: "test-detail-meta-vertical" }, [
                  h("div", [h("b", "Goal:"), " ", h("span", this.testcaseDetails.goal)]),
                  h("div", [h("b", "Requirements:"), " ", h("span", (this.testcaseDetails.requirements || []).join(", "))]),
                  h("div", [h("b", "Status:"), " ", h("span", this.testcaseDetails.status)]),
                ]),
                h("div", { class: "teststeps-list" }, this.StepTree({ lines: this.testcaseDetails.lines || [], indent: 0 }))
              ]
        ]
      ])
    ]);
  }
}).mount('#app');

// Demo section unchanged
function renderTestCases(testCases) {
  testCases.sort((a, b) => a.index - b.index);
  const testCaseContainer = document.getElementById("test-case-container");
  if (!testCaseContainer) return;
  testCaseContainer.innerHTML = "";
  testCases.forEach((testCase) => {
    const el = document.createElement("div");
    el.className = "test-case";
    el.innerHTML = `
      <div class="test-case-index">#${testCase.index}</div>
      <div class="test-case-name">${testCase.name}</div>
      <div class="test-case-status ${testCase.status.toLowerCase()}">${testCase.status}</div>
    `;
    testCaseContainer.appendChild(el);
  });
}
fetch("/api/test-cases")
  .then((r) => r.json())
  .then(renderTestCases)
  .catch(() => {});