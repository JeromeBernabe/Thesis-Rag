import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from config import settings
from config.settings import DEVICE


class QNetwork(nn.Module):
    """Linear(768 -> 128) -> ReLU -> Linear(128 -> 64) -> ReLU -> Linear(64 -> 5)."""

    def __init__(
        self,
        input_dim: int = settings.EMBEDDING_DIM,
        hidden_1: int = settings.DQN_HIDDEN_1,
        hidden_2: int = settings.DQN_HIDDEN_2,
        num_actions: int = settings.NUM_ACTIONS,
    ):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_1),
            nn.ReLU(),
            nn.Linear(hidden_1, hidden_2),
            nn.ReLU(),
            nn.Linear(hidden_2, num_actions),
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.net(state)


@dataclass
class Experience:
    state: np.ndarray
    action: int
    reward: float
    done: int = 1


class ReplayBuffer:
    def __init__(self, capacity: int = settings.DQN_BUFFER_SIZE):
        self.buffer: deque = deque(maxlen=capacity)

    def push(self, state, action, reward, done=1) -> None:
        self.buffer.append(Experience(np.asarray(state, dtype=np.float32), action, reward, done))

    def sample(self, batch_size: int) -> tuple:
        batch = random.sample(self.buffer, batch_size)
        states = torch.tensor(
            np.stack([e.state for e in batch]), dtype=torch.float32
        ).to(DEVICE)
        actions = torch.tensor([e.action for e in batch], dtype=torch.long).to(DEVICE)
        rewards = torch.tensor([e.reward for e in batch], dtype=torch.float32).to(DEVICE)
        dones = torch.tensor([e.done for e in batch], dtype=torch.float32).to(DEVICE)
        return states, actions, rewards, dones

    def __len__(self) -> int:
        return len(self.buffer)


class DQNAgent:
    def __init__(
        self,
        gamma: float = settings.DQN_GAMMA,
        epsilon: float = settings.DQN_EPSILON_INIT,
        epsilon_min: float = settings.DQN_EPSILON_MIN,
        epsilon_decay: float = settings.DQN_EPSILON_DECAY,
        buffer_size: int = settings.DQN_BUFFER_SIZE,
        batch_size: int = settings.DQN_BATCH_SIZE,
        lr: float = settings.DQN_LR,
        target_refresh: int = settings.DQN_TARGET_REFRESH,
        checkpoint_path: Path = settings.DQN_CHECKPOINT_PATH,
    ):
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.target_refresh = target_refresh
        self.checkpoint_path = Path(checkpoint_path)

        self.num_actions = settings.NUM_ACTIONS
        self.q_net = QNetwork().to(DEVICE)
        self.target_net = QNetwork().to(DEVICE)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        self.optimizer = torch.optim.Adam(self.q_net.parameters(), lr=lr)
        self.loss_fn = nn.MSELoss()
        self.replay_buffer = ReplayBuffer(buffer_size)

        self.steps = 0

    def _state_tensor(self, state) -> torch.Tensor:
        arr = np.asarray(state, dtype=np.float32).reshape(1, -1)
        return torch.tensor(arr, dtype=torch.float32).to(DEVICE)

    def q_values(self, state) -> list[float]:
        """Q-value for every action, index i corresponding to k = i + ACTION_MIN_K.

        Exposed as the single way to read the network's scores. Both
        `run_experiment_logged.get_q_values` and `src.dqn_rag` need them, and
        duplicating the torch plumbing in each place previously meant both had
        to know about `q_net` and `DEVICE`.
        """
        with torch.no_grad():
            q = self.q_net(self._state_tensor(state)).squeeze(0)
        return [float(q[i]) for i in range(self.num_actions)]

    def greedy_action(self, state) -> int:
        return int(max(range(self.num_actions), key=self.q_values(state).__getitem__))

    def select_action(self, state) -> int:
        if random.random() < self.epsilon:
            return random.randint(0, self.num_actions - 1)
        return self.greedy_action(state)

    def store(self, state, action, reward) -> None:
        self.replay_buffer.push(state, action, reward)

    def train_step(self) -> float | None:
        if len(self.replay_buffer) < self.batch_size:
            return None
        states, actions, rewards, dones = self.replay_buffer.sample(self.batch_size)
        q_values = self.q_net(states).gather(1, actions.unsqueeze(1)).squeeze(1)
        with torch.no_grad():
            next_q = self.target_net(states).max(dim=1).values
        targets = rewards + self.gamma * next_q * (1.0 - dones)
        loss = self.loss_fn(q_values, targets)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        self.steps += 1
        if self.steps % self.target_refresh == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())
        return float(loss.item())

    def decay_epsilon(self) -> None:
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def save(self, path: Path | None = None) -> None:
        path = Path(path) if path is not None else self.checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "q_net": {k: v.cpu() for k, v in self.q_net.state_dict().items()},
                "target_net": {k: v.cpu() for k, v in self.target_net.state_dict().items()},
                "optimizer": {k: v.cpu() if isinstance(v, torch.Tensor) else v
                              for k, v in self.optimizer.state_dict().items()},
                "epsilon": self.epsilon,
                "steps": self.steps,
            },
            path,
        )

    def load(self, path: Path | None = None) -> None:
        path = Path(path) if path is not None else self.checkpoint_path
        if not path.exists():
            raise FileNotFoundError(f"checkpoint not found: {path}")
        ckpt = torch.load(path, map_location=DEVICE)
        self.q_net.load_state_dict(ckpt["q_net"])
        self.target_net.load_state_dict(ckpt["target_net"])
        self.optimizer.load_state_dict(ckpt["optimizer"])
        self.epsilon = ckpt["epsilon"]
        self.steps = ckpt["steps"]