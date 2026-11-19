"""Pydantic schemas for football player statistics.

The collection layer splits every player-match row into four pillars:

* :class:`OffensiveStats` — finishing and chance creation, stored flat so the
  most queried shooting columns can be indexed without JSON unpacking.
* :class:`DefensiveStats` — nested duel, block, foul, card, interception,
  recovery, and ball-lost structures.
* :class:`DistributionStats` — nested success/total ratios for passing by
  length, third, direction, and destination.
* :class:`PossessionStats` — on-ball time and possession share.

All counts are non-negative integers. Ratio helpers are derived
:attr:`computed_field` values and are never persisted independently of the
underlying success/total pair.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Self
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    """Base model that forbids undeclared fields and re-validates on assignment."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        from_attributes=True,
        ser_json_timedelta="iso8601",
    )


class AttemptSplit(StrictModel):
    """Success/total pairing used for duels, passes, crosses, and cutbacks.

    Attributes:
        success: Number of successful attempts.
        total: Number of attempts, successful or not.
    """

    success: int = Field(default=0, ge=0, description="Successful attempts.")
    total: int = Field(default=0, ge=0, description="Total attempts.")

    @model_validator(mode="after")
    def success_cannot_exceed_total(self) -> Self:
        """Reject splits where successes are greater than attempts."""

        if self.success > self.total:
            raise ValueError(f"success ({self.success}) cannot exceed total ({self.total}).")
        return self

    @computed_field
    @property
    def failed(self) -> int:
        """Unsuccessful attempts (``total - success``)."""

        return self.total - self.success

    @computed_field
    @property
    def success_rate(self) -> float:
        """Success ratio in ``[0, 1]``. Returns ``0.0`` when ``total`` is 0."""

        if self.total == 0:
            return 0.0
        return round(self.success / self.total, 4)

    def add(self, *, succeeded: bool) -> AttemptSplit:
        """Return a new split with one additional attempt.

        Args:
            succeeded: Whether the additional attempt was successful.

        Returns:
            A new :class:`AttemptSplit` with ``total`` incremented by one and
            ``success`` incremented when ``succeeded`` is true.
        """

        return AttemptSplit(
            success=self.success + int(succeeded),
            total=self.total + 1,
        )


