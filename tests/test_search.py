import unittest

from typing import Optional, Sequence

from logic.constraints import Constraints
from objects.coordinate import (
    Coordinate as C,
    DigCoordinate as DC,
    DigTimeCoordinate as DTC,
    TimeCoordinate as TC,
    PowerTimeCoordinate as PTC,
)
from objects.actions.unit_action import MoveAction as MA, UnitAction, DigAction as DA, PickupAction as PA
from objects.direction import Direction as D
from objects.resource import Resource
from search.search import PickupPowerGraph, DigAtGraph, MoveToGraph, Search
from lux.kit import GameState
from lux.config import EnvConfig
from tests.generate_game_state import get_state, FactoryPositions, UnitPos, Tiles, RubbleTile as RT
from tests.init_constraints import init_constraints


ENV_CFG = EnvConfig()


class TestMoveToSearch(unittest.TestCase):
    def _test_move_to_search(
        self,
        state: GameState,
        start: TC,
        goal: C,
        expected_actions: Sequence[UnitAction],
        time_to_power_cost: float = 50,
        unit_type: str = "LIGHT",
        constraints: Optional[Constraints] = None,
    ):
        if constraints is None:
            constraints = Constraints()

        expected_actions = list(expected_actions)

        unit_cfg = ENV_CFG.ROBOTS[unit_type]

        move_to_graph = MoveToGraph(
            board=state.board,
            time_to_power_cost=time_to_power_cost,
            unit_cfg=unit_cfg,
            constraints=constraints,
            goal=goal,
        )
        search = Search(move_to_graph)
        actions = search.get_actions_to_complete_goal(start=start)
        self.assertEqual(actions, expected_actions)

    def test_already_there_path(self):
        start = TC(3, 3, 0)
        goal = C(3, 3)
        state = get_state(board_width=9)
        expected_actions = []

        self._test_move_to_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_one_down_path(self):

        start = TC(3, 2, 0)
        goal = C(3, 3)
        state = get_state(board_width=9)
        expected_actions = [MA(D.DOWN)]

        self._test_move_to_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_through_own_factory(self):

        start = TC(1, 3, 0)
        goal = C(1, 7)
        factory_positions = FactoryPositions(player=[UnitPos(2, 5)])
        expected_actions = [MA(D.DOWN)] * 4

        state = get_state(board_width=9, factory_positions=factory_positions)
        self._test_move_to_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_around_opponent_factory(self):
        start = TC(1, 3, 0)
        goal = C(1, 7)
        factory_positions = FactoryPositions(opp=[UnitPos(2, 5)])
        expected_actions = [MA(D.LEFT)] + [MA(D.DOWN)] * 4 + [MA(D.RIGHT)]

        state = get_state(board_width=9, factory_positions=factory_positions)

        self._test_move_to_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_through_the_rubble(self):
        start = TC(2, 2, 0)
        goal = C(5, 5)
        rubble_tiles = [RT(3, 2, 20), RT(2, 4, 20), RT(4, 3, 20), RT(3, 5, 20), RT(5, 4, 20)]

        tiles = Tiles(rubble=rubble_tiles)
        expected_actions = [MA(D.DOWN), MA(D.RIGHT)] * 3

        state = get_state(board_width=9, tiles=tiles)

        self._test_move_to_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_neg_constraint_wait_now(self):
        start = TC(2, 2, 0)
        goal = C(5, 2)
        constraints = init_constraints(negative_constraints=[TC(3, 2, 1)])
        expected_actions = [MA(D.CENTER), MA(D.RIGHT), MA(D.RIGHT), MA(D.RIGHT)]

        state = get_state(board_width=9)

        self._test_move_to_search(
            state=state, start=start, goal=goal, expected_actions=expected_actions, constraints=constraints
        )

    def test_neg_constraint_wait_in_3_steps(self):
        start = TC(2, 2, 0)
        goal = C(5, 2)
        constraints = init_constraints(negative_constraints=[TC(5, 2, 3)])

        expected_actions = [MA(D.RIGHT), MA(D.RIGHT), MA(D.CENTER), MA(D.RIGHT)]

        state = get_state(board_width=9)

        self._test_move_to_search(
            state=state, start=start, goal=goal, expected_actions=expected_actions, constraints=constraints
        )

    def test_low_time_to_power_cost_move_around_rubble(self):
        start = TC(2, 2, 0)
        goal = C(5, 2)
        time_to_power_cost = 3
        unit_type = "LIGHT"
        rubble_tiles = [RT(3, 2, 100), RT(4, 2, 100), RT(3, 3, 100)]
        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.UP), MA(D.RIGHT), MA(D.RIGHT), MA(D.RIGHT), MA(D.DOWN)]

        state = get_state(board_width=9, tiles=tiles)

        self._test_move_to_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )

    def test_high_time_to_power_cost_move_through_rubble(self):
        start = TC(2, 2, 0)
        goal = C(5, 2)
        time_to_power_cost = 5
        unit_type = "LIGHT"
        rubble_tiles = [RT(3, 2, 100), RT(4, 2, 100), RT(3, 3, 100)]
        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.RIGHT), MA(D.RIGHT), MA(D.RIGHT)]

        state = get_state(board_width=9, tiles=tiles)

        self._test_move_to_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )

    def test_low_time_to_power_cost_move_around_many_rubble(self):
        start = TC(2, 2, 0)
        goal = C(20, 2)
        time_to_power_cost = 41.499
        unit_type = "LIGHT"
        rubble_tiles = [RT(x, 2, 100) for x in range(2, 20)] + [RT(3, 3, 20)]

        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.UP)] + [MA(D.RIGHT)] * 18 + [MA(D.DOWN)]

        state = get_state(board_width=22, tiles=tiles)

        self._test_move_to_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )

    def test_high_time_to_power_cost_move_through_many_rubble(self):
        start = TC(2, 2, 0)
        goal = C(20, 2)
        time_to_power_cost = 41.501
        unit_type = "LIGHT"
        rubble_tiles = [RT(x, 2, 100) for x in range(2, 20)]
        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.RIGHT)] * 18

        state = get_state(board_width=22, tiles=tiles)

        self._test_move_to_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )


