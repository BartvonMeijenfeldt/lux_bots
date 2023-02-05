from __future__ import annotations
from typing import TYPE_CHECKING

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from math import ceil

from search import get_actions_a_to_b, PowerCostGraph
from objects.action import Action, DigAction, MoveAction, TransferAction, PickupAction
from objects.action_plan import ActionPlan
from objects.coordinate import Direction
from objects.resource import Resource

if TYPE_CHECKING:
    from objects.unit import Unit
    from objects.game_state import GameState
    from objects.board import Board
    from objects.coordinate import Coordinate, CoordinateList


@dataclass(kw_only=True)
class Goal(metaclass=ABCMeta):
    unit: Unit

    action_plan: ActionPlan = field(init=False)
    _value: Optional[float] = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.action_plan = self._init_action_plan()

    def generate_and_evaluate_action_plan(self, game_state: GameState) -> None:
        self.generate_action_plan(game_state=game_state)
        self._value = self.get_value_action_plan(action_plan=self.action_plan, game_state=game_state)

    @abstractmethod
    def generate_action_plan(self, game_state: GameState) -> None:
        ...

    @abstractmethod
    def get_value_action_plan(self, action_plan: ActionPlan, game_state: GameState) -> float:
        ...

    @property
    def value(self) -> float:
        if self._value is None:
            raise ValueError("Value is not supposed to be None here")

        return self._value

    @property
    def __eq__(self, other: "Goal") -> bool:
        self.value < other.value

    def _add_power_pickup_action(self, game_state: GameState) -> list[PickupAction]:
        power_space_left = self.unit.power_space_left
        closest_factory = game_state.get_closest_factory(c=self.unit.c)

        if closest_factory.is_on_factory(c=self.unit.c):
            power_in_factory = closest_factory.power
            cargo_to_pickup = min(power_space_left, power_in_factory)
            self.action_plan.append(PickupAction(cargo_to_pickup, Resource.Power))

    def _init_action_plan(self) -> None:
        self.action_plan = ActionPlan(unit=self.unit)

    def __lt__(self, other: Goal):
        return self.value < other.value


@dataclass
class CollectIceGoal(Goal):
    ice_c: Coordinate
    factory_pos: Coordinate
    quantity: Optional[int] = None

    def generate_action_plan(self, game_state: GameState) -> None:
        self.graph = PowerCostGraph(game_state.board, time_to_power_cost=20)
        self._init_action_plan()
        self._add_power_pickup_action(game_state=game_state)
        self._add_pos_to_ice_actions()
        self._add_max_dig_action(game_state=game_state)
        self._add_ice_to_factory_actions()
        self._add_transfer_action()

    def _add_pos_to_ice_actions(self) -> None:
        actions = get_actions_a_to_b(graph=self.graph, start=self.unit.c, end=self.ice_c)
        self.action_plan.extend(actions=actions)

    def _add_ice_to_factory_actions(self) -> None:
        actions = self._get_ice_to_factory_actions()
        self.action_plan.extend(actions=actions)

    def _get_ice_to_factory_actions(self) -> list[MoveAction]:
        return get_actions_a_to_b(graph=self.graph, start=self.ice_c, end=self.factory_pos)

    def _add_transfer_action(self) -> None:
        max_cargo = self.unit.unit_cfg.CARGO_SPACE
        transfer_action = TransferAction(direction=Direction.CENTER, amount=max_cargo, resource=Resource.Ice)
        self.action_plan.append(transfer_action)

    def _get_transfer_action(self) -> TransferAction:
        max_cargo = self.unit.unit_cfg.CARGO_SPACE
        return TransferAction(direction=Direction.CENTER, amount=max_cargo, resource=Resource.Ice)

    def _get_actions_after_digging(self) -> list[Action]:
        ice_to_factory_actions = self._get_ice_to_factory_actions()
        transfer_action = self._get_transfer_action()
        return ice_to_factory_actions + [transfer_action]

    def _add_max_dig_action(self, game_state: GameState) -> None:
        # TODO make this a binary search or something otherwise more efficient
        best_n = None
        n_digging = 0

        actions_after_digging = self._get_actions_after_digging()

        while True:
            potential_dig_action = DigAction(n=n_digging)
            new_actions = [potential_dig_action] + actions_after_digging
            potential_action_plan = self.action_plan + new_actions
            if not potential_action_plan.unit_can_carry_out_plan(game_state=game_state):
                break

            best_n = n_digging
            n_digging += 1

        if best_n:
            potential_dig_action = DigAction(n=best_n)
            self.action_plan.append(DigAction(n=best_n))

    def get_value_action_plan(self, action_plan: ActionPlan, game_state: GameState) -> float:
        number_of_steps = len(action_plan)
        power_cost = action_plan.get_power_used(board=game_state.board)
        return number_of_steps + 0.1 * power_cost