class OffensiveStats(StrictModel):
    """Flattened attacking output for a player in a single match.

    Shot taxonomy follows the Opta/Wyscout convention that
    ``total_shots == shots_on_target + blocked_shots + missed_shots`` and
    ``total_shots == shots_inside_penalty_area + shots_outside_penalty_area``.
    Goals are a subset of shots on target (own goals are not attributed here).

    Attributes:
        minutes: Minutes played, including stoppage and extra time.
        goals: Goals scored by the player (excluding own goals).
        assists: Goal-creating passes officially credited as assists.
        total_shots: All shot attempts excluding throws and own-goal deflections.
        shots_on_target: Shots requiring a save or resulting in a goal.
        blocked_shots: Shots blocked by an outfield defender before the goal.
        missed_shots: Shots off target that were not blocked.
        shots_inside_penalty_area: Shot attempts originating in the attacking box.
        shots_outside_penalty_area: Shot attempts originating outside the box.
        offsides: Times the player was judged offside.
        freekicks: Set-piece free kicks taken by the player.
        corners: Corner kicks taken by the player.
        penalty_kicks: Penalty kicks taken (also counted in ``total_shots``).
        throw_ins: Throw-ins taken.
    """

    minutes: float = Field(
        default=0.0,
        ge=0.0,
        le=150.0,
        description="Minutes played, including stoppage and extra time.",
    )
    goals: int = Field(default=0, ge=0, description="Goals scored, excluding own goals.")
    assists: int = Field(default=0, ge=0, description="Assists credited to the player.")
    total_shots: int = Field(default=0, ge=0, description="All shot attempts.")
    shots_on_target: int = Field(default=0, ge=0, description="Shots on target.")
    blocked_shots: int = Field(default=0, ge=0, description="Shots blocked by an outfield player.")
    missed_shots: int = Field(default=0, ge=0, description="Shots off target and not blocked.")
    shots_inside_penalty_area: int = Field(
        default=0, ge=0, description="Shots originating inside the attacking penalty area."
    )
    shots_outside_penalty_area: int = Field(
        default=0, ge=0, description="Shots originating outside the attacking penalty area."
    )
    offsides: int = Field(default=0, ge=0, description="Offside judgements against the player.")
    freekicks: int = Field(default=0, ge=0, description="Free kicks taken.")
    corners: int = Field(default=0, ge=0, description="Corner kicks taken.")
    penalty_kicks: int = Field(default=0, ge=0, description="Penalty kicks taken.")
    throw_ins: int = Field(default=0, ge=0, description="Throw-ins taken.")

    @field_validator("minutes")
    @classmethod
    def minutes_one_decimal(cls, value: float) -> float:
        """Store minutes at one decimal place to match typical tagging clocks."""

        return round(value, 1)

    @model_validator(mode="after")
    def shot_components_must_reconcile(self) -> Self:
        """Enforce the two industry shot identities and goals ⊆ on-target."""

        outcome_sum = self.shots_on_target + self.blocked_shots + self.missed_shots
        if outcome_sum != self.total_shots:
            raise ValueError(
                "total_shots must equal shots_on_target + blocked_shots + missed_shots "
                f"({self.total_shots} != {outcome_sum})."
            )
        zone_sum = self.shots_inside_penalty_area + self.shots_outside_penalty_area
        if zone_sum != self.total_shots:
            raise ValueError(
                "total_shots must equal shots_inside_penalty_area + "
                f"shots_outside_penalty_area ({self.total_shots} != {zone_sum})."
            )
        if self.goals > self.shots_on_target:
            raise ValueError(
                f"goals ({self.goals}) cannot exceed shots_on_target ({self.shots_on_target})."
            )
        if self.penalty_kicks > self.total_shots:
            raise ValueError(
                f"penalty_kicks ({self.penalty_kicks}) cannot exceed total_shots "
                f"({self.total_shots})."
            )
        return self

    @computed_field
    @property
    def shot_accuracy(self) -> float:
        """On-target ratio over all shots. Returns ``0.0`` when no shots were taken."""

        if self.total_shots == 0:
            return 0.0
        return round(self.shots_on_target / self.total_shots, 4)

    def with_minutes(self, minutes: float) -> OffensiveStats:
        """Return a copy with the minutes-played clock updated.

        Args:
            minutes: Cumulative minutes played, including stoppage time.
        """

        return self.model_copy(update={"minutes": minutes})

    def record_shot(
        self,
        *,
        inside_penalty_area: bool,
        on_target: bool = False,
        blocked: bool = False,
        missed: bool | None = None,
        is_goal: bool = False,
        is_penalty: bool = False,
    ) -> OffensiveStats:
        """Return a copy with one shot (and optional goal) applied.

        Exactly one of ``on_target``, ``blocked``, or ``missed`` must hold.
        ``is_goal=True`` forces ``on_target=True``.

        Args:
            inside_penalty_area: Whether the attempt originated in the attacking box.
            on_target: Shot required a save or resulted in a goal.
            blocked: Shot was blocked by an outfield defender.
            missed: Shot missed the target and was not blocked. Inferred when omitted.
            is_goal: Whether the shot resulted in a goal for the shooting team.
            is_penalty: Whether the attempt was a penalty kick.

        Returns:
            A new :class:`OffensiveStats` instance with reconciled shot counters.

        Raises:
            ValueError: If the shot outcome flags are not mutually exclusive.
        """

        if is_goal:
            on_target = True
            blocked = False
            missed = False
        if missed is None:
            missed = not on_target and not blocked
        outcome_count = int(on_target) + int(blocked) + int(missed)
        if outcome_count != 1:
            raise ValueError("A shot must be exactly one of on_target, blocked, or missed.")
        return self.model_copy(
            update={
                "goals": self.goals + int(is_goal),
                "total_shots": self.total_shots + 1,
                "shots_on_target": self.shots_on_target + int(on_target),
                "blocked_shots": self.blocked_shots + int(blocked),
                "missed_shots": self.missed_shots + int(missed),
                "shots_inside_penalty_area": self.shots_inside_penalty_area
                + int(inside_penalty_area),
                "shots_outside_penalty_area": self.shots_outside_penalty_area
                + int(not inside_penalty_area),
                "penalty_kicks": self.penalty_kicks + int(is_penalty),
            }
        )

    def record_assist(self) -> OffensiveStats:
        """Return a copy with one additional assist."""

        return self.model_copy(update={"assists": self.assists + 1})

    def record_offside(self) -> OffensiveStats:
        """Return a copy with one additional offside judgement."""

        return self.model_copy(update={"offsides": self.offsides + 1})

    def record_freekick(self) -> OffensiveStats:
        """Return a copy with one additional free kick taken."""

        return self.model_copy(update={"freekicks": self.freekicks + 1})

    def record_corner(self) -> OffensiveStats:
        """Return a copy with one additional corner kick taken."""

        return self.model_copy(update={"corners": self.corners + 1})

    def record_throw_in(self) -> OffensiveStats:
        """Return a copy with one additional throw-in taken."""

        return self.model_copy(update={"throw_ins": self.throw_ins + 1})


