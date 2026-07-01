import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from inject_real_positives import split_clips, inject  # noqa: E402


def test_split_is_deterministic_and_partitions():
    files = [f"c{i}.wav" for i in range(100)]
    tr, te = split_clips(files, test_frac=0.2, seed=42)
    assert len(te) == 20 and len(tr) == 80
    assert set(tr) | set(te) == set(files)   # nothing lost
    assert not (set(tr) & set(te))           # disjoint
    tr2, te2 = split_clips(files, test_frac=0.2, seed=42)
    assert (tr, te) == (tr2, te2)            # deterministic


def test_split_small_set_keeps_one_each():
    tr, te = split_clips(["a.wav", "b.wav", "c.wav"], test_frac=0.15, seed=1)
    assert len(te) >= 1 and len(tr) >= 1


def test_inject_copies_and_clears_stale_features(tmp_path):
    src = tmp_path / "realmic_train" / "positive"
    src.mkdir(parents=True)
    for i in range(10):
        (src / f"positive_{i:03d}.wav").write_bytes(b"RIFFwav")
    run = tmp_path / "runs" / "hey_loki"
    run.mkdir(parents=True)
    # pre-existing synthetic clips + a stale feature cache that must be cleared
    (run / "positive_train").mkdir()
    (run / "positive_train" / "synthetic_0001.wav").write_bytes(b"x")
    (run / "positive_features_train.npy").write_bytes(b"stale")

    res = inject(src, run, test_frac=0.2, seed=7)

    assert res["train"] + res["test"] == 10
    assert res["test"] >= 1
    # real clips copied in with a realmic_ prefix, synthetic untouched
    train_wavs = {p.name for p in (run / "positive_train").glob("*.wav")}
    assert "synthetic_0001.wav" in train_wavs
    assert any(n.startswith("realmic_") for n in train_wavs)
    assert (run / "positive_test").is_dir()
    # stale feature cache cleared so --augment_clips recomputes with the new clips
    assert not (run / "positive_features_train.npy").exists()
    assert res["cleared_features"] == 1
