import numpy as np

from app.worker.pipeline import _crop_and_zoom_thumbnail


def _make_frame(w=640, h=360):
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_no_bbox_returns_full_frame_unchanged():
    frame = _make_frame()
    result = _crop_and_zoom_thumbnail(frame, None)
    assert result.shape == frame.shape


def test_small_bbox_is_cropped_and_zoomed_in():
    frame = _make_frame()
    # a small 20x20 object near the top-left
    bbox = (50, 50, 20, 20)
    result = _crop_and_zoom_thumbnail(frame, bbox, pad_ratio=0.25, target_min_dim=300)

    # crop must be much smaller than the full frame before any zoom, so a
    # meaningful zoom factor should have been applied
    assert result.shape[0] < frame.shape[0]
    assert result.shape[1] < frame.shape[1]
    # zoomed up to (at least) the target minimum dimension
    assert min(result.shape[0], result.shape[1]) >= 300


def test_large_bbox_is_not_upscaled():
    frame = _make_frame()
    # object + padding already covers the whole frame - no zoom should be applied
    bbox = (10, 10, 600, 340)
    result = _crop_and_zoom_thumbnail(frame, bbox, pad_ratio=0.1, target_min_dim=300)
    assert result.shape == frame.shape


def test_bbox_padding_stays_within_frame_bounds():
    frame = _make_frame()
    # object right at the edge - padding must not go out of bounds / crash
    bbox = (0, 0, 10, 10)
    result = _crop_and_zoom_thumbnail(frame, bbox)
    assert result is not None
    assert result.shape[0] > 0 and result.shape[1] > 0
