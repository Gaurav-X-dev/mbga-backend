import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

import { Card, PageHeader, StatCard } from "../../components/layout/Page";
import { formatCurrency } from "../../utils/format";

// Mock Data for UI
const REVENUE_DATA = [
  { name: "Jan", revenue: 400000, orders: 240 },
  { name: "Feb", revenue: 300000, orders: 139 },
  { name: "Mar", revenue: 200000, orders: 980 },
  { name: "Apr", revenue: 278000, orders: 390 },
  { name: "May", revenue: 189000, orders: 480 },
  { name: "Jun", revenue: 239000, orders: 380 },
  { name: "Jul", revenue: 349000, orders: 430 }
];

const ORDER_STATUS_DATA = [
  { name: "Delivered", value: 400, color: "#10b981" }, // green-500
  { name: "Pending", value: 300, color: "#f59e0b" }, // amber-500
  { name: "Cancelled", value: 50, color: "#ef4444" } // red-500
];

const TOP_MERCHANTS_DATA = [
  { name: "Sharma Agency", sales: 1240 },
  { name: "Gupta Gas Point", sales: 980 },
  { name: "Verma Enterprises", sales: 850 },
  { name: "MBGA Main Hub", sales: 720 },
  { name: "Rao Distributors", sales: 610 }
];

export function AdminReportsPage() {
  const totalRevenue = useMemo(() => REVENUE_DATA.reduce((acc, curr) => acc + curr.revenue, 0), []);
  const totalOrders = useMemo(() => REVENUE_DATA.reduce((acc, curr) => acc + curr.orders, 0), []);

  return (
    <div className="page dashboard-page">
      <PageHeader
        title="Business Reports"
        documentTitle="Reports"
        description="View analytics, revenue, and overall business performance across all merchants."
      />

      {/* KPI Cards */}
      <div className="kpi-grid">
        <StatCard
          label="Total Revenue (YTD)"
          value={formatCurrency(totalRevenue)}
          icon="trendingUp"
          tone="green"
          hint="+12.5% from last year"
        />
        <StatCard
          label="Total Orders (YTD)"
          value={totalOrders.toLocaleString()}
          icon="chart"
          tone="blue"
          hint="+8.2% from last year"
        />
        <StatCard
          label="Average Order Value"
          value={formatCurrency(totalOrders > 0 ? totalRevenue / totalOrders : 0)}
          icon="wallet"
          tone="violet"
          hint="Stable across all regions"
        />
      </div>

      <div className="chart-grid" style={{ marginTop: "24px" }}>
        {/* Revenue Trend Line Chart */}
        <Card title="Revenue Trend" className="col-8">
          <div style={{ height: "350px", width: "100%", marginTop: "16px" }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={REVENUE_DATA} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e5e7eb" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "#6b7280", fontSize: 12 }}
                  tickFormatter={(value) => `₹${value / 1000}k`}
                />
                <Tooltip
                  formatter={(value: number) => formatCurrency(value)}
                  contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                />
                <Legend iconType="circle" />
                <Line
                  type="monotone"
                  dataKey="revenue"
                  name="Revenue"
                  stroke="#3b82f6"
                  strokeWidth={3}
                  activeDot={{ r: 8 }}
                  dot={{ r: 4, strokeWidth: 2 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Order Status Pie Chart */}
        <Card title="Fulfillment Status" className="col-4">
          <div style={{ height: "350px", width: "100%", marginTop: "16px" }}>
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={ORDER_STATUS_DATA}
                  cx="50%"
                  cy="50%"
                  innerRadius={70}
                  outerRadius={100}
                  paddingAngle={5}
                  dataKey="value"
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  labelLine={false}
                >
                  {ORDER_STATUS_DATA.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ borderRadius: "8px", border: "none", boxShadow: "0 4px 6px -1px rgb(0 0 0 / 0.1)" }}
                />
                <Legend verticalAlign="bottom" height={36} iconType="circle" />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <div className="grid-3" style={{ marginTop: "24px" }}>
        {/* Top Merchants Bar Chart */}
        <Card title="Top Performing Merchants" className="col-span-3">
          <div style={{ height: "300px", width: "100%", marginTop: "16px" }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={TOP_MERCHANTS_DATA} margin={{ top: 5, right: 30, left: 20, bottom: 5 }} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e5e7eb" />
                <XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: "#6b7280", fontSize: 12 }} />
                <YAxis
                  dataKey="name"
                  type="category"
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: "#9ca3af", fontSize: 13, fontWeight: 500 }}
                  width={150}
                />
                <Tooltip
                  cursor={{ fill: "#1f2937" }}
                  contentStyle={{ borderRadius: "8px", border: "none", backgroundColor: "#111827" }}
                />
                <Bar dataKey="sales" name="Total Orders" fill="#6366f1" radius={[0, 4, 4, 0]} barSize={24} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>
    </div>
  );
}

export default AdminReportsPage;
