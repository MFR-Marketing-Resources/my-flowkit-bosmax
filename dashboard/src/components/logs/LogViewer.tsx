type LogViewerProps = {
	title?: string;
	message?: string;
};

export default function LogViewer({
	title = "Live Log Stream",
	message = "No dashboard log data source is wired in this checkout. This panel is read-only placeholder UI so existing dashboard routes can compile without introducing runtime execution hooks, persistence, or Flow controls.",
}: LogViewerProps) {
	return (
		<section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
			<div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500">
				{title}
			</div>
			<div className="mt-3 rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-4">
				<div className="text-sm font-medium text-slate-200">
					Read-only placeholder
				</div>
				<p className="mt-2 text-sm leading-6 text-slate-400">{message}</p>
				<ul className="mt-4 space-y-2 text-xs text-slate-500">
					<li>No Google Flow execution wiring.</li>
					<li>No Chrome extension execution wiring.</li>
					<li>No batch execution, queue jobs, or persistence.</li>
				</ul>
			</div>
		</section>
	);
}