class BlockStats(StrictModel):
    """Defensive blocks split by the object that was obstructed.

    Attributes:
        shots: Shot attempts blocked.
        crosses: Crosses blocked or deflected away from the box.
        passes: Open-play passes blocked (excluding shots and crosses).
    """

    shots: int = Field(default=0, ge=0, description="Shot blocks.")
    crosses: int = Field(default=0, ge=0, description="Cross blocks.")
    passes: int = Field(default=0, ge=0, description="Open-play pass blocks.")

    @computed_field
    @property
    def total(self) -> int:
        """All recorded blocks."""

        return self.shots + self.crosses + self.passes

    def record(self, kind: str) -> BlockStats:
        """Return a copy with one additional block of ``kind``.

        Args:
            kind: One of ``\"shots\"``, ``\"crosses\"``, or ``\"passes\"``.

        Raises:
            ValueError: If ``kind`` is not a recognised block type.
        """

        if kind not in {"shots", "crosses", "passes"}:
            raise ValueError(f"Unknown block kind: {kind!r}.")
        return self.model_copy(update={kind: getattr(self, kind) + 1})


class FoulStats(StrictModel):
    """Fouls conceded and fouls won.

    Attributes:
        committed: Fouls given away by the player.
        won: Fouls drawn from an opponent.
    """

    committed: int = Field(default=0, ge=0, description="Fouls conceded.")
    won: int = Field(default=0, ge=0, description="Fouls won.")

    def record_committed(self) -> FoulStats:
        """Return a copy with one additional foul conceded."""

        return self.model_copy(update={"committed": self.committed + 1})

    def record_won(self) -> FoulStats:
        """Return a copy with one additional foul won."""

        return self.model_copy(update={"won": self.won + 1})


