"""Config flow for DESS Monitor Local."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import detector
from .const import (
    CONF_FRAMING,
    CONF_HOST,
    CONF_PORT,
    CONF_PROTOCOL,
    CONF_TIMEOUT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_FRAMING,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PROTOCOL,
    DEFAULT_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FRAMING_AUTO,
    MAX_TIMEOUT,
    MAX_UPDATE_INTERVAL,
    MIN_TIMEOUT,
    MIN_UPDATE_INTERVAL,
    PROTOCOL_AUTO,
    PROTOCOL_OPTIONS,
)
from .transport import TransportError

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=0, max=65535)
            ),
            vol.Required(
                CONF_PROTOCOL, default=defaults.get(CONF_PROTOCOL, DEFAULT_PROTOCOL)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(PROTOCOL_OPTIONS),
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="protocol",
                )
            ),
            vol.Required(
                CONF_FRAMING, default=defaults.get(CONF_FRAMING, DEFAULT_FRAMING)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[FRAMING_AUTO, "ascii", "rtu", "modbus_tcp"],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                    translation_key="framing",
                )
            ),
            vol.Required(
                CONF_UPDATE_INTERVAL,
                default=defaults.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)),
            vol.Required(
                CONF_TIMEOUT, default=defaults.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
            ): vol.All(vol.Coerce(float), vol.Range(min=MIN_TIMEOUT, max=MAX_TIMEOUT)),
            vol.Optional("name", default=defaults.get("name", "DESS Inverter")): str,
        }
    )


class DessLocalConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the DESS Monitor Local config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        defaults: dict[str, Any] = dict(user_input or {})

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            port = int(user_input[CONF_PORT])
            protocol = user_input[CONF_PROTOCOL]
            timeout = float(user_input[CONF_TIMEOUT])

            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                await self.async_set_unique_id(host.lower())
                self._abort_if_unique_id_configured()

                framed_ok = (
                    protocol != PROTOCOL_AUTO
                    and port
                    and user_input.get(CONF_FRAMING, FRAMING_AUTO) != FRAMING_AUTO
                )
                try:
                    if framed_ok:
                        result = await detector.probe(
                            host, port, protocol,
                            user_input[CONF_FRAMING], timeout=timeout,
                        )
                        if result is None:
                            raise TimeoutError("device did not answer")
                    else:
                        result = await detector.detect_device(
                            host, port, timeout=timeout
                        )
                except (TimeoutError, OSError, TransportError, ValueError) as err:
                    _LOGGER.debug("DESS local detection failed: %s", err)
                    errors["base"] = "cannot_connect"
                else:
                    data = {
                        CONF_HOST: host,
                        CONF_PORT: result.port,
                        CONF_PROTOCOL: result.protocol,
                        CONF_FRAMING: result.framing,
                        CONF_TIMEOUT: timeout,
                        "name": user_input.get("name") or f"DESS {host}",
                    }
                    options = {
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL])
                    }
                    return self.async_create_entry(
                        title=data["name"], data=data, options=options
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(defaults),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: Any) -> OptionsFlow:
        return DessLocalOptionsFlow()


class DessLocalOptionsFlow(OptionsFlow):
    """Poll-interval options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    )
                }
            ),
            errors=errors,
        )
