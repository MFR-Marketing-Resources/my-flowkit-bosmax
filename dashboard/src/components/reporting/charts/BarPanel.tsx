import {
	Bar,
	BarChart,
	CartesianGrid,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";

// Dumb horizontal bar chart — pure view. Takes already-aggregated data via props and
// renders. This is one of only two files that import recharts, so swapping the chart
// library later (ECharts / Nivo) touches only this file, never the API or the widgets.
// Cross-filter would be wired by adding an onClick here that calls the filter context;
// it is intentionally left out in Tier A (seam only).

export interface BarDatum {
	label: string;
	value: number;
}

export interface BarPanelProps {
	data: BarDatum[];
	color?: string;
	height?: number;
}

export function BarPanel({ data, color = "#38bdf8", height = 320 }: BarPanelProps) {
	return (
		<ResponsiveContainer width="100%" height={height}>
			<BarChart
				data={data}
				layout="vertical"
				margin={{ left: 8, right: 20, top: 4, bottom: 4 }}
			>
				<CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
				<XAxis type="number" stroke="#64748b" fontSize={11} allowDecimals={false} />
				<YAxis
					type="category"
					dataKey="label"
					stroke="#94a3b8"
					fontSize={11}
					width={150}
					tickLine={false}
				/>
				<Tooltip
					cursor={{ fill: "rgba(148,163,184,0.08)" }}
					contentStyle={{
						background: "#0f172a",
						border: "1px solid #1e293b",
						borderRadius: 8,
						fontSize: 12,
						color: "#e2e8f0",
					}}
				/>
				<Bar dataKey="value" fill={color} radius={[0, 4, 4, 0]} maxBarSize={22} />
			</BarChart>
		</ResponsiveContainer>
	);
}