class InterceptionStats(StrictModel):
    """Interceptions, optionally split by the third in which they occurred.

    When any zonal count is non-zero, the three thirds must sum to ``total``.
    A post-match feed that only supplies a headline interception count may
    leave the zonal fields at zero.

    Attributes:
        total: All interceptions.
        defensive_third: Interceptions in the defensive third.
        middle_third: Interceptions in the middle third.
        final_third: Interceptions in the final third.
    """

    total: int = Field(default=0, ge=0, description="All interceptions.")
    defensive_third: int = Field(
        default=0, ge=0, description="Interceptions in the defensive third."
    )
    middle_third: int = Field(default=0, ge=0, description="Interceptions in the middle third.")
    final_third: int = Field(default=0, ge=0, description="Interceptions in the final third.")

    @model_validator(mode="after")
    def zonal_split_must_match_total_when_present(self) -> Self:
        """Require the third split to reconcile once any zone is populated."""

        zonal_sum = self.defensive_third + self.middle_third + self.final_third
        if zonal_sum == 0:
            return self
        if zonal_sum != self.total:
            raise ValueError(
                "interception thirds must sum to total when a zonal split is provided "
                f"({zonal_sum} != {self.total})."
            )
        return self

    def record(self, third: str) -> InterceptionStats:
        """Return a copy with one interception in ``third``.

        Args:
            third: ``\"defensive\"``, ``\"middle\"``, or ``\"final\"``.
        """

        field_name = {
            "defensive": "defensive_third",
            "middle": "middle_third",
            "final": "final_third",
        }.get(third)
        if field_name is None:
            raise ValueError(f"Unknown tactical third: {third!r}.")
        return self.model_copy(
            update={
                "total": self.total + 1,
                field_name: getattr(self, field_name) + 1,
            }
        )


class BallRecoveryStats(StrictModel):
    """Loose-ball recoveries split by tactical third.

    Attributes:
        defensive_third: Recoveries in the defensive third.
        middle_third: Recoveries in the middle third.
        final_third: Recoveries in the final third.
    """

    defensive_third: int = Field(default=0, ge=0, description="Recoveries in the defensive third.")
    middle_third: int = Field(default=0, ge=0, description="Recoveries in the middle third.")
    final_third: int = Field(default=0, ge=0, description="Recoveries in the final third.")

    @computed_field
    @property
    def total(self) -> int:
        """All recoveries across the three thirds."""

        return self.defensive_third + self.middle_third + self.final_third

    def record(self, third: str) -> BallRecoveryStats:
        """Return a copy with one recovery in ``third``.

        Args:
            third: ``\"defensive\"``, ``\"middle\"``, or ``\"final\"``.
        """

        field_name = {
            "defensive": "defensive_third",
            "middle": "middle_third",
            "final": "final_third",
        }.get(third)
        if field_name is None:
            raise ValueError(f"Unknown tactical third: {third!r}.")
        return self.model_copy(update={field_name: getattr(self, field_name) + 1})


class BallLostStats(BallRecoveryStats):
    """Turnovers / balls lost split by tactical third."""


