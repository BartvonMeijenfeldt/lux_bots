import heapq
import math

from typing import TypeVar, List, Tuple
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass

from objects.coordinate import PowerTimeCoordinate, DigTimeCoordinate, TimeCoordinate, DigCoordinate, Coordinate
from objects.direction import Direction
from objects.board import Board
from objects.actions.unit_action import UnitAction, MoveAction, DigAction, PickupAction
from objects.resource import Resource
from objects.actors.unit import UnitConfig
from logic.constraints import Constraints


T = TypeVar("T")


class PriorityQueue:
    def __init__(self):
        self.elements: list[tuple[float, T]] = []

    def empty(self) -> bool:
        return not self.elements

    def put(self, item: T, priority: float):
        heapq.heappush(self.elements, (priority, item))

    def get(self) -> T:
        return heapq.heappop(self.elements)[1]


@dataclass
class Graph(metaclass=ABCMeta):
    board: Board
    time_to_power_cost: float
    unit_cfg: UnitConfig
    constraints: Constraints

    @abstractmethod
    def potential_actions(self, c: TimeCoordinate) -> List[UnitAction]:
        ...

    def get_valid_action_nodes(self, c: TimeCoordinate) -> List[Tuple[UnitAction, TimeCoordinate]]:
        action_nodes = []

        for action in self.potential_actions(c=c):
            new_c = c + action
            if self.board.is_valid_c_for_player(c=new_c):
                action_nodes.append((action, new_c))

        return action_nodes

    def cost(self, action: UnitAction, from_c: TimeCoordinate, to_c: TimeCoordinate) -> float:
        if self.constraints.tc_violates_constraint(to_c):
            return math.inf

        action_power_cost = self.get_power_cost(action=action, to_c=to_c)
        return action_power_cost + self.time_to_power_cost

    def get_power_cost(self, action: UnitAction, to_c: Coordinate) -> float:
        power_change = action.get_power_change_by_end_c(unit_cfg=self.unit_cfg, end_c=to_c, board=self.board)
        power_cost = max(0, -power_change)
        return power_cost

    @abstractmethod
    def heuristic(self, node: Coordinate) -> float:
        ...

    @abstractmethod
    def node_completes_goal(self, node: Coordinate) -> bool:
        ...

    def _get_distance_heuristic(self, node: Coordinate) -> float:
        min_nr_steps = node.distance_to(self.goal)
        min_cost_per_step = self.time_to_power_cost + self.unit_cfg.MOVE_COST
        min_distance_cost = min_nr_steps * min_cost_per_step
        return min_distance_cost


@dataclass
class MoveToGraph(Graph):
    goal: Coordinate
    _potential_actions = [MoveAction(direction) for direction in Direction]

    def __post_init__(self):
        if not self.constraints.has_time_constraints:
            self._potential_actions = [
                MoveAction(direction) for direction in Direction if direction != direction.CENTER
            ]

    def potential_actions(self, c: TimeCoordinate) -> List[UnitAction]:
        return self._potential_actions

    def heuristic(self, node: Coordinate) -> float:
        return self._get_distance_heuristic(node=node)

    def node_completes_goal(self, node: Coordinate) -> bool:
        return self.goal == node


@dataclass
class FleeToGraph(Graph):
    goal: Coordinate
    start_c: TimeCoordinate
    opp_c: Coordinate
    _potential_actions = [MoveAction(direction) for direction in Direction]

    def __post_init__(self):
        if not self.constraints.has_time_constraints:
            self._potential_actions = [
                MoveAction(direction) for direction in Direction if direction != direction.CENTER
            ]

    def potential_actions(self, c: TimeCoordinate) -> List[UnitAction]:
        if c.t == self.start_c.t:
            return [
                action
                for action in self._potential_actions
                if action.get_final_c(start_c=c).xy != self.opp_c.xy and not action.is_stationary
            ]

        if c.t == self.start_c.t + 1:
            return [action for action in self._potential_actions if action.get_final_c(start_c=c).xy != self.start_c.xy]

        return self._potential_actions

    def heuristic(self, node: Coordinate) -> float:
        return self._get_distance_heuristic(node=node)

    def node_completes_goal(self, node: Coordinate) -> bool:
        return self.goal == node


