from __future__ import annotations
from typing import TYPE_CHECKING, Sequence

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from math import ceil

from search import Search, MoveToGraph, FleeToGraph, DigAtGraph, PickupPowerGraph, Graph
from objects.actions.unit_action import DigAction, TransferAction
from objects.actions.unit_action_plan import UnitActionPlan
from objects.direction import Direction
from objects.resource import Resource
from objects.coordinate import (
    PowerTimeCoordinate,
    DigCoordinate,
    DigTimeCoordinate,
    TimeCoordinate,
    Coordinate,
    CoordinateList,
)
from logic.constraints import Constraints
from logic.goals.goal import Goal


if TYPE_CHECKING:
    from objects.actors.unit import Unit
    from objects.game_state import GameState
    from objects.board import Board
    from objects.actions.unit_action import UnitAction


@dataclass
class UnitGoal(Goal):
    unit: Unit

    _value: Optional[float] = field(init=False, default=None)
    _is_valid: Optional[bool] = field(init=False, default=None)
    solution_hash: dict[str, UnitActionPlan] = field(init=False, default_factory=dict)

    def generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        if constraints is None:
            constraints = Constraints()

        if constraints.key in self.solution_hash:
            return self.solution_hash[constraints.key]

        if constraints.parent in self.solution_hash:
            parent_solution = self.solution_hash[constraints.parent]
            if self._parent_solution_is_valid(parent_solution, constraints):
                self.solution_hash[constraints.key] = parent_solution
                return parent_solution

        action_plan = self._generate_action_plan(game_state, constraints=constraints)
        self.solution_hash[constraints.key] = action_plan
        return action_plan

    def _parent_solution_is_valid(self, parent_solution: UnitActionPlan, constraints: Constraints) -> bool:
        for tc in parent_solution.time_coordinates:
            if constraints.tc_violates_constraint(tc):
                return False

        if constraints.max_power_request is not None:
            if parent_solution.power_requested > constraints.max_power_request:
                return False

        return True

    @abstractmethod
    def _generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        ...

    @property
    def value(self) -> float:
        if self._value is None:
            raise ValueError("Value is not supposed to be None here")

        return self._value

    @property
    def is_valid(self) -> bool:
        if self._is_valid is None:
            raise ValueError("_is_valid is not supposed to be None here")

        return self._is_valid

    def _get_move_graph(self, board: Board, goal: Coordinate, constraints: Constraints) -> MoveToGraph:
        graph = MoveToGraph(
            board=board,
            time_to_power_cost=self.unit.time_to_power_cost,
            unit_cfg=self.unit.unit_cfg,
            goal=goal,
            constraints=constraints,
        )

        return graph

    def _get_recharge_graph(self, board: Board, recharge_amount: int, constraints: Constraints) -> PickupPowerGraph:
        graph = PickupPowerGraph(
            board=board,
            time_to_power_cost=self.unit.time_to_power_cost,
            unit_cfg=self.unit.unit_cfg,
            power_pickup_goal=recharge_amount,
            constraints=constraints,
        )

        return graph

    def _get_dig_graph(self, board: Board, goal: DigCoordinate, constraints: Constraints) -> DigAtGraph:
        graph = DigAtGraph(
            board=board,
            time_to_power_cost=self.unit.time_to_power_cost,
            unit_cfg=self.unit.unit_cfg,
            constraints=constraints,
            goal=goal,
        )

        return graph

    def _search_graph(self, graph: Graph, start: TimeCoordinate) -> list[UnitAction]:
        search = Search(graph=graph)
        optimal_actions = search.get_actions_to_complete_goal(start=start)
        return optimal_actions

    def _optional_add_power_pickup_action(self, game_state: GameState, constraints: Constraints) -> None:
        if constraints.max_power_request is not None and constraints.max_power_request < 10:
            return

        power_space_left = self.unit.power_space_left
        if not power_space_left:
            return

        closest_factory = game_state.get_closest_factory(c=self.unit.tc)
        if not closest_factory.is_on_factory(c=self.unit.tc):
            return

        power_in_factory = closest_factory.power
        power_to_pickup = min(power_space_left, power_in_factory)

        if self.unit.power and power_to_pickup / self.unit.power < 0.1:
            return

        graph = self._get_recharge_graph(
            board=game_state.board, recharge_amount=power_to_pickup, constraints=constraints
        )

        recharge_tc = PowerTimeCoordinate(*self.action_plan.final_tc, p=0)
        new_actions = self._search_graph(graph=graph, start=recharge_tc)
        potential_action_plan = self.action_plan + new_actions
        if potential_action_plan.unit_has_enough_power(game_state):
            self.action_plan.extend(new_actions)

    def _get_move_to_plan(
        self, start_tc: TimeCoordinate, goal: Coordinate, constraints: Constraints, board: Board,
    ) -> list[UnitAction]:

        graph = self._get_move_graph(board=board, goal=goal, constraints=constraints)
        actions = self._search_graph(graph=graph, start=start_tc)
        return actions

    def _get_dig_plan(
        self, start_tc: TimeCoordinate, dig_c: Coordinate, nr_digs: int, constraints: Constraints, board: Board,
    ) -> list[UnitAction]:
        if constraints.has_time_constraints:
            return self._get_dig_plan_with_constraints(start_tc, dig_c, nr_digs, constraints, board)

        return self._get_dig_plan_wihout_constraints(start_tc, dig_c, nr_digs, board)

    def _get_dig_plan_with_constraints(
        self, start_tc: TimeCoordinate, dig_c: Coordinate, nr_digs: int, constraints: Constraints, board: Board
    ) -> list[UnitAction]:

        start_dtc = DigTimeCoordinate(*start_tc, d=0)
        dig_coordinate = DigCoordinate(x=dig_c.x, y=dig_c.y, d=nr_digs)

        graph = self._get_dig_graph(board=board, goal=dig_coordinate, constraints=constraints)
        actions = self._search_graph(graph=graph, start=start_dtc)
        return actions

    def _get_dig_plan_wihout_constraints(
        self, start_tc: TimeCoordinate, dig_c: Coordinate, nr_digs: int, board: Board
    ) -> list[UnitAction]:
        move_to_actions = self._get_move_to_plan(start_tc, goal=dig_c, constraints=Constraints(), board=board)
        dig_actions = [DigAction(n=1)] * nr_digs
        return move_to_actions + dig_actions

    def _get_valid_actions(self, actions: list[UnitAction], game_state: GameState) -> list[UnitAction]:
        potential_action_plan = self.action_plan + actions
        nr_valid_primitive_actions = potential_action_plan.get_nr_valid_primitive_actions(game_state)
        nr_original_primitive_actions = len(self.action_plan.primitive_actions)
        return potential_action_plan.primitive_actions[nr_original_primitive_actions:nr_valid_primitive_actions]

    def find_max_dig_actions_can_still_reach_factory(
        self, actions: Sequence[UnitAction], game_state: GameState, constraints: Constraints
    ) -> list[UnitAction]:
        # TODO, see if when we first start with the upper limit, if that were to improve the speed

        low = 0
        high = self._get_nr_digs_in_actions(actions)

        while low < high:
            mid = (high + low) // 2
            if mid == low:
                mid += 1

            potential_actions = self._get_actions_up_to_n_digs(actions, mid)
            potential_action_plan = self.action_plan + potential_actions

            if self._unit_can_still_reach_factory(potential_action_plan, game_state, constraints):
                low = mid
            else:
                high = mid - 1

        actions = self._get_actions_up_to_n_digs(actions, low)
        return actions

    def _get_nr_digs_in_actions(self, actions: Sequence[UnitAction]) -> int:
        return sum(dig_action.n for dig_action in actions if isinstance(dig_action, DigAction))

    def _get_actions_up_to_n_digs(self, actions: Sequence[UnitAction], n: int) -> list[UnitAction]:
        if n == 0:
            return []

        return_actions = []
        nr_added_actions = 0
        for action in actions:
            return_actions.append(action)

            if isinstance(action, DigAction):
                nr_added_actions += 1
                if nr_added_actions == n:
                    return return_actions

        raise ValueError(f"Only found {nr_added_actions}, of the required {n} actions")

    def _unit_can_still_reach_factory(
        self, action_plan: UnitActionPlan, game_state: GameState, constraints: Constraints
    ) -> bool:
        return action_plan.unit_can_add_reach_factory_to_plan(
            game_state=game_state, constraints=constraints
        ) or action_plan.unit_can_reach_factory_after_action_plan(game_state=game_state, constraints=constraints)

    def _init_action_plan(self) -> None:
        self.action_plan = UnitActionPlan(actor=self.unit)

    def _get_cost_plan(self, action_plan: UnitActionPlan, game_state: GameState) -> float:
        number_of_steps = len(action_plan)
        power_cost = action_plan.get_power_used(board=game_state.board)
        total_cost = number_of_steps * self.unit.time_to_power_cost + power_cost
        return total_cost

    def __lt__(self, other: UnitGoal):
        return self.value < other.value