class DefensiveStats(StrictModel):
    """Nested defensive actions for a player in a single match.

    Attributes:
        aerial_duels: Aerial duel success/total.
        ground_duels: Ground duel success/total (tackles, dribbles contested).
        blocks: Shot, cross, and pass blocks.
        fouls: Fouls conceded and fouls won.
        interceptions: Interceptions with optional zonal split.
        ball_recoveries: Recoveries split by defensive, middle, and final third.
        ball_lost: Turnovers split by defensive, middle, and final third.
        yellow_cards: Yellow cards received.
        red_cards: Red cards received (straight or second yellow).
        goals_against: Goals conceded while the player was on the pitch.
        ppda: Passes allowed per defensive action (pressing intensity).
    """

    aerial_duels: AttemptSplit = Field(default_factory=AttemptSplit)
    ground_duels: AttemptSplit = Field(default_factory=AttemptSplit)
    blocks: BlockStats = Field(default_factory=BlockStats)
    fouls: FoulStats = Field(default_factory=FoulStats)
    interceptions: InterceptionStats = Field(default_factory=InterceptionStats)
    ball_recoveries: BallRecoveryStats = Field(default_factory=BallRecoveryStats)
    ball_lost: BallLostStats = Field(default_factory=BallLostStats)
    yellow_cards: int = Field(default=0, ge=0, description="Yellow cards received.")
    red_cards: int = Field(default=0, ge=0, description="Red cards received.")
    goals_against: int = Field(default=0, ge=0, description="Goals conceded while on the pitch.")
    ppda: float = Field(
        default=0.0,
        ge=0.0,
        description="Passes per defensive action (pressing intensity).",
    )

    @field_validator("ppda")
    @classmethod
    def ppda_two_decimals(cls, value: float) -> float:
        """Store PPDA at two decimal places."""

        return round(value, 2)

    def record_aerial_duel(self, *, succeeded: bool) -> DefensiveStats:
        """Return a copy with one aerial duel applied."""

        return self.model_copy(update={"aerial_duels": self.aerial_duels.add(succeeded=succeeded)})

    def record_ground_duel(self, *, succeeded: bool) -> DefensiveStats:
        """Return a copy with one ground duel applied."""

        return self.model_copy(update={"ground_duels": self.ground_duels.add(succeeded=succeeded)})

    def record_block(self, kind: str) -> DefensiveStats:
        """Return a copy with one block of ``kind`` applied."""

        return self.model_copy(update={"blocks": self.blocks.record(kind)})

    def record_foul(self, *, won: bool) -> DefensiveStats:
        """Return a copy with a foul won or conceded."""

        fouls = self.fouls.record_won() if won else self.fouls.record_committed()
        return self.model_copy(update={"fouls": fouls})

    def record_interception(self, third: str) -> DefensiveStats:
        """Return a copy with one interception in ``third``."""

        return self.model_copy(update={"interceptions": self.interceptions.record(third)})

    def record_recovery(self, third: str) -> DefensiveStats:
        """Return a copy with one ball recovery in ``third``."""

        return self.model_copy(update={"ball_recoveries": self.ball_recoveries.record(third)})

    def record_ball_lost(self, third: str) -> DefensiveStats:
        """Return a copy with one turnover in ``third``."""

        return self.model_copy(update={"ball_lost": self.ball_lost.record(third)})

    def record_yellow_card(self) -> DefensiveStats:
        """Return a copy with one additional yellow card."""

        return self.model_copy(update={"yellow_cards": self.yellow_cards + 1})

    def record_red_card(self) -> DefensiveStats:
        """Return a copy with one additional red card."""

        return self.model_copy(update={"red_cards": self.red_cards + 1})

    def record_goal_against(self) -> DefensiveStats:
        """Return a copy with one additional goal conceded."""

        return self.model_copy(update={"goals_against": self.goals_against + 1})


class PassLocationStats(StrictModel):
    """Pass attempts grouped by length band and by destination in the box.

    Length bands follow the industry default of short < 15 m, medium 15–30 m,
    and long > 30 m, measured on the FIFA pitch. ``into_penalty_area`` is a
    destination filter and may overlap the length bands (a short cutback into
    the box increments both ``short`` and ``into_penalty_area``).

    Attributes:
        short: Passes shorter than 15 m.
        medium: Passes from 15 m inclusive to 30 m inclusive.
        long: Passes longer than 30 m.
        into_penalty_area: Passes whose end point is inside the attacking box.
    """

    short: AttemptSplit = Field(default_factory=AttemptSplit)
    medium: AttemptSplit = Field(default_factory=AttemptSplit)
    long: AttemptSplit = Field(default_factory=AttemptSplit)
    into_penalty_area: AttemptSplit = Field(default_factory=AttemptSplit)

    def record(
        self,
        *,
        band: str,
        succeeded: bool,
        into_penalty_area: bool,
    ) -> PassLocationStats:
        """Return a copy with one pass applied to a length band and optional box.

        Args:
            band: ``\"short\"``, ``\"medium\"``, or ``\"long\"``.
            succeeded: Whether the pass reached a teammate.
            into_penalty_area: Whether the end point is inside the attacking box.
        """

        if band not in {"short", "medium", "long"}:
            raise ValueError(f"Unknown pass length band: {band!r}.")
        updates: dict[str, AttemptSplit] = {
            band: getattr(self, band).add(succeeded=succeeded),
        }
        if into_penalty_area:
            updates["into_penalty_area"] = self.into_penalty_area.add(succeeded=succeeded)
        return self.model_copy(update=updates)


