from app.geo import distance_m, offset


def test_offset_round_trips_through_distance():
    lat, lon = 40.695, -89.589
    lat2, lon2 = offset(lat, lon, 30.0, 40.0)
    assert abs(distance_m(lat, lon, lat2, lon2) - 50.0) < 0.1


def test_distance_zero_for_same_point():
    assert distance_m(1.0, 2.0, 1.0, 2.0) == 0.0