@dataclass
class CollectGoal(UnitGoal):
    resource_c: Coordinate
    factory_c: Coordinate
    quantity: Optional[int] = None
    resource: Resource = field(init=False)

    def _generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        if constraints is None:
            constraints = Constraints()

        self._is_valid = True
        self._init_action_plan()
        self._optional_add_power_pickup_action(game_state=game_state, constraints=constraints)
        self._add_dig_actions(game_state=game_state, constraints=constraints)
        self._add_ice_to_factory_actions(board=game_state.board, constraints=constraints)
        self._add_transfer_action()
        return self.action_plan

    def _get_transfer_action(self) -> TransferAction:
        max_cargo = self.unit.unit_cfg.CARGO_SPACE
        return TransferAction(direction=Direction.CENTER, amount=max_cargo, resource=Resource.Ice)

    def _add_dig_actions(self, game_state: GameState, constraints: Constraints) -> None:
        max_nr_digs = self._get_max_nr_digs(game_state)
        actions_max_nr_digs = self._get_dig_plan(
            start_tc=self.action_plan.final_tc,
            dig_c=self.resource_c,
            nr_digs=max_nr_digs,
            constraints=constraints,
            board=game_state.board,
        )

        max_valid_dig_actions = self._get_valid_actions(actions_max_nr_digs, game_state)
        max_valid_digs_actions = self.find_max_dig_actions_can_still_reach_factory(
            max_valid_dig_actions, game_state, constraints
        )

        if len(max_valid_digs_actions) == 0:
            self._is_valid = False
        else:
            self.action_plan.extend(max_valid_digs_actions)

    def _get_max_nr_digs(self, game_state: GameState) -> int:
        cur_power = self.action_plan.get_final_ptc(game_state).p
        dig_power_cost = self.unit.dig_power_cost
        recharge_power = self.unit.recharge_power
        min_power_change_per_dig = dig_power_cost - recharge_power

        quotient, remainder = divmod(cur_power, min_power_change_per_dig)
        if remainder >= recharge_power:
            max_nr_digs = quotient
        else:
            max_nr_digs = max(0, quotient - 1)

        return max_nr_digs

    def _add_ice_to_factory_actions(self, board: Board, constraints: Constraints) -> None:
        actions = self._get_move_to_factory_actions(board=board, constraints=constraints)
        self.action_plan.extend(actions=actions)

    def _get_move_to_factory_actions(self, board: Board, constraints: Constraints) -> list[UnitAction]:
        # TODO, this should move to any Factory tile not a specific tile
        return self._get_move_to_plan(
            start_tc=self.action_plan.final_tc, goal=self.factory_c, constraints=constraints, board=board
        )

    def _add_transfer_action(self) -> None:
        max_cargo = self.unit.unit_cfg.CARGO_SPACE
        transfer_action = TransferAction(direction=Direction.CENTER, amount=max_cargo, resource=self.resource)
        self.action_plan.append(transfer_action)

    def get_value_action_plan(self, action_plan: UnitActionPlan, game_state: GameState) -> float:
        number_of_digs = action_plan.nr_digs
        total_cost = self._get_cost_plan(action_plan, game_state)
        return 100 * number_of_digs / total_cost