class PassThirdStats(StrictModel):
    """Pass attempts grouped by the tactical third they were played from."""

    defensive_third: AttemptSplit = Field(default_factory=AttemptSplit)
    middle_third: AttemptSplit = Field(default_factory=AttemptSplit)
    final_third: AttemptSplit = Field(default_factory=AttemptSplit)

    def record(self, third: str, *, succeeded: bool) -> PassThirdStats:
        """Return a copy with one pass from ``third``."""

        field_name = {
            "defensive": "defensive_third",
            "middle": "middle_third",
            "final": "final_third",
        }.get(third)
        if field_name is None:
            raise ValueError(f"Unknown tactical third: {third!r}.")
        return self.model_copy(
            update={field_name: getattr(self, field_name).add(succeeded=succeeded)}
        )


class PassDirectionStats(StrictModel):
    """Pass attempts grouped by direction of travel on the attacking frame."""

    forward: AttemptSplit = Field(default_factory=AttemptSplit)
    sideways: AttemptSplit = Field(default_factory=AttemptSplit)
    backward: AttemptSplit = Field(default_factory=AttemptSplit)

    def record(self, direction: str, *, succeeded: bool) -> PassDirectionStats:
        """Return a copy with one pass of ``direction``."""

        if direction not in {"forward", "sideways", "backward"}:
            raise ValueError(f"Unknown pass direction: {direction!r}.")
        return self.model_copy(
            update={direction: getattr(self, direction).add(succeeded=succeeded)}
        )


