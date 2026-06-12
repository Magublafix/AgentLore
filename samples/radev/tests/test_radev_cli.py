"""
Acceptance test suite for the radev CLI (restful-api.dev client).
All tests run against the live API — determinism enforced via create-then-operate fixtures.
Run with: pytest samples/radev/tests/test_radev_cli.py -v
"""
import json
import subprocess
import pytest


def radev(*args, check=True):
    result = subprocess.run(
        ["radev", *args],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if check and result.returncode != 0:
        pytest.fail(
            f"radev {' '.join(args)} exited {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

class TestList:
    def test_returns_json_array(self):
        result = radev("list")
        data = json.loads(result.stdout)
        assert isinstance(data, list)

    def test_each_item_has_id_and_name(self):
        result = radev("list")
        items = json.loads(result.stdout)
        assert len(items) > 0
        for item in items:
            assert "id" in item
            assert "name" in item


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_returns_object_with_id(self):
        result = radev("create", "--name", "Benchmark-Create", "--data", '{"year": 2026}')
        obj = json.loads(result.stdout)
        assert "id" in obj
        assert obj["name"] == "Benchmark-Create"

    def test_missing_name_exits_nonzero(self):
        result = radev("create", "--data", '{"year": 2026}', check=False)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# get
# ---------------------------------------------------------------------------

class TestGet:
    @pytest.fixture
    def created_id(self):
        result = radev("create", "--name", "Benchmark-Get", "--data", '{"val": 1}')
        return json.loads(result.stdout)["id"]

    def test_returns_correct_object(self, created_id):
        result = radev("get", str(created_id))
        obj = json.loads(result.stdout)
        assert obj["id"] == created_id
        assert obj["name"] == "Benchmark-Get"

    def test_nonexistent_id_exits_nonzero(self):
        result = radev("get", "nonexistent-id-xyz-000", check=False)
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------

class TestUpdate:
    @pytest.fixture
    def created_id(self):
        result = radev("create", "--name", "Benchmark-Update", "--data", '{"year": 2025}')
        return json.loads(result.stdout)["id"]

    def test_update_reflects_in_get(self, created_id):
        radev("update", str(created_id), "--data", '{"year": 2026}')
        result = radev("get", str(created_id))
        obj = json.loads(result.stdout)
        assert obj["data"]["year"] == 2026


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------

class TestDelete:
    @pytest.fixture
    def created_id(self):
        result = radev("create", "--name", "Benchmark-Delete", "--data", '{}')
        return json.loads(result.stdout)["id"]

    def test_delete_exits_zero(self, created_id):
        result = radev("delete", str(created_id))
        assert result.returncode == 0

    def test_get_after_delete_exits_nonzero(self, created_id):
        radev("delete", str(created_id))
        result = radev("get", str(created_id), check=False)
        assert result.returncode != 0
