import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from angelone_order_manager import AngelOneOrderManager


class AngelOneOrderLifecycleTests(unittest.TestCase):
    def test_existing_order_tag_is_reconciled_without_a_second_submission(self):
        intent_id = "nse-stable-intent"
        execution = SimpleNamespace(
            enabled=True,
            orders=Mock(return_value=[{
                "tag": intent_id,
                "order_id": "broker-order-1",
                "status": "COMPLETE",
                "quantity": 1,
                "filled_quantity": 1,
                "average_price": 100.0,
            }]),
            place_limit=Mock(),
        )
        request = SimpleNamespace(tag=intent_id)
        manager = AngelOneOrderManager(execution)

        result = manager.submit(request, intent_id)

        self.assertEqual(result["order_id"], "broker-order-1")
        execution.orders.assert_called_once()
        execution.place_limit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
