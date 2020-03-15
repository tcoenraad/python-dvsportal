# -*- coding: utf-8 -*-
"""Asynchronous Python client for the DVSPortal API."""
import asyncio
import base64
import json
import re
import socket

from datetime import datetime, timedelta
from functools import reduce
from typing import Dict, Optional

import aiohttp
import async_timeout
from yarl import URL

from .__version__ import __version__
from .const import API_BASE_URI
from .exceptions import (
    DVSPortalAuthError,
    DVSPortalConnectionError,
    DVSPortalError,
)


class DVSPortal:
    """Main class for handling connections with DVSPortal."""

    def __init__(
        self,
        api_host: str,
        identifier: str,
        password: str,
        loop=None,
        request_timeout: int = 10,
        session=None,
        user_agent: str = None,
    ):
        """Initialize connection with DVSPortal."""
        self._loop = loop
        self._session = session
        self._close_session = False

        self.api_host = api_host
        self._identifier = identifier
        self._password = password

        self.request_timeout = request_timeout
        self.user_agent = user_agent

        self._token = None

        if self._loop is None:
            self._loop = asyncio.get_event_loop()

        if self._session is None:
            self._session = aiohttp.ClientSession(loop=self._loop)
            self._close_session = True

        if self.user_agent is None:
            self.user_agent = "PythonDVSPortal/{}".format(__version__)

    async def _request(self, uri: str, method: str = "POST", data={}, headers={}):
        """Handle a request to DVSPortal."""
        url = URL.build(
            scheme="https", host=self.api_host, port=443, path=API_BASE_URI
        ).join(URL(uri))

        default_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        try:
            with async_timeout.timeout(self.request_timeout):
                response = await self._session.request(
                    method, url, data=data, headers={**default_headers, **headers}, ssl=True
                )
        except asyncio.TimeoutError as exception:
            raise DVSPortalConnectionError(
                "Timeout occurred while connecting to DVSPortal API."
            ) from exception
        except (aiohttp.ClientError, socket.gaierror) as exception:
            raise DVSPortalConnectionError(
                "Error occurred while communicating with DVSPortal."
            ) from exception

        content_type = response.headers.get("Content-Type", "")
        if (response.status // 100) in [4, 5]:
            contents = await response.read()
            response.close()

            if content_type == "application/json":
                raise DVSPortalError(
                    response.status, json.loads(contents.decode("utf8"))
                )
            raise DVSPortalError(
                response.status, {"message": contents.decode("utf8")}
            )

        if "application/json" in response.headers["Content-Type"]:
            return await response.json()
        return await response.text()

    async def token(self) -> Optional[int]:
        """Return token."""
        if self._token is None:
            response = await self._request(
                "login",
                data={
                    "identifier": self._identifier,
                    "loginMethod": "Pas",
                    "password": self._password,
                    "permitMediaTypeID": 1}
            )
            if "ErrorMessage" in response:
                raise DVSPortalAuthError(response["ErrorMessage"])
            self._token = response["Token"]
        return self._token

    async def update(self) -> None:
        """Fetch data from DVSPortal."""
        await self.token()

        response = await self._request(
            "login/getbase",
            headers={
              "Authorization": "Token " + str(base64.b64encode(self._token.encode("utf-8")), "utf-8")
            }
        )

        permit_medias = [item for sublist in response["Permits"] for item in sublist["PermitMedias"]]
        self._permits = [{
            "code": permit["Code"],
            "zone_code": permit["ZoneCode"],
            "license_plates": {
                re.sub('[^a-zA-Z\d]', '', license_plate["Value"]): license_plate["Name"]
                for license_plate in permit["LicensePlates"]},
            "reservations":
                [{
                    "id": reservation["ReservationID"],
                    "valid_from": reservation["ValidFrom"],
                    "valid_until": reservation["ValidUntil"],
                    "license_plate": reservation["LicensePlate"]["Value"]
                } for reservation in permit["ActiveReservations"]]
        } for permit in permit_medias]

    async def permits(self):
        """Return active permits"""
        return self._permits

    async def close(self) -> None:
        """Close open client session."""
        if self._close_session:
            await self._session.close()

    async def __aenter__(self) -> "DVSPortal":
        """Async enter."""
        return self

    async def __aexit__(self, *exc_info) -> None:
        """Async exit."""
        await self.close()
