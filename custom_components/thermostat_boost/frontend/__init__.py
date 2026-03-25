"""Thermostat Boost frontend resource registration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace import MODE_STORAGE, LovelaceData
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from ..const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

URL_BASE = f"/{DOMAIN}"
JS_MODULES = [
    {
        "name": "Thermostat Boost Card",
        "filename": "thermostat-boost-card.js",
        "version": VERSION,
    },
]


class JSModuleRegistration:
    """Register Thermostat Boost Lovelace resources."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.lovelace: LovelaceData | None = self.hass.data.get("lovelace")
        self.resource_mode = getattr(
            self.lovelace, "resource_mode", getattr(self.lovelace, "mode", None)
        )

    async def async_register(self) -> None:
        """Register the static path and, for storage mode, the Lovelace resource."""
        await self._async_register_path()
        if self.lovelace and self.resource_mode == MODE_STORAGE:
            await self._async_wait_for_lovelace_resources()

    async def _async_register_path(self) -> None:
        """Expose the bundled frontend files via Home Assistant's HTTP server."""
        try:
            await self.hass.http.async_register_static_paths(
                [StaticPathConfig(URL_BASE, Path(__file__).parent, False)]
            )
            _LOGGER.debug(
                "Registered Thermostat Boost frontend path from %s",
                Path(__file__).parent,
            )
        except RuntimeError:
            _LOGGER.debug("Thermostat Boost frontend path already registered")

    async def _async_wait_for_lovelace_resources(self) -> None:
        """Wait until Lovelace resources are available before mutating them."""

        async def _check_lovelace_resources_loaded(_now):
            if self.lovelace and self.lovelace.resources.loaded:
                await self._async_register_modules()
            else:
                _LOGGER.debug(
                    "Thermostat Boost Lovelace resources not ready yet; retrying in 5 seconds"
                )
                async_call_later(self.hass, 5, _check_lovelace_resources_loaded)

        await _check_lovelace_resources_loaded(0)

    async def _async_register_modules(self) -> None:
        """Create or update the Lovelace resource entry for the bundled card."""
        if not self.lovelace or not self.lovelace.resources.loaded:
            return

        _LOGGER.debug("Installing Thermostat Boost frontend module")
        resources = list(self.lovelace.resources.async_items())

        for module in JS_MODULES:
            desired_url = f"{URL_BASE}/{module['filename']}"
            desired_version = module["version"]
            card_registered = False

            for resource in resources:
                resource_url = str(resource["url"])
                if not self._resource_matches(resource_url, module["filename"]):
                    continue

                card_registered = True
                if (
                    self._get_resource_path(resource_url) != desired_url
                    or self._get_resource_version(resource_url) != desired_version
                ):
                    _LOGGER.debug(
                        "Updating %s to version %s", module["name"], desired_version
                    )
                    await self.lovelace.resources.async_update_item(
                        resource.get("id"),
                        {
                            "res_type": "module",
                            "url": f"{desired_url}?v={desired_version}",
                        },
                    )
                else:
                    _LOGGER.debug(
                        "%s already registered as version %s",
                        module["name"],
                        desired_version,
                    )
                break

            if not card_registered:
                _LOGGER.debug(
                    "Registering %s as version %s", module["name"], desired_version
                )
                await self.lovelace.resources.async_create_item(
                    {
                        "res_type": "module",
                        "url": f"{desired_url}?v={desired_version}",
                    }
                )

    async def async_unregister(self) -> None:
        """Remove the Lovelace resource entry when the integration unloads."""
        if self.resource_mode != MODE_STORAGE or not self.lovelace:
            return

        for module in JS_MODULES:
            resources = [
                resource
                for resource in self.lovelace.resources.async_items()
                if self._resource_matches(str(resource["url"]), module["filename"])
            ]
            for resource in resources:
                await self.lovelace.resources.async_delete_item(resource.get("id"))

    def _get_resource_path(self, url: str) -> str:
        return url.split("?", 1)[0]

    def _resource_matches(self, url: str, filename: str) -> bool:
        return self._get_resource_path(url).endswith(f"/{filename}")

    def _get_resource_version(self, url: str) -> str:
        parts = url.split("?", 1)
        if len(parts) != 2:
            return "0"
        query = parts[1]
        if query.startswith("v="):
            return query.removeprefix("v=")
        return "0"
