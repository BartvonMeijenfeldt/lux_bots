from __future__ import annotations
from typing import TYPE_CHECKING
from dataclasses import dataclass, field

# from objects.actors.factory import Factory
from objects.coordinate import TimeCoordinate
from objects.actions.action_plan import ActionPlan
from objects.actions.factory_action import FactoryAction, BuildAction

if TYPE_CHECKING:
    from objects.actors.factory import Factory
    from objects.game_state import GameState


@dataclass
class FactoryActionPlan(ActionPlan):
    actor: Factory
    actions: list[FactoryAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        # TODO allow for multiple actions
        assert len(self.actions) <= 1

    def actor_can_carry_out_plan(self, game_state: GameState) -> bool:
        return self.actor_has_enough_resources(game_state)

    def actor_has_enough_resources(self, game_state: GameState) -> bool:
        return self.actor_has_enough_power and self.actor_has_enough_metal and self.actor_has_enough_water(game_state)

    @property
    def actor_has_enough_power(self) -> bool:
        power_requested = sum(action.requested_power for action in self.actions)
        return power_requested <= self.actor.power

    @property
    def actor_has_enough_metal(self) -> bool:
        metal_requested = sum(action.metal_cost for action in self.actions)
        return metal_requested <= self.actor.cargo.metal

    def actor_has_enough_water(self, game_state: GameState) -> bool:
        power_requested = sum(action.get_water_cost(game_state, self.actor.strain_id) for action in self.actions)
        return power_requested <= self.actor.cargo.water

    @property
    def time_coordinates(self) -> set[TimeCoordinate]:
        return {
            TimeCoordinate(*self.actor.center_tc.xy, t)
            for t, action in enumerate(self.actions, start=self.actor.center_tc.t + 1)
            if isinstance(action, BuildAction)
        }

    def to_lux_output(self):
        if not self.actions:
            return None

        return self.actions[0].to_lux_output()