"""Home Assistant camera for the local Vimar View Door bridge."""
import asyncio

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import async_get_image
from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ViewDoorCamera(entry, hass.data[DOMAIN][entry.entry_id])])

class ViewDoorCamera(Camera):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, entry, backend):
        super().__init__()
        self._backend = backend
        self._lock = asyncio.Lock()
        self._attr_unique_id = f"{backend.info.identifier}_camera"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, backend.info.identifier)},
            name=entry.data[CONF_NAME], manufacturer="Vimar / Qualvision",
            model=backend.info.model, sw_version=backend.info.firmware,
        )
        self.stream_options = {"rtsp_transport": "tcp"}

    @property
    def use_stream_for_stills(self):
        return True

    async def stream_source(self):
        async with self._lock:
            return await self.hass.async_add_executor_job(self._backend.stream_url)

    async def async_camera_image(self, width=None, height=None):
        source = await self.stream_source()
        return await async_get_image(self.hass, f"-rtsp_transport tcp -i {source}", width=width, height=height)