class DistributionStats(StrictModel):
    """Nested success/total passing metrics for a player in a single match.

    ``crosses``, ``cutbacks``, and ``progressive_passes`` are overlapping
    subsets of ``passes`` and are therefore not required to be disjoint.
    When a length-band split is present, ``short + medium + long`` totals
    must equal ``passes.total`` (and the same for successes).

    Attributes:
        passes: All open-play and set-piece passes except throw-ins.
        crosses: High or driven deliveries from wide areas.
        cutbacks: Low, backward or square deliveries from the byline.
        progressive_passes: Passes that move the ball significantly toward goal.
        pass_locations: Length-band and penalty-area destination splits.
        pass_thirds: Passes played from each tactical third.
        into_final_third: Passes that enter the final third.
        pass_directions: Forward / sideways / backward splits.
    """

    passes: AttemptSplit = Field(default_factory=AttemptSplit)
    crosses: AttemptSplit = Field(default_factory=AttemptSplit)
    cutbacks: AttemptSplit = Field(default_factory=AttemptSplit)
    progressive_passes: AttemptSplit = Field(default_factory=AttemptSplit)
    pass_locations: PassLocationStats = Field(default_factory=PassLocationStats)
    pass_thirds: PassThirdStats = Field(default_factory=PassThirdStats)
    into_final_third: AttemptSplit = Field(default_factory=AttemptSplit)
    pass_directions: PassDirectionStats = Field(default_factory=PassDirectionStats)

    @model_validator(mode="after")
    def length_bands_must_match_headline_passes(self) -> Self:
        """Reconcile short/medium/long splits with the headline pass counts."""

        locations = self.pass_locations
        band_total = locations.short.total + locations.medium.total + locations.long.total
        band_success = locations.short.success + locations.medium.success + locations.long.success
        if band_total or band_success:
            if band_total != self.passes.total:
                raise ValueError(
                    "short + medium + long pass totals must equal passes.total when a "
                    f"length split is provided ({band_total} != {self.passes.total})."
                )
            if band_success != self.passes.success:
                raise ValueError(
                    "short + medium + long pass successes must equal passes.success when a "
                    f"length split is provided ({band_success} != {self.passes.success})."
                )
        if self.crosses.total > self.passes.total:
            raise ValueError("crosses.total cannot exceed passes.total.")
        if self.cutbacks.total > self.passes.total:
            raise ValueError("cutbacks.total cannot exceed passes.total.")
        if self.progressive_passes.total > self.passes.total:
            raise ValueError("progressive_passes.total cannot exceed passes.total.")
        if self.pass_locations.into_penalty_area.total > self.passes.total:
            raise ValueError("passes into the penalty area cannot exceed passes.total.")
        if self.into_final_third.total > self.passes.total:
            raise ValueError("passes into the final third cannot exceed passes.total.")
        self._require_split_matches(
            (
                self.pass_thirds.defensive_third,
                self.pass_thirds.middle_third,
                self.pass_thirds.final_third,
            ),
            label="third split",
        )
        self._require_split_matches(
            (
                self.pass_directions.forward,
                self.pass_directions.sideways,
                self.pass_directions.backward,
            ),
            label="direction split",
        )
        return self

    def _require_split_matches(self, parts: tuple[AttemptSplit, ...], *, label: str) -> None:
        """When a split is populated, require it to reconcile with ``passes``."""

        split_total = sum(part.total for part in parts)
        split_success = sum(part.success for part in parts)
        if split_total or split_success:
            if split_total != self.passes.total:
                raise ValueError(
                    f"{label} totals must equal passes.total when provided "
                    f"({split_total} != {self.passes.total})."
                )
            if split_success != self.passes.success:
                raise ValueError(
                    f"{label} successes must equal passes.success when provided "
                    f"({split_success} != {self.passes.success})."
                )

    def record_pass(
        self,
        *,
        succeeded: bool,
        band: str,
        into_penalty_area: bool = False,
        is_cross: bool = False,
        is_cutback: bool = False,
        is_progressive: bool = False,
        start_third: str | None = None,
        into_final_third: bool = False,
        direction: str | None = None,
    ) -> DistributionStats:
        """Return a copy with one pass applied to headline and location splits.

        Args:
            succeeded: Whether the pass reached a teammate.
            band: Length band ``\"short\"``, ``\"medium\"``, or ``\"long\"``.
            into_penalty_area: Whether the end point is inside the attacking box.
            is_cross: Whether the pass is also tagged as a cross.
            is_cutback: Whether the pass is also tagged as a cutback.
            is_progressive: Whether the pass is tagged as progressive.
            start_third: ``\"defensive\"``, ``\"middle\"``, or ``\"final\"`` when known.
            into_final_third: Whether the pass entered the final third.
            direction: ``\"forward\"``, ``\"sideways\"``, or ``\"backward\"`` when known.
        """

        updates: dict[str, object] = {
            "passes": self.passes.add(succeeded=succeeded),
            "crosses": self.crosses.add(succeeded=succeeded) if is_cross else self.crosses,
            "cutbacks": self.cutbacks.add(succeeded=succeeded) if is_cutback else self.cutbacks,
            "progressive_passes": (
                self.progressive_passes.add(succeeded=succeeded)
                if is_progressive
                else self.progressive_passes
            ),
            "pass_locations": self.pass_locations.record(
                band=band,
                succeeded=succeeded,
                into_penalty_area=into_penalty_area,
            ),
        }
        if start_third is not None:
            updates["pass_thirds"] = self.pass_thirds.record(start_third, succeeded=succeeded)
        if into_final_third:
            updates["into_final_third"] = self.into_final_third.add(succeeded=succeeded)
        if direction is not None:
            updates["pass_directions"] = self.pass_directions.record(direction, succeeded=succeeded)
        return self.model_copy(update=updates)


