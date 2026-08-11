import json

from sac.experiment_metadata import sha256_file, write_experiment_metadata


def test_hpt_experiment_metadata_records_git_and_file_hash(tmp_path):
    model = tmp_path / "toy_model.slx"
    model.write_bytes(b"toy switch model")
    checkpoint = tmp_path / "actor.zip"
    checkpoint.write_bytes(b"actor weights")

    metadata = write_experiment_metadata(
        tmp_path,
        experiment_name="unit-test",
        config={"seed": 7, "steps": 12},
        topology_models={"toy": model},
        policy_checkpoint=checkpoint,
    )

    saved = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert saved == metadata
    assert metadata["schema"] == "hpt-v2-experiment-metadata-v1"
    assert metadata["experiment_name"] == "unit-test"
    assert metadata["config"]["seed"] == 7
    assert "commit_short" in metadata["git"]
    assert metadata["git"]["commit_short"] is None or metadata["git"]["commit_short"]
    assert metadata["model_hashes"]["toy"] == sha256_file(model)
    assert metadata["policy_checkpoint_hash"] == sha256_file(checkpoint)
