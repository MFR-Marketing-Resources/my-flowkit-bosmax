import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchCurrentSession } from "../api/auth";
import type { StaffProfile } from "../api/staffIdentity";

export interface StaffIdentityState {
	profiles: StaffProfile[];
	selectedStaff: StaffProfile | null;
	staffId: string;
	loading: boolean;
	error: string;
	hasStaff: boolean;
	selectStaff: (staffId: string) => void;
	createProfile: (displayName: string) => Promise<StaffProfile>;
	refresh: () => Promise<void>;
}

export function useStaffIdentity(): StaffIdentityState {
	const [profiles, setProfiles] = useState<StaffProfile[]>([]);
	const [selectedId, setSelectedId] = useState("");
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			const response = await fetchCurrentSession();
			const user = response.authenticated ? response.user : null;
			const sessionProfile = user
				? [{
					staff_id: user.staff_id,
					display_name: user.display_name,
					active: user.staff_active,
					created_at: "",
					updated_at: "",
				}]
				: [];
			setProfiles(sessionProfile);
			setSelectedId(user?.staff_id ?? "");
			setError("");
		} catch (cause) {
			setError(cause instanceof Error ? cause.message : "Staff profiles unavailable.");
		} finally {
			setLoading(false);
		}
	}, []);

	useEffect(() => {
		void refresh();
	}, [refresh]);

	const selectStaff = useCallback((_staffId: string) => {
		// Deliberately no-op: authenticated session StaffProfile is the only
		// production attribution authority. UI callers cannot switch identity.
	}, []);

	const createProfile = useCallback(
		async (_displayName: string) => {
			throw new Error("Staff profiles are managed from System → Staff & Access.");
		},
		[],
	);

	const selectedStaff = useMemo(
		() => profiles.find((profile) => profile.staff_id === selectedId) ?? null,
		[profiles, selectedId],
	);

	return {
		profiles,
		selectedStaff,
		staffId: selectedStaff?.staff_id ?? "",
		loading,
		error,
		hasStaff: Boolean(selectedStaff?.staff_id),
		selectStaff,
		createProfile,
		refresh,
	};
}