class DigAtSearch(unittest.TestCase):
    def _test_dig_at_search(
        self,
        state: GameState,
        start: DTC,
        goal: DC,
        expected_actions: Sequence[UnitAction],
        time_to_power_cost: float = 50,
        unit_type: str = "LIGHT",
        constraints: Optional[Constraints] = None,
    ):
        if constraints is None:
            constraints = Constraints()

        expected_actions = list(expected_actions)

        unit_cfg = ENV_CFG.ROBOTS[unit_type]

        move_to_graph = DigAtGraph(
            board=state.board,
            time_to_power_cost=time_to_power_cost,
            unit_cfg=unit_cfg,
            constraints=constraints,
            goal=goal,
        )
        search = Search(move_to_graph)
        actions = search.get_actions_to_complete_goal(start=start)
        self.assertEqual(actions, expected_actions)

    def test_already_there_path(self):
        start = DTC(3, 3, 0, 0)
        goal = DC(3, 3, 3)
        state = get_state(board_width=9)
        expected_actions = [DA()] * 3

        self._test_dig_at_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_one_down_path(self):
        start = DTC(3, 2, 0, 0)
        goal = DC(3, 3, 3)
        state = get_state(board_width=9)
        expected_actions = [MA(D.DOWN)] + [DA()] * 3

        self._test_dig_at_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_through_own_factory(self):
        start = DTC(1, 3, 0, 0)
        goal = DC(1, 7, 2)
        factory_positions = FactoryPositions(player=[UnitPos(2, 5)])
        expected_actions = [MA(D.DOWN)] * 4 + [DA()] * 2

        state = get_state(board_width=9, factory_positions=factory_positions)
        self._test_dig_at_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_around_opponent_factory(self):
        start = DTC(1, 3, 0, 0)
        goal = DC(1, 7, 2)
        factory_positions = FactoryPositions(opp=[UnitPos(2, 5)])

        expected_actions = [MA(D.LEFT)] + [MA(D.DOWN)] * 4 + [MA(D.RIGHT)] + [DA()] * 2

        state = get_state(board_width=9, factory_positions=factory_positions)

        self._test_dig_at_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_through_the_rubble(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 5, 3)
        rubble_tiles = [
            RT(3, 2, 20),
            RT(2, 4, 20),
            RT(4, 3, 20),
            RT(3, 5, 20),
            RT(5, 4, 20),
        ]

        tiles = Tiles(rubble=rubble_tiles)
        expected_actions = [MA(D.DOWN), MA(D.RIGHT)] * 3 + [DA()] * 3

        state = get_state(board_width=9, tiles=tiles)

        self._test_dig_at_search(state=state, start=start, goal=goal, expected_actions=expected_actions)

    def test_neg_constraint_wait_now(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 2, 3)
        constraints = init_constraints(negative_constraints=[TC(3, 2, 1)])

        expected_actions = [MA(D.CENTER)] + [MA(D.RIGHT)] * 3 + [DA()] * 3

        state = get_state(board_width=9)

        self._test_dig_at_search(
            state=state, start=start, goal=goal, expected_actions=expected_actions, constraints=constraints
        )

    def test_neg_constraint_wait_in_3_steps(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 2, 3)
        constraints = init_constraints(negative_constraints=[TC(5, 2, 3)])
        expected_actions = [MA(D.RIGHT), MA(D.RIGHT), MA(D.CENTER), MA(D.RIGHT)] + [DA()] * 3

        state = get_state(board_width=9)

        self._test_dig_at_search(
            state=state, start=start, goal=goal, expected_actions=expected_actions, constraints=constraints
        )

    def test_neg_constraint_at_first_dig_possibility(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 2, 3)
        constraints = init_constraints(negative_constraints=[TC(5, 2, 4)])
        expected_actions = [MA(D.RIGHT), MA(D.RIGHT), MA(D.CENTER), MA(D.CENTER), MA(D.RIGHT)] + [DA()] * 3

        state = get_state(board_width=9)

        self._test_dig_at_search(
            state=state, start=start, goal=goal, expected_actions=expected_actions, constraints=constraints
        )

    def test_neg_constraint_at_second_dig_possibility(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 2, 3)
        constraints = init_constraints(negative_constraints=[TC(5, 2, 5)])
        rubble_tiles = [RT(5, 1, 20), RT(5, 3, 20), RT(6, 2, 20)]
        tiles = Tiles(rubble=rubble_tiles)
        expected_actions = [MA(D.RIGHT)] * 3 + [DA(), MA(D.LEFT), MA(D.RIGHT)] + [DA()] * 2

        state = get_state(board_width=9, tiles=tiles)

        self._test_dig_at_search(
            state=state, start=start, goal=goal, expected_actions=expected_actions, constraints=constraints
        )

    def test_low_time_to_power_cost_move_around_rubble(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 2, 3)
        time_to_power_cost = 3
        unit_type = "LIGHT"
        rubble_tiles = [RT(3, 2, 100), RT(4, 2, 100), RT(3, 3, 100)]
        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.UP)] + [MA(D.RIGHT)] * 3 + [MA(D.DOWN)] + [DA()] * 3

        state = get_state(board_width=9, tiles=tiles)

        self._test_dig_at_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )

    def test_high_time_to_power_cost_move_through_rubble(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(5, 2, 3)
        time_to_power_cost = 5
        unit_type = "LIGHT"
        rubble_tiles = [RT(3, 2, 100), RT(4, 2, 100), RT(3, 3, 100)]
        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.RIGHT)] * 3 + [DA()] * 3

        state = get_state(board_width=9, tiles=tiles)

        self._test_dig_at_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )

    def test_low_time_to_power_cost_move_around_many_rubble(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(20, 2, 3)
        time_to_power_cost = 41.499
        unit_type = "LIGHT"
        rubble_tiles = [RT(x, 2, 100) for x in range(2, 20)] + [RT(3, 3, 20)]

        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.UP)] + [MA(D.RIGHT)] * 18 + [MA(D.DOWN)] + [DA()] * 3

        state = get_state(board_width=22, tiles=tiles)

        self._test_dig_at_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )

    def test_high_time_to_power_cost_move_through_many_rubble(self):
        start = DTC(2, 2, 0, 0)
        goal = DC(20, 2, 3)
        time_to_power_cost = 41.501
        unit_type = "LIGHT"
        rubble_tiles = [RT(x, 2, 100) for x in range(2, 20)]
        tiles = Tiles(rubble=rubble_tiles)

        expected_actions = [MA(D.RIGHT)] * 18 + [DA()] * 3

        state = get_state(board_width=22, tiles=tiles)

        self._test_dig_at_search(
            state=state,
            start=start,
            goal=goal,
            unit_type=unit_type,
            expected_actions=expected_actions,
            time_to_power_cost=time_to_power_cost,
        )