@dataclass
class CollectIceGoal(CollectGoal):
    resource = Resource.Ice

    def __repr__(self) -> str:
        return f"collect_ice_[{self.resource_c}]"

    @property
    def key(self) -> str:
        return str(self)


@dataclass
class CollectOreGoal(CollectGoal):
    resource = Resource.Ore

    def __repr__(self) -> str:
        return f"collect_ore_[{self.resource_c}]"

    @property
    def key(self) -> str:
        return str(self)


@dataclass
class ClearRubbleGoal(UnitGoal):
    rubble_positions: CoordinateList

    def __repr__(self) -> str:
        first_rubble_c = self.rubble_positions[0]
        return f"clear_rubble_[{first_rubble_c}]"

    @property
    def key(self) -> str:
        return str(self)

    def _generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        self._init_action_plan()
        self._optional_add_power_pickup_action(game_state=game_state, constraints=constraints)
        self._add_clear_initial_rubble_actions(game_state=game_state, constraints=constraints)
        # self._add_additional_rubble_actions(game_state=game_state, constraints=constraints)
        self._optional_add_go_to_factory_actions(game_state=game_state, constraints=constraints)
        return self.action_plan

    def _add_clear_initial_rubble_actions(self, game_state: GameState, constraints: Constraints) -> None:
        for rubble_c in self.rubble_positions:
            nr_required_digs = self._get_nr_required_digs(rubble_c=rubble_c, board=game_state.board)

            potential_dig_actions = self._get_dig_plan(
                start_tc=self.action_plan.final_tc,
                dig_c=rubble_c,
                nr_digs=nr_required_digs,
                constraints=constraints,
                board=game_state.board,
            )

            potential_dig_actions = self._get_valid_actions(potential_dig_actions, game_state)

            max_valid_digs_actions = self.find_max_dig_actions_can_still_reach_factory(
                potential_dig_actions, game_state, constraints
            )

            if len(max_valid_digs_actions) == 0:
                self._is_valid = False
                return
            else:
                self.action_plan.extend(max_valid_digs_actions)

        self._is_valid = True

    def _get_nr_required_digs(self, rubble_c: Coordinate, board: Board) -> int:

        rubble_at_pos = board.rubble[rubble_c.xy]
        nr_required_digs = ceil(rubble_at_pos / self.unit.unit_cfg.DIG_RUBBLE_REMOVED)
        return nr_required_digs

    # def _add_additional_rubble_actions(self, game_state: GameState, constraints: Constraints):
    #     if len(self.action_plan.actions) == 0 or not isinstance(self.action_plan.actions[-1], DigAction):
    #         return

    #     while True:
    #         closest_rubble = game_state.board.get_closest_rubble_tile(self.cur_tc, exclude_c=self.rubble_positions)
    #         dig_time_coordinate = DigTimeCoordinate(*self.cur_tc, d=0)
    #         potential_dig_rubble_actions = self._get_dig_plan(
    #             start_tc=dig_time_coordinate, dig_c=closest_rubble, board=game_state.board, constraints=constraints
    #         )

    #         potential_action_plan = self.action_plan + potential_dig_rubble_actions

    #         if potential_action_plan.unit_can_carry_out_plan(
    #             game_state=game_state
    #         ) and self._unit_can_still_reach_factory(
    #             action_plan=potential_action_plan, game_state=game_state, constraints=constraints
    #         ):
    #             self.action_plan.extend(potential_dig_rubble_actions)
    #             self.rubble_positions.append(c=closest_rubble)
    #             self.cur_tc = self.action_plan.final_tc
    #         else:
    #             return

    def _optional_add_go_to_factory_actions(self, game_state: GameState, constraints: Constraints) -> None:
        closest_factory_c = game_state.get_closest_factory_c(c=self.action_plan.final_tc)
        graph = self._get_move_graph(board=game_state.board, goal=closest_factory_c, constraints=constraints)
        potential_move_actions = self._search_graph(graph=graph, start=self.action_plan.final_tc)

        potential_action_plan = self.action_plan + potential_move_actions

        if potential_action_plan.actor_can_carry_out_plan(game_state=game_state):
            self.action_plan.extend(potential_move_actions)

    def get_value_action_plan(self, action_plan: UnitActionPlan, game_state: GameState) -> float:
        number_of_steps = len(action_plan)
        if number_of_steps == 0:
            return -10000000000

        number_of_digs = action_plan.nr_digs
        total_cost = self._get_cost_plan(action_plan, game_state)

        return 100 * number_of_digs / total_cost


