import gym
from gym.spaces import Discrete, Box, MultiDiscrete, Tuple

from ray.rllib.env.multi_agent_env import MultiAgentEnv
import numpy as np
import random

# from marketsai.utils import encode
# import math


class Capital_planner_ma(MultiAgentEnv):
    """An Rllib compatible environment of capital accumulation.

    - n_hh households prduce the consumption good using n_capital capital goods.

    - Each period, each househods decide how much of production to allocate to investment in
    new capital goods. The rest is consumed and the hh's get logarithmic utility.

    -The problem is formulated as a collaborative multi-agent problem, in which one policy control all agents,
    and the reward of each agent is the mean of the utilities of all agents.

    - Capital goods are durable and have a depreciation rate delta. THe n_capital goods are boundled
    in a Coob-Douglas aggregate. In latex math, $ K = \Pi_{j=0}^{n_h-1} K_j^(1/n_capital) $

    - Each household faces two TFP shocks, an idiosyncratic shock affect only his production,
    and an aggregate shock that affects all househods.  In latex math, $ Y_i = Z^{agg} Z_i^{ind} \Pi_{j=0}^{n_h-1} K_j^(1/n_capital) $

    - The observation space includes the stock of all houeholds on all capital goods (n_hh * n_capital stocks),
    the idiosyncratic shock of each  household (n_hh shocks), and an aggreagte shock.

    - The action space for each houeholds is the proportion of final good that is to be investeed in each
    capital good (n_capital actions)

    - we index households with i, and capital goods with j.

    """

    def __init__(
        self,
        env_config={},
    ):

        # UNPACK CONFIG
        self.env_config = env_config

        # GLOBAL ENV CONFIGS
        self.horizon = self.env_config.get("horizon", 1000)
        self.n_hh = self.env_config.get("n_hh", 1)
        self.n_capital = self.env_config.get("n_capital", 1)
        self.eval_mode = self.env_config.get("eval_mode", False)
        self.analysis_mode = self.env_config.get("analysis_mode", False)
        self.max_savings = self.env_config.get("max_savings", 0.6)
        self.bgt_penalty = self.env_config.get("bgt_penalty", 1)

        self.shock_idtc_values = self.env_config.get("shock_idtc_values", [0.9, 1.1])
        self.shock_idtc_transition = self.env_config.get(
            "shock_idtc_transition", [[0.9, 0.1], [0.1, 0.9]]
        )
        self.shock_agg_values = self.env_config.get("shock_agg_values", [0.8, 1.2])
        self.shock_agg_transition = self.env_config.get(
            "shock_agg_transition", [[0.95, 0.05], [0.05, 0.95]]
        )

        # UNPACK PARAMETERS
        self.params = self.env_config.get(
            "parameters",
            {"delta": 0.04, "alpha": 0.3, "phi": 0.5, "beta": 0.98},
        )

        # STEADY STATE
        self.k_ss = (
            self.params["phi"]
            * self.params["delta"]
            * self.n_hh
            * self.n_capital
            * (
                (1 - self.params["beta"] * (1 - self.params["delta"]))
                / (self.params["alpha"] * self.params["beta"])
                + self.params["delta"] * (self.n_capital - 1) / self.n_capital
            )
        ) ** (1 / (self.params["alpha"] - 2))

        # MAX SAVING RATE PER CAPITAL GOOD
        self.max_s_ij = self.max_savings / self.n_capital * 1.5

        # SPECIFIC SHOCK VALUES THAT ARE USEFUL FOR EVALUATION
        if self.eval_mode == True:
            self.shocks_eval_agg = {0: 0}
            for t in range(1, self.horizon + 1):
                self.shocks_eval_agg[t] = (
                    1
                    if (t // (1 / self.shock_agg_transition[0][1]) + 1) % 2 == 0
                    else 0
                )
            self.shocks_eval_idtc = {0: [1 - (i % 2) for i in range(self.n_hh)]}
            for t in range(1, self.horizon + 1):
                self.shocks_eval_idtc[t] = (
                    [(i % 2) for i in range(self.n_hh)]
                    if (t // (1 / self.shock_idtc_transition[0][1]) + 1) % 2 == 0
                    else [1 - (i % 2) for i in range(self.n_hh)]
                )
        # SPECIFIC SHOCK VALUES THAT ARE USEFUL FOR EVALUATION
        if self.analysis_mode == True:
            self.shocks_analysis_agg = {0: 0}
            for t in range(1, self.horizon + 1):
                self.shocks_analysis_agg[t] = (
                    1
                    if (t // (1 / self.shock_agg_transition[0][1]) + 1) % 2 == 0
                    else 0
                )
            self.shocks_analysis_idtc = {0: [0 for i in range(self.n_hh)]}
            for t in range(1, self.horizon + 1):
                self.shocks_analysis_idtc[t] = (
                    [0 for i in range(self.n_hh)]
                    if (t // (1 / self.shock_idtc_transition[0][1]) + 1) % 2 == 0
                    else [0 for i in range(self.n_hh)]
                )

        # CREATE SPACES

        # n_actions: for each households, decide expenditure on each capital type
        self.n_actions = self.n_hh * self.n_capital
        # boundaries: actions are normalized to be between -1 and 1 (and then unsquashed)
        self.action_space = {
            f"hh_{i}": Box(low=-1.0, high=1.0, shape=(self.n_capital,))
            for i in range(self.n_hh)
        }

        # n_hh ind have stocks of n_capital goods.
        self.n_obs_stock = self.n_hh * self.n_capital
        # n_hh idtc shocks and 1 aggregate shock
        self.n_obs_shock_idtc = self.n_hh
        self.observation_space = {
            f"hh_{i}": Tuple(
                [
                    Box(
                        low=0.0,
                        high=float("inf"),
                        shape=(self.n_obs_stock,),
                    ),
                    MultiDiscrete(
                        [
                            len(self.shock_idtc_values)
                            for i in range(self.n_obs_shock_idtc)
                        ]
                    ),
                    Discrete(len(self.shock_agg_values)),
                ]
            )
            for i in range(self.n_hh)
        }

        self.timestep = None

    def reset(self):
        """Rreset function
        it specifies three types of initial obs. Random (default),
        for evaluation, and for posterior analysis"""

        self.timestep = 0

        # to evaluate policies, we fix the initial observation
        if self.eval_mode == True:
            k_init = np.array(
                [
                    self.k_ss * 0.9 if i % 2 == 0 else self.k_ss * 0.8
                    for i in range(self.n_hh * self.n_capital)
                ],
                dtype=float,
            )

            shocks_idtc_init = self.shocks_eval_idtc[0]
            shock_agg_init = self.shocks_eval_agg[0]

        elif self.analysis_mode == True:
            k_init = np.array(
                [
                    self.k_ss * 0.9 if i % 2 == 0 else self.k_ss * 0.8
                    for i in range(self.n_hh * self.n_capital)
                ],
                dtype=float,
            )

            shocks_idtc_init = self.shocks_analysis_idtc[0]
            shock_agg_init = self.shocks_analysis_agg[0]

        # DEFAULT: when learning, we randomize the initial observations
        else:
            k_init = np.array(
                [
                    random.uniform(self.k_ss * 0.5, self.k_ss * 1.25)
                    for i in range(self.n_hh * self.n_capital)
                ],
                dtype=float,
            )

            shocks_idtc_init = np.array(
                [
                    random.choices(list(range(len(self.shock_idtc_values))))[0]
                    for i in range(self.n_hh)
                ]
            )
            shock_agg_init = random.choices(list(range(len(self.shock_idtc_values))))[0]

        # Now we need to reorganize the state so each firm observes his own state first.
        # First, organize stocks as list of lists, where inner list [i] reflect stocks for  hh with index i.
        k_ij_init = [
            list(k_init[i * self.n_capital : i * self.n_capital + self.n_capital])
            for i in range(self.n_hh)
        ]

        k_ij_init_perfirm = [[] for i in range(self.n_hh)]
        k_init_perfirm = [[] for i in range(self.n_hh)]
        shocks_idtc_init_perfirm = [[] for i in range(self.n_hh)]

        # put your own state first
        for i in range(self.n_hh):
            k_ij_init_perfirm[i] = [k_ij_init[i]] + [
                x for z, x in enumerate(k_ij_init) if z != i
            ]
            k_init_perfirm[i] = [
                item for sublist in k_ij_init_perfirm[i] for item in sublist
            ]
            shocks_idtc_init_perfirm[i] = [shocks_idtc_init[i]] + [
                x for z, x in enumerate(shocks_idtc_init) if z != i
            ]

        # create Dictionary wtih agents as keys and with Tuple spaces as values
        self.obs_ = {
            f"hh_{i}": (k_init_perfirm[i], shocks_idtc_init_perfirm[i], shock_agg_init)
            for i in range(self.n_hh)
        }
        return self.obs_

    def step(self, action_dict):  # INPUT: Action Dictionary
        """
        STEP FUNCTION
        0. update recursive structure (e.g. k=k_next)
        1. Preprocess acrion space (e.g. unsquash and create useful variables such as production y)
        2. Calculate obs_next (e.g. calculate k_next and update shocks by evaluation a markoc chain)
        3. Calculate Rewards (e.g., calculate the logarithm of consumption and budget penalties)
        4. Create Info (e.g., create a dictionary with useful data per agent)

        """
        # 0. UPDATE recursive structure

        self.timestep += 1
        k = self.obs_["hh_0"][
            0
        ]  # we take the ordering of the first agents as the global ordering.
        shocks_idtc_id = self.obs_["hh_0"][1]
        shock_agg_id = self.obs_["hh_0"][2]

        # go from shock_id (e.g. 0) to shock value (e.g. 0.8)
        shocks_idtc = [
            self.shock_idtc_values[shocks_idtc_id[i]] for i in range(self.n_hh)
        ]
        shock_agg = self.shock_agg_values[shock_agg_id]

        # 1. PREPROCESS action and state

        # unsquash action
        s_ij = [
            [
                (action_dict[f"hh_{i}"][j] + 1) / 2 * self.max_s_ij
                for j in range(self.n_capital)
            ]
            for i in range(self.n_hh)
        ]

        # coorect if bgt constraint is violated
        bgt_penalty_ind = [0 for i in range(self.n_hh)]  # only for info
        for i in range(self.n_hh):
            if np.sum(s_ij[i]) > 1:
                s_ij[i] = [s_ij[i][j] / np.sum(s_ij[i]) for j in range(self.n_capital)]
                bgt_penalty_ind[i] = 1

        # organize per houehold per firm and create capital bundle
        k_ij = [
            list(k[i * self.n_capital : i * self.n_capital + self.n_capital])
            for i in range(self.n_hh)
        ]
        k_bundle_i = [1 for i in range(self.n_hh)]
        for i in range(self.n_hh):
            for j in range(self.n_capital):
                k_bundle_i[i] *= k_ij[i][j] ** (1 / self.n_capital)

        # Useful variables
        y_i = [
            shocks_idtc[i] * shock_agg * k_bundle_i[i] ** self.params["alpha"]
            for i in range(self.n_hh)
        ]

        c_i = [y_i[i] * (1 - np.sum(s_ij[i])) for i in range(self.n_hh)]

        utility_i = [
            np.log(c_i[i]) if c_i[i] > 0 else -self.bgt_penalty
            for i in range(self.n_hh)
        ]

        inv_exp_ij = [
            [s_ij[i][j] * y_i[i] for j in range(self.n_capital)]
            for i in range(self.n_hh)
        ]  # in utility, if bgt constraint is violated, c[i]=0, so penalty

        inv_exp_j = [
            np.sum([inv_exp_ij[i][j] for i in range(self.n_hh)])
            for j in range(self.n_capital)
        ]
        inv_j = [
            np.sqrt((2 / self.params["phi"]) * inv_exp_j[j])
            for j in range(self.n_capital)
        ]

        inv_ij = [
            [
                (inv_exp_ij[i][j] / max(inv_exp_j[j], 0.0001)) * inv_j[j]
                for j in range(self.n_capital)
            ]
            for i in range(self.n_hh)
        ]

        # 2. NEXT OBS
        k_ij_new = [
            [
                k_ij[i][j] * (1 - self.params["delta"]) + inv_ij[i][j]
                for j in range(self.n_capital)
            ]
            for i in range(self.n_hh)
        ]
        # update shock
        if self.eval_mode == True:
            shocks_idtc_id_new = np.array(self.shocks_eval_idtc[self.timestep])
            shock_agg_id_new = self.shocks_eval_agg[self.timestep]
        elif self.analysis_mode == True:
            shocks_idtc_id_new = np.array(self.shocks_analysis_idtc[self.timestep])
            shock_agg_id_new = self.shocks_analysis_agg[self.timestep]
        else:
            shocks_idtc_id_new = np.array(
                [
                    random.choices(
                        list(range(len(self.shock_idtc_values))),
                        weights=self.shock_idtc_transition[shocks_idtc_id[i]],
                    )[0]
                    for i in range(self.n_hh)
                ]
            )
            shock_agg_id_new = random.choices(
                list(range(len(self.shock_agg_values))),
                weights=self.shock_agg_transition[shock_agg_id],
            )[0]

        # reorganize state so each hh sees his state first
        k_ij_new_perfirm = [[] for i in range(self.n_hh)]
        k_new_perfirm = [[] for i in range(self.n_hh)]
        shocks_idtc_id_new_perfirm = [[] for i in range(self.n_hh)]
        # put your own state first

        for i in range(self.n_hh):
            k_ij_new_perfirm[i] = [k_ij_new[i]] + [
                x for z, x in enumerate(k_ij_new) if z != i
            ]
            k_new_perfirm[i] = [
                item for sublist in k_ij_new_perfirm[i] for item in sublist
            ]
            shocks_idtc_id_new_perfirm[i] = [shocks_idtc_id_new[i]] + [
                x for z, x in enumerate(shocks_idtc_id_new) if z != i
            ]
        # create Tuple
        self.obs_ = {
            f"hh_{i}": (
                k_new_perfirm[i],
                shocks_idtc_id_new_perfirm[i],
                shock_agg_id_new,
            )
            for i in range(self.n_hh)
        }

        # 3. CALCUALTE REWARD
        rew = {f"hh_{i}": np.mean(utility_i) for i in range(self.n_hh)}

        # DONE FLAGS
        if self.timestep < self.horizon:
            done = {"__all__": False}
        else:
            done = {"__all__": True}

        # 4. CREATE INFO

        # The info of the first household contain global info, to make it easy to retrieve
        if self.analysis_mode == False:
            info = {}
        else:
            info_global = {
                "hh_0": {
                    "savings": s_ij,
                    "reward": np.mean(utility_i),
                    "income": y_i,
                    "consumption": c_i,
                    "bgt_penalty": bgt_penalty_ind,
                    "capital": k_ij,
                    "capital_new": k_ij_new,
                }
            }

            info_ind = {
                f"hh_{i}": {
                    "savings": s_ij[i],
                    "reward": np.mean(utility_i),
                    "income": y_i[i],
                    "consumption": c_i[i],
                    "bgt_penalty": bgt_penalty_ind[i],
                    "capital": k_ij[i],
                    "capital_new": k_ij_new[i],
                }
                for i in range(1, self.n_hh)
            }

            info = {**info_global, **info_ind}

        # RETURN

        return self.obs_, rew, done, info


""" TEST AND DEBUG CODE """


def main():
    env = Capital_planner_ma(
        env_config={
            "horizon": 200,
            "n_hh": 2,
            "n_capital": 2,
            "eval_mode": False,
            "max_savings": 0.6,
            "bgt_penalty": 100,
            "shock_idtc_values": [0.9, 1.1],
            "shock_idtc_transition": [[0.9, 0.1], [0.1, 0.9]],
            "shock_agg_values": [0.8, 1.2],
            "shock_agg_transition": [[0.95, 0.05], [0.05, 0.95]],
            "parameters": {"delta": 0.04, "alpha": 0.33, "phi": 0.5, "beta": 0.98},
        },
    )

    env.reset()
    print("k_ss:", env.k_ss, "y_ss:", env.k_ss ** env.params["alpha"])
    print("obs", env.obs_)

    for i in range(20):
        obs, rew, done, info = env.step(
            {
                f"hh_{i}": np.array(
                    [np.random.uniform(-1, 1) for i in range(env.n_capital)]
                )
                for i in range(env.n_hh)
            }
        )

        print("obs", obs)
        # print("rew", rew)
        # print("info", info)


if __name__ == "__main__":
    main()
