"""An explicitly unverified call candidate during an active camera preview."""
from homeassistant.components.event import EventEntity
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from .const import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([ViewDoorCallCandidate(entry, hass.data[DOMAIN][entry.entry_id])])

class ViewDoorCallCandidate(EventEntity):
    _attr_has_entity_name = True
    _attr_name = 'Call candidate (experimental)'
    _attr_event_types = ['call_candidate']
    _attr_icon = 'mdi:doorbell-video'
    _attr_should_poll = False

    def __init__(self, entry, backend):
        self._backend = backend
        self._attr_unique_id = f'{backend.info.identifier}_call_candidate'
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, backend.info.identifier)})
        self._attr_extra_state_attributes = {
            'verified': False,
            'monitoring_scope': 'Active camera previews only; initial ring delivery unknown',
        }

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._backend.call_observer = self._received_from_thread

    def _received_from_thread(self, candidate):
        self.hass.add_job(self._received, candidate)

    @callback
    def _received(self, candidate):
        self._trigger_event('call_candidate', {'channel': candidate.channel, 'verified': False})
        self.async_write_ha_state()

    async def async_will_remove_from_hass(self):
        self._backend.call_observer = None
        await super().async_will_remove_from_hass()