@dataclass
class ClearRubbleGoal(Goal):
    rubble_positions: CoordinateList

    def generate_action_plan(self, game_state: GameState) -> ActionPlan:
        self.graph = PowerCostGraph(game_state.board, time_to_power_cost=20)
        self._init_action_plan()
        self._add_power_pickup_action(game_state=game_state)
        self._add_clear_initial_rubble_actions(game_state=game_state)
        self._add_additional_rubble_actions(game_state=game_state)
        self._optional_add_go_to_factory_actions(game_state=game_state)

    def _add_clear_initial_rubble_actions(self, game_state: GameState) -> None:
        self.cur_c = self.unit.c

        for rubble_c in self.rubble_positions:
            potential_dig_rubble_actions = self._get_rubble_actions(
                start_c=self.cur_c, rubble_c=rubble_c, board=game_state.board
            )
            potential_action_plan = self.action_plan + potential_dig_rubble_actions

            if not potential_action_plan.unit_can_carry_out_plan(game_state=game_state):
                return

            if self._unit_can_still_reach_factory(action_plan=potential_action_plan, game_state=game_state):
                self.action_plan.extend(potential_dig_rubble_actions)
                self.cur_c = rubble_c
            else:
                return

    def _unit_can_still_reach_factory(self, action_plan: ActionPlan, game_state: GameState) -> bool:
        return action_plan.unit_can_add_reach_factory_to_plan(
            game_state=game_state, graph=self.graph
        ) or action_plan.unit_can_reach_factory_after_action_plan(game_state=game_state, graph=self.graph)

    def _get_rubble_actions(self, start_c: Coordinate, rubble_c: Coordinate, board: Board) -> list[Action]:
        pos_to_rubble_actions = get_actions_a_to_b(graph=self.graph, start=start_c, end=rubble_c)

        rubble_at_pos = board.rubble[tuple(rubble_c)]
        nr_required_digs = ceil(rubble_at_pos / self.unit.unit_cfg.DIG_RUBBLE_REMOVED)
        dig_action = [DigAction(n=nr_required_digs)]

        actions = pos_to_rubble_actions + dig_action
        return actions

    def _add_additional_rubble_actions(self, game_state: GameState) -> list[Action]:
        while True:
            closest_rubble = game_state.board.get_closest_rubble_tile(self.cur_c, exclude_c=self.rubble_positions)
            potential_dig_rubble_actions = self._get_rubble_actions(
                start_c=self.cur_c, rubble_c=closest_rubble, board=game_state.board
            )

            potential_action_plan = self.action_plan + potential_dig_rubble_actions

            if not potential_action_plan.unit_can_carry_out_plan(game_state=game_state):
                return

            if self._unit_can_still_reach_factory(action_plan=potential_action_plan, game_state=game_state):
                self.action_plan.extend(potential_dig_rubble_actions)
                self.rubble_positions.append(c=closest_rubble)
                self.cur_c = closest_rubble
            else:
                return

    def _optional_add_go_to_factory_actions(self, game_state: GameState) -> None:
        closest_factory_c = game_state.get_closest_factory_c(c=self.cur_c)
        potential_rubble_to_factory_actions = get_actions_a_to_b(self.graph, start=self.cur_c, end=closest_factory_c)
        potential_action_plan = self.action_plan + potential_rubble_to_factory_actions

        if potential_action_plan.unit_can_carry_out_plan(game_state=game_state):
            self.action_plan.extend(potential_rubble_to_factory_actions)

    def get_value_action_plan(self, action_plan: ActionPlan, game_state: GameState) -> float:
        number_of_steps = len(action_plan)
        power_cost = action_plan.get_power_used(board=game_state.board)
        number_of_rubble_cleared = len(self.rubble_positions)
        rubble_cleared_per_step = number_of_rubble_cleared / number_of_steps
        rubble_cleared_per_power = number_of_rubble_cleared / power_cost
        return rubble_cleared_per_step + rubble_cleared_per_power


@dataclass
class GoalCollection:
    goals: list[Goal]

    def generate_and_evaluate_action_plans(self, game_state: GameState) -> None:
        for goal in self.goals:
            goal.generate_and_evaluate_action_plan(game_state=game_state)

    @property
    def best_action_plan(self) -> ActionPlan:
        best_goal = max(self.goals)
        return best_goal.action_plan