@dataclass
class FleeGoal(UnitGoal):
    opp_c: Coordinate
    _is_valid = True

    def _generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        self._init_action_plan()
        self._go_to_factory_actions(game_state, constraints)

        return self.action_plan

    def _go_to_factory_actions(self, game_state: GameState, constraints: Constraints) -> None:
        closest_factory_c = game_state.get_closest_factory_c(c=self.action_plan.final_tc)
        graph = self._get_flee_to_graph(board=game_state.board, goal=closest_factory_c, constraints=constraints)
        potential_move_actions = self._search_graph(graph=graph, start=self.action_plan.final_tc)
        potential_move_actions = self._get_valid_actions(potential_move_actions, game_state)

        while potential_move_actions:
            potential_action_plan = self.action_plan + potential_move_actions

            if potential_action_plan.is_valid_size:
                self.action_plan.extend(potential_move_actions)
                self.cur_tc = self.action_plan.final_tc
                break

            potential_move_actions = potential_move_actions[:-1]
        else:
            self._is_valid = False
            return

    def _get_flee_to_graph(self, board: Board, goal: Coordinate, constraints: Constraints) -> FleeToGraph:
        graph = FleeToGraph(
            board=board,
            time_to_power_cost=self.unit.time_to_power_cost,
            unit_cfg=self.unit.unit_cfg,
            goal=goal,
            start_c=self.unit.tc,
            opp_c=self.opp_c,
            constraints=constraints,
        )

        return graph

    def get_value_action_plan(self, action_plan: UnitActionPlan, game_state: GameState) -> float:
        return 1000

    def __repr__(self) -> str:
        return f"Flee_Goal_{self.unit.unit_id}"

    @property
    def key(self) -> str:
        return str(self)


