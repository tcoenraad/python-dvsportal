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

    async def _request(self, uri: str, method: str = "POST", json={}, headers={}):
        """Handle a request to DVSPortal."""
        url = URL.build(
            scheme="https", host=self.api_host, port=443, path=API_BASE_URI
        ).join(URL(uri))

        default_headers = {
            "User-Agent": self.user_agent,
        }

        try:
            with async_timeout.timeout(self.request_timeout):
                response = await self._session.request(
                    method, url, json=json, headers={**default_headers, **headers}, ssl=True
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

        if not content_type.startswith("application/json"):
            response_text = await response.text()
            raise DVSPortalError(
                response.status, {"message": response_text}
            )

        response_json = await response.json()
        if (response.status // 100) in [4, 5] or "ErrorMessage" in response_json:
            raise DVSPortalError(
                response.status, response_json
            )

        return response_json

    async def token(self) -> Optional[int]:
        """Return token."""
        if self._token is None:
            response = await self._request(
                "login",
                json={
                    "identifier": self._identifier,
                    "loginMethod": "Pas",
                    "password": self._password,
                    "permitMediaTypeID": 1}
            )
            self._token = response["Token"]
        return self._token

    async def authorization_header(self):
        await self.token()
        return {
            "Authorization": "Token " + str(base64.b64encode(self._token.encode("utf-8")), "utf-8")
        }

    async def update(self) -> None:
        """Fetch data from DVSPortal."""
        await self.token()

        authorization_header = await self.authorization_header()
        response = await self._request(
            "login/getbase",
            headers=authorization_header
        )

        permit_medias = [item for sublist in response["Permits"]
                         for item in sublist["PermitMedias"]]
        self._permits = [{
            "type_id": permit["TypeID"],
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

    async def end_reservation(self, type_id=None, code=None, reservation_id=None):
        """Ends reservation"""
        authorization_header = await self.authorization_header()

        return await self._request(
            "reservation/end",
            headers=authorization_header,
            json={
                "ReservationID": reservation_id,
                "permitMediaTypeID": type_id,
                "permitMediaCode": code
            }
        )

    async def create_reservation(self, license_plate_value=None, license_plate_name=None, type_id=None, code=None):
        authorization_header = await self.authorization_header()

        return await self._request(
            "reservation/create",
            headers=authorization_header,
            json={
                "DateFrom": datetime.now().isoformat(),
                "LicensePlate": {
                    "Value": license_plate_value,
                    "Name": license_plate_name
                },
                "permitMediaTypeID": type_id,
                "permitMediaCode": code
            }
        )

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
