"""Train the HPT voltage-regulation/FRT-transition SAC actor.

This runner is intentionally separate from the FRT SAC runners.  It trains on
the averaged HPT surrogate and exports an actor that matches the Simulink
deployment contract: 24-D observation, 4-D modulation action.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch as th
import torch.nn.functional as F
from stable_baselines3 import SAC
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.utils import constant_fn, polyak_update
from stable_baselines3.common.vec_env import DummyVecEnv
from stable_baselines3.sac.policies import Actor, SACPolicy

def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


ROOT = _repo_root()
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sac.hpt_voltage_sac_env import (
    ACT_DIM_HPT,
    DEFAULT_PROXY_CALIBRATION,
    OBS_DIM_HPT,
    HPTVoltageEnvConfig,
    HPTVoltageScenario,
    HPTVoltageSACEnv,
    _neg_seq_for_fault,
    default_hpt_voltage_scenarios,
)
from sac.export_hpt_sac_actor import export_hpt_actor
from sac.experiment_metadata import write_experiment_metadata
from sac.expert_workspace import expert_workspace
from sac.runtime_utils import pick_device
from sac.summaries.summarize_sac_reward_traces import summarize_sac_reward_traces


RESULTS = ROOT / "lab" / "results"
MODELS = ROOT / "data" / "models"
SIMULINK_V2 = ROOT / "simulink"
TOPOLOGY_MODELS = {
    "topology1": SIMULINK_V2 / "topology1" / "hpt_v2_1to1_switchlevel.slx",
    "topology2": SIMULINK_V2 / "topology2" / "hpt_v2_topology2_paper.slx",
}


def scale_physical_actions_to_unit_box(
    actions: np.ndarray,
    action_low: np.ndarray,
    action_high: np.ndarray,
) -> np.ndarray:
    """Map environment actions to the squashed actor's ``[-1, 1]`` space.

    Stable-Baselines3's ``Actor.forward`` returns normalized tanh actions,
    while datasets and ``model.predict`` use physical environment actions.
    Any loss evaluated directly on ``Actor.forward`` must therefore scale its
    physical targets first.
    """

    values = np.asarray(actions, dtype=np.float32)
    low = np.asarray(action_low, dtype=np.float32)
    high = np.asarray(action_high, dtype=np.float32)
    span = high - low
    if np.any(span <= 0):
        raise ValueError("Action-space upper bounds must exceed lower bounds")
    scaled = 2.0 * (values - low) / span - 1.0
    return np.clip(scaled, -1.0, 1.0).astype(np.float32)


class SplitBridgeHead(th.nn.Module):
    """Separate final heads for regulating and energy bridge commands."""

    def __init__(self, latent_dim: int, reg_dim: int = 2, energy_dim: int = 2):
        super().__init__()
        self.reg_head = th.nn.Linear(latent_dim, reg_dim)
        self.energy_head = th.nn.Linear(latent_dim, energy_dim)

    def forward(self, latent: th.Tensor) -> th.Tensor:
        return th.cat((self.reg_head(latent), self.energy_head(latent)), dim=-1)


class SplitHeadSACActor(Actor):
    """SAC actor with independent reg and energy output heads."""

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        action_dim = int(np.prod(self.action_space.shape))
        if action_dim != ACT_DIM_HPT:
            raise ValueError(
                f"SplitHeadSACActor expects {ACT_DIM_HPT} actions, got {action_dim}"
            )
        if self.use_sde:
            raise ValueError("Split-head SAC actor is only implemented for non-SDE SAC")
        latent_dim = int(self.net_arch[-1]) if len(self.net_arch) > 0 else int(self.features_dim)
        self.mu = SplitBridgeHead(latent_dim)
        self.log_std = SplitBridgeHead(latent_dim)  # type: ignore[assignment]


class SplitHeadSACPolicy(SACPolicy):
    """SAC policy with separate final output heads for HPT bridge groups."""

    def make_actor(self, features_extractor: Any | None = None) -> SplitHeadSACActor:
        actor_kwargs = self._update_features_extractor(self.actor_kwargs, features_extractor)
        return SplitHeadSACActor(**actor_kwargs).to(self.device)


class SupportRegularizedSAC(SAC):
    """SAC with an in-update actor support penalty.

    This is a BRAC-style actor regularizer: SAC remains the policy update, but
    the actor is discouraged from leaving a switch-supported action region.
    The support samples are collected from a validated warm-start actor and are
    used inside every actor optimization step, not as a post-hoc BC repair.
    """

    support_regularization_weight: float
    support_regularization_batch_size: int
    support_regularization_nearest_replay: bool

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.support_regularization_weight = 0.0
        self.support_regularization_batch_size = 256
        self.support_regularization_nearest_replay = False
        self.energy_head_only_actor_update = False
        self.critic_only_warmup_updates = 0
        self._support_obs: th.Tensor | None = None
        self._support_actions: th.Tensor | None = None
        self._support_action_weights: th.Tensor | None = None

    def _excluded_save_params(self) -> list[str]:
        excluded = super()._excluded_save_params()
        return excluded + ["_support_obs", "_support_actions", "_support_action_weights"]

    def set_support_regularization(
        self,
        observations: np.ndarray,
        actions: np.ndarray,
        *,
        weight: float,
        batch_size: int,
        action_weights: tuple[float, ...],
        nearest_replay: bool = False,
    ) -> None:
        if observations.ndim != 2 or observations.shape[1] != OBS_DIM_HPT:
            raise ValueError(
                f"Support observations must have shape (n, {OBS_DIM_HPT}), "
                f"got {observations.shape}"
            )
        if actions.ndim != 2 or actions.shape[1] != ACT_DIM_HPT:
            raise ValueError(
                f"Support actions must have shape (n, {ACT_DIM_HPT}), got {actions.shape}"
            )
        if len(action_weights) != ACT_DIM_HPT:
            raise ValueError("Support action weights must contain four values")
        self.support_regularization_weight = float(weight)
        self.support_regularization_batch_size = int(max(1, batch_size))
        self.support_regularization_nearest_replay = bool(nearest_replay)
        self._support_obs = th.as_tensor(observations, dtype=th.float32, device=self.device)
        scaled_actions = scale_physical_actions_to_unit_box(
            actions,
            np.asarray(self.action_space.low, dtype=np.float32),
            np.asarray(self.action_space.high, dtype=np.float32),
        )
        self._support_actions = th.as_tensor(
            scaled_actions,
            dtype=th.float32,
            device=self.device,
        )
        self._support_action_weights = th.as_tensor(
            action_weights, dtype=th.float32, device=self.device
        ).reshape(1, ACT_DIM_HPT)

    def set_energy_head_only_actor_update(self, enabled: bool) -> None:
        """Restrict SAC actor updates to the split-head energy output head.

        The regulating head and shared policy trunk are kept fixed so that a
        dq-seeded voltage-survival trajectory is not destroyed while SAC tunes
        the DC-link/energy branch.  This is only meaningful for
        ``SplitHeadSACPolicy`` where ``mu.energy_head`` exists.
        """

        self.energy_head_only_actor_update = bool(enabled)

    def set_critic_only_warmup(self, updates: int) -> None:
        """Keep a warm-start actor fixed while a fresh critic learns its scale."""

        if updates < 0:
            raise ValueError("Critic-only warm-up updates must be non-negative")
        self.critic_only_warmup_updates = int(updates)

    def _apply_actor_update_mask(self) -> None:
        if not self.energy_head_only_actor_update:
            return
        for name, parameter in self.actor.named_parameters():
            if "mu.energy_head" not in name:
                parameter.grad = None

    def _sample_support_batch(self) -> tuple[th.Tensor, th.Tensor, th.Tensor] | None:
        if (
            self.support_regularization_weight <= 0
            or self._support_obs is None
            or self._support_actions is None
            or self._support_action_weights is None
        ):
            return None
        count = int(self._support_obs.shape[0])
        if count <= 0:
            return None
        batch_size = min(int(self.support_regularization_batch_size), count)
        idx = th.randint(0, count, (batch_size,), device=self.device)
        return self._support_obs[idx], self._support_actions[idx], self._support_action_weights

    def train(self, gradient_steps: int, batch_size: int = 64) -> None:
        # This mirrors the installed SB3 SAC implementation, with one added
        # actor regularization term. Keeping the structure local makes the
        # experiment reproducible even if later SB3 versions change internals.
        self.policy.set_training_mode(True)
        optimizers = [self.actor.optimizer, self.critic.optimizer]
        if self.ent_coef_optimizer is not None:
            optimizers += [self.ent_coef_optimizer]
        self._update_learning_rate(optimizers)

        ent_coef_losses, ent_coefs = [], []
        actor_losses, actor_base_losses = [], []
        actor_update_enabled = []
        critic_losses = []
        support_losses, support_weighted_losses = [], []
        replay_support_losses, replay_support_weighted_losses = [], []

        for gradient_step in range(gradient_steps):
            replay_data = self.replay_buffer.sample(  # type: ignore[union-attr]
                batch_size, env=self._vec_normalize_env
            )

            if self.use_sde:
                self.actor.reset_noise()

            actions_pi, log_prob = self.actor.action_log_prob(replay_data.observations)
            log_prob = log_prob.reshape(-1, 1)

            ent_coef_loss = None
            if self.ent_coef_optimizer is not None and self.log_ent_coef is not None:
                ent_coef = th.exp(self.log_ent_coef.detach())
                ent_coef_loss = -(
                    self.log_ent_coef * (log_prob + self.target_entropy).detach()
                ).mean()
                ent_coef_losses.append(ent_coef_loss.item())
            else:
                ent_coef = self.ent_coef_tensor
            ent_coefs.append(ent_coef.item())

            if ent_coef_loss is not None and self.ent_coef_optimizer is not None:
                self.ent_coef_optimizer.zero_grad()
                ent_coef_loss.backward()
                self.ent_coef_optimizer.step()

            with th.no_grad():
                next_actions, next_log_prob = self.actor.action_log_prob(
                    replay_data.next_observations
                )
                next_q_values = th.cat(
                    self.critic_target(replay_data.next_observations, next_actions), dim=1
                )
                next_q_values, _ = th.min(next_q_values, dim=1, keepdim=True)
                next_q_values = next_q_values - ent_coef * next_log_prob.reshape(-1, 1)
                target_q_values = (
                    replay_data.rewards
                    + (1 - replay_data.dones) * self.gamma * next_q_values
                )

            current_q_values = self.critic(replay_data.observations, replay_data.actions)
            critic_loss = 0.5 * sum(
                F.mse_loss(current_q, target_q_values) for current_q in current_q_values
            )
            assert isinstance(critic_loss, th.Tensor)
            critic_losses.append(critic_loss.item())

            self.critic.optimizer.zero_grad()
            critic_loss.backward()
            self.critic.optimizer.step()

            q_values_pi = th.cat(self.critic(replay_data.observations, actions_pi), dim=1)
            min_qf_pi, _ = th.min(q_values_pi, dim=1, keepdim=True)
            actor_base_loss = (ent_coef * log_prob - min_qf_pi).mean()
            actor_loss = actor_base_loss
            support_batch = self._sample_support_batch()
            if support_batch is not None:
                support_obs, support_actions, support_action_weights = support_batch
                support_pred = self.actor(support_obs, deterministic=True)
                support_loss = (
                    (support_pred - support_actions).pow(2) * support_action_weights
                ).mean()
                support_weighted_loss = (
                    float(self.support_regularization_weight) * support_loss
                )
                actor_loss = actor_loss + support_weighted_loss
                support_losses.append(float(support_loss.detach().cpu().item()))
                support_weighted_losses.append(
                    float(support_weighted_loss.detach().cpu().item())
                )
            else:
                support_losses.append(0.0)
                support_weighted_losses.append(0.0)

            if (
                self.support_regularization_nearest_replay
                and self.support_regularization_weight > 0
                and self._support_obs is not None
                and self._support_actions is not None
                and self._support_action_weights is not None
            ):
                with th.no_grad():
                    distances = th.cdist(
                        replay_data.observations.detach(),
                        self._support_obs.detach(),
                    )
                    nearest_idx = th.argmin(distances, dim=1)
                    nearest_actions = self._support_actions[nearest_idx]
                replay_support_pred = self.actor(
                    replay_data.observations,
                    deterministic=True,
                )
                replay_support_loss = (
                    (replay_support_pred - nearest_actions).pow(2)
                    * self._support_action_weights
                ).mean()
                replay_support_weighted_loss = (
                    float(self.support_regularization_weight) * replay_support_loss
                )
                actor_loss = actor_loss + replay_support_weighted_loss
                replay_support_losses.append(
                    float(replay_support_loss.detach().cpu().item())
                )
                replay_support_weighted_losses.append(
                    float(replay_support_weighted_loss.detach().cpu().item())
                )
            else:
                replay_support_losses.append(0.0)
                replay_support_weighted_losses.append(0.0)

            actor_base_losses.append(float(actor_base_loss.detach().cpu().item()))
            actor_losses.append(float(actor_loss.detach().cpu().item()))

            update_actor = (
                self._n_updates + gradient_step >= self.critic_only_warmup_updates
            )
            actor_update_enabled.append(float(update_actor))
            if update_actor:
                self.actor.optimizer.zero_grad()
                actor_loss.backward()
                self._apply_actor_update_mask()
                self.actor.optimizer.step()

            if gradient_step % self.target_update_interval == 0:
                polyak_update(self.critic.parameters(), self.critic_target.parameters(), self.tau)
                polyak_update(self.batch_norm_stats, self.batch_norm_stats_target, 1.0)

        self._n_updates += gradient_steps

        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/ent_coef", np.mean(ent_coefs))
        self.logger.record("train/actor_loss", np.mean(actor_losses))
        self.logger.record("train/actor_base_loss", np.mean(actor_base_losses))
        self.logger.record("train/critic_loss", np.mean(critic_losses))
        self.logger.record("train/support_actor_loss", np.mean(support_losses))
        self.logger.record("train/support_actor_weighted_loss", np.mean(support_weighted_losses))
        self.logger.record("train/replay_support_actor_loss", np.mean(replay_support_losses))
        self.logger.record(
            "train/replay_support_actor_weighted_loss",
            np.mean(replay_support_weighted_losses),
        )
        self.logger.record("train/support_actor_weight", self.support_regularization_weight)
        self.logger.record(
            "train/actor_update_enabled_fraction", np.mean(actor_update_enabled)
        )
        self.logger.record(
            "train/critic_only_warmup_updates", self.critic_only_warmup_updates
        )
        self.logger.record(
            "train/energy_head_only_actor_update",
            float(self.energy_head_only_actor_update),
        )
        if len(ent_coef_losses) > 0:
            self.logger.record("train/ent_coef_loss", np.mean(ent_coef_losses))


class RewardTraceCallback(BaseCallback):
    """Record per-episode SAC rewards for convergence figures."""

    def __init__(self) -> None:
        super().__init__()
        self._returns: list[float] = []
        self._lengths: list[int] = []
        self._cost_sums: list[dict[str, float]] = []
        self._maxima: list[dict[str, float]] = []
        self._last_n_updates = -1
        self.rows: list[dict] = []
        self.train_rows: list[dict] = []

    @staticmethod
    def _finite(value, default: float = float("nan")) -> float:
        try:
            out = float(value)
        except (TypeError, ValueError):
            return default
        return out if np.isfinite(out) else default

    def _on_training_start(self) -> None:
        n_envs = int(getattr(self.training_env, "num_envs", 1))
        self._returns = [0.0 for _ in range(n_envs)]
        self._lengths = [0 for _ in range(n_envs)]
        self._cost_sums = [self._new_cost_sums() for _ in range(n_envs)]
        self._maxima = [self._new_maxima() for _ in range(n_envs)]

    @staticmethod
    def _new_cost_sums() -> dict[str, float]:
        return {
            "cost_tracking_sum": 0.0,
            "cost_unbalance_sum": 0.0,
            "cost_vdc_soft_sum": 0.0,
            "cost_vdc_bounds_sum": 0.0,
            "cost_vdc_lower_barrier_sum": 0.0,
            "cost_envelope_sum": 0.0,
            "cost_fault_band_sum": 0.0,
            "cost_recovery_sum": 0.0,
            "cost_topology2_dynamic_sum": 0.0,
            "cost_calibrated_survival_sum": 0.0,
            "cost_support_sum": 0.0,
            "cost_support_for_reward_sum": 0.0,
            "cost_reactive_shortfall_sum": 0.0,
            "cost_reactive_wrong_sign_sum": 0.0,
            "cost_grid_current_sum": 0.0,
            "cost_reg_action_sum": 0.0,
            "cost_energy_action_sum": 0.0,
            "cost_slew_sum": 0.0,
            "cost_safety_sum": 0.0,
            "cost_teacher_gap_sum": 0.0,
            "cost_action_limit_sum": 0.0,
        }

    @staticmethod
    def _new_maxima() -> dict[str, float]:
        return {
            "action_max_abs_max": 0.0,
            "raw_action_max_abs_max": 0.0,
            "projection_delta_norm_max": 0.0,
            "support_violation_max": 0.0,
            "safety_gap_max": 0.0,
            "envelope_violation_max_seen_pu": 0.0,
            "fault_band_violation_max_seen_pu": 0.0,
            "recovery_violation_max_seen_pu": 0.0,
        }

    def _record_train_diagnostics(self) -> None:
        n_updates = int(getattr(self.model, "_n_updates", -1))
        if n_updates <= self._last_n_updates:
            return
        self._last_n_updates = n_updates
        logger_values = getattr(getattr(self.model, "logger", None), "name_to_value", {}) or {}
        row = {
            "timesteps": int(self.num_timesteps),
            "n_updates": n_updates,
            "actor_loss": self._finite(logger_values.get("train/actor_loss")),
            "actor_base_loss": self._finite(logger_values.get("train/actor_base_loss")),
            "critic_loss": self._finite(logger_values.get("train/critic_loss")),
            "ent_coef": self._finite(logger_values.get("train/ent_coef")),
            "ent_coef_loss": self._finite(logger_values.get("train/ent_coef_loss")),
            "support_actor_loss": self._finite(
                logger_values.get("train/support_actor_loss")
            ),
            "support_actor_weighted_loss": self._finite(
                logger_values.get("train/support_actor_weighted_loss")
            ),
            "replay_support_actor_loss": self._finite(
                logger_values.get("train/replay_support_actor_loss")
            ),
            "replay_support_actor_weighted_loss": self._finite(
                logger_values.get("train/replay_support_actor_weighted_loss")
            ),
            "support_actor_weight": self._finite(
                logger_values.get("train/support_actor_weight")
            ),
            "actor_update_enabled_fraction": self._finite(
                logger_values.get("train/actor_update_enabled_fraction")
            ),
            "critic_only_warmup_updates": int(
                self._finite(logger_values.get("train/critic_only_warmup_updates"), 0.0)
            ),
            "learning_rate": self._finite(logger_values.get("train/learning_rate")),
            "replay_buffer_pos": int(getattr(getattr(self.model, "replay_buffer", None), "pos", -1)),
            "replay_buffer_full": bool(getattr(getattr(self.model, "replay_buffer", None), "full", False)),
        }
        self.train_rows.append(row)

    def _update_episode_diagnostics(self, idx: int, info: dict) -> None:
        while len(self._cost_sums) <= idx:
            self._cost_sums.append(self._new_cost_sums())
            self._maxima.append(self._new_maxima())
        for key in list(self._cost_sums[idx]):
            source_key = key[:-4] if key.endswith("_sum") else key
            self._cost_sums[idx][key] += self._finite(info.get(source_key), 0.0)
        maxima_sources = {
            "action_max_abs_max": "action_max_abs",
            "raw_action_max_abs_max": "raw_action_max_abs",
            "projection_delta_norm_max": "projection_delta_norm",
            "support_violation_max": "calibration_support_violation",
            "safety_gap_max": "safety_gap",
            "envelope_violation_max_seen_pu": "envelope_violation_pu",
            "fault_band_violation_max_seen_pu": "fault_band_violation_pu",
            "recovery_violation_max_seen_pu": "recovery_violation_pu",
        }
        for max_key, source_key in maxima_sources.items():
            self._maxima[idx][max_key] = max(
                self._maxima[idx][max_key],
                abs(self._finite(info.get(source_key), 0.0)),
            )

    def _on_step(self) -> bool:
        self._record_train_diagnostics()
        rewards = np.asarray(self.locals.get("rewards", []), dtype=float).reshape(-1)
        dones = np.asarray(self.locals.get("dones", []), dtype=bool).reshape(-1)
        infos = list(self.locals.get("infos", [{} for _ in range(len(rewards))]))
        if len(self._returns) < len(rewards):
            extra = len(rewards) - len(self._returns)
            self._returns.extend([0.0] * extra)
            self._lengths.extend([0] * extra)
            self._cost_sums.extend([self._new_cost_sums() for _ in range(extra)])
            self._maxima.extend([self._new_maxima() for _ in range(extra)])
        for idx, reward in enumerate(rewards):
            self._returns[idx] += float(reward)
            self._lengths[idx] += 1
            info = infos[idx] if idx < len(infos) and isinstance(infos[idx], dict) else {}
            self._update_episode_diagnostics(idx, info)
            if idx < len(dones) and bool(dones[idx]):
                row = {
                    "timesteps": int(self.num_timesteps),
                    "env_index": int(idx),
                    "episode_return": float(self._returns[idx]),
                    "episode_length": int(self._lengths[idx]),
                    "condition": str(info.get("condition", "")),
                    "v_lv_pu": float(info.get("v_lv_pu", np.nan)),
                    "vdc_pu": float(info.get("vdc_pu", np.nan)),
                    "envelope_violation_pu": float(info.get("envelope_violation_pu", np.nan)),
                    "fault_lv_band_violation_pu": float(
                        info.get("fault_lv_band_violation_pu", np.nan)
                    ),
                    "recovery_violation_pu": float(info.get("recovery_violation_pu", np.nan)),
                    "grid_current_violation_pu": float(
                        info.get("grid_current_violation_pu", np.nan)
                    ),
                    "final_action_max_abs": self._finite(info.get("action_max_abs")),
                    "final_raw_action_max_abs": self._finite(info.get("raw_action_max_abs")),
                    "final_projection_delta_norm": self._finite(info.get("projection_delta_norm")),
                    "final_support_violation": self._finite(
                        info.get("calibration_support_violation")
                    ),
                    "final_safety_gap": self._finite(info.get("safety_gap")),
                }
                row.update(self._cost_sums[idx])
                row.update(self._maxima[idx])
                self.rows.append(row)
                self._returns[idx] = 0.0
                self._lengths[idx] = 0
                self._cost_sums[idx] = self._new_cost_sums()
                self._maxima[idx] = self._new_maxima()
        return True

    def _on_training_end(self) -> None:
        self._record_train_diagnostics()
        for idx, length in enumerate(self._lengths):
            if length <= 0:
                continue
            row = {
                "timesteps": int(self.num_timesteps),
                "env_index": int(idx),
                "episode_return": float(self._returns[idx]),
                "episode_length": int(length),
                "condition": "partial_chunk",
                "v_lv_pu": float("nan"),
                "vdc_pu": float("nan"),
                "envelope_violation_pu": float("nan"),
                "fault_lv_band_violation_pu": float("nan"),
                "recovery_violation_pu": float("nan"),
                "grid_current_violation_pu": float("nan"),
            }
            row.update(self._cost_sums[idx])
            row.update(self._maxima[idx])
            self.rows.append(row)
            self._returns[idx] = 0.0
            self._lengths[idx] = 0
            self._cost_sums[idx] = self._new_cost_sums()
            self._maxima[idx] = self._new_maxima()


def write_rows_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def select_scenarios(curriculum: str) -> list[HPTVoltageScenario]:
    scenarios = default_hpt_voltage_scenarios()
    if curriculum == "all":
        return scenarios
    if curriculum == "steady_step4":
        selected = [
            HPTVoltageScenario(
                topology=topology,
                grid_pu=grid_pu,
                duration_s=0.18,
                category="steady",
                fault_type="steady",
            )
            for topology in ("topology1", "topology2")
            for grid_pu in (0.90, 1.00, 1.10)
        ]
    elif curriculum == "topology2_fault":
        selected = [
            s
            for s in scenarios
            if s.topology == "topology2" and (s.category != "steady" or s.grid_pu in (0.90, 1.10))
        ]
    elif curriculum == "switch_fault_transition":
        selected = [
            HPTVoltageScenario(
                topology=topology,
                grid_pu=grid_pu,
                duration_s=0.16,
                category=category,
                fault_type=fault_type,
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
            for topology in ("topology1", "topology2")
            for grid_pu, category, fault_type in (
                (0.90, "LVRT", "sym3ph"),
                (1.10, "HVRT", "swell_3ph"),
            )
        ]
    elif curriculum == "topology2_a_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.90,
                neg_seq_pu=_neg_seq_for_fault("1ph_g", 0.90),
                fault_phase_key="a",
                duration_s=0.220,
                category="LVRT",
                fault_type="1ph_g",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_ab_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.90,
                neg_seq_pu=_neg_seq_for_fault("2ph", 0.90),
                fault_phase_key="ab",
                duration_s=0.220,
                category="LVRT",
                fault_type="2ph",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology1_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=0.90,
                duration_s=0.220,
                category="LVRT",
                fault_type="sym3ph",
                fault_start_s=0.080,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology1_hvrt110_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=1.10,
                duration_s=0.220,
                category="HVRT",
                fault_type="swell_3ph",
                fault_start_s=0.080,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.90,
                duration_s=0.220,
                category="LVRT",
                fault_type="sym3ph",
                fault_start_s=0.080,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_lvrt090_60ms_f035":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.90,
                duration_s=0.220,
                category="LVRT",
                fault_type="sym3ph",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_hvrt110_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=1.10,
                duration_s=0.220,
                category="HVRT",
                fault_type="swell_3ph",
                fault_start_s=0.080,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology1_a_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=0.90,
                neg_seq_pu=_neg_seq_for_fault("1ph_g", 0.90),
                fault_phase_key="a",
                duration_s=0.220,
                category="LVRT",
                fault_type="1ph_g",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology1_ab_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology1",
                grid_pu=0.90,
                neg_seq_pu=_neg_seq_for_fault("2ph", 0.90),
                fault_phase_key="ab",
                duration_s=0.220,
                category="LVRT",
                fault_type="2ph",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_a_hvrt105_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=1.05,
                neg_seq_pu=_neg_seq_for_fault("swell_1ph", 1.05),
                fault_phase_key="a",
                duration_s=0.220,
                category="HVRT",
                fault_type="swell_1ph",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_a_hvrt110_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=1.10,
                neg_seq_pu=_neg_seq_for_fault("swell_1ph", 1.10),
                fault_phase_key="a",
                duration_s=0.220,
                category="HVRT",
                fault_type="swell_1ph",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_ab_hvrt105_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=1.05,
                neg_seq_pu=_neg_seq_for_fault("swell_2ph", 1.05),
                fault_phase_key="ab",
                duration_s=0.220,
                category="HVRT",
                fault_type="swell_2ph",
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
        ]
    elif curriculum == "topology2_unbalanced_lvrt090_60ms":
        selected = [
            HPTVoltageScenario(
                topology="topology2",
                grid_pu=0.90,
                neg_seq_pu=_neg_seq_for_fault(fault_type, 0.90),
                fault_phase_key=phase_key,
                duration_s=0.220,
                category="LVRT",
                fault_type=fault_type,
                fault_start_s=0.035,
                fault_duration_s=0.060,
                recovery_tau_s=0.035,
            )
            for fault_type, phase_key in (("1ph_g", "a"), ("2ph", "ab"))
        ]
    elif curriculum == "topology2_lvrt_family_v1":
        selected = []
        for target in (0.85, 0.90, 0.95):
            for duration_s in (0.040, 0.060, 0.080, 0.120):
                for fault_type, phase_key in (
                    ("sym3ph", "abc"),
                    ("1ph_g", "a"),
                    ("2ph", "ab"),
                ):
                    selected.append(
                        HPTVoltageScenario(
                            topology="topology2",
                            grid_pu=target,
                            neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                            fault_phase_key=phase_key,
                            duration_s=0.220,
                            category="LVRT",
                            fault_type=fault_type,
                            fault_start_s=0.080 if fault_type == "sym3ph" else 0.035,
                            fault_duration_s=duration_s,
                            recovery_tau_s=0.035,
                        )
                    )
    elif curriculum == "topology2_lvrt_family_holdout_v1":
        selected = []
        for target in (0.875, 0.925):
            for fault_type, phase_key in (
                ("sym3ph", "abc"),
                ("1ph_g", "b"),
                ("2ph", "bc"),
            ):
                selected.append(
                    HPTVoltageScenario(
                        topology="topology2",
                        grid_pu=target,
                        neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                        fault_phase_key=phase_key,
                        duration_s=0.220,
                        category="LVRT",
                        fault_type=fault_type,
                        fault_start_s=0.080 if fault_type == "sym3ph" else 0.035,
                        fault_duration_s=0.100,
                        recovery_tau_s=0.035,
                    )
                )
    elif curriculum == "topology1_lvrt_balanced_family_v1":
        selected = []
        for target in (0.85, 0.90, 0.95):
            for duration_s in (0.040, 0.060, 0.080):
                selected.append(
                    HPTVoltageScenario(
                        topology="topology1",
                        grid_pu=target,
                        neg_seq_pu=0.0,
                        fault_phase_key="abc",
                        duration_s=0.220,
                        category="LVRT",
                        fault_type="sym3ph",
                        fault_start_s=0.080,
                        fault_duration_s=duration_s,
                        recovery_tau_s=0.035,
                    )
                )
    elif curriculum == "topology1_lvrt_balanced_family_holdout_v1":
        selected = []
        for target in (0.825, 0.875, 0.925):
            for duration_s in (0.120, 0.160):
                selected.append(
                    HPTVoltageScenario(
                        topology="topology1",
                        grid_pu=target,
                        neg_seq_pu=0.0,
                        fault_phase_key="abc",
                        duration_s=max(0.220, 0.080 + duration_s + 0.125),
                        category="LVRT",
                        fault_type="sym3ph",
                        fault_start_s=0.080,
                        fault_duration_s=duration_s,
                        recovery_tau_s=0.035,
                    )
                )
    elif curriculum == "expanded_fault_transition":
        selected = []
        for topology in ("topology1", "topology2"):
            for target in (0.20, 0.50, 0.75, 0.85, 0.90):
                for fault_type in ("sym3ph", "1ph_g", "2ph", "2ph_g"):
                    selected.append(
                        HPTVoltageScenario(
                            topology=topology,
                            grid_pu=target,
                            neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                            duration_s=0.26,
                            category="LVRT",
                            fault_type=fault_type,
                            fault_start_s=0.035,
                            fault_duration_s=0.090,
                            recovery_tau_s=0.035,
                        )
                    )
            for target in (1.10, 1.20, 1.25, 1.30):
                for fault_type in ("swell_3ph", "swell_1ph"):
                    selected.append(
                        HPTVoltageScenario(
                            topology=topology,
                            grid_pu=target,
                            neg_seq_pu=_neg_seq_for_fault(fault_type, target),
                            duration_s=0.26,
                            category="HVRT",
                            fault_type=fault_type,
                            fault_start_s=0.035,
                            fault_duration_s=0.090,
                            recovery_tau_s=0.035,
                        )
                    )
    else:
        raise ValueError(f"Unknown HPT SAC curriculum: {curriculum}")

    if not selected:
        raise ValueError(f"Curriculum {curriculum} produced no scenarios")
    return selected


def scenario_summary(scenarios: list[HPTVoltageScenario]) -> dict:
    out: dict[str, dict[str, int] | int] = {"count": len(scenarios)}
    for attr in ("topology", "category", "fault_type"):
        bucket: dict[str, int] = {}
        for s in scenarios:
            key = str(getattr(s, attr))
            bucket[key] = bucket.get(key, 0) + 1
        out[attr] = dict(sorted(bucket.items()))
    return out


def fault_type_from_category_phase(category: str, phase_key: str) -> str:
    """Infer the proxy fault-type label from an FRT category and phase key."""

    phase_key = str(phase_key).strip().lower()
    if phase_key in ("", "balanced"):
        phase_key = "abc"
    if str(category).upper() == "HVRT":
        if phase_key == "abc":
            return "swell_3ph"
        if len(phase_key) == 1:
            return "swell_1ph"
        return "swell_2ph"
    if phase_key == "abc":
        return "sym3ph"
    if len(phase_key) == 1:
        return "1ph_g"
    return "2ph"


def single_case_scenario(
    *,
    topology: str,
    grid_pu: float,
    fault_duration_s: float,
    fault_start_s: float,
    fault_stop_margin_s: float,
    category: str | None = None,
    phase_key: str = "abc",
) -> HPTVoltageScenario:
    """Build one explicit FRT scenario for boundary/specialist experiments."""

    if topology not in ("topology1", "topology2"):
        raise ValueError(f"Unsupported single-case topology: {topology}")
    category_label = str(category or ("HVRT" if grid_pu > 1.0 else "LVRT")).upper()
    if category_label not in ("LVRT", "HVRT"):
        raise ValueError(f"Unsupported single-case category: {category_label}")
    phase = str(phase_key).strip().lower()
    if phase in ("", "balanced"):
        phase = "abc"
    fault_type = fault_type_from_category_phase(category_label, phase)
    stop_time = max(0.220, fault_start_s + fault_duration_s + fault_stop_margin_s)
    return HPTVoltageScenario(
        topology=topology,
        grid_pu=float(grid_pu),
        neg_seq_pu=_neg_seq_for_fault(fault_type, float(grid_pu)),
        fault_phase_key=phase,
        duration_s=float(stop_time),
        category=category_label,
        fault_type=fault_type,
        fault_start_s=float(fault_start_s),
        fault_duration_s=float(fault_duration_s),
        recovery_tau_s=0.035,
    )


def parse_float_list(text: str, *, name: str) -> list[float]:
    values = [float(part.strip()) for part in str(text).split(",") if part.strip()]
    if not values:
        raise ValueError(f"{name} must contain at least one value")
    return values


def parse_duration_ms_list(text: str, *, name: str) -> list[float]:
    values_ms = parse_float_list(text, name=name)
    return [value / 1000.0 for value in values_ms]


def parse_phase_key_list(text: str, *, name: str) -> list[str]:
    aliases = {
        "": "abc",
        "balanced": "abc",
        "single": "a,b,c",
        "single_phase": "a,b,c",
        "two": "ab,bc,ca",
        "two_phase": "ab,bc,ca",
    }
    expanded = aliases.get(str(text or "").strip().lower(), str(text or "abc"))
    values = [part.strip().lower() for part in expanded.split(",") if part.strip()]
    if not values:
        raise ValueError(f"{name} must contain at least one phase key")
    allowed = {"abc", "a", "b", "c", "ab", "bc", "ca"}
    unsupported = [value for value in values if value not in allowed]
    if unsupported:
        raise ValueError(f"{name} contains unsupported phase keys: {unsupported!r}")
    return list(dict.fromkeys(values))


def representative_phase_key(phase_keys: list[str]) -> str:
    if set(phase_keys) == {"a", "b", "c"}:
        return "a"
    if set(phase_keys) == {"ab", "bc", "ca"}:
        return "ab"
    return phase_keys[0]


def family_case_scenarios(
    *,
    topology: str,
    grid_pus: list[float],
    fault_durations_s: list[float],
    fault_start_s: float,
    fault_stop_margin_s: float,
    category: str,
    phase_keys: list[str],
) -> list[HPTVoltageScenario]:
    scenarios: list[HPTVoltageScenario] = []
    for phase_key in phase_keys:
        for grid_pu in grid_pus:
            for duration_s in fault_durations_s:
                scenarios.append(
                    single_case_scenario(
                        topology=topology,
                        grid_pu=float(grid_pu),
                        fault_duration_s=float(duration_s),
                        fault_start_s=float(fault_start_s),
                        fault_stop_margin_s=float(fault_stop_margin_s),
                        category=category,
                        phase_key=phase_key,
                    )
                )
    return scenarios


def evaluate_teacher_or_policy(
    model,
    scenarios: list[HPTVoltageScenario],
    n_rollouts: int = 20,
    config: HPTVoltageEnvConfig | None = None,
) -> dict:
    eval_scenarios = scenarios if n_rollouts <= 0 else scenarios[:n_rollouts]
    env = HPTVoltageSACEnv(scenarios, config=config, train_mode=False)
    returns = []
    final_v = []
    final_vdc = []
    vdc_min = []
    v_min = []
    v_max = []
    condition_counts: dict[str, int] = {}
    hybrid_dc_source_counts: dict[str, int] = {}
    for _ in range(len(eval_scenarios)):
        obs, _ = env.reset()
        done = False
        ret = 0.0
        info = {}
        episode_vdc_min = float(obs[3])
        episode_v_min = float(obs[0])
        episode_v_max = float(obs[0])
        while not done:
            act, _ = model.predict(obs, deterministic=True)
            obs, rew, terminated, truncated, info = env.step(act)
            episode_vdc_min = min(episode_vdc_min, float(obs[3]))
            episode_v_min = min(episode_v_min, float(obs[0]))
            episode_v_max = max(episode_v_max, float(obs[0]))
            hybrid_source = str(info.get("hybrid_dc_channel_source", "unknown"))
            hybrid_dc_source_counts[hybrid_source] = hybrid_dc_source_counts.get(hybrid_source, 0) + 1
            ret += rew
            done = terminated or truncated
        returns.append(ret)
        final_v.append(float(info["v_lv_pu"]))
        final_vdc.append(float(info["vdc_pu"]))
        vdc_min.append(episode_vdc_min)
        v_min.append(episode_v_min)
        v_max.append(episode_v_max)
        condition = str(info.get("condition", "unknown"))
        condition_counts[condition] = condition_counts.get(condition, 0) + 1
    return {
        "rollouts": len(eval_scenarios),
        "mean_return": float(np.mean(returns)),
        "mean_final_v_pu": float(np.mean(final_v)),
        "max_abs_final_v_err": float(np.max(np.abs(np.asarray(final_v) - 1.0))),
        "mean_final_vdc_pu": float(np.mean(final_vdc)),
        "min_vdc_pu": float(np.min(vdc_min)),
        "min_episode_v_pu": float(np.min(v_min)),
        "max_episode_v_pu": float(np.max(v_max)),
        "condition_counts": dict(sorted(condition_counts.items())),
        "hybrid_dc_source_counts": dict(sorted(hybrid_dc_source_counts.items())),
    }


def set_learning_rate(model: SAC, learning_rate: float) -> None:
    """Update SB3 SAC optimizers after loading a warm-start checkpoint."""

    model.learning_rate = float(learning_rate)
    model.lr_schedule = constant_fn(float(learning_rate))
    for optimizer in (
        getattr(model.policy.actor, "optimizer", None),
        getattr(model.policy.critic, "optimizer", None),
        getattr(model, "ent_coef_optimizer", None),
    ):
        if optimizer is None:
            continue
        for group in optimizer.param_groups:
            group["lr"] = float(learning_rate)


def actor_state_uses_split_heads(state: dict[str, th.Tensor]) -> bool:
    return any(key.startswith("mu.reg_head.") for key in state)


def copy_shared_actor_to_split(shared_model: SAC, split_model: SAC) -> None:
    """Initialize a split-head actor from a standard shared-head actor.

    Historical BC/DAgger checkpoints use the normal SB3 actor with one
    4-output ``mu`` and one 4-output ``log_std`` layer.  The current HPT
    controller uses separate regulating and energy heads.  This bridge keeps
    the learned trunk and copies output rows 0:2 into the regulating heads and
    rows 2:4 into the energy heads.
    """

    src_actor = shared_model.policy.actor.state_dict()
    dst_actor = split_model.policy.actor.state_dict()
    for key, value in list(dst_actor.items()):
        if key in src_actor and tuple(src_actor[key].shape) == tuple(value.shape):
            dst_actor[key] = src_actor[key].detach().clone()

    for name in ("mu", "log_std"):
        src_w = src_actor.get(f"{name}.weight")
        src_b = src_actor.get(f"{name}.bias")
        if src_w is None or src_b is None:
            continue
        dst_actor[f"{name}.reg_head.weight"] = src_w[:2, :].detach().clone()
        dst_actor[f"{name}.reg_head.bias"] = src_b[:2].detach().clone()
        dst_actor[f"{name}.energy_head.weight"] = src_w[2:4, :].detach().clone()
        dst_actor[f"{name}.energy_head.bias"] = src_b[2:4].detach().clone()
    split_model.policy.actor.load_state_dict(dst_actor)

    for module_name in ("critic", "critic_target"):
        src_module = getattr(shared_model.policy, module_name, None)
        dst_module = getattr(split_model.policy, module_name, None)
        if src_module is None or dst_module is None:
            continue
        src_state = src_module.state_dict()
        dst_state = dst_module.state_dict()
        compatible = all(
            key in src_state and tuple(src_state[key].shape) == tuple(value.shape)
            for key, value in dst_state.items()
        )
        if compatible:
            dst_module.load_state_dict(src_state)


def copy_actor_only(source_model: SAC, target_model: SAC) -> None:
    """Copy actor parameters while preserving fresh critic and replay state.

    This path is required when a run changes the numerical reward scale:
    reusing a critic trained on the old scale would contaminate new Bellman
    targets even though the warm-start policy itself remains useful.
    """

    source_state = source_model.policy.actor.state_dict()
    target_state = target_model.policy.actor.state_dict()
    compatible = (
        source_state.keys() == target_state.keys()
        and all(
            tuple(source_state[key].shape) == tuple(value.shape)
            for key, value in target_state.items()
        )
    )
    if compatible:
        target_model.policy.actor.load_state_dict(source_state)
        return
    if actor_state_uses_split_heads(target_state) and not actor_state_uses_split_heads(
        source_state
    ):
        critic_state = target_model.policy.critic.state_dict()
        target_critic_state = target_model.policy.critic_target.state_dict()
        copy_shared_actor_to_split(source_model, target_model)
        target_model.policy.critic.load_state_dict(critic_state)
        target_model.policy.critic_target.load_state_dict(target_critic_state)
        return
    raise ValueError("Actor-only initialization requires compatible actor architectures")


def collect_init_actor_anchor_samples(
    init_model: Path,
    scenarios: list[HPTVoltageScenario],
    *,
    config: HPTVoltageEnvConfig,
    episodes: int,
    noise_std: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Collect state/action anchors from the currently accepted init actor."""

    teacher = SAC.load(str(init_model), device=pick_device())
    env = HPTVoltageSACEnv(scenarios, config=config, seed=seed, train_mode=True)
    rng = np.random.default_rng(seed)
    obs_rows: list[np.ndarray] = []
    act_rows: list[np.ndarray] = []
    for _ in range(max(1, int(episodes))):
        obs, _ = env.reset()
        done = False
        while not done:
            obs_for_action = np.asarray(obs, dtype=np.float32)
            if noise_std > 0:
                obs_for_action = obs_for_action + rng.normal(
                    0.0, float(noise_std), size=obs_for_action.shape
                ).astype(np.float32)
            act, _ = teacher.predict(obs_for_action, deterministic=True)
            act = np.asarray(act, dtype=np.float32)
            obs_rows.append(obs_for_action.astype(np.float32))
            act_rows.append(act.astype(np.float32))
            obs, _, terminated, truncated, _ = env.step(act)
            done = bool(terminated or truncated)
    return np.asarray(obs_rows, dtype=np.float32), np.asarray(act_rows, dtype=np.float32)


