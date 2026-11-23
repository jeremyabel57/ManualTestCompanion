import unittest

from manual_test_companion.queues import Deque, ProgramQueue


class DequeTests(unittest.TestCase):
    def test_fifo_and_front_operations_keep_expected_order(self) -> None:
        queue: Deque[str] = Deque()
        queue.push("second")
        queue.push_front("first")
        queue.push("third")

        self.assertEqual(queue.peek(), "first")
        self.assertEqual(queue.peek_back(), "third")
        self.assertEqual(queue.to_list(), ["first", "second", "third"])
        self.assertEqual(queue.pop(), "first")
        self.assertEqual(queue.pop_back(), "third")
        self.assertEqual(queue.to_list(), ["second"])

    def test_draining_to_front_preserves_source_order(self) -> None:
        source: Deque[int] = Deque()
        source.push(1)
        source.push(2)
        target: Deque[int] = Deque()
        target.push(3)

        source.drain_into(target, front=True)

        self.assertEqual(source.to_list(), [])
        self.assertEqual(target.to_list(), [2, 1, 3])


class ProgramQueueTests(unittest.TestCase):
    def test_program_queue_transitions_parked_active_done_and_restart(self) -> None:
        queue: ProgramQueue[str] = ProgramQueue("if", "$enabled")
        queue.push("first")
        queue.push("second")

        self.assertTrue(queue.is_parked)
        with self.assertRaisesRegex(RuntimeError, "parked"):
            queue.next_item()

        queue.release()
        self.assertTrue(queue.is_start)
        self.assertEqual(queue.next_item(), "first")
        self.assertEqual(queue.next_item(), "second")
        self.assertTrue(queue.is_done)
        with self.assertRaises(StopIteration):
            queue.next_item()

        queue.restart()
        self.assertEqual(queue.next_item(), "first")

    def test_appending_after_current_end_resumes_at_new_instruction(self) -> None:
        queue: ProgramQueue[str] = ProgramQueue()
        queue.push("first")
        queue.release()
        self.assertEqual(queue.next_item(), "first")
        self.assertTrue(queue.is_done)

        queue.push("second")

        self.assertFalse(queue.is_done)
        self.assertEqual(queue.next_item(), "second")


if __name__ == "__main__":
    unittest.main()
