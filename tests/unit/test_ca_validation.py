# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
import os
import stat
import tempfile
import unittest
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx

from pyppetdb.ca import validation
from pyppetdb.ca.validation import CSRValidator
from pyppetdb.ca.validation import pem_file
from pyppetdb.ca.validation import script_environment
from pyppetdb.errors import QueryParamValidationError
from pyppetdb.model.ca_validation import CAHTTPValidation
from pyppetdb.model.ca_validation import CAScriptValidation


class TestScriptCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = MagicMock()
        self.validator = CSRValidator(log=self.log, crud_secrets=AsyncMock())
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _script(self, body):
        path = os.path.join(self.tmp.name, "check.sh")
        with open(path, "w") as handle:
            handle.write("#!/bin/sh\n" + body + "\n")
        os.chmod(path, stat.S_IRWXU)
        return CAScriptValidation(script_path=path, timeout_seconds=5)

    def test_environment_contains_only_path_cn_and_sans(self):
        env = script_environment("node1", ["a.example", "b.example"])

        self.assertEqual(
            env,
            {
                "PATH": validation.SCRIPT_PATH,
                "CN": "node1",
                "SAN1": "a.example",
                "SAN2": "b.example",
            },
        )

    async def test_script_does_not_see_process_secrets(self):
        config = self._script(
            '[ -z "$APP_SECRETKEY" ] && [ -z "$MONGODB_URL" ] '
            '&& [ "$CN" = node1 ] && [ "$SAN1" = a.example ]'
        )

        with patch.dict(
            os.environ, {"APP_SECRETKEY": "s3cret", "MONGODB_URL": "mongodb://u:p@h"}
        ):
            await self.validator.run_script_check("node1", ["a.example"], config)

    async def test_failure_output_is_logged_not_returned(self):
        config = self._script("echo internal-detail >&2; exit 3")

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.validator.run_script_check("node1", [], config)

        self.assertEqual(ctx.exception.detail, "External script validation failed")
        logged = str(self.log.error.call_args)
        self.assertIn("internal-detail", logged)
        self.assertIn("exit 3", logged)

    async def test_missing_script_gives_generic_error(self):
        config = CAScriptValidation(
            script_path=os.path.join(self.tmp.name, "missing"), timeout_seconds=1
        )

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.validator.run_script_check("node1", [], config)

        self.assertEqual(
            ctx.exception.detail, "External script validation could not be executed"
        )
        self.assertNotIn(self.tmp.name, ctx.exception.detail)

    async def test_timeout_kills_and_reaps_the_process(self):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        proc.wait = AsyncMock(return_value=-9)
        config = CAScriptValidation(script_path="/bin/true", timeout_seconds=1)

        with patch(
            "asyncio.create_subprocess_exec", AsyncMock(return_value=proc)
        ):
            with self.assertRaises(QueryParamValidationError) as ctx:
                await self.validator.run_script_check("node1", [], config)

        self.assertEqual(ctx.exception.detail, "External script validation timed out")
        proc.kill.assert_called_once()
        proc.wait.assert_awaited_once()


class TestHttpCheck(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = MagicMock()
        self.validator = CSRValidator(log=self.log, crud_secrets=AsyncMock())

    async def test_transport_error_details_are_not_returned(self):
        config = CAHTTPValidation(url="https://internal-validator.corp.example/check")

        with patch(
            "httpx.AsyncClient.request",
            AsyncMock(side_effect=httpx.ConnectError("connection refused")),
        ):
            with self.assertRaises(QueryParamValidationError) as ctx:
                await self.validator.run_http_check("node1", [], config, "ca", "space")

        self.assertEqual(
            ctx.exception.detail, "External HTTP validation could not be completed"
        )
        self.assertNotIn("internal-validator", ctx.exception.detail)
        self.assertIn("connection refused", str(self.log.error.call_args))

    async def test_invalid_tls_material_is_a_validation_error(self):
        config = CAHTTPValidation(url="https://v.example", ca_cert="not a pem")

        with self.assertRaises(QueryParamValidationError) as ctx:
            await self.validator.run_http_check("node1", [], config, "ca", "space")

        self.assertEqual(
            ctx.exception.detail, "Invalid HTTP validation configuration: TLS settings"
        )


class TestPemFile(unittest.TestCase):
    def test_memfd_content_is_readable_and_closed_afterwards(self):
        if getattr(os, "memfd_create", None) is None:
            self.skipTest("memfd_create not available")
        with pem_file("KEY DATA") as path:
            self.assertTrue(path.startswith("/proc/self/fd/"))
            with open(path) as handle:
                self.assertEqual(handle.read(), "KEY DATA")
        self.assertFalse(os.path.exists(path))

    def test_fallback_temp_file_is_removed(self):
        with patch.object(validation.os, "memfd_create", None, create=True):
            with pem_file("KEY DATA") as path:
                self.assertFalse(path.startswith("/proc/self/fd/"))
                with open(path) as handle:
                    self.assertEqual(handle.read(), "KEY DATA")
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
