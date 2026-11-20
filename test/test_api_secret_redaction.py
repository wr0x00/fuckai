from __future__ import annotations

import unittest
from unittest.mock import patch

from web import app as web_app


class ApiSecretRedactionTests(unittest.TestCase):
    def test_config_response_does_not_return_api_keys(self):
        raw = {
            "attack_model": {"api_key": "attack-secret"},
            "target_model": {"api_key": "target-secret"},
        }
        with patch.object(web_app, "_read_config_raw", return_value=raw):
            result = web_app.get_config()

        self.assertEqual(result["attack_api_key"], "")
        self.assertEqual(result["target_api_key"], "")

    def test_model_list_only_reports_key_presence(self):
        models = [{"id": "m1", "name": "test", "api_key": "model-secret"}]
        with patch.object(web_app, "_ensure_models", return_value=(models, "m1", "")):
            result = web_app.list_models()

        self.assertNotIn("api_key", result["models"][0])
        self.assertTrue(result["models"][0]["has_api_key"])

    def test_blank_api_key_keeps_existing_model_secret(self):
        models = [{
            "id": "m1",
            "name": "test",
            "base_url": "https://example.invalid/v1",
            "api_key": "model-secret",
            "model": "model",
            "temperature": 0.0,
        }]
        saved = {}
        with (
            patch.object(web_app, "_ensure_models", return_value=(models, "m1", "")),
            patch.object(web_app, "_save_models", side_effect=lambda entries, *_: saved.update(
                models=entries
            )),
        ):
            web_app.save_model(web_app.ModelItem(
                id="m1",
                name="test",
                base_url="https://example.invalid/v1",
                model="model",
            ))

        self.assertEqual(saved["models"][0]["api_key"], "model-secret")

    def test_chat_session_responses_do_not_return_api_key(self):
        session = {"id": "s1", "api_key": "session-secret", "messages": []}
        with patch.object(web_app, "_load_chat_sessions", return_value=[session]):
            result = web_app.get_chat_session("s1")

        self.assertNotIn("api_key", result["session"])


if __name__ == "__main__":
    unittest.main()