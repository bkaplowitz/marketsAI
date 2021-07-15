from marketsai.economies.single_agent.capital_sa import Capital_planner


# from marketsai.markets.gm_adj import GM_adj

# import ray
from ray import tune, shutdown, init
from ray.tune.registry import register_env
from typing import Dict

# For Callbacks
from ray.rllib.agents.callbacks import DefaultCallbacks
from ray.rllib.env import BaseEnv
from ray.rllib.evaluation import MultiAgentEpisode, RolloutWorker
from ray.rllib.policy import Policy

# from ray.tune.integration.mlflow import MLflowLoggerCallback
# from ray.rllib.agents.dqn import DQNTrainer

import random
import math
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sn
import logging

# STEP 0: Global configs
date = "July12_"
test = False
plot_progress = False
algo = "PPO"
env_label = "capital_planner"
exp_label = "native_1hh_1c_"
register_env(env_label, Capital_planner)

# Macro parameters
env_horizon = 1000
n_hh = 1
n_capital = 1
beta = 0.98

# STEP 1: Parallelization options
NUM_CPUS = 9
NUM_TRIALS = 1
NUM_ROLLOUT = env_horizon * 1
NUM_ENV_PW = 1
# num_env_per_worker
NUM_GPUS = 0
BATCH_ROLLOUT = 1
NUM_MINI_BATCH = 1

n_workers = (NUM_CPUS - NUM_TRIALS) // NUM_TRIALS
batch_size = NUM_ROLLOUT * (max(n_workers, 1)) * NUM_ENV_PW * BATCH_ROLLOUT
print(n_workers, batch_size)
shutdown()
init(
    num_cpus=NUM_CPUS,
    num_gpus=NUM_GPUS,
    # logging_level=logging.ERROR,
)

# STEP 2: Experiment configuratios
if test == True:
    MAX_STEPS = 10 * batch_size
    exp_name = exp_label + env_label + "_test_" + date + algo
else:
    MAX_STEPS = 200 * batch_size
    exp_name = exp_label + env_label + "_run_" + date + algo

CHKPT_FREQ = 50

stop = {"timesteps_total": MAX_STEPS}


# Callbacks
def process_rewards(r):
    """Compute discounted reward from a vector of rewards."""
    discounted_r = np.zeros_like(r)
    running_add = 0
    for t in reversed(range(0, len(r))):
        running_add = running_add * beta + r[t]
        discounted_r[t] = running_add
    return discounted_r[0]


class MyCallbacks(DefaultCallbacks):
    def on_episode_start(
        self,
        *,
        worker: RolloutWorker,
        base_env: BaseEnv,
        policies: Dict[str, Policy],
        episode: MultiAgentEpisode,
        env_index: int,
        **kwargs
    ):
        # Make sure this episode has just been started (only initial obs
        # logged so far).
        assert episode.length == 0, (
            "ERROR: `on_episode_start()` callback should be called right "
            "after env reset!"
        )
        episode.user_data["rewards"] = []
        episode.user_data["bgt_penalty"] = []

    def on_episode_step(
        self,
        *,
        worker: RolloutWorker,
        base_env: BaseEnv,
        episode: MultiAgentEpisode,
        env_index: int,
        **kwargs
    ):
        # Make sure this episode is ongoing.
        # assert episode.length > 0, \
        #     "ERROR: `on_episode_step()` callback should not be called right " \
        #     "after env reset!"
        if episode.length > 1:
            rewards = episode.prev_reward_for()
            bgt_penalty = episode.last_info_for()["bgt_penalty"]
            episode.user_data["rewards"].append(rewards)
            episode.user_data["bgt_penalty"].append(bgt_penalty)

    def on_episode_end(
        self,
        *,
        worker: RolloutWorker,
        base_env: BaseEnv,
        policies: Dict[str, Policy],
        episode: MultiAgentEpisode,
        env_index: int,
        **kwargs
    ):
        discounted_rewards = process_rewards(episode.user_data["rewards"])
        episode.custom_metrics["discounted_rewards"] = discounted_rewards
        episode.custom_metrics["bgt_penalty"] = np.mean(
            episode.user_data["bgt_penalty"]
        )


env_config = {
    "horizon": env_horizon,
    "n_hh": n_hh,
    "n_capital": n_capital,
    "eval_mode": False,
    "max_savings": 0.8,
    "k_init": 20,
    "bgt_penalty": 1,
    "shock_values": [0.8, 1.2],
    "shock_transition": [[0.9, 0.1], [0.1, 0.9]],
    "parameters": {"delta": 0.04, "alpha": 0.3, "phi": 0.5, "beta": beta},
}

env_config_eval = env_config.copy()
env_config_eval["eval_mode"] = True

common_config = {
    "callbacks": MyCallbacks,
    # ENVIRONMENT
    "gamma": beta,
    "env": env_label,
    "env_config": env_config,
    "horizon": env_horizon,
    # MODEL
    "framework": "torch",
    # "model": tune.grid_search([{"use_lstm": True}, {"use_lstm": False}]),
    # TRAINING CONFIG
    "num_workers": n_workers,
    "create_env_on_driver": False,
    "num_gpus": NUM_GPUS / NUM_TRIALS,
    "num_envs_per_worker": NUM_ENV_PW,
    "rollout_fragment_length": NUM_ROLLOUT,
    "train_batch_size": batch_size,
    # EVALUATION
    "evaluation_interval": 10,
    "evaluation_num_episodes": 1,
    "evaluation_config": {
        "explore": False,
        "env_config": env_config_eval,
    },
}

ppo_config = {
    # "lr":0.0003
    "lr_schedule": [[0, 0.00003], [MAX_STEPS * 1 / 2, 0.00001]],
    "sgd_minibatch_size": batch_size // NUM_MINI_BATCH,
    "num_sgd_iter": NUM_MINI_BATCH,
    "batch_mode": "complete_episodes",
    "lambda": 1,
    "entropy_coeff": 0,
    "kl_coeff": 0.2,
    # "vf_loss_coeff": 0.5,
    # "vf_clip_param": 100.0,
    # "entropy_coeff_schedule": [[0, 0.01], [5120 * 1000, 0]],
    "clip_param": 0.2,
    "clip_actions": True,
}

sac_config = {
    "prioritized_replay": True,
}

if algo == "PPO":
    training_config = {**common_config, **ppo_config}
elif algo == "SAC":
    training_config = {**common_config, **sac_config}
else:
    training_config = common_config


# STEP 3: run experiment
checkpoints = []
experiments = []
analysis = tune.run(
    algo,
    name=exp_name,
    config=training_config,
    stop=stop,
    checkpoint_freq=CHKPT_FREQ,
    checkpoint_at_end=True,
    metric="episode_reward_mean",
    mode="max",
    num_samples=1,
    # resources_per_trial={"gpu": 0.5},
)

best_checkpoint = analysis.best_checkpoint
best_logdir = analysis.best_logdir
best_progress = analysis.best_dataframe
evaluation_progress = analysis.best_trial.metric_analysis[
    "evaluation/custom_metrics/discounted_rewards_mean"
]
print(list(best_progress.columns))

# STEP 4: Plot and evaluate
# Plot progress
if plot_progress == True:
    progress_plot = sn.lineplot(
        data=best_progress,
        x="episodes_total",
        y="custom_metrics/discounted_rewards_mean",
    )
    progress_plot = progress_plot.get_figure()
    progress_plot.savefig("marketsai/results/progress_plots" + exp_name + ".png")

# Plot evaluation