@dataclass
class PickupPowerGraph(Graph):
    power_pickup_goal: int
    _potential_move_actions = [MoveAction(direction) for direction in Direction]

    def __post_init__(self):
        if self.constraints.max_power_request and self.constraints.max_power_request < self.power_pickup_goal:
            self.power_pickup_goal = self.constraints.max_power_request

        self._potential_recharge_actions = [PickupAction(amount=self.power_pickup_goal, resource=Resource.Power)]

        if not self.constraints.has_time_constraints:
            self._potential_move_actions = [
                MoveAction(direction) for direction in Direction if direction != direction.CENTER
            ]

    def potential_actions(self, c: TimeCoordinate) -> List[UnitAction]:
        if self.board.is_player_factory_tile(c=c):
            return self._potential_move_actions + self._potential_recharge_actions
        else:
            return self._potential_move_actions

    def heuristic(self, node: PowerTimeCoordinate) -> float:
        min_distance_cost = self._get_distance_heuristic(node=node)
        min_time_recharge_cost = self._get_time_recharge_heuristic(node=node)
        return min_distance_cost + min_time_recharge_cost

    def _get_distance_heuristic(self, node: Coordinate) -> float:
        closest_factory_tile = self.board.get_closest_factory_tile(node)
        min_distance_to_factory = closest_factory_tile.distance_to(node)
        return min_distance_to_factory

    def _get_time_recharge_heuristic(self, node: PowerTimeCoordinate) -> float:
        if self.node_completes_goal(node=node):
            return 0
        else:
            return self.time_to_power_cost

    def node_completes_goal(self, node: PowerTimeCoordinate) -> bool:
        return self.power_pickup_goal <= node.p


@dataclass
class DigAtGraph(Graph):
    goal: DigCoordinate
    _potential_move_actions = [MoveAction(direction) for direction in Direction]
    _potential_dig_actions = [DigAction()]

    def __post_init__(self):
        if not self.constraints.has_time_constraints:
            self._potential_move_actions = [
                MoveAction(direction) for direction in Direction if direction != direction.CENTER
            ]

    def potential_actions(self, c: TimeCoordinate) -> List[UnitAction]:
        if self.goal.x == c.x and self.goal.y == c.y:
            if self.constraints.has_time_constraints and self.constraints.max_t <= c.t:
                return self._potential_dig_actions
            else:
                return self._potential_move_actions + self._potential_dig_actions
        else:
            return self._potential_move_actions

    def heuristic(self, node: DigTimeCoordinate) -> float:
        distance_min_cost = self._get_distance_heuristic(node=node)
        digs_min_cost = self._get_digs_min_cost(node=node)

        return distance_min_cost + digs_min_cost

    def _get_digs_min_cost(self, node: DigTimeCoordinate) -> float:
        nr_digs_required = self.goal.d - node.d
        cost_per_dig = self.unit_cfg.DIG_COST + self.time_to_power_cost
        min_cost = nr_digs_required * cost_per_dig
        return min_cost

    def node_completes_goal(self, node: DigTimeCoordinate) -> bool:
        return self.goal == node


class Search:
    def __init__(self, graph: Graph) -> None:
        self.frontier = PriorityQueue()
        self.came_from: dict[TimeCoordinate, tuple[UnitAction, TimeCoordinate]] = {}
        self.cost_so_far: dict[TimeCoordinate, float] = {}
        self.graph = graph

    def get_actions_to_complete_goal(self, start: TimeCoordinate) -> List[UnitAction]:
        self._init_search(start)
        self._find_optimal_solution()
        return self._get_solution_actions()

    def _init_search(self, start: TimeCoordinate) -> None:
        self.cost_so_far[start] = 0
        self.frontier.put(start, 0)

    def _find_optimal_solution(self) -> None:
        while not self.frontier.empty():
            current_node: TimeCoordinate = self.frontier.get()

            if self.graph.node_completes_goal(node=current_node):
                break

            current_cost = self.cost_so_far[current_node]

            for action, next_node in self.graph.get_valid_action_nodes(current_node):
                new_cost = current_cost + self.graph.cost(action=action, from_c=current_node, to_c=next_node)
                # With a good heuristic (new_cost < cost_so_far[node]) shouldn't be relevant
                if next_node not in self.cost_so_far or new_cost < self.cost_so_far[next_node]:
                    self._add_node(node=next_node, action=action, current_node=current_node, node_cost=new_cost)

        self.final_node = current_node

    def _add_node(self, node: TimeCoordinate, action: UnitAction, current_node: TimeCoordinate, node_cost: float) -> None:
        self.cost_so_far[node] = node_cost
        priority = node_cost + self.graph.heuristic(node)
        self.frontier.put(node, priority)
        self.came_from[node] = (action, current_node)

    def _get_solution_actions(self) -> List[UnitAction]:
        solution = []
        cur_c = self.final_node

        while cur_c in self.came_from:
            action, cur_c = self.came_from[cur_c]
            solution.insert(0, action)

        return solution
