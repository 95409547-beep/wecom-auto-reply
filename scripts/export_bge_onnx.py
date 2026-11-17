"""Export the local BGE weights for the Windows portable build.

Requires the project's Python environment plus onnx==1.17.0. PyTorch is
used only on the build machine.
"""

from pathlib import Path
from tempfile import TemporaryDirectory


MODEL_DIR = Path(__file__).resolve().parents[1] / "bge_model"


def export_model(model_dir: Path) -> None:
    import torch
    from transformers import AutoModel

    model = AutoModel.from_pretrained(
        model_dir, local_files_only=True, attn_implementation="eager",
    )

    class ClsEmbedding(torch.nn.Module):
        def __init__(self, encoder):
            super().__init__()
            self.encoder = encoder

        def forward(self, input_ids, attention_mask, token_type_ids):
            outputs = self.encoder(
                input_ids=input_ids, attention_mask=attention_mask,
                token_type_ids=token_type_ids,
            )
            return outputs.last_hidden_state[:, 0, :]

    inputs = {
        "input_ids": torch.tensor([[101, 100, 102]], dtype=torch.long),
        "attention_mask": torch.ones((1, 3), dtype=torch.long),
        "token_type_ids": torch.zeros((1, 3), dtype=torch.long),
    }
    with TemporaryDirectory(prefix=".onnx-", dir=model_dir) as folder:
        output = Path(folder) / "model.onnx"
        with torch.no_grad():
            torch.onnx.export(
                ClsEmbedding(model).eval(), tuple(inputs.values()), str(output),
                input_names=list(inputs), output_names=["embedding"], opset_version=17,
                dynamic_axes={name: {1: "sequence_length"} for name in inputs},
                dynamo=False,
            )
        output.replace(model_dir / output.name)


if __name__ == "__main__":
    export_model(MODEL_DIR)
