import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import resolve_eval_dirs  # noqa: E402


def test_default_uses_eval_data_and_background_clips(tmp_path):
    here = tmp_path
    d = resolve_eval_dirs(here, None)
    assert d["positive"] == here / "eval_data" / "positive"
    assert d["hard_negative"] == here / "eval_data" / "hard_negative"
    assert d["speech_negative"] == here / "eval_data" / "speech_negative"
    # no eval_data/fa_audio -> FA source falls back to datasets/background_clips
    assert d["fa_source"] == here / "datasets" / "background_clips"


def test_data_dir_with_fa_audio_uses_it(tmp_path):
    here = tmp_path
    data = tmp_path / "realmic_eval"
    (data / "fa_audio").mkdir(parents=True)
    d = resolve_eval_dirs(here, str(data))
    assert d["positive"] == data / "positive"
    assert d["fa_source"] == data / "fa_audio"
