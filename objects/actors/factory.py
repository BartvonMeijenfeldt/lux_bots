from __future__ import annotations

import numpy as np


from typing import Tuple, TYPE_CHECKING, Optional, Iterable, Set, Generator, List
from itertools import product
from dataclasses import dataclass, field, replace
from collections import Counter
from copy import copy
from enum import Enum, auto
from math import floor

from objects.actions.unit_action_plan import UnitActionPlan
from objects.cargo import Cargo
from objects.actions.factory_action import WaterAction
from objects.actors.actor import Actor
from exceptions import NoValidGoalFoundError
from objects.coordinate import TimeCoordinate, Coordinate, CoordinateList
from logic.goals.unit_goal import DigGoal, CollectGoal
from objects.actions.factory_action_plan import FactoryActionPlan
from logic.goals.unit_goal import (
    UnitGoal,
    ClearRubbleGoal,
    CollectOreGoal,
    CollectIceGoal,
    SupplyPowerGoal,
    DestroyLichenGoal,
    CampResourceGoal,
)
from logic.goals.factory_goal import BuildHeavyGoal, BuildLightGoal, WaterGoal, FactoryNoGoal, FactoryGoal
from distances import (
    get_min_distance_between_positions,
    get_min_distance_between_pos_and_positions,
    get_min_distances_between_positions,
    get_closest_pos_between_pos_and_positions,
    get_positions_on_optimal_path_between_pos_and_pos,
)
from image_processing import get_islands
from positions import init_empty_positions, get_neighboring_positions, append_positions, positions_to_set
from lux.config import EnvConfig, LIGHT_CONFIG, HEAVY_CONFIG
from config import CONFIG

if TYPE_CHECKING:
    from logic.goal_resolution.scheduler import ScheduleInfo
    from objects.game_state import GameState
    from objects.board import Board
    from objects.actors.unit import Unit


class Strategy(Enum):
    INCREASE_LICHEN_TILES = auto()
    INCREASE_LICHEN = auto()
    COLLECT_ICE = auto()
    COLLECT_ORE = auto()
    ATTACK_OPPONENT = auto()


