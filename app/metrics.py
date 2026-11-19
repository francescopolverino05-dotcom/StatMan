"""Pass-direction helpers for the EnjoyStats dashboard."""

from __future__ import annotations

from dataclasses import dataclass

from data_models.player_stats import DistributionStats


@dataclass(frozen=True, slots=True)
class PassDirections:
    """Forward / sideways / backward pass counts for the distribution column."""

    forward: int = 0
    sideways: int = 0
    backward: int = 0

    @property
    def total(self) -> int:
        """All direction-tagged attempts."""

        return self.forward + self.sideways + self.backward

    def as_rows(self) -> list[dict[str, object]]:
        """Return a table-ready breakdown including share of attempts."""

        total = self.total
        rows: list[dict[str, object]] = []
        for label, count in (
            ("Forward", self.forward),
            ("Sideways", self.sideways),
            ("Backward", self.backward),
        ):
            share = 0.0 if total == 0 else round(count / total, 4)
            rows.append({"Direction": label, "Passes": count, "Share": share})
        return rows


def directions_from_distribution(
    distribution: DistributionStats,
    *,
    explicit: PassDirections | None = None,
) -> PassDirections:
    """Resolve a direction split for the UI.

    Prefers tagged :attr:`~data_models.player_stats.DistributionStats.pass_directions`
    when that split is populated. Otherwise progressive passes stand in for
    forward, cutbacks for backward, and the remaining attempts are sideways.

    Args:
        distribution: Nested passing pillar from :class:`PlayerMatchProfile`.
        explicit: Optional tagged split from dummy/showcase data.
    """

    if explicit is not None:
        return explicit
    tagged = distribution.pass_directions
    tagged_total = tagged.forward.total + tagged.sideways.total + tagged.backward.total
    if tagged_total:
        return PassDirections(
            forward=tagged.forward.total,
            sideways=tagged.sideways.total,
            backward=tagged.backward.total,
        )
    forward = distribution.progressive_passes.total
    backward = distribution.cutbacks.total
    sideways = max(distribution.passes.total - forward - backward, 0)
    return PassDirections(forward=forward, sideways=sideways, backward=backward)
