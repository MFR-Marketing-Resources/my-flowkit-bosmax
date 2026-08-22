import { getAPI, postAPI } from "./client";

export interface StaffProfile {
	staff_id: string;
	display_name: string;
	active: boolean;
	created_at: string;
	updated_at: string;
}

export interface StaffProfilesResponse {
	profiles: StaffProfile[];
}

export function fetchStaffProfiles(includeInactive = false): Promise<StaffProfilesResponse> {
	return getAPI<StaffProfilesResponse>(
		`/api/staff/profiles?include_inactive=${includeInactive ? "true" : "false"}`,
	);
}

export function createStaffProfile(display_name: string): Promise<StaffProfile> {
	return postAPI<StaffProfile>("/api/staff/profiles", { display_name });
}
