from gym.spaces import Discrete, Box, MultiDiscrete
from ray.rllib.env.multi_agent_env import MultiAgentEnv
from marketsai.agents.agents import Household, Firm
import math
import numpy as np


class DiffDemandDiscrete(MultiAgentEnv):
    """A gym compatible environment consisting of a differentiated demand.
    Firms post prices and the environment gives them back revenue
     (or, equivalenty, quantity).
    Quantity of each firm is given by:
    q_i(p)= e^((a_i-p_i)/mu) / (sum_j=1^N e^((a_j-p_j)/mu)+e^(a_0/mu)

    Inputs:
    1. config = a dictionary that ...


    Example:

    """

    def __init__(self, mkt_config={}, agents_dict={"agent_0": Firm, "agent_1": Firm}):

        # Parameters to create spaces
        self.agents_dict = agents_dict
        self.n_agents = len(self.agents_dict)
        self.gridpoints = mkt_config.get("gridpoints", 16)

        # spaces
        self.action_space = {}
        for (key, value) in self.agents_dict.items():
            self.action_space[key] = Discrete(self.gridpoints)

        self.observation_space = {}
        for (key, value) in self.agents_dict.items():
            self.observation_space[key] = MultiDiscrete(
                [self.gridpoints, self.gridpoints]
            )

        # Episodic or not
        self.finite_periods = mkt_config.get("finite_periods", False)
        self.n_periods = mkt_config.get("n_periods", 1000)

        # Paraterers of the markets
        self.parameters = mkt_config.get(
            "parameters",
            {
                "cost": [1 for i in range(self.n_agents)],
                "values": [2 for i in range(self.n_agents)],
                "ext_demand": 0,
                "substitution": 0.25,
            },
        )
        self.cost = self.parameters["cost"]
        self.values = self.parameters["values"]
        self.ext_demand = self.parameters["ext_demand"]
        self.substitution = self.parameters["substitution"]

        # Grid of possible prices
        self.lower_price = mkt_config.get("lower_price", self.cost)
        self.higher_price = mkt_config.get("higher_price", self.values)

        self.num_steps = 0

        # assert isinstance(config["gridpoint"], int)
        if not isinstance(self.gridpoints, int):
            raise TypeError("gridpoint must be integer")

    def reset(self):
        self.num_steps = 0
        self.obs = {
            "agent_{}".format(i): [
                np.uint8(np.floor(self.gridpoints / 2)) for i in range(self.n_agents)
            ]
            for i in range(self.n_agents)
        }

        return self.obs

    def step(self, action_dict):  # INPUT: Action Dictionary

        actions = list(action_dict.values())  # evaluate robustness of order

        # OUTPUT1: obs_ - Next period obs

        self.obs = {"agent_{}".format(i): [] for i in range(self.n_agents)}

        for i in range(self.n_agents):
            for j in range(self.n_agents):
                self.obs["agent_{}".format(i)].append(np.uint8(actions[j]))

        # OUTPUT2: rew: Reward Dictionary

        prices = [
            self.lower_price[i]
            + (self.higher_price[i] - self.lower_price[i])
            * (actions[i] / (self.gridpoints - 1))
            for i in range(self.n_agents)
        ]

        rewards_notnorm = [
            math.e ** ((self.values[i] - prices[i]) / self.substitution)
            for i in range(self.n_agents)
        ]

        rewards_denom = math.e ** ((self.ext_demand) / self.substitution) + np.sum(
            rewards_notnorm
        )

        rewards_list = [
            (prices[i] - self.cost[i]) * rewards_notnorm[i] / rewards_denom
            for i in range(self.n_agents)
        ]

        rew = {"agent_{}".format(i): rewards_list[i] for i in range(self.n_agents)}

        # OUTPUT3: done: True if in num_spets is higher than max periods.

        if self.finite_periods:
            done = {
                "agent_{}".format(i): self.num_steps >= self.n_periods
                for i in range(self.n_agents)
            }
            done["__all__"] = self.num_steps >= self.n_periods
        else:
            # done = {"agent_{}".format(i): False for i in range(self.n_agents)}
            done = {"__all__": False}

        # OUTPUT4: info - Info dictionary.

        info = {"agent_{}".format(i): prices[i] for i in range(self.n_agents)}

        self.num_steps += 1

        # RETURN
        return self.obs, rew, done, info


# Manual test for debugging

# PRICE_BAND_WIDE = 0.1
# LOWER_PRICE = 1.47 - PRICE_BAND_WIDE
# HIGHER_PRICE = 1.92 + PRICE_BAND_WIDE

# n_firms = 2
# env = DiffDemandDiscrete(
#     mkt_config={
#         "lower_price": [LOWER_PRICE for i in range(n_firms)],
#         "higher_price": [HIGHER_PRICE for i in range(n_firms)],
#         "gridpoint": 16,
#     },
#     agents_dict={"agent_0": Firm, "agent_1": Firm},
# )

# env.reset()
# obs_, reward, done, info = env.step({"agent_0": 7, "agent_1": 7})
# print(obs_, reward, done, info)
