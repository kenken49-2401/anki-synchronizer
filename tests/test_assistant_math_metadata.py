import copy
import pytest
from scripts.assistant_math_metadata import merge_metadata


def test_metadata_enriches_only_missing_values_and_is_idempotent():
    record = {"id":"x", "name":"2025", "subject":"数学",
              "questions":[{"name":str(i), "score":i, "minutes":i*2} for i in range(1,7)]}
    record["questions"][0]["difficulty"] = "A"
    current = {"schema_version":1, "scores":[record], "tasks":[{"id":"t"}]}
    original = copy.deepcopy(current)
    payload = {"format":"study-atlas-math-metadata-v1","items":[
        {"year":"2025","difficulty":["B"]*6,"expectedMinutes":[25]*6}]}
    updated,count = merge_metadata(current,payload)
    assert current == original and count == 11
    assert updated["scores"][0]["questions"][0]["difficulty"] == "A"
    assert updated["scores"][0]["questions"][0]["minutes"] == 2
    assert updated["tasks"] == current["tasks"]
    assert merge_metadata(updated,payload)[1] == 0


def test_invalid_duration_does_not_change_snapshot():
    current={"schema_version":1,"scores":[]}
    with pytest.raises(ValueError):
        merge_metadata(current,{"format":"study-atlas-math-metadata-v1","items":[
          {"year":"2025","difficulty":["A"]*6,"expectedMinutes":[27]*6}]})
    assert current=={"schema_version":1,"scores":[]}
