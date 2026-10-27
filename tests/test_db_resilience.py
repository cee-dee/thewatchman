import sqlite3
from unittest.mock import patch

from custom_components.watchman.const import COORD_DATA_MISSING_ENTITIES, DOMAIN
from custom_components.watchman.utils.parser_core import WatchmanParser
from homeassistant.exceptions import HomeAssistantError
import pytest
from tests import async_init_integration


@pytest.mark.asyncio
async def test_coordinator_resilience_read_timeout(hass):
    """Test coordinator keeps its last data when a DB read fails (locking)."""
    config_entry = await async_init_integration(hass)
    try:
        coordinator = hass.data[DOMAIN][config_entry.entry_id]
        missing_before = coordinator.data[COORD_DATA_MISSING_ENTITIES]
        assert missing_before > 0
        # Worst case: the refresh after a parse runs a full status check
        coordinator._force_full_rescan = True

        # Mock parser.get_found_items to raise OperationalError (database locked)
        with patch.object(WatchmanParser, 'get_found_items', side_effect=sqlite3.OperationalError("database is locked")):

            # Trigger refresh
            await coordinator.async_refresh()
            await hass.async_block_till_done()

            # Verify coordinator did NOT fail
            assert coordinator.last_update_success is True, "Coordinator should succeed even if DB read fails"

            # Verify sensors keep their last values instead of dropping to 0
            assert coordinator.data[COORD_DATA_MISSING_ENTITIES] == missing_before
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_report_fails_on_db_read_timeout(hass):
    """Test watchman.report fails instead of returning an empty report on a DB read error."""
    config_entry = await async_init_integration(hass)
    try:
        with (
            patch.object(WatchmanParser, 'get_found_items', side_effect=sqlite3.OperationalError("database is locked")),
            pytest.raises(HomeAssistantError, match="database is locked"),
        ):
            await hass.services.async_call(
                DOMAIN, "report", {"create_file": False}, blocking=True, return_response=True
            )
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

@pytest.mark.asyncio
async def test_coordinator_resilience_parse_timeout(hass, tmp_path):
    """Test coordinator handles DB write timeout during parsing gracefully."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    config_entry = await async_init_integration(hass, add_params={"included_folders": [str(config_dir)]})
    try:
        coordinator = hass.data[DOMAIN][config_entry.entry_id]

        # Mock _init_db to raise OperationalError
        # This allows scan() code to run and its try-except block to catch the error
        with patch.object(WatchmanParser, '_init_db', side_effect=sqlite3.OperationalError("database is locked")):

            # Request parsing
            await coordinator._async_update_data()
            # Should not raise exception (test passes if no unhandled exception)
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()

@pytest.mark.asyncio
async def test_coordinator_resilience_info_timeout(hass, tmp_path):
    """Test coordinator handles DB timeout when fetching last parse info."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    config_entry = await async_init_integration(hass, add_params={"included_folders": [str(config_dir)]})
    try:
        coordinator = hass.data[DOMAIN][config_entry.entry_id]

        # Mock get_last_parse_info to raise OperationalError
        with patch.object(
            WatchmanParser,
            "get_last_parse_info",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            info = await coordinator.hub.async_get_last_parse_info()

            # Verify default values returned
            assert info["duration"] == 0.0
            assert info["processed_files_count"] == 0
    finally:
        await hass.config_entries.async_unload(config_entry.entry_id)
        await hass.async_block_till_done()