def load_anchor_dataset(dataset: Path) -> tuple[np.ndarray, np.ndarray]:
    with np.load(dataset, allow_pickle=False) as data:
        if "observations" in data and "actions" in data:
            obs = data["observations"]
            actions = data["actions"]
        elif "obs" in data and "action" in data:
            obs = data["obs"]
            actions = data["action"]
        else:
            raise ValueError(
                f"Anchor dataset must contain observations/actions or obs/action: {dataset}"
            )
    obs = np.asarray(obs, dtype=np.float32)
    actions = np.asarray(actions, dtype=np.float32)
    if obs.ndim != 2 or obs.shape[1] != OBS_DIM_HPT:
        raise ValueError(f"Anchor obs shape must be (n, {OBS_DIM_HPT}), got {obs.shape}")
    if actions.ndim != 2 or actions.shape[1] != ACT_DIM_HPT:
        raise ValueError(f"Anchor action shape must be (n, {ACT_DIM_HPT}), got {actions.shape}")
    return obs, actions


def _optional_float(row: dict, key: str, default: float) -> float:
    raw = row.get(key, "")
    if raw in ("", None):
        return float(default)
    return float(raw)


def _manifest_fault_type(category: str, phase_key: str) -> str:
    if str(category).upper() == "HVRT":
        if phase_key in ("", "abc", "balanced"):
            return "swell_3ph"
        if len(phase_key) == 1:
            return "swell_1ph"
        return "swell_2ph"
    if phase_key in ("", "abc", "balanced"):
        return "sym3ph"
    if len(phase_key) == 1:
        return "1ph_g"
    return "2ph"


