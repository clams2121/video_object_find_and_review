from app.config import DetectionConfig
from app.worker.motion import MotionResult, _score_confidence, _size_score


def _cfg(**overrides):
    return DetectionConfig(**{
        "min_frames": 5,
        "min_size_ratio": 0.01,
        "max_size_ratio": 0.9,
        "min_duration_seconds": 0.5,
        "ambiguous_band": [0.35, 0.65],
        **overrides,
    })


def test_clean_coherent_motion_scores_high():
    cfg = _cfg()
    result = MotionResult(
        frame_count=40, size_max=0.03, active_duration_seconds=2.5, path_straightness=1.0,
    )
    confidence = _score_confidence(result, cfg)
    assert confidence > cfg.ambiguous_band[1]


def test_jittery_undersized_short_motion_scores_low():
    cfg = _cfg()
    result = MotionResult(
        frame_count=2, size_max=0.0006, active_duration_seconds=0.13, path_straightness=0.1,
    )
    confidence = _score_confidence(result, cfg)
    assert confidence < cfg.ambiguous_band[0]


def test_size_score_penalizes_oversized_objects():
    cfg = _cfg()
    assert _size_score(0.5, cfg.min_size_ratio, cfg.max_size_ratio) == 1.0
    huge = _size_score(1.8, cfg.min_size_ratio, cfg.max_size_ratio)
    assert 0.0 <= huge < 1.0