class PossessionStats(StrictModel):
    """On-ball time and share of possession for a player in a single match.

    Attributes:
        time_minutes: Minutes the player (or their team while they played)
            spent in possession.
        percentage: Possession share in ``[0, 100]``.
    """

    time_minutes: float = Field(
        default=0.0,
        ge=0.0,
        le=150.0,
        description="Minutes in possession.",
    )
    percentage: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Possession share as a percentage.",
    )

    @field_validator("time_minutes", "percentage")
    @classmethod
    def one_decimal(cls, value: float) -> float:
        """Store possession clocks at one decimal place."""

        return round(value, 1)


class PlayerMatchStats(StrictModel):
    """Complete player-match statistical profile across the three pillars.

    Attributes:
        stats_id: Stable identifier for this stats row.
        match_id: Match the row belongs to.
        player_id: Player the row belongs to.
        team_id: Team the player represented in the match.
        jersey_number: Shirt number worn in the match, if known.
        player_name: Display name used on the dashboard.
        position: Primary position code (e.g. ``CB``, ``CM``, ``ST``).
        offensive: Flattened attacking metrics.
        defensive: Nested defensive metrics.
        distribution: Nested passing metrics.
        possession: On-ball time and possession share.
        collected_at: UTC timestamp when the row was last written.
    """

    stats_id: UUID = Field(default_factory=uuid4)
    match_id: UUID
    player_id: UUID
    team_id: UUID
    jersey_number: int | None = Field(default=None, ge=1, le=99)
    player_name: str = Field(default="", max_length=80, description="Player display name.")
    position: str = Field(default="", max_length=8, description="Primary position code.")
    offensive: OffensiveStats = Field(default_factory=OffensiveStats)
    defensive: DefensiveStats = Field(default_factory=DefensiveStats)
    distribution: DistributionStats = Field(default_factory=DistributionStats)
    possession: PossessionStats = Field(default_factory=PossessionStats)
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("position")
    @classmethod
    def normalize_position(cls, value: str) -> str:
        """Upper-case compact position codes."""

        return value.strip().upper()

    def replace_pillars(
        self,
        *,
        offensive: OffensiveStats | None = None,
        defensive: DefensiveStats | None = None,
        distribution: DistributionStats | None = None,
        possession: PossessionStats | None = None,
    ) -> PlayerMatchStats:
        """Return a copy with any supplied pillars replaced and timestamp refreshed.

        Args:
            offensive: Replacement attacking block, if any.
            defensive: Replacement defensive block, if any.
            distribution: Replacement passing block, if any.
            possession: Replacement possession block, if any.
        """

        return self.model_copy(
            update={
                "offensive": offensive if offensive is not None else self.offensive,
                "defensive": defensive if defensive is not None else self.defensive,
                "distribution": distribution if distribution is not None else self.distribution,
                "possession": possession if possession is not None else self.possession,
                "collected_at": datetime.now(timezone.utc),
            }
        )


class PlayerMatchProfile(PlayerMatchStats):
    """Persistence-facing player-match profile used by the storage layer.

    The schema is identical to :class:`PlayerMatchStats`. The dedicated name
    exists so database adapters can depend on a stable persistence type while
    collectors continue to emit the in-memory stats object (a compatible
    subclass instance).
    """

    @classmethod
    def from_stats(cls, stats: PlayerMatchStats) -> PlayerMatchProfile:
        """Build a profile from an in-memory :class:`PlayerMatchStats` row.

        Args:
            stats: Collector snapshot across the three statistical pillars.

        Returns:
            A :class:`PlayerMatchProfile` with the same field values.
        """

        if isinstance(stats, cls):
            return stats
        return cls(
            stats_id=stats.stats_id,
            match_id=stats.match_id,
            player_id=stats.player_id,
            team_id=stats.team_id,
            jersey_number=stats.jersey_number,
            player_name=stats.player_name,
            position=stats.position,
            offensive=stats.offensive,
            defensive=stats.defensive,
            distribution=stats.distribution,
            possession=stats.possession,
            collected_at=stats.collected_at,
        )