def scenario_from_manifest_row(row: dict) -> HPTVoltageScenario:
    """Build a proxy scenario from a switch-level validation manifest row."""

    topology = str(row.get("topology", "")).strip()
    if topology not in ("topology1", "topology2"):
        raise ValueError(f"Unsupported topology in manifest row: {topology!r}")
    category = str(row.get("fault_family") or row.get("category") or "LVRT").strip().upper()
    phase_key = str(row.get("fault_phase_key") or row.get("phase_key") or "abc").strip().lower()
    if phase_key in ("", "balanced"):
        phase_key = "abc"
    grid_pu = _optional_float(row, "fault_pu", _optional_float(row, "grid_pu", 0.90))
    fault_duration_s = _optional_float(row, "duration_s", 0.060)
    fault_start_s = _optional_float(
        row, "fault_start_s", 0.080 if phase_key == "abc" else 0.035
    )
    fault_stop_margin_s = _optional_float(row, "fault_stop_margin_s", 0.125)
    recovery_tau_s = _optional_float(row, "recovery_tau_s", 0.035)
    fault_type = str(row.get("fault_type") or "").strip()
    if not fault_type:
        fault_type = _manifest_fault_type(category, phase_key)
    duration_s = max(0.220, fault_start_s + fault_duration_s + fault_stop_margin_s)
    return HPTVoltageScenario(
        topology=topology,
        grid_pu=grid_pu,
        neg_seq_pu=_neg_seq_for_fault(fault_type, grid_pu),
        fault_phase_key=phase_key,
        duration_s=duration_s,
        category=category,
        fault_type=fault_type,
        fault_start_s=fault_start_s,
        fault_duration_s=fault_duration_s,
        recovery_tau_s=recovery_tau_s,
    )


