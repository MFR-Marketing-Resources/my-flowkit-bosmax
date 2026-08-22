import { useCallback, useEffect, useMemo, useState } from "react";
import {
	createStaffProfile,
	fetchStaffProfiles,
	type StaffProfile,
} from "../api/staffIdentity";

const STAFF_STORAGE_KEY = "bosmax.staff_identity.v1";

function storedStaffId(): string {
	try {
		return window.localStorage.getItem(STAFF_STORAGE_KEY)?.trim() ?? "";
	} catch {
		return "";
	}
}

function persistStaffId(staffId: string): void {
	try {
		if (staffId) window.localStorage.setItem(STAFF_STORAGE_KEY, staffId);
		else window.localStorage.removeItem(STAFF_STORAGE_KEY);
	} catch {
		// Selection convenience must never become a generation authority.
	}
}

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
	const [selectedId, setSelectedId] = useState(storedStaffId);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	const refresh = useCallback(async () => {
		setLoading(true);
		try {
			const response = await fetchStaffProfiles(false);
			const activeProfiles = response.profiles.filter((profile) => profile.active);
			setProfiles(activeProfiles);
			setSelectedId((current) => {
				const remembered = current || storedStaffId();
				if (!activeProfiles.some((profile) => profile.staff_id === remembered)) {
					persistStaffId("");
					return "";
				}
				return remembered;
			});
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

	const selectStaff = useCallback((staffId: string) => {
		const normalized = staffId.trim();
		setSelectedId(normalized);
		persistStaffId(normalized);
	}, []);

	const createProfile = useCallback(
		async (displayName: string) => {
			const profile = await createStaffProfile(displayName.trim());
			setProfiles((current) =>
				[...current.filter((item) => item.staff_id !== profile.staff_id), profile].sort(
					(a, b) => a.display_name.localeCompare(b.display_name),
				),
			);
			selectStaff(profile.staff_id);
			return profile;
		},
		[selectStaff],
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
