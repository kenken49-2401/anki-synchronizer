import copy
import pytest
from scripts.assistant_math_reference import merge_reference


def test_merge_preserves_current_data_and_is_idempotent():
    existing={"schema_version":1,"scores":[{"id":"s","score":12}],"studies":[{"id":"study"}]}
    original=copy.deepcopy(existing)
    questions=[{"difficulty":"B","minutes":16,"expectedMinutes":25} for _ in range(6)]
    payload={"format":"study-atlas-math-reference-v1","items":[{"year":"2025","questions":questions}]}
    merged,count=merge_reference(existing,payload)
    assert count==1 and existing==original
    assert merged["scores"]==existing["scores"] and merged["mathReference"]["2025"]==questions
    assert merge_reference(merged,payload)[1]==0


def test_invalid_metadata_rejected_without_mutation():
    existing={"schema_version":1,"scores":[]}
    original=copy.deepcopy(existing)
    questions=[{"difficulty":"B","minutes":16,"expectedMinutes":27} for _ in range(6)]
    with pytest.raises(ValueError):
        merge_reference(existing,{"format":"study-atlas-math-reference-v1","items":[{"year":"2025","questions":questions}]})
    assert existing==original
