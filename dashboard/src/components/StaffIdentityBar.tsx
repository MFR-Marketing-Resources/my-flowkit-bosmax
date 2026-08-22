import { useState } from "react";
import type { StaffIdentityState } from "../hooks/useStaffIdentity";

interface StaffIdentityBarProps {
	identity: StaffIdentityState;
	surface: string;
}

export default function StaffIdentityBar({ identity, surface }: StaffIdentityBarProps) {
	const [newName, setNewName] = useState("");
	const [creating, setCreating] = useState(false);
	const [createError, setCreateError] = useState("");

	const createProfile = async () => {
		const name = newName.trim();
		if (!name) return;
		setCreating(true);
		setCreateError("");
		try {
			await identity.createProfile(name);
			setNewName("");
		} catch (cause) {
			setCreateError(cause instanceof Error ? cause.message : "Could not create staff profile.");
		} finally {
			setCreating(false);
		}
	};

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
				<label className="flex min-w-[220px] flex-1 items-center gap-2 text-xs text-slate-300">
					<span className="sr-only">Active staff profile</span>
					<select
						value={identity.staffId}
						onChange={(event) => identity.selectStaff(event.target.value)}
						disabled={identity.loading}
						className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 disabled:opacity-60"
						data-testid="staff-identity-select"
					>
						<option value="">Select active staff…</option>
						{identity.profiles.map((profile) => (
							<option key={profile.staff_id} value={profile.staff_id}>
								{profile.display_name}
							</option>
						))}
					</select>
				</label>
				<div className="flex min-w-[250px] flex-1 items-center gap-2">
					<input
						value={newName}
						onChange={(event) => setNewName(event.target.value)}
						onKeyDown={(event) => {
							if (event.key === "Enter") void createProfile();
						}}
						placeholder="Register a staff name"
						className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
						aria-label="Register a staff name"
					/>
					<button
						type="button"
						onClick={() => void createProfile()}
						disabled={creating || !newName.trim()}
						className="rounded-lg border border-cyan-400/50 px-3 py-2 text-xs font-semibold text-cyan-200 disabled:cursor-not-allowed disabled:opacity-40"
					>
						{creating ? "Registering…" : "Register"}
					</button>
				</div>
			</div>
			{identity.loading ? <p className="mt-2 text-xs text-slate-500">Loading active staff…</p> : null}
			{identity.error ? <p className="mt-2 text-xs text-rose-300">{identity.error}</p> : null}
			{createError ? <p className="mt-2 text-xs text-rose-300">{createError}</p> : null}
			{!identity.loading && !identity.hasStaff ? (
				<p className="mt-2 text-xs font-semibold text-amber-300">
					No active staff selected. Production actions remain blocked until a real profile is selected.
				</p>
			) : null}
		</section>
	);
}
