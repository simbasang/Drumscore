from app.api.schemas import TempoMapResponse, TempoPointResponse
from app.timing import TempoMap, TempoPoint


def test_tempo_point_response_from_domain():
    point = TempoPoint(source_time=1.5, bpm=120.0)

    response = TempoPointResponse.from_domain(point)

    assert response.source_time == 1.5
    assert response.bpm == 120.0


def test_tempo_map_response_from_domain():
    tempo_map = TempoMap(points=[TempoPoint(source_time=0.0, bpm=100.0), TempoPoint(source_time=2.0, bpm=110.0)])

    response = TempoMapResponse.from_domain(tempo_map)

    assert [(p.source_time, p.bpm) for p in response.points] == [(0.0, 100.0), (2.0, 110.0)]
