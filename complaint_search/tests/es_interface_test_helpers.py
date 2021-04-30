import json
import os.path

from deepdiff import DeepDiff


# -------------------------------------------------------------------------
# Helper Methods
# -------------------------------------------------------------------------

def to_absolute(fileName):
    # where is this module?
    thisDir = os.path.dirname(__file__)
    return os.path.join(thisDir, "expected_results", fileName)


def load(shortName):
    fileName = to_absolute(shortName + '.json')
    with open(fileName, 'r') as f:
        return json.load(f)


# -------------------------------------------------------------------------
# Test Helper Methods
# -------------------------------------------------------------------------

def assertBodyEqual(expected, actual):
    diff = DeepDiff(actual, expected)
    # print("***Actual*****",actual, "/n**********\n" )
    # print("***Expected*****", expected, "/n**********\n")
    # print("***Diff****", diff, "/n**********\n")
    if diff:  # pragma: no cover
        print(json.dumps(json.loads(diff.to_json()), indent=2, sort_keys=True))
        raise AssertionError('Request bodies do not match')
