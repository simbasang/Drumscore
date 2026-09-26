import numpy as np
import pytest
import soundfile as sf

from app.audio_mix import mix_stems

SR = 8000


def _write(path, samples, sr=SR):
    sf.write(str(path), np.asarray(samples, dtype=np.float32), sr, subtype="FLOAT")
    return path


def test_mix_is_the_sample_wise_sum_of_both_stems(tmp_path):
    drums = _write(tmp_path / "drums.wav", [[0.1, 0.2], [0.3, -0.4]])
    accompaniment = _write(tmp_path / "acc.wav", [[0.05, 0.0], [-0.3, 0.1]])

    result = mix_stems(drums, accompaniment, tmp_path / "mix.wav")

    mixed, sr = sf.read(str(result), always_2d=True)
    assert sr == SR
    np.testing.assert_allclose(mixed, [[0.15, 0.2], [0.0, -0.3]], atol=1e-6)


def test_pads_the_shorter_stem_with_silence(tmp_path):
    drums = _write(tmp_path / "drums.wav", [0.1, 0.2, 0.3])
    accompaniment = _write(tmp_path / "acc.wav", [0.5])

    result = mix_stems(drums, accompaniment, tmp_path / "mix.wav")

    mixed, _ = sf.read(str(result), always_2d=True)
    np.testing.assert_allclose(mixed[:, 0], [0.6, 0.2, 0.3], atol=1e-6)


def test_mixes_a_mono_stem_into_a_stereo_stem(tmp_path):
    drums = _write(tmp_path / "drums.wav", [0.1, 0.2])
    accompaniment = _write(tmp_path / "acc.wav", [[0.0, 0.5], [0.5, 0.0]])

    result = mix_stems(drums, accompaniment, tmp_path / "mix.wav")

    mixed, _ = sf.read(str(result), always_2d=True)
    np.testing.assert_allclose(mixed, [[0.1, 0.6], [0.7, 0.2]], atol=1e-6)


def test_rejects_stems_with_different_sample_rates(tmp_path):
    drums = _write(tmp_path / "drums.wav", [0.1], sr=SR)
    accompaniment = _write(tmp_path / "acc.wav", [0.1], sr=SR * 2)

    with pytest.raises(ValueError, match="sample rates differ"):
        mix_stems(drums, accompaniment, tmp_path / "mix.wav")