@dataclass
class ActionQueueGoal(UnitGoal):
    """Goal currently in action queue"""

    goal: UnitGoal
    action_plan: UnitActionPlan
    _is_valid = True

    def _generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        # TODO add something to generation infeasible if it violates constraints
        return self.action_plan

    def get_value_action_plan(self, action_plan: UnitActionPlan, game_state: GameState) -> float:
        if self.unit.is_under_threath(game_state) and action_plan.actions[0].is_stationary:
            return -1000

        value_including_update_cost = self.goal.get_value_action_plan(self.action_plan, game_state)
        return value_including_update_cost + 100_000
        # return value_including_update_cost + self.unit.unit_cfg.ACTION_QUEUE_POWER_COST

    @property
    def key(self) -> str:
        # This will cause trouble when we allow goal switching, those goals will have the same ID
        # Can probably be solved by just picking the highest one / returning highest one by the goal collection
        return self.goal.key


class UnitNoGoal(UnitGoal):
    _value = None
    _is_valid = True

    def _generate_action_plan(self, game_state: GameState, constraints: Constraints) -> UnitActionPlan:
        self._init_action_plan()
        return self.action_plan

    def get_value_action_plan(self, action_plan: UnitActionPlan, game_state: GameState) -> float:
        return 0.0

    def __repr__(self) -> str:
        return f"No_Goal_Unit_{self.unit.unit_id}"

    @property
    def key(self) -> str:
        return str(self)