"""Vimar View Door local camera integration."""
from datetime import timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .backend import AuthenticationError, CertificateChangedError, ViewDoorBackend
from .const import CONF_CHANNEL, CONF_FINGERPRINT, CONF_STREAM, DOMAIN

PLATFORMS = [Platform.CAMERA, Platform.EVENT]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    backend = ViewDoorBackend(
        entry.data[CONF_HOST], entry.data[CONF_PASSWORD],
        fingerprint=entry.data[CONF_FINGERPRINT],
        channel=entry.data.get(CONF_CHANNEL, 1), stream=entry.data.get(CONF_STREAM, 2),
        data_dir=Path(hass.config.path(".storage", DOMAIN, entry.entry_id)),
    )
    try:
        await hass.async_add_executor_job(backend.initialize)
    except AuthenticationError as err:
        raise ConfigEntryAuthFailed("View Door rejected the device password") from err
    except CertificateChangedError as err:
        raise ConfigEntryAuthFailed("The monitor certificate changed; reconfigure the integration") from err
    except (OSError, ValueError, ET.ParseError) as err:
        raise ConfigEntryNotReady("Unable to read the View Door monitor") from err
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = backend

    async def check_idle(_now):
        await hass.async_add_executor_job(backend.close_if_idle)

    async def shutdown(_event):
        await hass.async_add_executor_job(backend.close)

    entry.async_on_unload(async_track_time_interval(hass, check_idle, timedelta(seconds=30)))
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown))
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await hass.async_add_executor_job(backend.close)
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    backend = hass.data[DOMAIN].pop(entry.entry_id)
    await hass.async_add_executor_job(backend.close)
    return True
