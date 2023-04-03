from __future__ import annotations
from typing import TYPE_CHECKING, Optional, Sequence

from dataclasses import dataclass

if TYPE_CHECKING:
    from objects.board import Board
    from objects.actors.actor import Actor
    from objects.actors.factory import Factory
    from objects.actors.unit import Unit
    from lux.team import Team
    from objects.coordinate import Coordinate, CoordinateList
    from lux.config import EnvConfig


@dataclass
class GameState:
    env_steps: int
    env_cfg: EnvConfig
    board: Board
    player_team: Team
    opp_team: Team

    def __hash__(self) -> int:
        return self.real_env_steps

    def __eq__(self, o: GameState) -> bool:
        return self.real_env_steps == o.real_env_steps

    def __repr__(self) -> str:
        return f"Gamestate [t={self.real_env_steps}]"

    @property
    def player_units(self) -> list[Unit]:
        return self.board.player_units

    @property
    def opp_units(self) -> list[Unit]:
        return self.board.opp_units

    @property
    def player_factories(self) -> list[Factory]:
        return self.board.player_factories

    @property
    def player_actors(self) -> Sequence[Actor]:
        return self.player_units + self.player_factories

    @property
    def opp_factories(self) -> list[Factory]:
        return self.board.opp_factories

    @property
    def player_nr_lights(self) -> int:
        return self.board.player_nr_lights

    @property
    def player_nr_heavies(self) -> int:
        return self.board.player_nr_heavies

    @property
    def player_light_heavy_ratio(self) -> float:
        return self.board.player_light_heavy_ratio

    @property
    def real_env_steps(self):
        """
        the actual env step in the environment, which subtracts the time spent bidding and placing factories
        """
        if self.env_cfg.BIDDING_SYSTEM:
            # + 1 for extra factory placement and + 1 for bidding step
            return self.env_steps - (self.board.factories_per_team * 2 + 1)
        else:
            return self.env_steps

    @property
    def steps_left(self) -> int:
        return 1000 - self.real_env_steps

    def is_day(self, t: int = 0):
        if not t:
            t = self.real_env_steps

        return t % self.env_cfg.CYCLE_LENGTH < self.env_cfg.DAY_LENGTH

    @property
    def ice_coordinates(self) -> CoordinateList:
        return self.board.ice_coordinates

    @property
    def player_factory_tiles(self) -> CoordinateList:
        return self.board.player_factory_tiles

    def is_player_factory_tile(self, c: Coordinate) -> bool:
        return self.board.is_player_factory_tile(c)

    def is_opponent_factory_tile(self, c: Coordinate) -> bool:
        return self.board.is_opponent_factory_tile(c)

    def get_opponent_on_c(self, c: Coordinate) -> Optional[Unit]:
        return self.board.get_opponent_on_c(c)

    def get_closest_player_factory(self, c: Coordinate) -> Factory:
        return self.board.get_closest_player_factory(c=c)

    def get_all_closest_factory_tiles(self, c: Coordinate) -> CoordinateList:
        return self.player_factory_tiles.get_all_closest_tiles(c)

    def get_closest_player_factory_c(self, c: Coordinate) -> Coordinate:
        return self.board.get_closest_player_factory_tile(c)

    def get_closest_ice_tile(self, c: Coordinate) -> Coordinate:
        return self.board.get_closest_ice_tile(c=c)

    def get_closest_ore_tile(self, c: Coordinate) -> Coordinate:
        return self.board.get_closest_ore_tile(c=c)

    def get_closest_rubble_tile(self, c: Coordinate) -> Coordinate:
        return self.board.get_closest_rubble_tile(c=c)

    def get_n_closest_rubble_tiles(self, c: Coordinate, n: int) -> CoordinateList:
        return self.board.get_n_closest_rubble_tiles(c=c, n=n)

    def get_n_closest_opp_lichen_tiles(self, c: Coordinate, n: int) -> CoordinateList:
        return self.board.get_n_closest_opp_lichen_tiles(c=c, n=n)

    def get_n_closest_ice_tiles(self, c: Coordinate, n: int) -> CoordinateList:
        return self.board.get_n_closest_ice_tiles(c=c, n=n)

    def get_n_closest_ore_tiles(self, c: Coordinate, n: int) -> CoordinateList:
        return self.board.get_n_closest_ore_tiles(c=c, n=n)

    def get_dis_to_closest_opp_heavy(self, c: Coordinate) -> float:
        return self.board.get_min_dis_to_opp_heavy(c=c)
