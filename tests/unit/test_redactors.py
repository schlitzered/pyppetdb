import unittest
from unittest.mock import MagicMock
import logging
from pyppetdb.crud.nodes_secrets_redactor import NodesSecretsRedactor
from pyppetdb.crud.nodes_reports import NodesReportsRedactor
from pyppetdb.crud.nodes_catalogs import NodesCatalogsRedactor


class TestRedactorsUnit(unittest.TestCase):
    def setUp(self):
        self.log = logging.getLogger("test")
        self.mock_protector = MagicMock()
        self.base_redactor = NodesSecretsRedactor(self.log, self.mock_protector)
        self.base_redactor.add_secret("SECRET123")
        self.base_redactor.add_secret("PASSWORD")

    def test_base_redactor_string(self):
        self.assertEqual(
            self.base_redactor.redact("My password is PASSWORD"), "My password is XXXXX"
        )
        self.assertEqual(
            self.base_redactor.redact("SECRET123 is here"), "XXXXX is here"
        )
        self.assertEqual(self.base_redactor.redact("Normal string"), "Normal string")

    def test_base_redactor_nested(self):
        data = {
            "key1": "SECRET123",
            "key_PASSWORD": "normal",
            "list": ["PASSWORD", "other"],
        }
        expected = {"key1": "XXXXX", "key_XXXXX": "normal", "list": ["XXXXX", "other"]}
        self.assertEqual(self.base_redactor.redact(data), expected)

    def test_base_redactor_overlapping(self):
        self.base_redactor.rebuild(["SECRET", "SECRET123"])
        self.assertEqual(
            self.base_redactor.redact("This is SECRET123"), "This is XXXXX"
        )

    def test_base_redactor_rebuild(self):
        self.base_redactor.rebuild(["NEW_SECRET"])
        self.assertEqual(self.base_redactor.redact("NEW_SECRET"), "XXXXX")
        # Old secret should be gone
        self.assertEqual(self.base_redactor.redact("SECRET123"), "SECRET123")

    def test_base_redactor_other_types(self):
        self.assertEqual(self.base_redactor.redact(123), 123)
        self.assertEqual(self.base_redactor.redact(("SECRET123",)), ("XXXXX",))

    def test_reports_redactor(self):
        reports_redactor = NodesReportsRedactor(self.log, self.base_redactor)

        report_data = {
            "placement": "SECRET123",  # Should NOT be redacted
            "report": {
                "logs": [
                    {
                        "level": "info",
                        "message": "My PASSWORD is here",
                    },  # message SHOULD be redacted
                    {
                        "level": "PASSWORD",
                        "message": "Normal",
                    },  # level SHOULD NOT be redacted
                ],
                "resources": [
                    {
                        "resource_title": "SECRET123",  # SHOULD NOT be redacted
                        "events": [
                            {
                                "new_value": "new_SECRET123",  # SHOULD be redacted
                                "old_value": "old_SECRET123",  # SHOULD be redacted
                                "message": "Applied PASSWORD",  # SHOULD be redacted
                                "status": "PASSWORD",  # status SHOULD NOT be redacted
                            }
                        ],
                    }
                ],
            },
        }

        redacted = reports_redactor.redact(report_data)

        self.assertEqual(redacted["placement"], "SECRET123")
        self.assertEqual(redacted["report"]["logs"][0]["message"], "My XXXXX is here")
        self.assertEqual(redacted["report"]["logs"][1]["level"], "PASSWORD")
        self.assertEqual(
            redacted["report"]["resources"][0]["resource_title"], "SECRET123"
        )

        event = redacted["report"]["resources"][0]["events"][0]
        self.assertEqual(event["new_value"], "new_XXXXX")
        self.assertEqual(event["old_value"], "old_XXXXX")
        self.assertEqual(event["message"], "Applied XXXXX")
        self.assertEqual(event["status"], "PASSWORD")

    def test_catalogs_redactor(self):
        catalogs_redactor = NodesCatalogsRedactor(self.log, self.base_redactor)

        catalog_data = {
            "placement": "SECRET123",  # SHOULD NOT be redacted
            "catalog": {
                "resources": [
                    {
                        "title": "SECRET123",  # SHOULD NOT be redacted
                        "parameters": {
                            "content": "My PASSWORD",  # SHOULD be redacted
                            "owner": "PASSWORD",  # SHOULD be redacted (all values in parameters)
                        },
                    }
                ]
            },
        }

        redacted = catalogs_redactor.redact(catalog_data)

        self.assertEqual(redacted["placement"], "SECRET123")
        self.assertEqual(redacted["catalog"]["resources"][0]["title"], "SECRET123")
        params = redacted["catalog"]["resources"][0]["parameters"]
        self.assertEqual(params["content"], "My XXXXX")
        self.assertEqual(params["owner"], "XXXXX")
