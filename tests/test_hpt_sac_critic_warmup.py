from __future__ import annotations

import gymnasium as gym
import numpy as np
import pytest
import torch

from sac.offline.train_hpt_voltage_sac import SupportRegularizedSAC


class _TinyContinuousEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(self) -> None:
        self.observation_space = gym.spaces.Box(-1.0, 1.0, shape=(24,), dtype=np.float32)
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(4,), dtype=np.float32)
        self.steps = 0

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        self.steps = 0
        return np.zeros(24, dtype=np.float32), {}

    def step(self, action):
        self.steps += 1
        observation = np.full(24, min(self.steps / 20.0, 1.0), dtype=np.float32)
        reward = -float(np.square(action).sum())
        return observation, reward, False, self.steps >= 20, {}


def _parameters(module) -> list[torch.Tensor]:
    return [parameter.detach().cpu().clone() for parameter in module.parameters()]


def test_critic_only_warmup_keeps_actor_fixed_and_updates_critic() -> None:
    model = SupportRegularizedSAC(
        "MlpPolicy",
        _TinyContinuousEnv(),
        learning_starts=0,
        train_freq=1,
        gradient_steps=1,
        batch_size=2,
        buffer_size=128,
        policy_kwargs={"net_arch": [16, 16]},
        seed=7,
        device="cpu",
        verbose=0,
    )
    model.set_critic_only_warmup(20)
    actor_before = _parameters(model.actor)
    critic_before = _parameters(model.critic)

    model.learn(total_timesteps=8)

    actor_after = _parameters(model.actor)
    critic_after = _parameters(model.critic)
    assert all(torch.equal(before, after) for before, after in zip(actor_before, actor_after))
    assert any(not torch.equal(before, after) for before, after in zip(critic_before, critic_after))


def test_critic_only_warmup_rejects_negative_updates() -> None:
    model = SupportRegularizedSAC(
        "MlpPolicy",
        _TinyContinuousEnv(),
        policy_kwargs={"net_arch": [8]},
        device="cpu",
        verbose=0,
    )
    with pytest.raises(ValueError, match="non-negative"):
        model.set_critic_only_warmup(-1)
