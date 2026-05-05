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

import unittest
from unittest.mock import MagicMock, AsyncMock
import logging
from pyppetdb.crud.ca_certificates import CrudCACertificates


class TestCrudCACertificatesUnit(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_config = MagicMock()
        self.mock_coll = MagicMock()

        self.crud = CrudCACertificates(
            config=self.mock_config, log=self.log, coll=self.mock_coll
        )

    async def test_count(self):
        self.mock_coll.count_documents = AsyncMock(return_value=10)
        res = await self.crud.count({"status": "signed"})
        self.assertEqual(res, 10)
        self.mock_coll.count_documents.assert_called_once_with({"status": "signed"})
