import numpy as np
import pandas as pd

from scipy.optimize import linear_sum_assignment

from lux.kit import obs_to_game_state
from lux.config import EnvConfig
from lux.utils import is_my_turn_to_place_factory
from objects.game_state import GameState
from objects.unit import Unit
from objects.action_plan import ActionPlan
from logic.early_setup import get_factory_spawn_loc
from logic.goal import Goal, GoalCollection


class Agent:
    def __init__(self, player: str, env_cfg: EnvConfig) -> None:
        self.player = player
        self.opp_player = "player_1" if self.player == "player_0" else "player_0"
        np.random.seed(0)
        self.env_cfg: EnvConfig = env_cfg
        self.prev_steps_goals: dict[str, Goal] = {}

    def early_setup(self, step: int, obs, remainingOverageTime: int = 60):
        game_state = obs_to_game_state(step, self.env_cfg, obs, self.player, self.opp_player)

        if step == 0:
            return dict(faction="AlphaStrike", bid=0)
        else:
            if is_my_turn_to_place_factory(game_state, step):
                spawn_loc = get_factory_spawn_loc(obs)
                return dict(spawn=spawn_loc, metal=150, water=150)
            return dict()

    def act(self, step: int, obs, remainingOverageTime: int = 60):

        """
        optionally do forward simulation to simulate positions of units, lichen, etc. in the future
        from lux.forward_sim import forward_sim
        forward_obs = forward_sim(obs, self.env_cfg, n=2)
        forward_game_states = [obs_to_game_state(step + i, self.env_cfg, f_obs) for i, f_obs in enumerate(forward_obs)]
        """
        game_state = obs_to_game_state(step, self.env_cfg, obs, self.player, self.opp_player)
        factory_actions = self.get_factory_actions(game_state)
        unit_actions = self.get_unit_actions(game_state)

        actions = factory_actions | unit_actions
        return actions

    def get_factory_actions(self, game_state: GameState) -> dict[str, list[np.ndarray]]:
        actions = dict()
        for factory in game_state.player_factories:
            action = factory.act(game_state=game_state)
            if isinstance(action, int):
                actions[factory.unit_id] = action

        return actions

    def get_unit_actions(self, game_state: GameState) -> dict[str, list[np.ndarray]]:
        unit_goal_collections = []

        for unit in game_state.player_units:
            if unit.has_actions_in_queue:
                last_step_goal = self.prev_steps_goals[unit.unit_id]
                last_step_goal.action_plan = ActionPlan(original_actions=unit.action_queue, unit=unit)
                last_step_goal._value = 1_000_000
                unit_goal_collection = (unit, GoalCollection([last_step_goal]))
            else:
                goal_collection = unit.generate_goals(game_state=game_state)
                goal_collection.generate_and_evaluate_action_plans(game_state=game_state)
                unit_goal_collection = (unit, goal_collection)
                if unit.unit_id in self.prev_steps_goals:
                    del self.prev_steps_goals[unit.unit_id]

            unit_goal_collections.append(unit_goal_collection)

        unit_goals = resolve_goal_conflicts(unit_goal_collections)
        best_action_plans = pick_best_collective_action_plan(unit_goals)
        unit_actions = {
            unit_id: plan.to_action_arrays()
            for unit_id, plan in best_action_plans.items()
            if unit_id not in self.prev_steps_goals and plan.actions
        }

        self._update_prev_step_goals(unit_goals)

        return unit_actions

    def _update_prev_step_goals(self, unit_goal_collections: list[tuple[Unit, Goal]]) -> None:
        self.prev_steps_goals = {unit.unit_id: goal for unit, goal in unit_goal_collections}


def resolve_goal_conflicts(unit_goal_collections: list[tuple[Unit, GoalCollection]]) -> list[tuple[Unit, Goal]]:
    if not unit_goal_collections:
        return []

    cost_matrix = _create_cost_matrix(unit_goal_collections)
    goal_keys = _solve_sum_assigment_problem(cost_matrix)
    unit_goals = _get_unit_goals(unit_goal_collections=unit_goal_collections, goal_keys=goal_keys)
    unit_goals = [(u, g) for u, g in unit_goals if g]

    return unit_goals


def _create_cost_matrix(unit_goal_collections: list[tuple[Unit, GoalCollection]]) -> pd.DataFrame:
    entries = [goal_collection.get_key_values() for _, goal_collection in unit_goal_collections]
    value_matrix = pd.DataFrame(entries)
    cost_matrix = -1 * value_matrix
    cost_matrix = cost_matrix.fillna(np.inf)

    return cost_matrix


def _solve_sum_assigment_problem(cost_matrix: pd.DataFrame) -> list[str]:
    rows, cols = linear_sum_assignment(cost_matrix)
    goal_keys = []
    for i in range(len(cost_matrix)):
        if i not in rows:
            goal_keys.append(None)
        else:
            index_ = np.argmax(rows == 4)
            c = cols[index_]
            goal_keys.append(cost_matrix.columns[c])

    goal_keys = [cost_matrix.columns[c] for c in cols]
    return goal_keys


def _get_unit_goals(
    unit_goal_collections: list[tuple[Unit, GoalCollection]], goal_keys: list[str]
) -> list[tuple[Unit, Goal]]:
    return [
        (unit, goal_collection.get_goal(goal))
        for goal, (unit, goal_collection) in zip(goal_keys, unit_goal_collections)
    ]


def pick_best_collective_action_plan(unit_goals: list[tuple[Unit, Goal]]) -> dict[str, ActionPlan]:
    # TODO
    best_action_plan = dict()
    for unit, goal in unit_goals:
        if goal:
            best_action_plan[unit.unit_id] = goal.action_plan

    return best_action_plan
