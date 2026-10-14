import contextlib
import io
import unittest
from unittest.mock import patch

from ai.scripts.config import FEATURES
from pipeline import replay


class ReplayTests(unittest.TestCase):
    def test_finite_input_count_unchanged(self):
        self.assertEqual(len(list(replay.synthetic_rows(3))), 3)

    def test_continuous_cli_sends_beyond_default_limit_and_stops_cleanly(self):
        sent = []

        def post(session, server, frame, location, floor, input_kind):
            self.assertEqual(input_kind, "synthetic")
            sent.append(frame)
            return {"inference": {"status": "ok"}}

        def wait(seconds):
            if len(sent) >= 35:
                raise KeyboardInterrupt

        output = io.StringIO()
        with patch("sys.argv", ["replay", "--synthetic", "--continuous"]), \
             patch.object(replay, "post_frame", side_effect=post), \
             patch.object(replay.time, "sleep", side_effect=wait), \
             contextlib.redirect_stdout(output):
            replay.main()
        self.assertEqual(len(sent), 35)
        self.assertEqual(set(sent[-1]["features"]), set(FEATURES))
        self.assertIn("Replay stopped.", output.getvalue())

    def test_finite_cli_prints_end_of_input(self):
        output = io.StringIO()
        with patch("sys.argv", ["replay", "--synthetic", "--count", "2"]), \
             patch.object(replay, "post_frame", return_value={"inference": {"status": "ok"}}) as post, \
             patch.object(replay.time, "sleep"), contextlib.redirect_stdout(output):
            replay.main()
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.args[-1], 2)
        self.assertEqual(post.call_args.kwargs["input_kind"], "synthetic")
        self.assertIn("Replay finished", output.getvalue())

    def test_csv_cannot_be_looped_as_live_measurement(self):
        with patch("sys.argv", ["replay", "--feature-file", "unused.csv", "--continuous"]), \
             contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            replay.main()
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
