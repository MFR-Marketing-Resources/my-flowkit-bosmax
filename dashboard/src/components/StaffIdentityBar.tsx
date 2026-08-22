import type { StaffIdentityState } from "../hooks/useStaffIdentity";

interface StaffIdentityBarProps {
	identity: StaffIdentityState;
	surface: string;
}

export default function StaffIdentityBar({ identity, surface }: StaffIdentityBarProps) {
	return (
		<section
			className="mb-4 rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-3"
			data-testid="staff-identity-bar"
		>
			<div className="flex flex-wrap items-center gap-3">
				<div className="min-w-[180px] flex-1">
					<p className="text-[10px] font-bold uppercase tracking-[0.16em] text-cyan-300">
						Staff identity · {surface}
					</p>
					<p className="mt-1 text-xs text-slate-400">
						The server validates the active profile for every production write.
					</p>
				</div>
				<div className="min-w-[220px] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2">
					<p className="text-[10px] uppercase tracking-wider text-slate-500">Authenticated staff</p>
					<p className="mt-1 text-sm font-semibold text-slate-100">
						{identity.selectedStaff?.display_name ?? "No authenticated staff"}
					</p>
				</div>
				<div className="min-w-[220px] flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-400">
					<p>Staff ID</p>
					<p className="mt-1 font-mono text-[11px] text-cyan-200">{identity.staffId || "—"}</p>
				</div>
			</div>
			{identity.loading ? <p className="mt-2 text-xs text-slate-500">Loading active staff…</p> : null}
			{identity.error ? <p className="mt-2 text-xs text-rose-300">{identity.error}</p> : null}
			{!identity.loading && !identity.hasStaff ? (
				<p className="mt-2 text-xs font-semibold text-amber-300">
					No active authenticated staff session. Production actions remain blocked until a real staff account is signed in.
				</p>
			) : null}
		</section>
	);
}
