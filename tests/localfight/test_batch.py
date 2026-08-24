"""Tests for the persistent generator pool (needs the generator)."""

import json

import pytest

from src.localfight.batch import GeneratorPool, GeneratorWorker, ensure_batch_main
from src.localfight.runner import RunnerError, check_generator, run_fight
from src.localfight.scenario import Scenario

# Valid JSON, but nothing the generator can turn into a Scenario.
NOT_A_SCENARIO = '{"garbage": true}'


@pytest.fixture(scope="module")
def generator_check():
    if not check_generator():
        pytest.skip("Generator not available")
    ensure_batch_main()


def test_pool_matches_one_shot_and_is_deterministic(generator_check):
    scenario = Scenario.create_1v1_pistol(seed=42)
    one_shot = run_fight(scenario)
    with GeneratorPool(workers=2) as pool:
        a = pool.run(scenario.to_json())
        b = pool.run(scenario.to_json())
    for r in (a, b):
        assert r["winner"] == one_shot["winner"]
        assert r["duration"] == one_shot["duration"]
        assert r["fight"]["actions"] == one_shot["fight"]["actions"]


def test_worker_survives_a_bad_scenario(generator_check):
    worker = GeneratorWorker(index=99)
    try:
        with pytest.raises(RunnerError):
            worker.run(NOT_A_SCENARIO)
        assert worker.alive
        with pytest.raises(RunnerError, match="not JSON"):
            worker.run("{not json")
        result = worker.run(Scenario.create_1v1_pistol(seed=7).to_json())
        assert "winner" in result and worker.fights == 1
    finally:
        worker.close()
    assert not worker.alive


def test_pool_map_keeps_order_and_reports_failures(generator_check):
    good = Scenario.create_1v1_pistol(seed=1).to_json()
    with GeneratorPool(workers=2) as pool:
        out = pool.map([good, NOT_A_SCENARIO, good])
    assert out[1] is None
    assert out[0] is not None and out[2] is not None
    assert out[0]["fight"]["actions"] == out[2]["fight"]["actions"]


def test_pool_raises_when_every_scenario_fails(generator_check):
    with GeneratorPool(workers=1) as pool:
        with pytest.raises(RunnerError):
            pool.map([NOT_A_SCENARIO, NOT_A_SCENARIO])
