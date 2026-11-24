import unittest
import os
import tempfile
from unittest.mock import Mock, patch

from adapters.zoho_recruit_metadata_exporter import ZohoRecruitMetadataExporter
from scripts import setup_zoho_recruit_oauth
from adapters.metadata_file_adapter import MetadataFileAdapter


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self._body


class ZohoRecruitMetadataTests(unittest.TestCase):
    def test_fields_only_exports_real_fields_without_requesting_module_metadata(self):
        session = Mock()
        session.get.return_value = FakeResponse({
            "fields": [{"api_name": "First_Name", "data_type": "text"}],
        })
        exporter = ZohoRecruitMetadataExporter(
            modules=["Candidates"],
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=session,
            fields_only=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "metadata.json")
            with patch.object(exporter.oauth, "get_access_token", return_value="access-token"):
                exporter.export(output)
            adapter = MetadataFileAdapter(output)
            catalog = adapter.get_catalog()
            self.assertEqual(catalog["metadata_scope"], "fields-only")
            self.assertTrue(catalog["limitations"])
            self.assertIsNone(catalog["modules"][0]["metadata"])
            self.assertEqual(
                adapter.as_schema(),
                {"Candidates": [{"name": "First_Name", "type": "text"}]},
            )
        session.get.assert_called_once()
        self.assertTrue(session.get.call_args.args[0].endswith("/settings/fields"))

    def test_fields_only_does_not_hide_field_scope_errors(self):
        session = Mock()
        session.get.return_value = FakeResponse(
            {"code": "OAUTH_SCOPE_MISMATCH", "message": "invalid oauth scope"},
            status_code=401,
        )
        exporter = ZohoRecruitMetadataExporter(
            modules=["Candidates"],
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=session,
            fields_only=True,
        )
        with patch.object(exporter.oauth, "get_access_token", return_value="access-token"):
            with self.assertRaisesRegex(RuntimeError, "invalid oauth scope"):
                exporter.collect()

    def test_collect_fetches_module_and_field_metadata_and_builds_schema(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse({
                "modules": [{
                    "api_name": "Candidates",
                    "module_name": "Candidates",
                    "singular_label": "Candidate",
                }]
            }),
            FakeResponse({
                "fields": [{
                    "api_name": "First_Name",
                    "data_type": "text",
                    "field_label": "First Name",
                }]
            }),
        ]
        exporter = ZohoRecruitMetadataExporter(
            modules=["Candidates"],
            client_id="client-id",
            client_secret="client-secret",
            refresh_token="refresh-token",
            session=session,
        )

        with patch.object(exporter.oauth, "get_access_token", return_value="access-token"):
            catalog = exporter.collect()

        self.assertEqual(
            catalog["entities"],
            [{
                "name": "Candidates",
                "module": "Zoho Recruit",
                "description": "Candidate",
                "fields": [{
                    "name": "First_Name",
                    "data_type": "text",
                    "description": "First Name",
                }],
                "relationships": [],
            }],
        )
        self.assertEqual(
            session.get.call_args_list[0].args[0],
            "https://recruit.zoho.eu/recruit/v2/settings/modules/Candidates",
        )
        self.assertEqual(
            session.get.call_args_list[1].args[0],
            "https://recruit.zoho.eu/recruit/v2/settings/fields",
        )
        self.assertEqual(
            session.get.call_args_list[1].kwargs["params"],
            {"module": "Candidates"},
        )
        self.assertEqual(
            session.get.call_args_list[0].kwargs["headers"]["Authorization"],
            "Zoho-oauthtoken access-token",
        )

    def test_missing_modules_is_reported_instead_of_exporting_empty_schema(self):
        with self.assertRaisesRegex(ValueError, "module API names"):
            ZohoRecruitMetadataExporter(
                modules=[],
                client_id="client-id",
                client_secret="client-secret",
                refresh_token="refresh-token",
            )

    def test_oauth_setup_explains_invalid_code_and_sends_registered_redirect_uri(self):
        response = FakeResponse({"error": "invalid_code"}, status_code=400)
        with tempfile.TemporaryDirectory() as directory:
            env_path = os.path.join(directory, ".env")
            with patch.dict(os.environ, {
                "ZOHO_RECRUIT_CLIENT_ID": "client-id",
                "ZOHO_RECRUIT_CLIENT_SECRET": "client-secret",
                "ZOHO_RECRUIT_ACCOUNTS_URL": "https://accounts.zoho.eu",
                "ZOHO_RECRUIT_REDIRECT_URI": "https://example.com/callback",
            }), patch("sys.argv", [
                "setup_zoho_recruit_oauth.py",
                "--env-file",
                env_path,
            ]), patch.object(
                setup_zoho_recruit_oauth.getpass,
                "getpass",
                return_value="one-time-code",
            ), patch.object(
                setup_zoho_recruit_oauth.requests,
                "post",
                return_value=response,
            ) as post:
                with self.assertRaisesRegex(
                    SystemExit,
                    "single-use and short-lived",
                ):
                    setup_zoho_recruit_oauth.main()

        self.assertEqual(
            post.call_args.kwargs["data"]["redirect_uri"],
            "https://example.com/callback",
        )


if __name__ == "__main__":
    unittest.main()
