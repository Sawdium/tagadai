#!/usr/bin/env python3
"""
Test Runner - Run LeekScript tests with a dummy opponent.

Creates a custom test scenario where opponent does nothing, then runs each test AI
and collects debug output to report results.

Usage:
    python -m src.tools.testrunner                    # Run all tests in TESTS folder
    python -m src.tools.testrunner --test test_Sort   # Run specific test
    python -m src.tools.testrunner --list             # List available tests
    python -m src.tools.testrunner --setup            # Setup test scenario (first time)
    python -m src.tools.testrunner --cleanup          # Remove test scenario
"""

import sys
import json
import time
import argparse
import re
from pathlib import Path
from typing import Optional

from src.common import LeekWarsAPI, load_credentials
from src.common.errors import TagadAIError
from src.tools.fight import wait_for_fight, fetch_fight_logs

# Test configuration
TEST_SCENARIO_NAME = "TagadAI_TestRunner"
DUMMY_AI_NAME = "dummyAI"
DUMMY_LEEK_NAME = "TestDummy"


def get_api() -> tuple[LeekWarsAPI, dict]:
    """Initialize API and login."""
    try:
        login, password = load_credentials()
    except TagadAIError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    api = LeekWarsAPI()
    farmer = api.login(login, password)
    return api, farmer


def find_ai_by_name(api: LeekWarsAPI, name: str) -> Optional[dict]:
    """Find an AI by name."""
    ai_data = api.get_farmer_ais()
    for ai in ai_data.get("ais", []):
        if ai.get("name") == name:
            return ai
    return None


def find_scenario_by_name(api: LeekWarsAPI, name: str) -> Optional[dict]:
    """Find a test scenario by name."""
    scenarios = api.get_test_scenarios()
    for sid, scenario in scenarios.get("scenarios", {}).items():
        if scenario.get("name") == name:
            scenario["id"] = int(sid)
            return scenario
    return None


def setup_test_scenario(api: LeekWarsAPI, farmer: dict) -> dict:
    """Create or get test scenario with dummy opponent."""
    print("Setting up test scenario...", file=sys.stderr)

    # Check if scenario already exists
    existing = find_scenario_by_name(api, TEST_SCENARIO_NAME)
    if existing:
        print(f"  Using existing scenario: {TEST_SCENARIO_NAME} (id:{existing['id']})", file=sys.stderr)
        return existing

    # Find or create dummy AI
    dummy_ai = find_ai_by_name(api, DUMMY_AI_NAME)
    if not dummy_ai:
        print("ERROR: dummyAI not found. Please upload TESTS/dummyAI first.", file=sys.stderr)
        print("  Run: python -m src.tools.aisync new dummyAI", file=sys.stderr)
        print("  Then: python -m src.tools.aisync put <id> tagadalive/TESTS/dummyAI", file=sys.stderr)
        sys.exit(1)

    dummy_ai_id = dummy_ai["id"]
    print(f"  Found dummyAI (id:{dummy_ai_id})", file=sys.stderr)

    # Create scenario
    result = api.create_test_scenario(TEST_SCENARIO_NAME)
    if "error" in result:
        raise Exception(f"Failed to create scenario: {result}")

    scenario_id = result.get("scenario", {}).get("id") or result.get("id")
    print(f"  Created scenario: {TEST_SCENARIO_NAME} (id:{scenario_id})", file=sys.stderr)

    # Get our leek
    leeks = farmer.get("leeks", {})
    if not leeks:
        raise Exception("No leeks on account!")
    our_leek_id = int(list(leeks.keys())[0])
    our_leek = leeks[str(our_leek_id)]
    print(f"  Our leek: {our_leek['name']} (id:{our_leek_id})", file=sys.stderr)

    # Create dummy test leek for opponent
    result = api.create_test_leek(DUMMY_LEEK_NAME)
    if "error" in result:
        # Might already exist, try to find it
        scenarios = api.get_test_scenarios()
        test_leeks = scenarios.get("leeks", [])
        dummy_leek = None
        for l in test_leeks:
            if l.get("name") == DUMMY_LEEK_NAME:
                dummy_leek = l
                break
        if not dummy_leek:
            raise Exception(f"Failed to create test leek: {result}")
        dummy_leek_id = dummy_leek["id"]
    else:
        dummy_leek_id = result.get("leek", {}).get("id") or result.get("id")
    print(f"  Dummy leek: {DUMMY_LEEK_NAME} (id:{dummy_leek_id})", file=sys.stderr)

    # Add our leek to team 1 (AI will be set per-test)
    # We'll use a placeholder AI for now
    our_ai_id = our_leek.get("ai", dummy_ai_id)
    result = api.add_leek_to_scenario(scenario_id, our_leek_id, team=1, ai_id=our_ai_id)
    if "error" in result:
        print(f"  Warning adding our leek: {result}", file=sys.stderr)

    # Add dummy leek to team 2 with dummy AI
    result = api.add_leek_to_scenario(scenario_id, dummy_leek_id, team=2, ai_id=dummy_ai_id)
    if "error" in result:
        print(f"  Warning adding dummy leek: {result}", file=sys.stderr)

    print(f"  Test scenario ready!", file=sys.stderr)

    return {"id": scenario_id, "name": TEST_SCENARIO_NAME}


