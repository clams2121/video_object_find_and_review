from app.web.routes_clips import _status_filter_from_param


def test_good_filter_maps_to_good_status():
    assert _status_filter_from_param("good") == "good"


def test_bad_filter_maps_to_no_detect_status():
    assert _status_filter_from_param("bad") == "no_detect"


def test_all_filter_means_no_restriction():
    assert _status_filter_from_param("all") is None


def test_unrecognized_filter_falls_back_to_no_restriction():
    assert _status_filter_from_param("bogus") is None
