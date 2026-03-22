import { Search, Database, ShieldCheck, Clock3, Copy, ChevronRight } from "lucide-react";

export default function EnterpriseDataAgentUI() {
  const sampleRows = [
    { customer: "Acme Corp", margin: "$12,450", orders: 83, region: "NA" },
    { customer: "Northwind", margin: "$10,220", orders: 61, region: "EU" },
    { customer: "Globex", margin: "$8,940", orders: 49, region: "APAC" },
  ];

  const traceSteps = [
    {
      title: "Query understanding",
      detail: "Detected a ranking query over customers with a 28-day time window.",
      status: "Complete",
    },
    {
      title: "Tool selection",
      detail: "Matched to the approved top-customers manifest instead of freeform SQL generation.",
      status: "Complete",
    },
    {
      title: "Execution",
      detail: "Bound parameters, applied access rules, and executed the trusted template.",
      status: "Complete",
    },
    {
      title: "Response formatting",
      detail: "Preparing tabular results, trace metadata, and evidence for the user.",
      status: "Active",
    },
  ];

  const traceTone = (status: string) => {
    if (status === "Active") return "bg-stone-200 text-stone-800 border-stone-300";
    return "bg-stone-100 text-stone-700 border-stone-300";
  };

  return (
    <div className="min-h-screen bg-stone-100 text-stone-900">
      <div className="mx-auto max-w-7xl px-6 py-8 md:px-8 md:py-10">
        <header className="mb-8 rounded-[28px] border border-stone-300 bg-white p-6 shadow-sm md:p-8">
          <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center rounded-full border border-stone-300 bg-stone-100 px-3 py-1 text-xs font-medium text-stone-700">
                Enterprise Data Agent
              </div>
              <h1 className="mt-4 text-3xl font-semibold tracking-tight md:text-5xl">
                Query warehouse data with a governed workflow
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-stone-600 md:text-base">
                Ask a business question in plain English and inspect exactly how the system routed,
                executed, and validated the answer.
              </p>
            </div>

            <div className="grid min-w-full grid-cols-1 gap-3 sm:grid-cols-3 lg:min-w-[420px]">
              <div className="rounded-2xl border border-stone-300 bg-stone-50 p-4">
                <div className="flex items-center gap-2 text-sm text-stone-500">
                  <Database className="h-4 w-4" /> Routing
                </div>
                <div className="mt-2 text-lg font-semibold">Semantic-first</div>
              </div>
              <div className="rounded-2xl border border-stone-300 bg-stone-50 p-4">
                <div className="flex items-center gap-2 text-sm text-stone-500">
                  <Clock3 className="h-4 w-4" /> Elapsed
                </div>
                <div className="mt-2 text-lg font-semibold">520 ms</div>
              </div>
              <div className="rounded-2xl border border-stone-300 bg-stone-50 p-4">
                <div className="flex items-center gap-2 text-sm text-stone-500">
                  <ShieldCheck className="h-4 w-4" /> Trust mode
                </div>
                <div className="mt-2 text-lg font-semibold">Approved + fallback</div>
              </div>
            </div>
          </div>
        </header>

        <div className="grid gap-6 xl:grid-cols-[1.5fr_0.9fr]">
          <div className="space-y-6">
            <section className="rounded-[28px] border border-stone-300 bg-white p-5 shadow-sm md:p-6">
              <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Ask a question</h2>
                  <p className="mt-1 text-sm text-stone-600">
                    Example: Show top 10 customers by margin in the last 28 days.
                  </p>
                </div>
                <button className="rounded-xl border border-stone-300 bg-white px-4 py-2 text-sm font-medium text-stone-700 transition hover:bg-stone-50">
                  Load sample
                </button>
              </div>

              <div className="overflow-hidden rounded-3xl border border-stone-300 bg-stone-50">
                <div className="flex items-center gap-2 border-b border-stone-300 px-4 py-3 text-sm text-stone-500">
                  <Search className="h-4 w-4" /> Natural language query
                </div>
                <textarea
                  className="min-h-[180px] w-full resize-none bg-transparent px-4 py-4 text-[15px] leading-7 outline-none placeholder:text-stone-400"
                  defaultValue="Who are my top 3 customers by margin over the last 28 days?"
                />
                <div className="flex flex-col gap-3 border-t border-stone-300 px-4 py-4 md:flex-row md:items-center md:justify-between">
                  <div className="flex flex-wrap gap-2">
                    {[
                      "Intent: metric query",
                      "Entity: customer",
                      "Window: last_28d",
                    ].map((item) => (
                      <span
                        key={item}
                        className="rounded-full border border-stone-300 bg-white px-3 py-1 text-xs font-medium text-stone-600"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                  <button className="inline-flex items-center justify-center gap-2 rounded-xl bg-stone-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-black">
                    Run query <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </section>

            <section className="rounded-[28px] border border-stone-300 bg-white p-5 shadow-sm md:p-6">
              <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Results</h2>
                  <p className="mt-1 text-sm text-stone-600">
                    Rows returned from the approved execution path.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {[
                    "Status: ok",
                    "Rows: 25",
                    "Request: rq_1A82",
                  ].map((item) => (
                    <span
                      key={item}
                      className="rounded-full border border-stone-300 bg-stone-50 px-3 py-1 text-xs font-medium text-stone-600"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>

              <div className="overflow-hidden rounded-3xl border border-stone-300">
                <div className="overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="bg-stone-50 text-stone-500">
                      <tr>
                        <th className="px-4 py-3 font-medium">Customer</th>
                        <th className="px-4 py-3 font-medium">Margin</th>
                        <th className="px-4 py-3 font-medium">Orders</th>
                        <th className="px-4 py-3 font-medium">Region</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sampleRows.map((row, idx) => (
                        <tr
                          key={row.customer}
                          className={idx !== sampleRows.length - 1 ? "border-t border-stone-200" : ""}
                        >
                          <td className="px-4 py-3 font-medium text-stone-900">{row.customer}</td>
                          <td className="px-4 py-3 text-stone-700">{row.margin}</td>
                          <td className="px-4 py-3 text-stone-700">{row.orders}</td>
                          <td className="px-4 py-3 text-stone-700">{row.region}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </section>

            <section className="rounded-[28px] border border-stone-300 bg-white p-5 shadow-sm md:p-6">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-semibold">Generated SQL</h2>
                  <p className="mt-1 text-sm text-stone-600">
                    Rendered from the selected manifest using validated parameters.
                  </p>
                </div>
                <button className="inline-flex items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50">
                  <Copy className="h-4 w-4" /> Copy
                </button>
              </div>

              <pre className="overflow-x-auto rounded-3xl border border-stone-300 bg-stone-50 p-4 text-sm leading-7 text-stone-700">
{`SELECT
  c.customer_id,
  c.customer_name,
  SUM(f.order_amount - f.cogs) AS margin
FROM fct_orders f
JOIN dim_customer c
  ON f.customer_id = c.customer_id
WHERE f.order_status = 'completed'
  AND f.order_timestamp >= :period_start
  AND f.order_timestamp < :period_end
GROUP BY 1, 2
ORDER BY margin DESC
LIMIT :n;`}
              </pre>
            </section>
          </div>

          <div className="space-y-6">
            <section className="rounded-[28px] border border-stone-300 bg-white p-5 shadow-sm md:p-6">
              <h2 className="text-xl font-semibold">Execution trace</h2>
              <p className="mt-1 text-sm text-stone-600">
                A readable step-by-step audit trail for how the answer was produced.
              </p>

              <div className="mt-5 space-y-3">
                {traceSteps.map((step, index) => (
                  <div key={step.title} className="rounded-2xl border border-stone-300 p-4">
                    <div className="flex items-start gap-3">
                      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-stone-900 text-sm font-semibold text-white">
                        {index + 1}
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                          <h3 className="font-medium text-stone-900">{step.title}</h3>
                          <span className={`rounded-full border px-2.5 py-1 text-xs font-medium w-fit ${traceTone(step.status)}`}>
                            {step.status}
                          </span>
                        </div>
                        <p className="mt-2 text-sm leading-6 text-stone-600">{step.detail}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>

            <section className="rounded-[28px] border border-stone-300 bg-white p-5 shadow-sm md:p-6">
              <h2 className="text-xl font-semibold">Selected tool</h2>
              <p className="mt-1 text-sm text-stone-600">
                Structured tool invocation chosen for a deterministic answer path.
              </p>

              <div className="mt-4 rounded-3xl border border-stone-300 bg-stone-50 p-4">
                <div className="text-sm font-semibold text-stone-900">orders.top_customers@2.1.0</div>
                <div className="mt-4 space-y-2">
                  {[
                    ["period", "last_28d"],
                    ["n", "3"],
                    ["metric", "margin"],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="flex items-center justify-between rounded-2xl border border-stone-300 bg-white px-3 py-2 text-sm"
                    >
                      <span className="text-stone-500">{label}</span>
                      <span className="font-medium text-stone-900">{value}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="rounded-[28px] border border-stone-300 bg-white p-5 shadow-sm md:p-6">
              <h2 className="text-xl font-semibold">Evidence</h2>
              <p className="mt-1 text-sm text-stone-600">
                Context that helps users trust the result.
              </p>

              <div className="mt-4 space-y-3">
                <div className="rounded-2xl border border-stone-300 bg-stone-50 p-4">
                  <div className="text-sm font-medium text-stone-900">Semantic objects</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {["margin", "customer", "time"].map((item) => (
                      <span
                        key={item}
                        className="rounded-full border border-stone-300 bg-white px-3 py-1 text-xs font-medium text-stone-600"
                      >
                        {item}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-stone-300 bg-stone-50 p-4">
                  <div className="text-sm font-medium text-stone-900">SQL fingerprint</div>
                  <div className="mt-2 font-mono text-xs text-stone-600">
                    9af3c0d8-warehouse-approved-template
                  </div>
                </div>

                <div className="rounded-2xl border border-stone-300 bg-stone-50 p-4">
                  <div className="text-sm font-medium text-stone-900">Access scope</div>
                  <div className="mt-2 text-sm text-stone-600">Region whitelist applied: EU, NA</div>
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}