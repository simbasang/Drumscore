import dataclasses


@dataclasses.dataclass(frozen=True)
class TempoPoint:
    """A tempo marking anchored to an immutable source-audio timestamp.
    See docs/ARCHITECTURE_V1.md's Timing model."""

    source_time: float
    bpm: float

    def __post_init__(self) -> None:
        if self.source_time < 0:
            raise ValueError(f"source_time must be >= 0, got {self.source_time}")
        if self.bpm <= 0:
            raise ValueError(f"bpm must be > 0, got {self.bpm}")


@dataclasses.dataclass(frozen=True)
class BeatPoint:
    """A detected beat anchored to an immutable source-audio timestamp,
    with its musical position and whether it starts a measure (downbeat).
    See docs/ARCHITECTURE_V1.md's Timing model."""

    source_time: float
    measure: int
    beat: int
    is_downbeat: bool
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.source_time < 0:
            raise ValueError(f"source_time must be >= 0, got {self.source_time}")
        if self.measure < 1:
            raise ValueError(f"measure must be >= 1, got {self.measure}")
        if self.beat < 1:
            raise ValueError(f"beat must be >= 1, got {self.beat}")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be between 0 and 1, got {self.confidence}")


@dataclasses.dataclass(frozen=True)
class TempoMap:
    """An ordered, source-time-anchored sequence of tempo points describing
    how tempo evolves across a song. Describes musical timing relative to
    source audio - it is not the playback clock. See
    docs/ARCHITECTURE_V1.md's Timing model."""

    points: tuple[TempoPoint, ...]

    def __post_init__(self) -> None:
        if len(self.points) == 0:
            raise ValueError("TempoMap must contain at least one TempoPoint")
        times = [point.source_time for point in self.points]
        if times != sorted(times):
            raise ValueError("TempoMap points must be sorted by non-decreasing source_time")

    def bpm_at(self, source_time: float) -> float:
        """The tempo in effect at source_time: the last point at or before
        it, or the first point if source_time precedes every point."""
        applicable = self.points[0]
        for point in self.points:
            if point.source_time > source_time:
                break
            applicable = point
        return applicable.bpm

    @classmethod
    def constant(cls, bpm: float) -> "TempoMap":
        """A single-point TempoMap holding one estimated tempo value for
        the whole song - informational display/diagnostics metadata only.
        Quantization never reads this; it always uses detected beat anchors
        (see app.beat_mapping.quantize_events_with_beats). Real
        tempo-change detection (TECHNICAL_DEBT.md, "Tempo estimation
        disagrees with DrumScript's own estimate") would replace this with
        a true multi-point TempoMap."""
        return cls(points=(TempoPoint(source_time=0.0, bpm=bpm),))
