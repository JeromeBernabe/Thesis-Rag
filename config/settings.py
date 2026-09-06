import os
from pathlib import Path

import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

DATA_DIR = PROJECT_ROOT / "data"
MATH_DATASET_DIR = DATA_DIR / "math_dataset"
DATASETS_DIR = DATA_DIR / "datasets"
FINTECH_DIR = DATASETS_DIR
HOTPOT_DIR = DATASETS_DIR
MATH_DIR = DATASETS_DIR
RAGTRUTH_DIR = DATASETS_DIR / "no_structure_yet"
CHROMA_DIR = DATA_DIR / "chroma_db"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
CHECKPOINTS_DIR = PROJECT_ROOT / "checkpoints"
RESULTS_DIR = PROJECT_ROOT / "results"
RAGAS_RESULTS_PATH = RESULTS_DIR / "ragas_results_math.csv"  # default (math)

os.makedirs(MATH_DATASET_DIR, exist_ok=True)
os.makedirs(DATASETS_DIR, exist_ok=True)
os.makedirs(CHROMA_DIR, exist_ok=True)
os.makedirs(PROMPTS_DIR, exist_ok=True)
os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

VALID_DATASETS = ("fintech", "hotpot", "math", "ragtruth")

DATASET_COLLECTION_NAMES = {
    "fintech": "finTech_docs",
    "hotpot": "hotpot_docs",
    "math": "math_docs",
    "ragtruth": "ragtruth_docs",
}

DATASET_CORPUS_FILES = {
    "fintech": ["FinTech-Train.json"],
    "hotpot": ["hotpot_train.json"],
    "math": ["Math-Train.csv"],
    "ragtruth": ["Rag_Truth_Source.jsonl"],
}

DATASET_TEST_FILES = {
    "fintech": ["FinTech-Test.json"],
    "hotpot": ["hotpot_test.json"],
    "math": ["Math-Test.csv"],
    "ragtruth": ["Rag_Truth_Response.jsonl"],
}

DATASET_EVAL_PROMPTS_PATH = {
    "fintech": PROMPTS_DIR / "eval_prompts_fintech.json",
    "hotpot": PROMPTS_DIR / "eval_prompts_hotpot.json",
    "math": PROMPTS_DIR / "eval_prompts_math.json",
    "ragtruth": PROMPTS_DIR / "eval_prompts_ragtruth.json",
}

DATASET_CHECKPOINT_PATH = {
    "fintech": CHECKPOINTS_DIR / "dqn_model_fintech.pth",
    "hotpot": CHECKPOINTS_DIR / "dqn_model_hotpot.pth",
    "math": CHECKPOINTS_DIR / "dqn_model_math.pth",
    "ragtruth": CHECKPOINTS_DIR / "dqn_model_ragtruth.pth",
}

DATASET_RESULTS_PATH = {
    "fintech": RESULTS_DIR / "ragas_results_fintech.csv",
    "hotpot": RESULTS_DIR / "ragas_results_hotpot.csv",
    "math": RESULTS_DIR / "ragas_results_math.csv",
    "ragtruth": RESULTS_DIR / "ragas_results_ragtruth.csv",
}

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

EMBED_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
GENERATOR_MODEL = "llama3.2"
JUDGE_MODEL = "qwen3:8b"

GENERATION_TEMPERATURE = 0.1
GENERATION_MAX_TOKENS = 1024

COLLECTION_NAME = "math_docs"  # default; overridden per dataset
BASELINE_K = 3
ACTION_MIN_K = 1
ACTION_MAX_K = 5
NUM_ACTIONS = ACTION_MAX_K - ACTION_MIN_K + 1

DQN_GAMMA = 0.99
DQN_EPSILON_INIT = 1.0
DQN_EPSILON_MIN = 0.05
DQN_EPSILON_DECAY = 0.995
DQN_BUFFER_SIZE = 5000
DQN_BATCH_SIZE = 8
DQN_LR = 0.001
DQN_TARGET_REFRESH = 50
DQN_HIDDEN_1 = 128
DQN_HIDDEN_2 = 64
DQN_CHECKPOINT_PATH = CHECKPOINTS_DIR / "dqn_model.pth"

REWARD_W_FAITHFULNESS = 0.35
REWARD_W_RELEVANCY = 0.35
REWARD_W_K = 0.20

NUM_EVAL_PROMPTS = 50
PROMPT_BUILD_SEED = 42

RAGTRUTH_RESPONSE_MODEL = "gpt-4-0613"

RAGAS_TIMEOUT = 300
RAGAS_MAX_WORKERS = 1

MAX_CORPUS_DOCS = 30000