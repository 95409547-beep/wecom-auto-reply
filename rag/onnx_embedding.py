"""CPU inference for the bundled BGE-small-zh-v1.5 embedding model."""

from pathlib import Path

import numpy as np


class OnnxBgeModel:
    def __init__(self, model_dir: Path):
        graph = model_dir / "model.onnx"
        tokenizer = model_dir / "tokenizer.json"
        if not graph.is_file() or not tokenizer.is_file():
            raise RuntimeError("便携版缺少资料库模型文件，请完整解压新版软件包。")

        from onnxruntime import InferenceSession, SessionOptions
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(tokenizer))
        self._tokenizer.enable_truncation(max_length=512)
        options = SessionOptions()
        options.intra_op_num_threads = 2
        self._session = InferenceSession(
            str(graph), sess_options=options, providers=["CPUExecutionProvider"],
        )

    def encode(self, text: str, *, normalize_embeddings: bool) -> np.ndarray:
        tokens = self._tokenizer.encode(text.strip().lower())
        feeds = {
            "input_ids": np.array([tokens.ids], dtype=np.int64),
            "attention_mask": np.array([tokens.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([tokens.type_ids], dtype=np.int64),
        }
        vector = self._session.run(["embedding"], feeds)[0][0]
        if normalize_embeddings:
            vector = vector / max(np.linalg.norm(vector), 1e-12)
        return vector