class TestPowerPickupSearch(unittest.TestCase):
    def _test_power_pickup_search(
        self,
        state: GameState,
        start: TC,
        power_pickup_goal: int,
        expected_actions: Sequence[UnitAction],
        next_goal_c: Optional[C] = None,
        time_to_power_cost: float = 50,
        unit_type: str = "LIGHT",
        constraints: Optional[Constraints] = None,
    ):
        if constraints is None:
            constraints = Constraints()

        expected_actions = list(expected_actions)

        start_ptc = PTC(*start, p=0)
        unit_cfg = ENV_CFG.ROBOTS[unit_type]

        move_to_graph = PickupPowerGraph(
            board=state.board,
            time_to_power_cost=time_to_power_cost,
            unit_cfg=unit_cfg,
            constraints=constraints,
            power_pickup_goal=power_pickup_goal,
            next_goal_c=next_goal_c,
        )
        search = Search(move_to_graph)
        actions = search.get_actions_to_complete_goal(start=start_ptc)
        self.assertEqual(actions, expected_actions)

    def test_already_there_path(self):
        start = TC(3, 3, 0)
        power_pickup_goal = 100
        factory_positions = FactoryPositions(player=[UnitPos(3, 3)])
        state = get_state(board_width=9, factory_positions=factory_positions)
        expected_actions = [PA(amount=power_pickup_goal, resource=Resource.Power)]

        self._test_power_pickup_search(
            state=state, start=start, power_pickup_goal=power_pickup_goal, expected_actions=expected_actions
        )

    def test_move_to_factory_path(self):
        start = TC(1, 3, 0)
        power_pickup_goal = 100
        factory_positions = FactoryPositions(player=[UnitPos(3, 3)])
        state = get_state(board_width=9, factory_positions=factory_positions)
        expected_actions = [MA(D.RIGHT), PA(amount=power_pickup_goal, resource=Resource.Power)]

        self._test_power_pickup_search(
            state=state, start=start, power_pickup_goal=power_pickup_goal, expected_actions=expected_actions
        )

    def test_move_take_next_goal_into_account_right(self):
        start = TC(3, 3, 0)
        power_pickup_goal = 100
        factory_positions = FactoryPositions(player=[UnitPos(3, 3)])
        constraints = init_constraints(negative_constraints=[TC(3, 3, 1)])
        next_goal_c = C(5, 3)

        expected_actions = [MA(D.RIGHT), PA(amount=power_pickup_goal, resource=Resource.Power)]

        state = get_state(board_width=9, factory_positions=factory_positions)

        self._test_power_pickup_search(
            state=state,
            start=start,
            power_pickup_goal=power_pickup_goal,
            expected_actions=expected_actions,
            constraints=constraints,
            next_goal_c=next_goal_c,
        )

    def test_move_take_next_goal_into_account_up(self):
        start = TC(3, 3, 0)
        power_pickup_goal = 100
        factory_positions = FactoryPositions(player=[UnitPos(3, 3)])
        constraints = init_constraints(negative_constraints=[TC(3, 3, 1)])
        next_goal_c = C(3, 1)

        expected_actions = [MA(D.UP), PA(amount=power_pickup_goal, resource=Resource.Power)]

        state = get_state(board_width=9, factory_positions=factory_positions)

        self._test_power_pickup_search(
            state=state,
            start=start,
            power_pickup_goal=power_pickup_goal,
            expected_actions=expected_actions,
            constraints=constraints,
            next_goal_c=next_goal_c,
        )

    def test_move_take_next_goal_into_account_down(self):
        start = TC(3, 3, 0)
        power_pickup_goal = 100
        factory_positions = FactoryPositions(player=[UnitPos(3, 3)])
        constraints = init_constraints(negative_constraints=[TC(3, 3, 1)])
        next_goal_c = C(3, 5)

        expected_actions = [MA(D.DOWN), PA(amount=power_pickup_goal, resource=Resource.Power)]

        state = get_state(board_width=9, factory_positions=factory_positions)

        self._test_power_pickup_search(
            state=state,
            start=start,
            power_pickup_goal=power_pickup_goal,
            expected_actions=expected_actions,
            constraints=constraints,
            next_goal_c=next_goal_c,
        )

    def test_move_take_next_goal_into_account_left(self):
        start = TC(3, 3, 0)
        power_pickup_goal = 100
        factory_positions = FactoryPositions(player=[UnitPos(3, 3)])
        constraints = init_constraints(negative_constraints=[TC(3, 3, 1)])
        next_goal_c = C(1, 3)

        expected_actions = [MA(D.LEFT), PA(amount=power_pickup_goal, resource=Resource.Power)]

        state = get_state(board_width=9, factory_positions=factory_positions)

        self._test_power_pickup_search(
            state=state,
            start=start,
            power_pickup_goal=power_pickup_goal,
            expected_actions=expected_actions,
            constraints=constraints,
            next_goal_c=next_goal_c,
        )


if __name__ == "__main__":
    unittest.main()