def collect_manifest_actor_anchor_samples(
    manifest: Path,
    *,
    config: HPTVoltageEnvConfig,
    episodes_per_row: int,
    noise_std: float,
    seed: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Collect state/action anchors from a manifest of validated actors."""

    rows = list(csv.DictReader(manifest.open(newline="", encoding="utf-8")))
    if not rows:
        raise ValueError(f"Support anchor manifest is empty: {manifest}")
    device = pick_device()
    rng = np.random.default_rng(seed)
    teachers: dict[str, SAC] = {}
    obs_rows: list[np.ndarray] = []
    act_rows: list[np.ndarray] = []
    for row_idx, row in enumerate(rows):
        model_raw = str(row.get("model_path") or "").strip()
        if not model_raw:
            raise ValueError(f"Manifest row {row_idx} is missing model_path")
        model_path = Path(model_raw)
        if not model_path.is_absolute():
            model_path = ROOT / model_path
        model_key = str(model_path)
        if model_key not in teachers:
            if not model_path.exists():
                raise FileNotFoundError(f"Support anchor model not found: {model_path}")
            teachers[model_key] = SAC.load(model_key, device=device)
        teacher = teachers[model_key]
        scenario = scenario_from_manifest_row(row)
        env = HPTVoltageSACEnv(
            [scenario],
            config=config,
            seed=seed + row_idx,
            train_mode=True,
        )
        for _ in range(max(1, int(episodes_per_row))):
            obs, _ = env.reset()
            done = False
            while not done:
                obs_for_action = np.asarray(obs, dtype=np.float32)
                if noise_std > 0:
                    obs_for_action = obs_for_action + rng.normal(
                        0.0, float(noise_std), size=obs_for_action.shape
                    ).astype(np.float32)
                act, _ = teacher.predict(obs_for_action, deterministic=True)
                obs_rows.append(obs_for_action.astype(np.float32))
                act_rows.append(np.asarray(act, dtype=np.float32))
                obs, _, terminated, truncated, _ = env.step(act)
                done = bool(terminated or truncated)
    return np.asarray(obs_rows, dtype=np.float32), np.asarray(act_rows, dtype=np.float32)


def load_support_anchor_dataset(dataset: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load pre-built switch-supported observation/action anchors."""

    if not dataset.exists():
        raise FileNotFoundError(f"Support anchor dataset not found: {dataset}")
    with np.load(dataset, allow_pickle=False) as data:
        obs_key = "observations" if "observations" in data.files else "obs"
        act_key = "actions" if "actions" in data.files else "act"
        if obs_key not in data.files or act_key not in data.files:
            raise ValueError(
                f"Support anchor dataset {dataset} must contain observations/actions "
                f"arrays; found {data.files}"
            )
        observations = np.asarray(data[obs_key], dtype=np.float32)
        actions = np.asarray(data[act_key], dtype=np.float32)
    if observations.ndim != 2 or observations.shape[1] != OBS_DIM_HPT:
        raise ValueError(
            f"Support observations must have shape (n, {OBS_DIM_HPT}), "
            f"got {observations.shape}"
        )
    if actions.ndim != 2 or actions.shape[1] != ACT_DIM_HPT:
        raise ValueError(
            f"Support actions must have shape (n, {ACT_DIM_HPT}), got {actions.shape}"
        )
    if observations.shape[0] != actions.shape[0]:
        raise ValueError(
            f"Support observations/actions row mismatch: "
            f"{observations.shape[0]} vs {actions.shape[0]}"
        )
    if observations.shape[0] <= 0:
        raise ValueError(f"Support anchor dataset is empty: {dataset}")
    return observations, actions


def parse_action_weights(text: str, *, name: str) -> tuple[float, ...]:
    values = tuple(float(x.strip()) for x in text.split(",") if x.strip())
    if len(values) != ACT_DIM_HPT:
        raise ValueError(f"{name} must contain four comma-separated values")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=120_000)
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument(
        "--target-gate",
        choices=["L1"],
        default="L1",
        help=(
            "Promotion gate optimized by this trainer. Only L1 is available "
            "until explicit connection-state and active-power-recovery signals exist."
        ),
    )
    parser.add_argument(
        "--l1-disable-current-limit",
        action="store_true",
        help="Diagnostic only: omit the grid-current limit from proxy L1 training.",
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument(
        "--results-root",
        type=Path,
        default=None,
        help=(
            "Directory that receives the run folder. Family and single-case "
            "runs default to their resolved expert workspace."
        ),
    )
    parser.add_argument(
        "--curriculum",
        choices=[
            "all",
            "steady_step4",
            "topology2_fault",
            "switch_fault_transition",
            "expanded_fault_transition",
            "topology1_lvrt090_60ms",
            "topology1_hvrt110_60ms",
            "topology2_lvrt090_60ms",
            "topology2_lvrt090_60ms_f035",
            "topology2_hvrt110_60ms",
            "topology1_a_lvrt090_60ms",
            "topology1_ab_lvrt090_60ms",
            "topology2_a_lvrt090_60ms",
            "topology2_ab_lvrt090_60ms",
            "topology2_a_hvrt105_60ms",
            "topology2_a_hvrt110_60ms",
            "topology2_ab_hvrt105_60ms",
            "topology2_unbalanced_lvrt090_60ms",
            "topology1_lvrt_balanced_family_v1",
            "topology1_lvrt_balanced_family_holdout_v1",
            "topology2_lvrt_family_v1",
            "topology2_lvrt_family_holdout_v1",
        ],
        default="all",
    )
    parser.add_argument(
        "--single-topology",
        choices=["topology1", "topology2"],
        default=None,
        help="Override --curriculum with one explicit FRT scenario.",
    )
    parser.add_argument(
        "--single-fault-pu",
        type=float,
        default=None,
        help="Fault voltage in pu for --single-topology.",
    )
    parser.add_argument(
        "--single-fault-duration-s",
        type=float,
        default=None,
        help="Fault duration in seconds for --single-topology.",
    )
    parser.add_argument(
        "--single-fault-start-s",
        type=float,
        default=0.035,
        help="Fault start time in seconds for --single-topology.",
    )
    parser.add_argument(
        "--single-fault-stop-margin-s",
        type=float,
        default=0.125,
        help="Post-clear simulation margin in seconds for --single-topology.",
    )
    parser.add_argument(
        "--single-category",
        choices=["LVRT", "HVRT"],
        default=None,
        help="Optional FRT family for --single-topology; inferred from fault pu if omitted.",
    )
    parser.add_argument(
        "--single-phase-key",
        default="abc",
        help="Fault phase key for --single-topology, e.g. abc, a, ab.",
    )
    parser.add_argument(
        "--family-topology",
        choices=["topology1", "topology2"],
        default=None,
        help=(
            "Override --curriculum with a fault family. One actor is trained "
            "across the cross product of --family-fault-pus and "
            "--family-fault-durations-ms."
        ),
    )
    parser.add_argument(
        "--family-fault-pus",
        default=None,
        help="Comma-separated fault voltage levels in pu for --family-topology.",
    )
    parser.add_argument(
        "--family-fault-durations-ms",
        default=None,
        help="Comma-separated fault durations in milliseconds for --family-topology.",
    )
    parser.add_argument(
        "--family-fault-start-s",
        type=float,
        default=0.035,
        help="Fault start time in seconds for --family-topology.",
    )
    parser.add_argument(
        "--family-fault-stop-margin-s",
        type=float,
        default=0.125,
        help="Post-clear simulation margin in seconds for --family-topology.",
    )
    parser.add_argument(
        "--family-category",
        choices=["LVRT", "HVRT"],
        default="LVRT",
        help="FRT family category for --family-topology.",
    )
    parser.add_argument(
        "--family-phase-key",
        default="abc",
        help=(
            "Fault phase key(s) for --family-topology, e.g. abc, a, ab, "
            "or comma-separated a,b,c for one single-phase family actor."
        ),
    )
    parser.add_argument(
        "--model-out",
        type=Path,
        default=None,
        help=(
            "SAC checkpoint path. Family and single-case runs default to their "
            "resolved expert workspace."
        ),
    )
    parser.add_argument(
        "--controller-heads",
        choices=["shared", "split"],
        default="shared",
        help="Use the old shared action head or separate reg/energy SAC actor heads.",
    )
    parser.add_argument(
        "--init-model",
        type=Path,
        default=None,
        help="Optional existing SAC checkpoint to fine-tune instead of training from scratch.",
    )
    parser.add_argument(
        "--init-actor-only",
        action="store_true",
        help=(
            "Copy only the actor from --init-model and initialize fresh critics, "
            "entropy state, and replay buffer. Use this when changing reward scale."
        ),
    )
    parser.add_argument(
        "--proxy-calibration",
        type=Path,
        default=DEFAULT_PROXY_CALIBRATION,
        help=(
            "Switch-level proxy calibration JSON used by the training environment. "
            "Use a family-specific file when the global calibration does not cover "
            "the requested fault depth, duration, phase, and action support."
        ),
    )
    parser.add_argument(
        "--allow-uncalibrated-fault-proxy",
        action="store_true",
        help=(
            "Diagnostic escape hatch. By default, fault training refuses a proxy "
            "that is not marked current under the v3 validator schema."
        ),
    )
    parser.add_argument(
        "--hybrid-dc-model",
        type=Path,
        default=None,
        help=(
            "Optional v5 physics-informed DC-link correction model. "
            "When supplied, it is used only inside its validated fault boundary region."
        ),
    )
    parser.add_argument("--hybrid-dc-fault-pu-max", type=float, default=0.85)
    parser.add_argument("--hybrid-dc-duration-ms-min", type=float, default=100.0)
    parser.add_argument("--hybrid-dc-duration-ms-max", type=float, default=180.0)
    parser.add_argument("--eval-rollouts", type=int, default=20)
    parser.add_argument(
        "--safety-classifier",
        type=Path,
        default=None,
        help="Optional classifier.joblib support mask from switch-level data.",
    )
    parser.add_argument("--safety-penalty-weight", type=float, default=8.0)
    parser.add_argument("--safety-unsafe-terminal", action="store_true")
    parser.add_argument("--reg-limit", type=float, default=0.80)
    parser.add_argument("--energy-limit", type=float, default=0.95)
    parser.add_argument("--reg-d-limit", type=float, default=0.80)
    parser.add_argument("--reg-q-limit", type=float, default=0.40)
    parser.add_argument("--energy-d-limit", type=float, default=0.95)
    parser.add_argument("--energy-q-limit", type=float, default=0.95)
    parser.add_argument(
        "--teacher-prior-weight",
        type=float,
        default=0.0,
        help="Penalty weight for deviating from the switch-sweep table teacher.",
    )
    parser.add_argument("--envelope-reward-weight", type=float, default=260.0)
    parser.add_argument("--calibrated-survival-reward-weight", type=float, default=140.0)
    parser.add_argument("--calibration-ood-reward-weight", type=float, default=220.0)
    parser.add_argument(
        "--calibration-ood-violation-reward-cap",
        type=float,
        default=4.0,
        help="Clip support-distance magnitude before applying the proxy-OOD reward penalty.",
    )
    parser.add_argument(
        "--reward-scale",
        type=float,
        default=1.0,
        help=(
            "Positive constant applied to the complete per-step reward. This changes "
            "numerical conditioning without changing relative reward terms."
        ),
    )
    parser.add_argument(
        "--action-projection-enable",
        action="store_true",
        help="Project raw actions through the surrogate execution guard before applying dynamics.",
    )
    parser.add_argument("--grid-reactive-reward-weight", type=float, default=40.0)
    parser.add_argument("--grid-current-reward-weight", type=float, default=50.0)
    parser.add_argument("--vdc-soft-reward-weight", type=float, default=55.0)
    parser.add_argument("--vdc-bounds-reward-weight", type=float, default=0.0)
    parser.add_argument("--vdc-margin-reward-weight", type=float, default=0.0)
    parser.add_argument("--vdc-margin-pu", type=float, default=0.05)
    parser.add_argument("--vdc-lower-barrier-reward-weight", type=float, default=0.0)
    parser.add_argument("--vdc-lower-barrier-start-pu", type=float, default=0.84)
    parser.add_argument("--vdc-lower-barrier-floor-pu", type=float, default=0.8125)
    parser.add_argument("--vdc-low-terminal-enable", action="store_true")
    parser.add_argument("--vdc-low-terminal-pu", type=float, default=0.8125)
    parser.add_argument("--vdc-low-terminal-penalty", type=float, default=0.0)
    parser.add_argument("--grid-current-margin-reward-weight", type=float, default=0.0)
    parser.add_argument("--grid-current-margin-pu", type=float, default=0.05)
    parser.add_argument("--recovery-action-reward-weight", type=float, default=0.0)
    parser.add_argument("--recovery-reg-action-limit", type=float, default=0.18)
    parser.add_argument("--recovery-energy-action-limit", type=float, default=0.20)
    parser.add_argument("--recovery-vdc-high-reward-weight", type=float, default=0.0)
    parser.add_argument("--recovery-vdc-high-limit-pu", type=float, default=1.20)
    parser.add_argument("--recovery-energy-overshoot-gain", type=float, default=0.0)
    parser.add_argument("--recovery-energy-overshoot-threshold", type=float, default=0.10)
    parser.add_argument("--lv-margin-reward-weight", type=float, default=0.0)
    parser.add_argument("--lv-margin-pu", type=float, default=0.02)
    parser.add_argument("--proxy-vdc-reward-downshift-pu", type=float, default=0.0)
    parser.add_argument("--proxy-grid-current-reward-upshift-pu", type=float, default=0.0)
    parser.add_argument("--slow-state-correction", type=Path, default=None)
    parser.add_argument("--slow-state-correction-fault-pu-max", type=float, default=0.85)
    parser.add_argument("--slow-state-correction-duration-ms-min", type=float, default=100.0)
    parser.add_argument("--slow-state-correction-duration-ms-max", type=float, default=180.0)
    parser.add_argument("--action-slew-weight", type=float, default=0.03)
    parser.add_argument(
        "--fault-time-norm-s",
        type=float,
        default=0.50,
        help=(
            "Causal fault-elapsed-time normalization used in the 24-D "
            "observation. Keep this synchronized with "
            "hpt_sac_fault_time_norm_s in switch-level validation."
        ),
    )
    parser.add_argument(
        "--recovery-time-norm-s",
        type=float,
        default=0.50,
        help=(
            "Causal recovery-elapsed-time normalization used in the 24-D "
            "observation. Keep this synchronized with "
            "hpt_sac_recovery_time_norm_s in switch-level validation."
        ),
    )
    parser.add_argument(
        "--behavior-anchor-epochs",
        type=int,
        default=0,
        help="BC epochs run after each SAC chunk against the init actor actions.",
    )
    parser.add_argument("--behavior-anchor-interval-steps", type=int, default=500)
    parser.add_argument("--behavior-anchor-episodes", type=int, default=4)
    parser.add_argument("--behavior-anchor-noise-std", type=float, default=0.01)
    parser.add_argument("--behavior-anchor-lr", type=float, default=5e-5)
    parser.add_argument("--behavior-anchor-batch-size", type=int, default=512)
    parser.add_argument("--behavior-anchor-action-weights", default="4,2,6,6")
    parser.add_argument(
        "--behavior-anchor-energy-head-only",
        action="store_true",
        help=(
            "During behavior-anchor BC, update only the split-head actor's "
            "energy mu head. This is useful when a switch-validated regulation "
            "head should be preserved while fitting calibrated DC-link support."
        ),
    )
    parser.add_argument(
        "--behavior-anchor-dataset",
        type=Path,
        default=None,
        help=(
            "Optional .npz with observations/actions arrays used for behavior "
            "anchor BC. If omitted, anchors are sampled from --init-model."
        ),
    )
    parser.add_argument(
        "--sac-support-regularization-weight",
        type=float,
        default=0.0,
        help=(
            "BRAC-style actor support penalty weight applied inside SAC actor updates. "
            "This keeps SAC as the main update instead of post-hoc BC repair."
        ),
    )
    parser.add_argument("--sac-support-regularization-batch-size", type=int, default=256)
    parser.add_argument(
        "--sac-support-anchor-manifest",
        type=Path,
        default=None,
        help=(
            "Optional manifest of switch-validated actors used to build the "
            "BRAC-style support set. If omitted, anchors are collected from --init-model."
        ),
    )
    parser.add_argument(
        "--sac-support-anchor-dataset",
        type=Path,
        default=None,
        help=(
            "Optional .npz with observations/actions arrays used directly as the "
            "BRAC-style support set. This is used for trajectory-derived family "
            "teachers that do not have a single actor checkpoint."
        ),
    )
    parser.add_argument("--sac-support-anchor-episodes", type=int, default=4)
    parser.add_argument("--sac-support-anchor-noise-std", type=float, default=0.01)
    parser.add_argument("--sac-support-action-weights", default="4,2,6,6")
    parser.add_argument(
        "--critic-only-warmup-updates",
        type=int,
        default=0,
        help=(
            "Freeze a warm-start actor for this many gradient updates while a "
            "fresh critic learns the scaled reward. Intended for "
            "--init-actor-only runs."
        ),
    )
    parser.add_argument(
        "--sac-support-nearest-replay",
        action="store_true",
        help=(
            "Also regularize current replay-buffer states toward the nearest "
            "switch-supported anchor action."
        ),
    )
    parser.add_argument(
        "--sac-energy-head-only",
        action="store_true",
        help=(
            "Restrict SAC actor updates to the split-head energy output head, "
            "leaving the shared trunk and regulating head fixed."
        ),
    )
    parser.add_argument("--export", action="store_true")
    parser.add_argument(
        "--export-out",
        type=Path,
        default=SIMULINK_V2 / "hpt_sac_actor_weights.mat",
        help="MAT actor export path used only with --export.",
    )
    args = parser.parse_args()
    if args.reward_scale <= 0.0:
        raise ValueError("--reward-scale must be positive")
    if args.critic_only_warmup_updates < 0:
        raise ValueError("--critic-only-warmup-updates must be non-negative")
    if args.critic_only_warmup_updates > 0 and not args.init_actor_only:
        raise ValueError(
            "--critic-only-warmup-updates currently requires --init-actor-only"
        )
    if args.init_actor_only and (args.init_model is None or not args.init_model.exists()):
        raise ValueError("--init-actor-only requires an existing --init-model")

    run_id = args.run_id or f"hpt_sac_{time.strftime('%Y%m%d_%H%M%S')}"
    workspace = None
    family_phase_keys = (
        parse_phase_key_list(args.family_phase_key, name="--family-phase-key")
        if args.family_topology is not None
        else []
    )
    if args.family_topology is not None:
        workspace = expert_workspace(
            args.family_topology,
            args.family_category,
            representative_phase_key(family_phase_keys),
            create=True,
        )
    elif args.single_topology is not None:
        workspace = expert_workspace(
            args.single_topology,
            args.single_category,
            args.single_phase_key,
            create=True,
        )
    results_root = Path(args.results_root) if args.results_root is not None else (
        workspace.results / "training" if workspace is not None else RESULTS
    )
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.model_out is None:
        args.model_out = (
            workspace.models / f"{run_id}.zip"
            if workspace is not None
            else MODELS / "hpt_voltage_sac_best.zip"
        )
    explicit_modes = sum(
        int(value is not None)
        for value in (args.single_topology, args.family_topology)
    )
    if explicit_modes > 1:
        raise ValueError("Use either --single-topology or --family-topology, not both")
    if args.family_topology is not None:
        if args.family_fault_pus is None or args.family_fault_durations_ms is None:
            raise ValueError(
                "--family-topology requires --family-fault-pus and "
                "--family-fault-durations-ms"
            )
        scenarios = family_case_scenarios(
            topology=args.family_topology,
            grid_pus=parse_float_list(
                args.family_fault_pus,
                name="--family-fault-pus",
            ),
            fault_durations_s=parse_duration_ms_list(
                args.family_fault_durations_ms,
                name="--family-fault-durations-ms",
            ),
            fault_start_s=args.family_fault_start_s,
            fault_stop_margin_s=args.family_fault_stop_margin_s,
            category=args.family_category,
            phase_keys=family_phase_keys,
        )
    elif args.single_topology is not None:
        if args.single_fault_pu is None or args.single_fault_duration_s is None:
            raise ValueError(
                "--single-topology requires --single-fault-pu and "
                "--single-fault-duration-s"
            )
        scenarios = [
            single_case_scenario(
                topology=args.single_topology,
                grid_pu=args.single_fault_pu,
                fault_duration_s=args.single_fault_duration_s,
                fault_start_s=args.single_fault_start_s,
                fault_stop_margin_s=args.single_fault_stop_margin_s,
                category=args.single_category,
                phase_key=args.single_phase_key,
            )
        ]
    else:
        scenarios = select_scenarios(args.curriculum)
    if any(str(s.category).lower() != "steady" for s in scenarios):
        proxy_path = args.proxy_calibration.resolve()
        proxy_meta = (
            json.loads(proxy_path.read_text(encoding="utf-8"))
            if proxy_path.exists()
            else {}
        )
        proxy_is_current = bool(
            proxy_meta.get("frt_validator_schema")
            == "hpt-frt-gates-v3-gbt19963.1"
            and proxy_meta.get("frt_calibration_status") == "current"
        )
        if not proxy_is_current and not args.allow_uncalibrated_fault_proxy:
            raise RuntimeError(
                "Fault SAC training requires a v3/current proxy calibration. "
                "Rebuild the family proxy from fresh switch-level rows, or use "
                "--allow-uncalibrated-fault-proxy for a non-promotable diagnostic run."
            )
    env_config = HPTVoltageEnvConfig(
        reg_limit=args.reg_limit,
        energy_limit=args.energy_limit,
        reg_d_limit=args.reg_d_limit,
        reg_q_limit=args.reg_q_limit,
        energy_d_limit=args.energy_d_limit,
        energy_q_limit=args.energy_q_limit,
        safety_classifier_path=str(args.safety_classifier) if args.safety_classifier else "",
        safety_penalty_weight=args.safety_penalty_weight,
        safety_unsafe_terminal=bool(args.safety_unsafe_terminal),
        teacher_prior_weight=args.teacher_prior_weight,
        envelope_reward_weight=args.envelope_reward_weight,
        calibrated_survival_reward_weight=args.calibrated_survival_reward_weight,
        calibration_ood_reward_weight=args.calibration_ood_reward_weight,
        calibration_ood_violation_reward_cap=args.calibration_ood_violation_reward_cap,
        reward_scale=args.reward_scale,
        action_projection_enable=bool(args.action_projection_enable),
        grid_reactive_reward_weight=args.grid_reactive_reward_weight,
        grid_current_reward_weight=args.grid_current_reward_weight,
        vdc_soft_reward_weight=args.vdc_soft_reward_weight,
        vdc_bounds_reward_weight=args.vdc_bounds_reward_weight,
        vdc_margin_reward_weight=args.vdc_margin_reward_weight,
        vdc_margin_pu=args.vdc_margin_pu,
        vdc_lower_barrier_reward_weight=args.vdc_lower_barrier_reward_weight,
        vdc_lower_barrier_start_pu=args.vdc_lower_barrier_start_pu,
        vdc_lower_barrier_floor_pu=args.vdc_lower_barrier_floor_pu,
        vdc_low_terminal_enable=bool(args.vdc_low_terminal_enable),
        vdc_low_terminal_pu=args.vdc_low_terminal_pu,
        vdc_low_terminal_penalty=args.vdc_low_terminal_penalty,
        grid_current_margin_reward_weight=args.grid_current_margin_reward_weight,
        grid_current_margin_pu=args.grid_current_margin_pu,
        recovery_action_reward_weight=args.recovery_action_reward_weight,
        recovery_reg_action_limit=args.recovery_reg_action_limit,
        recovery_energy_action_limit=args.recovery_energy_action_limit,
        recovery_vdc_high_reward_weight=args.recovery_vdc_high_reward_weight,
        recovery_vdc_high_limit_pu=args.recovery_vdc_high_limit_pu,
        recovery_energy_overshoot_gain=args.recovery_energy_overshoot_gain,
        recovery_energy_overshoot_threshold=args.recovery_energy_overshoot_threshold,
        lv_margin_reward_weight=args.lv_margin_reward_weight,
        lv_margin_pu=args.lv_margin_pu,
        proxy_vdc_reward_downshift_pu=args.proxy_vdc_reward_downshift_pu,
        proxy_grid_current_reward_upshift_pu=args.proxy_grid_current_reward_upshift_pu,
        action_slew_weight=args.action_slew_weight,
        fault_time_norm_s=args.fault_time_norm_s,
        recovery_time_norm_s=args.recovery_time_norm_s,
        calibration_path=str(args.proxy_calibration.resolve()),
        target_gate=args.target_gate,
        l1_current_limit_required=not bool(args.l1_disable_current_limit),
        hybrid_dc_channel_enable=bool(args.hybrid_dc_model),
        hybrid_dc_model_path=str(args.hybrid_dc_model.resolve()) if args.hybrid_dc_model else "",
        hybrid_dc_fault_pu_max=args.hybrid_dc_fault_pu_max,
        hybrid_dc_duration_ms_min=args.hybrid_dc_duration_ms_min,
        hybrid_dc_duration_ms_max=args.hybrid_dc_duration_ms_max,
        slow_state_correction_enable=bool(args.slow_state_correction),
        slow_state_correction_path=str(args.slow_state_correction.resolve())
        if args.slow_state_correction
        else "",
        slow_state_correction_fault_pu_max=args.slow_state_correction_fault_pu_max,
        slow_state_correction_duration_ms_min=args.slow_state_correction_duration_ms_min,
        slow_state_correction_duration_ms_max=args.slow_state_correction_duration_ms_max,
    )

    def make_env(idx: int):
        return lambda: HPTVoltageSACEnv(
            scenarios,
            config=env_config,
            seed=args.seed + idx,
            train_mode=True,
        )

    vec = DummyVecEnv([make_env(i) for i in range(args.n_envs)])
    assert vec.observation_space.shape == (OBS_DIM_HPT,)
    assert vec.action_space.shape == (ACT_DIM_HPT,)

    support_regularization_enabled = bool(args.sac_support_regularization_weight > 0)
    model_cls = (
        SupportRegularizedSAC
        if support_regularization_enabled or args.critic_only_warmup_updates > 0
        else SAC
    )
    split_head_init_from_shared = False
    actor_only_init = False

    def make_fresh_model() -> SAC:
        policy: str | type[SACPolicy] = (
            SplitHeadSACPolicy if args.controller_heads == "split" else "MlpPolicy"
        )
        return model_cls(
            policy,
            vec,
            learning_rate=args.learning_rate,
            buffer_size=100_000,
            batch_size=256,
            tau=0.005,
            gamma=0.99,
            train_freq=1,
            gradient_steps=1,
            policy_kwargs=dict(net_arch=[256, 256, 256]),
            device=pick_device(),
            seed=args.seed,
            verbose=1,
        )

    if args.init_model is not None and args.init_model.exists():
        if args.init_actor_only:
            init_probe = SAC.load(str(args.init_model), device=pick_device())
            model = make_fresh_model()
            copy_actor_only(init_probe, model)
            actor_only_init = True
        elif args.controller_heads == "split":
            init_probe = SAC.load(str(args.init_model), device=pick_device())
            init_actor_state = init_probe.policy.actor.state_dict()
            if actor_state_uses_split_heads(init_actor_state):
                model = model_cls.load(str(args.init_model), env=vec, device=pick_device())
            else:
                model = make_fresh_model()
                copy_shared_actor_to_split(init_probe, model)
                split_head_init_from_shared = True
        else:
            model = model_cls.load(str(args.init_model), env=vec, device=pick_device())
        model.verbose = 1
        set_learning_rate(model, args.learning_rate)
    else:
        model = make_fresh_model()

    behavior_anchor_x: np.ndarray | None = None
    behavior_anchor_y: np.ndarray | None = None
    support_anchor_x: np.ndarray | None = None
    support_anchor_y: np.ndarray | None = None
    anchor_metrics: list[dict] = []
    if args.behavior_anchor_epochs > 0:
        if args.behavior_anchor_dataset is not None:
            behavior_anchor_x, behavior_anchor_y = load_anchor_dataset(
                args.behavior_anchor_dataset
            )
        elif args.init_model is None or not args.init_model.exists():
            raise ValueError("--behavior-anchor-epochs requires a valid --init-model")
        else:
            behavior_anchor_x, behavior_anchor_y = collect_init_actor_anchor_samples(
                args.init_model,
                scenarios,
                config=env_config,
                episodes=args.behavior_anchor_episodes,
                noise_std=args.behavior_anchor_noise_std,
                seed=args.seed,
            )
    if support_regularization_enabled:
        if not isinstance(model, SupportRegularizedSAC):
            raise TypeError("Support regularization requires SupportRegularizedSAC")
        if (
            args.sac_support_anchor_dataset is not None
            and args.sac_support_anchor_manifest is not None
        ):
            raise ValueError(
                "Use either --sac-support-anchor-dataset or "
                "--sac-support-anchor-manifest, not both"
            )
        if args.sac_support_anchor_dataset is not None:
            support_anchor_x, support_anchor_y = load_support_anchor_dataset(
                args.sac_support_anchor_dataset
            )
        elif args.sac_support_anchor_manifest is not None:
            support_anchor_x, support_anchor_y = collect_manifest_actor_anchor_samples(
                args.sac_support_anchor_manifest,
                config=env_config,
                episodes_per_row=args.sac_support_anchor_episodes,
                noise_std=args.sac_support_anchor_noise_std,
                seed=args.seed,
            )
        else:
            if args.init_model is None or not args.init_model.exists():
                raise ValueError(
                    "--sac-support-regularization-weight requires either "
                    "--sac-support-anchor-manifest or a valid --init-model"
                )
            support_anchor_x, support_anchor_y = collect_init_actor_anchor_samples(
                args.init_model,
                scenarios,
                config=env_config,
                episodes=args.sac_support_anchor_episodes,
                noise_std=args.sac_support_anchor_noise_std,
                seed=args.seed,
            )
        model.set_support_regularization(
            support_anchor_x,
            support_anchor_y,
            weight=args.sac_support_regularization_weight,
            batch_size=args.sac_support_regularization_batch_size,
            action_weights=parse_action_weights(
                args.sac_support_action_weights,
                name="--sac-support-action-weights",
            ),
            nearest_replay=bool(args.sac_support_nearest_replay),
        )
        if bool(args.sac_energy_head_only):
            if args.controller_heads != "split":
                raise ValueError("--sac-energy-head-only requires --controller-heads split")
            model.set_energy_head_only_actor_update(True)
    if args.critic_only_warmup_updates > 0:
        if not isinstance(model, SupportRegularizedSAC):
            raise TypeError("Critic-only warm-up requires SupportRegularizedSAC")
        model.set_critic_only_warmup(args.critic_only_warmup_updates)
    reward_trace = RewardTraceCallback()
    if args.steps > 0:
        if args.behavior_anchor_epochs > 0:
            from sac.pretrain_hpt_actor_bc import train_actor_bc

            if behavior_anchor_x is None or behavior_anchor_y is None:
                raise RuntimeError("Behavior-anchor dataset was not built")
            trained = 0
            interval = max(1, int(args.behavior_anchor_interval_steps))
            action_weights = parse_action_weights(
                args.behavior_anchor_action_weights,
                name="--behavior-anchor-action-weights",
            )
            while trained < args.steps:
                chunk = min(interval, args.steps - trained)
                model.learn(total_timesteps=chunk, reset_num_timesteps=False, callback=reward_trace)
                trained += chunk
                anchor_metrics.append(
                    train_actor_bc(
                        model,
                        behavior_anchor_x,
                        behavior_anchor_y,
                        epochs=args.behavior_anchor_epochs,
                        batch_size=args.behavior_anchor_batch_size,
                        lr=args.behavior_anchor_lr,
                        seed=args.seed + trained,
                        action_weights=action_weights,  # type: ignore[arg-type]
                        energy_head_only=bool(args.behavior_anchor_energy_head_only),
                    )
                )
        else:
            model.learn(
                total_timesteps=args.steps,
                reset_num_timesteps=(args.init_model is None or args.init_actor_only),
                callback=reward_trace,
            )

    model_path = args.model_out
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(model_path))
    reward_trace_csv = run_dir / "sac_training_reward_trace.csv"
    write_rows_csv(reward_trace_csv, reward_trace.rows)
    diagnostics_trace_csv = run_dir / "sac_training_diagnostics_trace.csv"
    write_rows_csv(diagnostics_trace_csv, reward_trace.train_rows)
    metrics = evaluate_teacher_or_policy(
        model,
        scenarios,
        n_rollouts=args.eval_rollouts,
        config=env_config,
    )
    calibration_meta = {}
    calibration_path = args.proxy_calibration.resolve()
    if calibration_path.exists():
        cal = json.loads(calibration_path.read_text(encoding="utf-8"))
        calibration_meta = {
            "path": str(calibration_path),
            "schema": cal.get("schema"),
            "source_csv": cal.get("source_csv"),
            "energy_source_csv": cal.get("energy_source_csv"),
            "energy_bridge_mode": cal.get("energy_bridge_mode"),
            "target_phase_rms": cal.get("target_phase_rms"),
            "topologies": sorted(cal.get("topologies", {}).keys()),
        }
    sidecar = {
        "run_id": run_id,
        "controller": "hpt-voltage-sac",
        "validator_schema": "hpt-frt-gates-v3-gbt19963.1",
        "target_gate": args.target_gate,
        "l1_current_limit_required": not bool(args.l1_disable_current_limit),
        "observation_dim": OBS_DIM_HPT,
        "action_dim": ACT_DIM_HPT,
        "steps": args.steps,
        "seed": args.seed,
        "init_model": str(args.init_model) if args.init_model is not None else None,
        "init_actor_only": actor_only_init,
        "critic_only_warmup_updates": int(args.critic_only_warmup_updates),
        "model_path": str(model_path),
        "curriculum": args.curriculum,
        "single_case": {
            "enabled": args.single_topology is not None,
            "topology": args.single_topology,
            "fault_pu": args.single_fault_pu,
            "fault_duration_s": args.single_fault_duration_s,
            "fault_start_s": args.single_fault_start_s,
            "fault_stop_margin_s": args.single_fault_stop_margin_s,
            "category": args.single_category,
            "phase_key": args.single_phase_key,
        },
        "family_case": {
            "enabled": args.family_topology is not None,
            "topology": args.family_topology,
            "fault_pus": args.family_fault_pus,
            "fault_durations_ms": args.family_fault_durations_ms,
            "fault_start_s": args.family_fault_start_s,
            "fault_stop_margin_s": args.family_fault_stop_margin_s,
            "category": args.family_category,
            "phase_key": args.family_phase_key,
            "phase_keys": family_phase_keys,
        },
        "controller_heads": args.controller_heads,
        "scenario_summary": scenario_summary(scenarios),
        "proxy_calibration": calibration_meta,
        "metrics": metrics,
        "reward_trace_csv": str(reward_trace_csv),
        "reward_trace_episodes": len(reward_trace.rows),
        "diagnostics_trace_csv": str(diagnostics_trace_csv),
        "diagnostics_trace_rows": len(reward_trace.train_rows),
        "split_head_init_from_shared": split_head_init_from_shared,
        "behavior_anchor": {
            "enabled": bool(args.behavior_anchor_epochs > 0),
            "epochs": int(args.behavior_anchor_epochs),
            "interval_steps": int(args.behavior_anchor_interval_steps),
            "episodes": int(args.behavior_anchor_episodes),
            "noise_std": float(args.behavior_anchor_noise_std),
            "dataset": str(args.behavior_anchor_dataset)
            if args.behavior_anchor_dataset is not None
            else None,
            "samples": int(behavior_anchor_x.shape[0])
            if behavior_anchor_x is not None
            else 0,
            "updates": len(anchor_metrics),
            "last_metrics": anchor_metrics[-1] if anchor_metrics else None,
            "energy_head_only": bool(args.behavior_anchor_energy_head_only),
        },
        "sac_support_regularization": {
            "enabled": support_regularization_enabled,
            "weight": float(args.sac_support_regularization_weight),
            "batch_size": int(args.sac_support_regularization_batch_size),
            "anchor_episodes": int(args.sac_support_anchor_episodes),
            "anchor_noise_std": float(args.sac_support_anchor_noise_std),
            "anchor_manifest": (
                str(args.sac_support_anchor_manifest)
                if args.sac_support_anchor_manifest is not None
                else None
            ),
            "anchor_dataset": (
                str(args.sac_support_anchor_dataset)
                if args.sac_support_anchor_dataset is not None
                else None
            ),
            "action_weights": args.sac_support_action_weights,
            "nearest_replay": bool(args.sac_support_nearest_replay),
            "energy_head_only": bool(args.sac_energy_head_only),
            "anchor_samples": int(support_anchor_x.shape[0])
            if support_anchor_x is not None
            else 0,
        },
        "metadata_path": str(run_dir / "metadata.json"),
    }
    reward_summary: dict[str, str | int | list[str]] = {}
    try:
        reward_summary = summarize_sac_reward_traces(run_dir)
    except Exception as exc:  # pragma: no cover - summary plotting is diagnostic
        reward_summary = {"error": f"{type(exc).__name__}: {exc}"}
    sidecar["reward_summary"] = reward_summary
    model_path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    (run_dir / "summary.json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    write_experiment_metadata(
        run_dir,
        experiment_name="hpt_voltage_sac_train",
        config={
            "steps": args.steps,
            "n_envs": args.n_envs,
            "seed": args.seed,
            "learning_rate": args.learning_rate,
            "validator_schema": "hpt-frt-gates-v3-gbt19963.1",
            "target_gate": args.target_gate,
            "l1_current_limit_required": not bool(args.l1_disable_current_limit),
            "controller_heads": args.controller_heads,
            "split_head_init_from_shared": split_head_init_from_shared,
            "run_id": run_id,
            "curriculum": args.curriculum,
            "single_topology": args.single_topology,
            "single_fault_pu": args.single_fault_pu,
            "single_fault_duration_s": args.single_fault_duration_s,
            "single_fault_start_s": args.single_fault_start_s,
            "single_fault_stop_margin_s": args.single_fault_stop_margin_s,
            "single_category": args.single_category,
            "single_phase_key": args.single_phase_key,
            "family_topology": args.family_topology,
            "family_fault_pus": args.family_fault_pus,
            "family_fault_durations_ms": args.family_fault_durations_ms,
            "family_fault_start_s": args.family_fault_start_s,
            "family_fault_stop_margin_s": args.family_fault_stop_margin_s,
            "family_category": args.family_category,
            "family_phase_key": args.family_phase_key,
            "init_model": str(args.init_model) if args.init_model is not None else None,
            "init_actor_only": actor_only_init,
            "critic_only_warmup_updates": args.critic_only_warmup_updates,
            "model_out": str(args.model_out),
            "eval_rollouts": args.eval_rollouts,
            "export": bool(args.export),
            "export_out": str(args.export_out),
            "safety_classifier": str(args.safety_classifier) if args.safety_classifier else None,
            "safety_penalty_weight": args.safety_penalty_weight,
            "safety_unsafe_terminal": bool(args.safety_unsafe_terminal),
            "reg_limit": args.reg_limit,
            "energy_limit": args.energy_limit,
            "reg_d_limit": args.reg_d_limit,
            "reg_q_limit": args.reg_q_limit,
            "energy_d_limit": args.energy_d_limit,
            "energy_q_limit": args.energy_q_limit,
            "teacher_prior_weight": args.teacher_prior_weight,
            "envelope_reward_weight": args.envelope_reward_weight,
            "calibrated_survival_reward_weight": args.calibrated_survival_reward_weight,
            "calibration_ood_reward_weight": args.calibration_ood_reward_weight,
            "calibration_ood_violation_reward_cap": args.calibration_ood_violation_reward_cap,
            "reward_scale": args.reward_scale,
            "action_projection_enable": bool(args.action_projection_enable),
            "grid_reactive_reward_weight": args.grid_reactive_reward_weight,
            "grid_current_reward_weight": args.grid_current_reward_weight,
            "vdc_soft_reward_weight": args.vdc_soft_reward_weight,
            "vdc_bounds_reward_weight": args.vdc_bounds_reward_weight,
            "vdc_margin_reward_weight": args.vdc_margin_reward_weight,
            "vdc_margin_pu": args.vdc_margin_pu,
            "vdc_lower_barrier_reward_weight": args.vdc_lower_barrier_reward_weight,
            "vdc_lower_barrier_start_pu": args.vdc_lower_barrier_start_pu,
            "vdc_lower_barrier_floor_pu": args.vdc_lower_barrier_floor_pu,
            "vdc_low_terminal_enable": bool(args.vdc_low_terminal_enable),
            "vdc_low_terminal_pu": args.vdc_low_terminal_pu,
            "vdc_low_terminal_penalty": args.vdc_low_terminal_penalty,
            "grid_current_margin_reward_weight": args.grid_current_margin_reward_weight,
            "grid_current_margin_pu": args.grid_current_margin_pu,
            "lv_margin_reward_weight": args.lv_margin_reward_weight,
            "lv_margin_pu": args.lv_margin_pu,
            "proxy_vdc_reward_downshift_pu": args.proxy_vdc_reward_downshift_pu,
            "proxy_grid_current_reward_upshift_pu": args.proxy_grid_current_reward_upshift_pu,
            "slow_state_correction": str(args.slow_state_correction)
            if args.slow_state_correction
            else None,
            "slow_state_correction_fault_pu_max": args.slow_state_correction_fault_pu_max,
            "slow_state_correction_duration_ms_min": args.slow_state_correction_duration_ms_min,
            "slow_state_correction_duration_ms_max": args.slow_state_correction_duration_ms_max,
            "proxy_calibration": str(calibration_path),
            "allow_uncalibrated_fault_proxy": bool(args.allow_uncalibrated_fault_proxy),
            "action_slew_weight": args.action_slew_weight,
            "behavior_anchor_epochs": args.behavior_anchor_epochs,
            "behavior_anchor_interval_steps": args.behavior_anchor_interval_steps,
            "behavior_anchor_episodes": args.behavior_anchor_episodes,
            "behavior_anchor_noise_std": args.behavior_anchor_noise_std,
            "behavior_anchor_lr": args.behavior_anchor_lr,
            "behavior_anchor_batch_size": args.behavior_anchor_batch_size,
            "behavior_anchor_action_weights": args.behavior_anchor_action_weights,
            "behavior_anchor_energy_head_only": bool(args.behavior_anchor_energy_head_only),
            "sac_support_regularization_weight": args.sac_support_regularization_weight,
            "sac_support_regularization_batch_size": args.sac_support_regularization_batch_size,
            "sac_support_anchor_manifest": str(args.sac_support_anchor_manifest)
            if args.sac_support_anchor_manifest is not None
            else None,
            "sac_support_anchor_dataset": str(args.sac_support_anchor_dataset)
            if args.sac_support_anchor_dataset is not None
            else None,
            "sac_support_anchor_episodes": args.sac_support_anchor_episodes,
            "sac_support_anchor_noise_std": args.sac_support_anchor_noise_std,
            "sac_support_action_weights": args.sac_support_action_weights,
            "sac_support_nearest_replay": bool(args.sac_support_nearest_replay),
            "sac_energy_head_only": bool(args.sac_energy_head_only),
            "observation_dim": OBS_DIM_HPT,
            "action_dim": ACT_DIM_HPT,
        },
        topology_models=TOPOLOGY_MODELS,
        policy_checkpoint=model_path,
        extra={
            "summary_path": str(run_dir / "summary.json"),
            "model_sidecar_path": str(model_path.with_suffix(".json")),
            "proxy_calibration": calibration_meta,
        },
    )

    if args.export:
        export_hpt_actor(model_path, args.export_out)

    print(json.dumps(sidecar, indent=2), flush=True)


if __name__ == "__main__":
    main()


