import gym
from gym.spaces import Discrete, Box, MultiDiscrete, Tuple

# from ray.rllib.env.multi_agent_env import MultiAgentEnv
from marketsai.functions.functions import MarkovChain, CRRA
import numpy as np
import random

# from marketsai.utils import encode
# import math


class Durable_sgm(gym.Env):
    """An gym compatible environment consisting of a durable good consumption and production problem
    The agent chooses how much to produce of a durable good subject to quadratci costs.

    """

    def __init__(
        self,
        env_config={},
    ):

        # UNPACK CONFIG
        self.env_config = env_config


        # UNPACK PARAMETERS
        self.params = self.env_config.get(
            "parameters",
            {"depreciation": 0.04, "alpha": 0.33, "tfp": 1},
        )

        # WE CREATE SPACES
        self.max_saving = self.env_config.get("max_saving", 0.2)
        self.action_space = Box(low=np.array([-1]), high=np.array([1]), shape=(1,))

        # self.observation_space = Box(
        #     low=np.array([0, 0]), high=np.array([2, 2]), shape=(2,), dtype=np.float32
        # )

        self.observation_space = Box(
            low=np.array([0]),
            high=np.array([float("inf")]),
            shape=(1,),
        )

        self.utility_function = env_config.get("utility_function", CRRA(coeff=2))

    def reset(self):

        k_init = np.array(
            random.choices(
                [0.01, 5, 7, 9, 11, 15],
                weights=[0.3, 0.15, 0.15, 0.15, 0.15, 0.1],
            )
        )
        self.obs_ = k_init

        return self.obs_

    def step(self, action):  # INPUT: Action Dictionary

        # UPDATE recursive structure
        k_old = self.obs_[0]

        # PREPROCESS action and state
        s = (action[0] + 1) / 2 * self.max_saving
        y = max(self.params["tfp"] * k_old ** self.params["alpha"], 0.00001)

        k = min(
            k_old * (1 - self.params["depreciation"]) + s,
            np.float(self.observation_space.high),
        )

        # NEXT OBS
        self.obs_ = np.array([k], dtype=np.float32)

        # REWARD
        rew = max(self.utility_function(max(y * (1 - s), 0.00001)) + 1, -1000)

        # rew = self.utility_function(h) - self.params["adj_cost"] * inv ** 2

        # DONE FLAGS
        done = False

        # ADDITION INFO
        info = {
            "savings_rate": s,
            "rewards": rew,
            "income": y,
            "capital_old": k_old,
            "capital_new": k,
        }

        # RETURN
        return self.obs_, rew, done, info


# Manual test for debugging

# env = Durable_sgm(
#     env_config={
#         "parameters": {"depreciation": 0.02, "alpha": 0.33, "tfp": 1},
#     },
# )

# env.reset()
# for i in range(100):
#     obs_, reward, done, info = env.step(np.array([random.uniform(a=-1.0, b=1.0)]))
#     print(info)