@dataclass(eq=False)
class Factory(Actor):
    strain_id: int
    center_tc: TimeCoordinate
    env_cfg: EnvConfig
    radius = 1
    units: set[Unit] = field(init=False, default_factory=set)
    goal: Optional[FactoryGoal] = field(init=False, default=None)
    private_action_plan: FactoryActionPlan = field(init=False)
    positions_set: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.id = int(self.unit_id[8:])
        self.x = self.center_tc.x
        self.y = self.center_tc.y

        self.private_action_plan = FactoryActionPlan(self, [])
        self._set_unit_state_variables()

    def _set_unit_state_variables(self) -> None:
        self.is_scheduled = False
        self.positions = np.array([[self.x + x, self.y + y] for x, y in product(range(-1, 2), range(-1, 2))])

    def update_state(self, center_tc: TimeCoordinate, power: int, cargo: Cargo) -> None:
        self.center_tc = center_tc
        self.power = power
        self.cargo = cargo
        self._set_unit_state_variables()

    def remove_units_not_in_obs(self, obs_units: set[Unit]) -> None:
        units_to_remove = self.units.difference(obs_units)
        for unit in units_to_remove:
            unit.remove_goal_and_private_action_plan()

        self.units.intersection_update(obs_units)

    def set_positions(self, board: Board) -> None:
        if not self.positions_set:
            self._set_positions_once(board)
            self.positions_set = True

        if self in board.player_factories:
            self._rubble_positions_to_clear_for_ore = self._get_rubble_positions_to_clear_for_pathing(
                board, self.ore_positions_distance_sorted[:5]
            )
            self._rubble_positions_to_clear_for_ice = self._get_rubble_positions_to_clear_for_pathing(
                board, self.ice_positions_distance_sorted[:5]
            )

            # TODO add other rubble positions
            self._rubble_positions_to_clear = (
                self._rubble_positions_to_clear_for_ore | self._rubble_positions_to_clear_for_ice
            )

        self.lichen_positions = np.argwhere(board.lichen_strains == self.strain_id)
        self.lichen_positions_set = positions_to_set(self.lichen_positions)
        # TODO, sort them, and add incoming invaders as well
        self.sorted_threaths_invaders = [unit for unit in board.opp_units if unit.tc.xy in self.lichen_positions_set]
        self.nr_lichen_tiles = len(self.lichen_positions)
        self.connected_lichen_positions = self._get_connected_lichen_positions(board)
        self.spreadable_lichen_positions = self._get_spreadable_lichen_positions(board)
        self.non_spreadable_connected_lichen_positions = self._get_not_spreadable_connected_lichen_positions(board)
        self.can_spread_positions = append_positions(self.positions, self.spreadable_lichen_positions)

        self.can_spread_to_positions = self._get_can_spread_to_positions(board, self.can_spread_positions)
        self.connected_positions = self._get_empty_or_lichen_connected_positions(board)

        # self.rubble_positions_pathing = self._get_rubble_positions_to_clear_for_resources(board)
        # self.rubble_positions_values_for_lichen = self._get_rubble_positions_to_clear_for_lichen(board)
        self.rubble_positions_next_to_can_spread_pos = self._get_rubble_positions_next_to_can_spread_pos(board)
        self.rubble_positions_next_to_can_not_spread_lichen = self._get_rubble_next_to_can_not_spread_lichen(board)
        self.rubble_positions_next_to_connected_or_self = self._get_rubble_next_to_connected_or_self(board)
        self.rubble_positions_next_to_connected_or_self_set = positions_to_set(
            self.rubble_positions_next_to_connected_or_self
        )

        self.nr_connected_lichen_tiles = len(self.connected_lichen_positions)
        self.nr_can_spread_positions = len(self.can_spread_positions)
        self.nr_connected_positions = len(self.connected_positions)
        self.nr_connected_positions_non_lichen_connected = self.nr_connected_positions - self.nr_connected_lichen_tiles
        self.max_nr_tiles_to_water = len(self.connected_lichen_positions) + len(self.can_spread_to_positions)

    def _set_positions_once(self, board: Board) -> None:
        self.ice_positions_distance_sorted = self._get_positions_distance_sorted(board.ice_positions)
        self.ore_positions_distance_sorted = self._get_positions_distance_sorted(board.ore_positions)

    def _get_positions_distance_sorted(self, positions: np.ndarray) -> np.ndarray:
        distances = get_min_distances_between_positions(positions, self.positions)
        sorted_indexes = np.argsort(distances)
        sorted_distance_positions = positions[sorted_indexes]
        return sorted_distance_positions

    @property
    def maintain_lichen_water_cost(self) -> float:
        """Assumes watering every other turn"""
        return EnvConfig.FACTORY_WATER_CONSUMPTION + self.water_cost / 2

    def get_rubble_positions_to_clear(self, game_state: GameState) -> Set[Tuple]:
        rubble_positions_free = self._rubble_positions_to_clear - game_state.positions_in_dig_goals
        return rubble_positions_free

    def get_rubble_positions_to_clear_for_ice(self, game_state: GameState) -> Set[Tuple]:
        rubble_positions_free = self._rubble_positions_to_clear_for_ice - game_state.positions_in_dig_goals
        return rubble_positions_free

    def get_rubble_positions_to_clear_for_ore(self, game_state: GameState) -> Set[Tuple]:
        rubble_positions_free = self._rubble_positions_to_clear_for_ore - game_state.positions_in_dig_goals
        return rubble_positions_free

    def nr_tiles_needed_to_grow_to_lichen_target(self, game_state: GameState) -> int:
        lichen_size_target = self.get_lichen_size_target_for_current_water_collection()
        nr_connected_positions = self.get_nr_connected_positions_including_being_cleared(game_state)
        nr_tiles_needed = lichen_size_target - nr_connected_positions
        nr_tiles_needed = max(0, nr_tiles_needed)
        return nr_tiles_needed

    def get_nr_connected_positions_including_being_cleared(self, game_state: GameState) -> int:
        # TODO, take into account if positions being cleared connects to other positions
        nr_positions_being_cleared = self.get_nr_positions_being_cleared_next_to_connected(game_state)
        return self.nr_connected_positions + nr_positions_being_cleared

    def get_nr_positions_being_cleared_next_to_connected(self, game_state: GameState) -> int:
        return sum(
            1
            for unit in game_state.player_units
            if isinstance(unit.goal, ClearRubbleGoal)
            and unit.goal.dig_c.xy in self.rubble_positions_next_to_connected_or_self_set
        )

    def _get_connected_lichen_positions(self, board: Board) -> np.ndarray:
        own_lichen = board.lichen_strains == self.strain_id
        return self._get_connected_positions(own_lichen)

    def _get_spreadable_lichen_positions(self, board: Board) -> np.ndarray:
        if not self.connected_lichen_positions.shape[0]:
            return init_empty_positions()

        lichen_available = board.lichen[self.connected_lichen_positions[:, 0], self.connected_lichen_positions[:, 1]]
        can_spread_mask = lichen_available >= EnvConfig.MIN_LICHEN_TO_SPREAD
        return self.connected_lichen_positions[can_spread_mask]

    def _get_not_spreadable_connected_lichen_positions(self, board: Board) -> np.ndarray:
        if not self.connected_lichen_positions.shape[0]:
            return init_empty_positions()

        lichen_available = board.lichen[self.connected_lichen_positions[:, 0], self.connected_lichen_positions[:, 1]]
        can_not_spread_mask = lichen_available < EnvConfig.MIN_LICHEN_TO_SPREAD
        return self.connected_lichen_positions[can_not_spread_mask]

    def _get_empty_or_lichen_connected_positions(self, board: Board) -> np.ndarray:
        is_empty_or_own_lichen = (board.lichen_strains == self.strain_id) | (board.is_empty_array)
        return self._get_connected_positions(is_empty_or_own_lichen)

    def _get_connected_positions(self, array: np.ndarray) -> np.ndarray:
        islands = get_islands(array)

        connected_positions = init_empty_positions()
        for single_island in islands:
            if get_min_distance_between_positions(self.positions, single_island) == 1:
                connected_positions = append_positions(connected_positions, single_island)

        return connected_positions

    def _get_can_spread_to_positions(self, board: Board, can_spread_positions: np.ndarray) -> np.ndarray:
        neighboring_positions = get_neighboring_positions(can_spread_positions)
        is_empty_mask = board.are_empty_postions(neighboring_positions)
        return neighboring_positions[is_empty_mask]

    def _get_rubble_positions_to_clear_for_pathing(self, board: Board, positions: np.ndarray) -> Set[Tuple]:
        for ore_pos in positions[:5]:
            closest_factory_pos = get_closest_pos_between_pos_and_positions(ore_pos, self.positions)
            positions = get_positions_on_optimal_path_between_pos_and_pos(ore_pos, closest_factory_pos, board)
            rubble_mask = board.are_rubble_positions(positions)
            rubble_positions = positions[rubble_mask]
            if rubble_positions.shape[0]:
                break
        else:
            rubble_positions = init_empty_positions()

        return positions_to_set(rubble_positions)

    # def _get_rubble_positions_to_clear_for_resources(self, board: Board) -> Counter[Tuple[int, int]]:
    #     closest_2_ice_positions = board.get_n_closest_ice_positions_to_factory(self, n=2)
    #     closest_2_ore_positions = board.get_n_closest_ore_positions_to_factory(self, n=2)
    #     closest_resource_positions = append_positions(closest_2_ice_positions, closest_2_ore_positions)

    #     positions = init_empty_positions()

    #     for pos in closest_resource_positions:
    #         closest_factory_pos = get_closest_pos_between_pos_and_positions(pos, self.positions)
    #         optimal_positions = get_positions_on_optimal_path_between_pos_and_pos(pos, closest_factory_pos, board)
    #         positions = append_positions(positions, optimal_positions)

    #     rubble_mask = board.are_rubble_positions(positions)
    #     rubble_positions = positions[rubble_mask]

    #     rubble_value_dict = Counter({tuple(pos): CONFIG.RUBBLE_VALUE_CLEAR_FOR_RESOURCE for pos in rubble_positions})

    #     return rubble_value_dict

    def _get_rubble_positions_to_clear_for_lichen(self, board: Board) -> Counter[Tuple[int, int]]:
        rubble_positions, distances = self._get_rubble_positions_and_distances_within_max_distance(board)
        values = self._get_rubble_positions_to_clear_for_lichen_score(distances)
        rubble_value_dict = Counter({tuple(pos): value for pos, value in zip(rubble_positions, values)})

        return rubble_value_dict

    def _get_rubble_positions_next_to_can_spread_pos(self, board: Board) -> np.ndarray:
        distances = get_min_distances_between_positions(board.rubble_positions, self.can_spread_positions)
        valid_distance_mask = distances == 1
        rubble_positions_next_to_can_spread_pos = board.rubble_positions[valid_distance_mask]
        return rubble_positions_next_to_can_spread_pos

    def _get_rubble_next_to_can_not_spread_lichen(self, board: Board) -> np.ndarray:
        if not board.rubble_positions.shape[0] or not self.non_spreadable_connected_lichen_positions.shape[0]:
            return init_empty_positions()

        distances_valid = get_min_distances_between_positions(
            board.rubble_positions, self.non_spreadable_connected_lichen_positions
        )
        valid_distance_mask = distances_valid == 1
        rubble_positions = board.rubble_positions[valid_distance_mask]
        return rubble_positions

    def _get_rubble_next_to_connected_or_self(self, board: Board) -> np.ndarray:
        if not board.rubble_positions.shape[0]:
            return init_empty_positions()

        connected_or_self_positions = append_positions(self.positions, self.connected_positions)

        distances = get_min_distances_between_positions(board.rubble_positions, connected_or_self_positions)
        valid_distance_mask = distances == 1
        rubble_positions = board.rubble_positions[valid_distance_mask]
        return rubble_positions

    def _get_rubble_positions_to_clear_for_lichen_score(self, distances: np.ndarray) -> np.ndarray:
        base_score = CONFIG.RUBBLE_VALUE_CLEAR_FOR_LICHEN_BASE
        distance_penalty = CONFIG.RUBBLE_VALUE_CLEAR_FOR_LICHEN_DISTANCE_PENALTY
        return base_score - distance_penalty * distances

    def _get_rubble_positions_and_distances_within_max_distance(self, board: Board) -> Tuple[np.ndarray, np.ndarray]:
        distances = get_min_distances_between_positions(board.rubble_positions, self.can_spread_positions)
        valid_distance_mask = distances < CONFIG.RUBBLE_CLEAR_FOR_LICHEN_MAX_DISTANCE
        rubble_postions_within_max_distance = board.rubble_positions[valid_distance_mask]
        distances_within_max_distance = distances[valid_distance_mask]
        return rubble_postions_within_max_distance, distances_within_max_distance

    def add_unit(self, unit: Unit) -> None:
        self.units.add(unit)

    def min_distance_to_connected_positions(self, positions: np.ndarray) -> int:
        rel_positions = np.append(self.positions, self.connected_positions, axis=0)
        return get_min_distance_between_positions(rel_positions, positions)

    # TODO Can build should be put into the constraints
    def schedule_goal(self, schedule_info: ScheduleInfo, can_build: bool = True) -> FactoryActionPlan:
        goal = self.get_goal(schedule_info.game_state, can_build)
        action_plan = goal.generate_action_plan(schedule_info)
        self.goal = goal
        self.private_action_plan = action_plan
        return action_plan

    def get_goal(self, game_state: GameState, can_build: bool = True) -> FactoryGoal:
        water_cost = self.water_cost
        safety_level = 50 if game_state.real_env_steps < 70 else 70
        if can_build and self.can_build_heavy:
            return BuildHeavyGoal(self)

        elif (
            can_build
            and self.can_build_light
            and (
                self.nr_light_units < 15
                or (self.nr_light_units < 20 and self.nr_heavy_units > 1)
                or (self.nr_light_units < 30 and self.nr_heavy_units > 2)
            )
        ):
            return BuildLightGoal(self)

        elif self.cargo.water - water_cost > safety_level and (water_cost < 5 or self.water > 150):
            return WaterGoal(self)

        elif game_state.env_steps > 750 and self.can_water() and self.cargo.water - water_cost > game_state.steps_left:
            return WaterGoal(self)

        return FactoryNoGoal(self)

    @property
    def light_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.units if unit.is_light)

    @property
    def heavy_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.units if unit.is_heavy)

    @property
    def nr_light_units(self) -> int:
        return sum(1 for _ in self.light_units)

    @property
    def nr_heavy_units(self) -> int:
        return sum(1 for _ in self.heavy_units)

    @property
    def nr_scheduled_units(self) -> int:
        return sum(1 for _ in self.scheduled_units)

    @property
    def nr_attack_scheduled_units(self) -> int:
        return sum(1 for _ in self.attack_scheduled_units)

    @property
    def daily_charge(self) -> int:
        return self.env_cfg.FACTORY_CHARGE

    @property
    def expected_power_gain(self) -> int:
        return self.env_cfg.FACTORY_CHARGE + self.nr_connected_lichen_tiles

    @property
    def can_build_heavy(self) -> bool:
        return self.power >= HEAVY_CONFIG.POWER_COST and self.cargo.metal >= HEAVY_CONFIG.METAL_COST

    @property
    def can_build_light(self) -> bool:
        return self.power >= LIGHT_CONFIG.POWER_COST and self.cargo.metal >= LIGHT_CONFIG.METAL_COST

    @property
    def water_cost(self) -> int:
        return WaterAction.get_water_cost(self)

    def can_water(self):
        return self.cargo.water >= self.water_cost

    @property
    def pos_slice(self) -> Tuple[slice, slice]:
        return self.x_slice, self.y_slice

    @property
    def x_slice(self) -> slice:
        return slice(self.center_tc.x - self.radius, self.center_tc.x + self.radius + 1)

    @property
    def y_slice(self) -> slice:
        return slice(self.center_tc.y - self.radius, self.center_tc.y + self.radius + 1)

    @property
    def pos_x_range(self):
        return range(self.center_tc.x - self.radius, self.center_tc.x + self.radius + 1)

    @property
    def pos_y_range(self):
        return range(self.center_tc.y - self.radius, self.center_tc.y + self.radius + 1)

    @property
    def coordinates(self) -> CoordinateList:
        return CoordinateList([Coordinate(x, y) for x in self.pos_x_range for y in self.pos_y_range])

    @property
    def water(self) -> int:
        return self.cargo.water

    @property
    def ice(self) -> int:
        return self.cargo.ice

    @property
    def ore(self) -> int:
        return self.cargo.ore

    @property
    def metal(self) -> int:
        return self.cargo.metal

    def __repr__(self) -> str:
        return f"Factory[id={self.unit_id}, center={self.center_tc.xy}]"

    @property
    def power_including_units(self) -> float:
        units_power = sum(unit.power for unit in self.units)
        power = self.power + units_power
        return power

    def get_expected_power_generation(self, game_state: GameState) -> int:
        expected_lichen_size = self.get_expected_lichen_size(game_state)
        power_generation = EnvConfig.FACTORY_CHARGE + expected_lichen_size * EnvConfig.POWER_PER_CONNECTED_LICHEN_TILE
        return power_generation

    def get_expected_lichen_size(self, game_state: GameState) -> int:
        lichen_size_target = self.get_lichen_size_target_for_current_water_collection()
        if lichen_size_target < self.nr_connected_lichen_tiles:
            return self.nr_connected_lichen_tiles

        nr_expected_connected_positions = self.get_nr_connected_positions_including_being_cleared(game_state)
        return min(nr_expected_connected_positions, lichen_size_target)

    def get_lichen_size_target_for_current_water_collection(self) -> int:
        water_collection_per_step = self.get_water_collection_per_step()
        tiles_target = floor(water_collection_per_step * EnvConfig.LICHEN_WATERING_COST_FACTOR) * 2  # Alternating water
        return tiles_target

    def get_expected_power_consumption(self) -> float:
        metal_in_factory = self.metal + self.ore / EnvConfig.ORE_METAL_RATIO
        metal_collection = self.get_metal_collection_per_step()
        metal_expected = metal_in_factory + metal_collection

        # Assume next unit just as likely to be light as heavy
        expected_nr_lights = self.nr_light_units + metal_expected / LIGHT_CONFIG.METAL_COST / 2
        expected_nr_heavies = self.nr_heavy_units + metal_expected / HEAVY_CONFIG.METAL_COST / 2

        lights_power_consumption = expected_nr_lights * CONFIG.EXPECTED_POWER_CONSUMPTION_LIGHT_PER_TURN
        heavies_power_consumption = expected_nr_heavies * CONFIG.EXPECTED_POWER_CONSUMPTION_HEAVY_PER_TURN

        expected_power_usage_per_step = lights_power_consumption + heavies_power_consumption
        return expected_power_usage_per_step

    def get_water_collection_per_step(self) -> float:
        ice_collection_per_step = self.get_ice_collection_per_step()
        water_collection_per_step = ice_collection_per_step / EnvConfig.ICE_WATER_RATIO
        return water_collection_per_step

    def get_ice_collection_per_step(self) -> float:
        return sum(
            self._resource_collection_per_step(unit.goal)
            for unit in self.scheduled_units
            if isinstance(unit.goal, CollectIceGoal)
        )

    def get_metal_collection_per_step(self) -> float:
        ore_collection_per_step = self.get_ore_collection_per_step()
        metal_collection_per_step = ore_collection_per_step / EnvConfig.ORE_METAL_RATIO
        return metal_collection_per_step

    def get_ore_collection_per_step(self) -> float:
        return sum(
            self._resource_collection_per_step(unit.goal)
            for unit in self.scheduled_units
            if isinstance(unit.goal, CollectOreGoal)
        )

    def _resource_collection_per_step(self, goal: CollectGoal) -> float:
        # Assumes full battery

        unit = goal.unit

        if goal.is_supplied:
            nr_steps_moving = 0
            nr_steps_power_pickup = 0
            nr_steps_digging = unit.nr_digs_empty_to_full_cargo
        else:

            distance_resource_to_factory = self.min_distance_to_c(goal.dig_c)
            nr_steps_moving = 2 * distance_resource_to_factory
            nr_steps_power_pickup = 1

            power_available_for_digging = unit.battery_capacity - nr_steps_moving * unit.move_power_cost
            ratio_day_night = EnvConfig.DAY_LENGTH / EnvConfig.CYCLE_LENGTH
            average_power_charge = ratio_day_night * unit.recharge_power
            net_power_change_per_dig = unit.dig_power_cost - average_power_charge
            # This is approximate value which will be different for day and night
            max_nr_digs = power_available_for_digging / net_power_change_per_dig
            nr_steps_digging = min(unit.nr_digs_empty_to_full_cargo, max_nr_digs)

        resource_collection = nr_steps_digging * unit.resources_gained_per_dig

        nr_steps_transfer = 1
        nr_steps = nr_steps_digging + nr_steps_moving + nr_steps_power_pickup + nr_steps_transfer

        resource_collection_per_step = resource_collection / nr_steps
        return resource_collection_per_step

    @property
    def nr_can_spread_to_positions_being_cleared(self) -> int:
        nr_positions = 0

        for unit in self.units:
            goal = unit.goal
            if isinstance(goal, ClearRubbleGoal):
                dig_pos = np.array(goal.dig_c.xy)  # type: ignore
                dis = get_min_distance_between_pos_and_positions(dig_pos, self.can_spread_positions)
                if dis == 1:
                    nr_positions += 1

        return nr_positions

    @property
    def has_heavy_unsupplied_collecting_next_to_factory(self) -> bool:
        return any(True for _ in self.heavy_units_unsupplied_collecting_next_to_factory)

    @property
    def heavy_units_unsupplied_collecting_next_to_factory(self) -> Generator[Unit, None, None]:
        return (
            heavy
            for heavy in self.heavy_units
            if isinstance(heavy.goal, CollectGoal)
            and self.min_distance_to_c(heavy.goal.dig_c) == 1
            and not heavy.supplied_by
        )

    def min_distance_to_c(self, c: Coordinate) -> int:
        pos = np.array(c.xy)
        return get_min_distance_between_pos_and_positions(pos, self.positions)

    @property
    def has_unit_available(self) -> bool:
        return any(True for _ in self.available_units)

    @property
    def has_heavy_unit_available(self) -> bool:
        return any(True for _ in self.heavy_available_units)

    @property
    def has_light_unit_available(self) -> bool:
        return any(True for _ in self.light_available_units)

    @property
    def available_units(self) -> Generator[Unit, None, None]:
        # TODO some checks to see if there is enough power or some other mechanic to set units as unavailable
        return (
            unit
            for unit in self.units
            if unit.can_update_action_queue and not unit.private_action_plan and unit.can_be_assigned
        )

    @property
    def heavy_available_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.available_units if unit.is_heavy)

    @property
    def light_available_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.available_units if unit.is_light)

    @property
    def attack_scheduled_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.scheduled_units if isinstance(unit.goal, DestroyLichenGoal))

    @property
    def scheduled_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.units if unit.is_scheduled)

    @property
    def unscheduled_units(self) -> Generator[Unit, None, None]:
        return (unit for unit in self.units if not unit.is_scheduled)

    @property
    def has_unassigned_units(self) -> bool:
        return any(not unit.private_action_plan for unit in self.units)

    def schedule_units(
        self,
        strategies: Iterable[Strategy],
        schedule_info: ScheduleInfo,
    ) -> List[UnitGoal]:
        if self.sorted_threaths_invaders:
            try:
                return [self._schedule_hunt_invaders(schedule_info)]
            except NoValidGoalFoundError:
                pass

        if self.has_heavy_unsupplied_collecting_next_to_factory and self.has_light_unit_available:
            try:
                return self._schedule_supply_goal_and_reschedule_receiving_unit(schedule_info)
            except NoValidGoalFoundError:
                pass

        for strategy in strategies:
            try:
                return [self._schedule_unit_on_strategy(strategy, schedule_info)]
            except NoValidGoalFoundError:
                continue

        return [self._schedule_first_unit_by_own_preference(schedule_info)]

    def _schedule_hunt_invaders(self, schedule_info: ScheduleInfo) -> UnitGoal:
        while self.sorted_threaths_invaders:
            invader = self.sorted_threaths_invaders.pop()
            if invader in schedule_info.game_state.hunted_opp_units:
                continue

            try:
                return self._schedule_hunt_invader(invader, schedule_info)
            except NoValidGoalFoundError:
                continue

        raise NoValidGoalFoundError

    def _schedule_hunt_invader(self, invader: Unit, schedule_info: ScheduleInfo) -> UnitGoal:
        if invader.is_light:
            return self._schedule_hunt_invader_with_units(invader, self.light_available_units, schedule_info)
        else:
            return self._schedule_hunt_invader_with_units(invader, self.heavy_available_units, schedule_info)

    def _schedule_hunt_invader_with_units(
        self, invader: Unit, units: Iterable[Unit], schedule_info: ScheduleInfo
    ) -> UnitGoal:

        potential_assignments = [(unit, goal) for unit in units for goal in unit._get_hunt_unit_goals(invader)]
        return self.get_best_assignment(potential_assignments, schedule_info)  # type: ignore

    def _schedule_unit_on_strategy(self, strategy: Strategy, schedule_info: ScheduleInfo) -> UnitGoal:

        if strategy == Strategy.INCREASE_LICHEN_TILES:
            goal = self.schedule_strategy_increase_lichen_tiles(schedule_info)
        elif strategy == Strategy.INCREASE_LICHEN:
            goal = self.schedule_strategy_increase_lichen(schedule_info)
        elif strategy == Strategy.COLLECT_ORE:
            goal = self.schedule_strategy_collect_ore(schedule_info)
        elif strategy == Strategy.COLLECT_ICE:
            goal = self.schedule_strategy_collect_ice(schedule_info)
        elif strategy == Strategy.ATTACK_OPPONENT:
            goal = self.schedule_strategy_attack_opponent(schedule_info)
        else:
            raise ValueError("Strategy is not a known strategy")

        return goal

    def _schedule_first_unit_by_own_preference(self, schedule_info: ScheduleInfo) -> UnitGoal:
        game_state = schedule_info.game_state

        unit = next(self.available_units)
        all_goals = unit.generate_goals(game_state, self)
        best_goal = max(all_goals, key=lambda g: g.get_best_value_per_step(game_state))
        dummy_goals = unit._get_dummy_goals(game_state)
        goals = [best_goal] + dummy_goals
        goal = unit.get_best_goal(goals, schedule_info)
        return goal

    def schedule_strategy_increase_lichen(self, schedule_info: ScheduleInfo) -> UnitGoal:
        if not self.enough_water_collection_for_next_turns():
            return self.schedule_strategy_collect_ice(schedule_info)
        else:
            return self.schedule_strategy_increase_lichen_tiles(schedule_info)

    def schedule_strategy_increase_lichen_tiles(self, schedule_info: ScheduleInfo) -> UnitGoal:
        game_state = schedule_info.game_state

        rubble_positions = self._get_suitable_dig_positions_for_lichen(game_state)
        if not rubble_positions:
            raise NoValidGoalFoundError

        if game_state.real_env_steps < CONFIG.FIRST_STEP_HEAVY_ALLOWED_TO_DIG_RUBBLE:
            units = self.light_available_units
        else:
            units = self.available_units

        return self._schedule_unit_on_rubble_pos(rubble_positions, units, schedule_info)

    def _schedule_unit_on_rubble_pos(
        self, rubble_positions: Iterable[Tuple], units: Iterable[Unit], schedule_info: ScheduleInfo
    ) -> UnitGoal:

        potential_assignments = [
            (unit, goal)
            for unit in units
            for pos in rubble_positions
            for goal in unit._get_clear_rubble_goals(Coordinate(*pos))
        ]

        return self.get_best_assignment(potential_assignments, schedule_info)  # type: ignore

    def get_best_assignment(
        self, potential_assignments: List[Tuple[Unit, UnitGoal]], schedule_info: ScheduleInfo
    ) -> UnitGoal:

        if not potential_assignments:
            raise NoValidGoalFoundError

        unit, goal = max(potential_assignments, key=lambda x: x[1].get_best_value_per_step(schedule_info.game_state))
        if isinstance(goal, DigGoal):
            schedule_info = self._get_schedule_info_without_units_on_dig_c(goal.dig_c, schedule_info)

        goal = unit.get_best_version_goal(goal, schedule_info)
        return goal

    def _get_suitable_dig_positions_for_lichen(self, game_state: GameState) -> Set[Tuple]:
        rubble_positions_favorite = positions_to_set(self.rubble_positions_next_to_can_spread_pos)
        valid_rubble_positions = rubble_positions_favorite - game_state.positions_in_dig_goals
        if valid_rubble_positions:
            return valid_rubble_positions

        rubble_positions_second_favorite = positions_to_set(self.rubble_positions_next_to_can_not_spread_lichen)
        valid_rubble_positions = rubble_positions_second_favorite - game_state.positions_in_dig_goals

        if valid_rubble_positions:
            return valid_rubble_positions

        return set()

    def enough_water_collection_for_next_turns(self) -> bool:
        water_collection = self.get_water_collection_per_step()
        water_available_next_n_turns = self.water + CONFIG.ENOUGH_WATER_COLLECTION_NR_TURNS * water_collection
        water_cost_next_n_turns = CONFIG.ENOUGH_WATER_COLLECTION_NR_TURNS * self.water_cost
        return water_available_next_n_turns > water_cost_next_n_turns

    def _schedule_supply_goal_and_reschedule_receiving_unit(self, schedule_info: ScheduleInfo) -> List[UnitGoal]:
        game_state = schedule_info.game_state

        supplying_unit, receiving_unit, receiving_c = self._assign_supplying_unit_and_receiving_unit(game_state)
        schedule_info = self._get_schedule_info_without_unit_scheduled_actions(schedule_info, receiving_unit)

        goal_receiving_unit = self._reschedule_receiving_collect_goal(
            schedule_info=schedule_info,
            unit=receiving_unit,
            receiving_c=receiving_c,
        )

        tcs = goal_receiving_unit.action_plan.get_time_coordinates(game_state)
        schedule_info.constraints.add_negative_constraints(tcs)
        schedule_info.power_tracker.add_power_requests(goal_receiving_unit.action_plan.get_power_requests(game_state))

        goal_supplying_unit = self._schedule_supply_goal(
            schedule_info=schedule_info,
            supplying_unit=supplying_unit,
            receiving_action_plan=goal_receiving_unit.action_plan,
            receiving_unit=receiving_unit,
            receiving_c=receiving_c,
        )

        return [goal_receiving_unit, goal_supplying_unit]

    def _assign_supplying_unit_and_receiving_unit(self, game_state: GameState) -> Tuple[Unit, Unit, Coordinate]:
        potential_assignments = [
            (supply_unit, goal)
            for supply_unit in self.light_available_units
            for receiving_unit in self.heavy_units_unsupplied_collecting_next_to_factory
            for goal in supply_unit._get_supply_power_goals(
                receiving_unit, receiving_unit.private_action_plan, receiving_unit.goal.dig_c  # type: ignore
            )
        ]

        if not potential_assignments:
            raise NoValidGoalFoundError

        supplying_unit, goal = max(potential_assignments, key=lambda x: x[1].get_best_value_per_step(game_state))
        receiving_unit = goal.receiving_unit
        receiving_c = goal.receiving_c

        return (supplying_unit, receiving_unit, receiving_c)

    def _reschedule_receiving_collect_goal(
        self, unit: Unit, receiving_c: Coordinate, schedule_info: ScheduleInfo
    ) -> CollectGoal:

        if isinstance(unit.goal, CollectOreGoal):
            return unit.generate_collect_ore_goal(
                schedule_info=schedule_info,
                c=receiving_c,
                is_supplied=True,
                factory=self,
            )
        elif isinstance(unit.goal, CollectIceGoal):
            return unit.generate_collect_ice_goal(
                schedule_info=schedule_info,
                c=receiving_c,
                is_supplied=True,
                factory=self,
            )

        raise RuntimeError("Not supposed to happen")

    def _schedule_supply_goal(
        self,
        schedule_info: ScheduleInfo,
        supplying_unit: Unit,
        receiving_unit: Unit,
        receiving_action_plan: UnitActionPlan,
        receiving_c: Coordinate,
    ) -> SupplyPowerGoal:

        goal = supplying_unit.generate_supply_power_goal(
            schedule_info, receiving_unit, receiving_action_plan, receiving_c
        )
        return goal

    def schedule_strategy_collect_ore(self, schedule_info: ScheduleInfo) -> UnitGoal:
        # Collect Ore / Clear Path to Ore / Supply Power to heavy on Ore
        if self.has_heavy_unit_available:
            return self._schedule_heavy_on_ore(schedule_info)
        else:
            return self._schedule_light_on_ore_task(schedule_info)

    def _schedule_heavy_on_ore(self, schedule_info: ScheduleInfo) -> UnitGoal:
        game_state = schedule_info.game_state
        valid_ore_positions_set = game_state.board.ore_positions_set - game_state.positions_in_heavy_dig_goals
        goal = self._schedule_unit_on_ore_pos(valid_ore_positions_set, self.heavy_available_units, schedule_info)
        return goal

    def _schedule_light_on_ore_task(self, schedule_info: ScheduleInfo) -> UnitGoal:
        try:
            return self._schedule_light_on_ore(schedule_info)
        except Exception:
            rubble_positions = self.get_rubble_positions_to_clear_for_ore(schedule_info.game_state)
            if not rubble_positions:
                raise NoValidGoalFoundError

            return self._schedule_unit_on_rubble_pos(
                rubble_positions,
                self.light_available_units,
                schedule_info,
            )

    def _schedule_light_on_ore(self, schedule_info: ScheduleInfo) -> UnitGoal:
        game_state = schedule_info.game_state
        valid_ore_positions_set = game_state.board.ore_positions_set - game_state.positions_in_dig_goals
        return self._schedule_unit_on_ore_pos(valid_ore_positions_set, self.light_available_units, schedule_info)

    def _schedule_unit_on_ore_pos(
        self, ore_positions: Iterable[Tuple], units: Iterable[Unit], schedule_info: ScheduleInfo
    ) -> CollectOreGoal:

        potential_assignments = [
            (unit, goal)
            for unit in units
            for pos in ore_positions
            for goal in unit._get_collect_ore_goals(
                Coordinate(*pos), schedule_info.game_state, factory=self, is_supplied=False
            )
        ]

        return self.get_best_assignment(potential_assignments, schedule_info)  # type: ignore

    def schedule_strategy_collect_ice(self, schedule_info: ScheduleInfo) -> UnitGoal:
        # Collect Ice / Clear Path to Ice / Supply Power to heavy on Ice
        if self.has_heavy_unit_available:
            return self._schedule_heavy_on_ice(schedule_info)
        else:
            return self._schedule_light_on_ice_task(schedule_info)

    def _schedule_heavy_on_ice(self, schedule_info: ScheduleInfo) -> UnitGoal:
        game_state = schedule_info.game_state
        valid_ice_positions_set = game_state.board.ice_positions_set - game_state.positions_in_heavy_dig_goals
        return self._schedule_unit_on_ice_pos(valid_ice_positions_set, self.heavy_available_units, schedule_info)

    def _schedule_light_on_ice_task(self, schedule_info: ScheduleInfo) -> UnitGoal:
        try:
            return self._schedule_light_on_ice(schedule_info)
        except Exception:
            rubble_positions = self.get_rubble_positions_to_clear_for_ice(schedule_info.game_state)
            if not rubble_positions:
                raise NoValidGoalFoundError

            return self._schedule_unit_on_rubble_pos(rubble_positions, self.light_available_units, schedule_info)

    def _schedule_light_on_ice(self, schedule_info: ScheduleInfo) -> UnitGoal:
        game_state = schedule_info.game_state
        valid_ice_positions_set = game_state.board.ice_positions_set - game_state.positions_in_dig_goals
        return self._schedule_unit_on_ice_pos(valid_ice_positions_set, self.light_available_units, schedule_info)

    def _schedule_unit_on_ice_pos(
        self, ice_positions: Iterable[Tuple], units: Iterable[Unit], schedule_info: ScheduleInfo
    ) -> CollectIceGoal:

        potential_assignments = [
            (unit, goal)
            for unit in units
            for pos in ice_positions
            for goal in unit._get_collect_ice_goals(
                Coordinate(*pos), schedule_info.game_state, factory=self, is_supplied=False
            )
        ]

        return self.get_best_assignment(potential_assignments, schedule_info)  # type: ignore

    def schedule_strategy_attack_opponent(self, schedule_info: ScheduleInfo) -> UnitGoal:
        try:
            return self._schedule_unit_camp_resource(schedule_info)
        except Exception:
            return self._schedule_unit_destroy_lichen(schedule_info)

    def _schedule_unit_camp_resource(self, schedule_info: ScheduleInfo) -> CampResourceGoal:
        game_state = schedule_info.game_state
        valid_postions = game_state.ice_positions_next_to_opp_factory - game_state.positions_in_camp_goals
        units = self.heavy_available_units

        potential_assignments = [
            (unit, goal)
            for pos in valid_postions
            for unit in units
            for goal in unit._get_camp_resource_goals(Coordinate(*pos))
        ]

        if not potential_assignments:
            raise NoValidGoalFoundError

        unit, goal = max(potential_assignments, key=lambda x: x[1].get_best_value_per_step(game_state))

        goal = unit.generate_camp_resource_goals(schedule_info=schedule_info, resource_c=goal.resource_c)
        return goal

    def _schedule_unit_destroy_lichen(self, schedule_info: ScheduleInfo) -> DestroyLichenGoal:
        game_state = schedule_info.game_state
        dig_pos_set = {c.xy for c in game_state.opp_lichen_tiles}
        valid_pos = dig_pos_set - game_state.positions_in_dig_goals

        if CONFIG.FIRST_STEP_HEAVY_ALLOWED_TO_DESTROY_LICHEN < game_state.real_env_steps:
            units = self.light_available_units
        else:
            units = self.available_units

        potential_assignments = [
            (unit, goal)
            for pos in valid_pos
            for unit in units
            for goal in unit._get_destroy_lichen_goals(Coordinate(*pos), game_state)
        ]

        return self.get_best_assignment(potential_assignments, schedule_info)  # type: ignore

    def _get_schedule_info_without_unit_scheduled_actions(
        self, schedule_info: ScheduleInfo, unit: Unit
    ) -> ScheduleInfo:
        if not unit.is_scheduled:
            return schedule_info

        game_state = schedule_info.game_state
        constraints = copy(schedule_info.constraints)
        power_tracker = copy(schedule_info.power_tracker)

        constraints.remove_negative_constraints(unit.private_action_plan.get_time_coordinates(game_state))
        power_tracker.remove_power_requests(unit.private_action_plan.get_power_requests(game_state))
        schedule_info = replace(schedule_info, constraints=constraints, power_tracker=power_tracker)

        return schedule_info

    def _get_schedule_info_without_units_on_dig_c(self, c: Coordinate, schedule_info: ScheduleInfo) -> ScheduleInfo:
        game_state = schedule_info.game_state
        constraints = copy(schedule_info.constraints)
        power_tracker = copy(schedule_info.power_tracker)

        for unit in game_state.units:
            if (
                unit.is_scheduled
                and isinstance(unit.goal, DigGoal)
                and unit.goal.dig_c == c
                and unit.private_action_plan
            ):
                constraints.remove_negative_constraints(unit.private_action_plan.get_time_coordinates(game_state))
                power_tracker.remove_power_requests(unit.private_action_plan.get_power_requests(game_state))

        schedule_info = replace(schedule_info, constraints=constraints, power_tracker=power_tracker)

        return schedule_info
