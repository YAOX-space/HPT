from sac.campaigns.run_hpt_t2_balanced_lvrt_dq_seeded_boundary import (
    bounded_artifact_path,
    compact_label,
)


def test_long_campaign_artifact_paths_are_bounded_and_deterministic(tmp_path) -> None:
    label = "family_" + "very_long_case_label_" * 20

    first = bounded_artifact_path(
        tmp_path,
        prefix="eval_",
        label=label,
        suffix=".m",
        max_path_chars=180,
    )
    second = bounded_artifact_path(
        tmp_path,
        prefix="eval_",
        label=label,
        suffix=".m",
        max_path_chars=180,
    )

    assert first == second
    assert len(str(first)) <= 180
    assert first.suffix == ".m"
    assert first.name.startswith("eval_family_")


def test_matlab_result_label_is_compact_and_hashed() -> None:
    label = "case_" + "long_family_name_" * 20

    compact = compact_label(label, max_chars=64)

    assert len(compact) == 64
    assert compact == compact_label(label, max_chars=64)
    assert compact != compact_label(label + "x", max_chars=64)
