import os
import unittest
from unittest.mock import patch

from runtime_guard import LiveRuntimeNotApproved, require_live_runtime


class RuntimeGuardTests(unittest.TestCase):
    def test_local_runtime_is_blocked(self):
        with patch.dict(os.environ, {
            "CLOUD_RUNTIME": "false",
            "LIVE_RUNTIME_APPROVED": "true",
        }, clear=False):
            with self.assertRaises(LiveRuntimeNotApproved):
                require_live_runtime()

    def test_unapproved_cloud_runtime_is_blocked(self):
        with patch.dict(os.environ, {
            "CLOUD_RUNTIME": "true",
            "LIVE_RUNTIME_APPROVED": "false",
        }, clear=False):
            with self.assertRaises(LiveRuntimeNotApproved):
                require_live_runtime()

    def test_approved_cloud_runtime_is_allowed(self):
        with patch.dict(os.environ, {
            "CLOUD_RUNTIME": "true",
            "LIVE_RUNTIME_APPROVED": "true",
        }, clear=False):
            require_live_runtime()


if __name__ == "__main__":
    unittest.main()
