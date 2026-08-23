import pytest

from agent.api import product_release


def _row(index: int, *, status: str = "HIDDEN", visibility: str = "OWNER_RELEASE_REQUIRED", eligible: str = "ELIGIBLE"):
	return {
		"id": f"product-{index}",
		"product_short_name": f"Product {index}",
		"staff_release_status": status,
		"visibility_reason": visibility,
		"minimum_eligibility_status": eligible,
		"blocker_codes": [] if eligible == "ELIGIBLE" else ["VISUAL_CUTOUT_NOT_READY"],
		"operationally_visible": status == "RELEASED" and eligible == "ELIGIBLE",
	}


@pytest.mark.asyncio
async def test_release_control_paginates_after_global_filter_summary(monkeypatch):
	rows = [
		_row(1),
		_row(2, status="RELEASED", visibility="VISIBLE_TO_STAFF"),
		_row(3, status="RELEASED", visibility="RELEASED_BUT_BLOCKED", eligible="BLOCKED"),
		_row(4),
		_row(5, status="RELEASED", visibility="VISIBLE_TO_STAFF"),
	]

	async def release_rows():
		return rows

	monkeypatch.setattr(product_release, "_require_owner", lambda: None)
	monkeypatch.setattr(product_release, "_release_control_rows", release_rows)

	result = await product_release.list_product_release_control(
		q=None,
		release_status=None,
		visibility=None,
		eligibility=None,
		blocker=None,
		limit=2,
		offset=2,
	)

	assert result["total_count"] == 5
	assert result["returned_count"] == 2
	assert [item["id"] for item in result["items"]] == ["product-3", "product-4"]
	assert result["has_pagination"] is True
	assert result["summary"] == {
		"hidden": 2,
		"released": 3,
		"visible_to_staff": 2,
		"released_but_blocked": 1,
		"eligible_to_release": 4,
	}
