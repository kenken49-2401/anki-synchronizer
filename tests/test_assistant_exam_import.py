import copy
import pytest
from scripts.assistant_exam_import import merge


def example():
    return {"id":"source", "sourceKey":"sheet:sample", "date":"", "kind":"未分類",
            "name":"sample", "subject":"数学", "score":0, "max":20,
            "scoreComplete":False, "questions":[{"name":"1","max":20,"score":None,
            "average":None,"selfscore":None,"feeling":None,"tags":[]}]}


def test_merge_preserves_existing_and_is_idempotent():
    current={"schema_version":1,"studies":[{"id":"s"}],"scores":[],
             "tasks":[{"id":"t"}],"pastPapers":[{"id":"p"}]}
    original=copy.deepcopy(current)
    payload={"format":"study-atlas-exams-v1","scores":[example()]}
    merged,count=merge(current,payload)
    assert count==1 and current==original
    assert merged["studies"]==current["studies"] and merged["pastPapers"]==current["pastPapers"]
    assert merged["scores"][0]["id"]!="source"
    repeated,count=merge(merged,payload)
    assert count==0 and repeated==merged


def test_invalid_data_does_not_mutate_current():
    current={"schema_version":1,"studies":[],"scores":[],"tasks":[]}
    original=copy.deepcopy(current)
    record=example()
    record["questions"][0]["score"]=21
    with pytest.raises(ValueError):
        merge(current,{"format":"study-atlas-exams-v1","scores":[record]})
    assert current==original
