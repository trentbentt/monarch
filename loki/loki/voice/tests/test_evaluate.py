import numpy as np

from loki.voice.training import evaluate


class FakeModel:
    """Returns a high score only on the frame whose first sample == 1."""
    def __init__(self):
        self.reset_calls = 0

    def reset(self):
        self.reset_calls += 1

    def predict(self, frame):
        return {"hey_loki": 0.99 if frame[0] == 1 else 0.01}


def test_frame_scores_peak_and_resets():
    # frame_scores() replaced the old score_clip(); it resets the sliding window
    # once per clip and returns the per-frame peak list (caller takes max()).
    m = FakeModel()
    audio = np.zeros(evaluate.FRAME * 3, dtype=np.int16)
    audio[evaluate.FRAME] = 1            # spike in the 2nd frame
    scores = evaluate.frame_scores(m, audio)
    assert abs(max(scores) - 0.99) < 1e-6
    assert m.reset_calls == 1            # sliding window cleared per clip