def cleanup_test_scenario(api: LeekWarsAPI):
    """Remove test scenario and dummy leek."""
    print("Cleaning up test scenario...", file=sys.stderr)

    scenario = find_scenario_by_name(api, TEST_SCENARIO_NAME)
    if scenario:
        result = api.delete_test_scenario(scenario["id"])
        print(f"  Deleted scenario: {result}", file=sys.stderr)
    else:
        print("  No scenario to delete", file=sys.stderr)

    # Find and delete dummy test leek
    scenarios = api.get_test_scenarios()
    for leek in scenarios.get("leeks", []):
        if leek.get("name") == DUMMY_LEEK_NAME:
            result = api.delete_test_leek(leek["id"])
            print(f"  Deleted test leek: {result}", file=sys.stderr)


def parse_test_output(api_logs: dict) -> list[dict]:
    """Parse debug output into test results (deduplicated by name - only first occurrence)."""
    results = []
    seen_names = set()  # Track test name only (not number) to deduplicate across turns

    for farmer_id, farmer_logs in api_logs.items():
        if isinstance(farmer_logs, dict):
            # Only look at first action (turn 1 results)
            for action_idx in sorted(farmer_logs.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                messages = farmer_logs[action_idx]
                if isinstance(messages, list):
                    for msg in messages:
                        if isinstance(msg, list) and len(msg) >= 3:
                            level = msg[1]
                            text = str(msg[2])

                            # Parse test assertions
                            if " OK" in text or " SUCCESS" in text:
                                # Extract test name and number
                                match = re.match(r"(\d+)\s*[-:]?\s*(.+?)\s+(OK|SUCCESS)", text)
                                if match:
                                    num = int(match.group(1))
                                    name = match.group(2).strip()
                                    if name not in seen_names:
                                        seen_names.add(name)
                                        results.append({
                                            "num": num,
                                            "name": name,
                                            "status": "PASS",
                                            "message": text
                                        })
                            elif " FAIL" in text:
                                match = re.match(r"(\d+)\s*[-:]?\s*(.+?)\s+FAIL", text)
                                if match:
                                    num = int(match.group(1))
                                    name = match.group(2).strip()
                                    if name not in seen_names:
                                        seen_names.add(name)
                                        results.append({
                                            "num": num,
                                            "name": name,
                                            "status": "FAIL",
                                            "message": text
                                        })

    return results


def run_test(api: LeekWarsAPI, farmer: dict, ai_id: int, ai_name: str, scenario_id: int = 0) -> dict:
    """Run a single test AI and return results."""
    print(f"Running test: {ai_name} (id:{ai_id})...", file=sys.stderr)

    try:
        # Start test fight
        fight_id = api.start_test_fight(ai_id, scenario_id=scenario_id)
        print(f"  Fight #{fight_id} started", file=sys.stderr)

        # Wait for completion
        result = wait_for_fight(api, fight_id, timeout=120, is_test=True)

        # Get debug logs
        api_logs = fetch_fight_logs(api, fight_id)

        # Check for errors in actions
        errors = []
        actions = result.get("actions") or result.get("data", {}).get("actions", [])
        for action in actions:
            if action and action[0] in [1002, 1003, 1004, 1005, 1006]:
                errors.append({
                    "type": action[0],
                    "description": {
                        1002: "Too many operations",
                        1003: "Timeout",
                        1004: "Runtime exception",
                        1005: "Stack overflow",
                        1006: "Invalid operation"
                    }.get(action[0], f"Error {action[0]}")
                })

        # Parse test results from debug output
        test_results = parse_test_output(api_logs)

        return {
            "ai_name": ai_name,
            "ai_id": ai_id,
            "fight_id": fight_id,
            "success": len(errors) == 0,
            "errors": errors,
            "tests": test_results,
            "passed": sum(1 for t in test_results if t["status"] == "PASS"),
            "failed": sum(1 for t in test_results if t["status"] == "FAIL"),
        }

    except Exception as e:
        return {
            "ai_name": ai_name,
            "ai_id": ai_id,
            "fight_id": None,
            "success": False,
            "errors": [{"type": "exception", "description": str(e)}],
            "tests": [],
            "passed": 0,
            "failed": 0,
        }


def list_test_ais(api: LeekWarsAPI) -> list[dict]:
    """List all AI files that look like tests."""
    ai_data = api.get_farmer_ais()
    tests = []

    for ai in ai_data.get("ais", []):
        name = ai.get("name", "")
        # Match test files: test_*, *Test, simpleTest, etc.
        if name.startswith("test_") or name.endswith("Test") or "test" in name.lower():
            if name != "mainTest":  # Skip the full test suite
                tests.append(ai)

    return tests


def format_results(all_results: list[dict]) -> str:
    """Format all test results into a report."""
    lines = []
    lines.append("=" * 70)
    lines.append("TEST RESULTS")
    lines.append("=" * 70)

    total_passed = 0
    total_failed = 0
    total_warnings = 0

    for result in all_results:
        lines.append("")

        # Determine test status:
        # - OK if no test failures (assertions all pass)
        # - FAIL only if there are actual assertion failures or fatal errors
        has_test_failures = result["failed"] > 0
        has_fatal_errors = any(
            err["description"] not in ["Too many operations", "Timeout"]
            for err in result.get("errors", [])
        )
        has_warnings = any(
            err["description"] in ["Too many operations", "Timeout"]
            for err in result.get("errors", [])
        )

        if has_test_failures or has_fatal_errors:
            status = "FAIL"
        elif has_warnings:
            status = "WARN"
            total_warnings += 1
        else:
            status = "OK"

        lines.append(f"[{status}] {result['ai_name']}")

        # Show warnings (non-fatal errors like operation limits)
        if has_warnings and not has_test_failures:
            warning_count = sum(1 for err in result.get("errors", [])
                               if err["description"] in ["Too many operations", "Timeout"])
            lines.append(f"  (operation limit hit {warning_count}x - tests still ran)")

        # Show actual errors (fatal)
        if has_fatal_errors:
            for err in result["errors"]:
                if err["description"] not in ["Too many operations", "Timeout"]:
                    lines.append(f"  ERROR: {err['description']}")

        if result["tests"]:
            for test in result["tests"]:
                prefix = "  PASS" if test["status"] == "PASS" else "  FAIL"
                lines.append(f"{prefix}: {test['name']}")

            total_passed += result["passed"]
            total_failed += result["failed"]
        elif not result["errors"]:
            lines.append("  (no test assertions found)")

    lines.append("")
    lines.append("=" * 70)
    summary = f"TOTAL: {total_passed} passed, {total_failed} failed"
    if total_warnings > 0:
        summary += f", {total_warnings} with warnings"
    lines.append(summary)
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Run LeekScript tests")
    parser.add_argument("--test", type=str, help="Run specific test by name")
    parser.add_argument("--list", action="store_true", help="List available tests")
    parser.add_argument("--setup", action="store_true", help="Setup test scenario")
    parser.add_argument("--cleanup", action="store_true", help="Remove test scenario")
    parser.add_argument("--scenario", type=int, default=0, help="Scenario ID (0=Domingo)")
    args = parser.parse_args()

    api, farmer = get_api()
    print("Logged in.", file=sys.stderr)

    if args.cleanup:
        cleanup_test_scenario(api)
        return

    if args.setup:
        setup_test_scenario(api, farmer)
        return

    if args.list:
        tests = list_test_ais(api)
        print("Available tests:")
        for t in tests:
            valid = "VALID" if t.get("valid") else "INVALID"
            print(f"  {t['name']} (id:{t['id']}) [{valid}]")
        return

    # Get scenario ID (use custom or default to Domingo)
    scenario_id = args.scenario

    # Find tests to run
    if args.test:
        ai = find_ai_by_name(api, args.test)
        if not ai:
            print(f"ERROR: Test '{args.test}' not found", file=sys.stderr)
            sys.exit(1)
        tests = [ai]
    else:
        tests = list_test_ais(api)
        if not tests:
            print("No tests found. Create test AIs with 'test_' prefix.", file=sys.stderr)
            sys.exit(1)

    # Run tests
    all_results = []
    for i, test_ai in enumerate(tests):
        if not test_ai.get("valid"):
            print(f"Skipping invalid AI: {test_ai['name']}", file=sys.stderr)
            continue

        result = run_test(api, farmer, test_ai["id"], test_ai["name"], scenario_id)
        all_results.append(result)

        # Rate limit: wait between tests to avoid API overload
        if i < len(tests) - 1:
            time.sleep(2)

    # Output results
    print(format_results(all_results))


if __name__ == "__main__":
    main()
