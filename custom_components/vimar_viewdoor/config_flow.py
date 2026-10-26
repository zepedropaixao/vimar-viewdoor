"""Set up a local View Door monitor from the UI."""
import xml.etree.ElementTree as ET

try:
    import probatio as vol
except ImportError:
    import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD
from homeassistant.helpers import selector

from .backend import AuthenticationError, CertificateChangedError, ViewDoorBackend
from .const import CONF_CHANNEL, CONF_FINGERPRINT, CONF_STREAM, DOMAIN

class ViewDoorConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                backend = ViewDoorBackend(user_input[CONF_HOST], user_input[CONF_PASSWORD])
                info = await self.hass.async_add_executor_job(backend.initialize)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (OSError, ET.ParseError):
                errors["base"] = "cannot_connect"
            except ValueError:
                errors["base"] = "invalid_device"
            else:
                await self.async_set_unique_id(info.identifier)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={**user_input, CONF_FINGERPRINT: info.fingerprint,
                          CONF_CHANNEL: 1, CONF_STREAM: 2},
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default="Front Door"): str,
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
            }), errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                backend = ViewDoorBackend(entry.data[CONF_HOST], user_input[CONF_PASSWORD],
                                         fingerprint=entry.data[CONF_FINGERPRINT])
                info = await self.hass.async_add_executor_job(backend.initialize)
                if info.identifier != entry.unique_id:
                    return self.async_abort(reason="wrong_device")
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CertificateChangedError:
                errors["base"] = "certificate_changed"
            except (OSError, ValueError, ET.ParseError):
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({
            vol.Required(CONF_PASSWORD): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        }), errors=errors)
