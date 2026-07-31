import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

// Dumb donut chart — pure view. Slices (label/value/color) are computed upstream; this
// only renders. One of only two files importing recharts (see BarPanel note).

export interface DonutSlice {
	label: string;
	value: number;
	color: string;
}

export interface DonutPanelProps {
	data: DonutSlice[];
	height?: number;
	centerValue?: string;
	centerLabel?: string;
}

export function DonutPanel({
	data,
	height = 220,
	centerValue,
	centerLabel,
}: DonutPanelProps) {
	return (
		<div className="relative">
			<ResponsiveContainer width="100%" height={height}>
				<PieChart>
					<Pie
						data={data}
						dataKey="value"
						nameKey="label"
						innerRadius="62%"
						outerRadius="90%"
						paddingAngle={2}
						stroke="none"
					>
						{data.map((slice) => (
							<Cell key={slice.label} fill={slice.color} />
						))}
					</Pie>
					<Tooltip
						contentStyle={{
							background: "#0f172a",
							border: "1px solid #1e293b",
							borderRadius: 8,
							fontSize: 12,
							color: "#e2e8f0",
						}}
					/>
				</PieChart>
			</ResponsiveContainer>
			{(centerValue != null || centerLabel != null) && (
				<div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
					{centerValue != null && (
						<span className="text-2xl font-semibold text-slate-100">
							{centerValue}
						</span>
					)}
					{centerLabel != null && (
						<span className="text-[10px] uppercase tracking-[0.16em] text-slate-500">
							{centerLabel}
						</span>
					)}
				</div>
			)}
		</div>
	);
}
