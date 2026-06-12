#!/usr/bin/env python
"""
Test and demonstration of the Plan Validation and Normalization Layer.

This script shows how the validator catches and corrects Gemini planner hallucinations.
"""

from plan_validator import validate_plan, validate_and_normalize_step, get_validation_error_feedback
from execution_models import ExecutionPlan, ExecutionStep


def test_case_1_invalid_tool_name():
    """Test: Invalid tool name detection."""
    print("\n" + "="*70)
    print("TEST 1: Invalid tool name detection")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a pump",
        chat_only=False,
        steps=[
            ExecutionStep(tool="unknown_tool", args={"block_name": "pump", "x": 0, "y": 0})
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Original plan: {plan.steps[0].tool}")
    print(f"Valid: {is_valid}")
    print(f"Errors: {errors}")
    assert not is_valid, "Should have caught invalid tool"
    print("✓ PASSED: Invalid tool detected")


def test_case_2_missing_required_args():
    """Test: Missing required arguments detection."""
    print("\n" + "="*70)
    print("TEST 2: Missing required arguments detection")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a pump",
        chat_only=False,
        steps=[
            ExecutionStep(tool="insert_symbol", args={"block_name": "pump"})  # Missing x, y
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Original args: {plan.steps[0].args}")
    print(f"Valid: {is_valid}")
    print(f"Errors: {errors}")
    assert not is_valid, "Should have caught missing required args"
    print("✓ PASSED: Missing required args detected")


def test_case_3_argument_alias_normalization():
    """Test: Argument alias normalization."""
    print("\n" + "="*70)
    print("TEST 3: Argument alias normalization")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a pump",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "name": "pump",  # Should be normalized to block_name
                    "position_x": 100,  # Should be normalized to x
                    "position_y": 200,  # Should be normalized to y
                }
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Original args: {plan.steps[0].args}")
    print(f"Valid: {is_valid}")
    if is_valid:
        print(f"Normalized args: {normalized_plan.steps[0].args}")
        assert normalized_plan.steps[0].args.get("block_name") == "pump", "Should normalize name -> block_name"
        assert normalized_plan.steps[0].args.get("x") == 100, "Should normalize position_x -> x"
        assert normalized_plan.steps[0].args.get("y") == 200, "Should normalize position_y -> y"
        print("✓ PASSED: Arguments normalized correctly")
    else:
        print(f"Errors: {errors}")


def test_case_4_invalid_symbol_detection():
    """Test: Invalid symbol detection."""
    print("\n" + "="*70)
    print("TEST 4: Invalid symbol detection")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a compressor",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "block_name": "compressor",  # Not in available symbols
                    "x": 100,
                    "y": 200,
                }
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Symbol requested: {plan.steps[0].args['block_name']}")
    print(f"Available symbols: {available_symbols}")
    print(f"Valid: {is_valid}")
    print(f"Errors: {errors}")
    assert not is_valid, "Should have caught invalid symbol"
    print("✓ PASSED: Invalid symbol detected")


def test_case_5_unsupported_expression_detection():
    """Test: Unsupported arithmetic expression detection."""
    print("\n" + "="*70)
    print("TEST 5: Unsupported expression detection")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a pump with offset",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "block_name": "pump",
                    "x": "$step1.x + 100",  # Unsupported arithmetic
                    "y": 200,
                }
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Original X value: {plan.steps[0].args['x']}")
    print(f"Valid: {is_valid}")
    print(f"Errors: {errors}")
    assert not is_valid, "Should have caught unsupported expression"
    print("✓ PASSED: Unsupported expression detected")


def test_case_6_unsupported_args_removal():
    """Test: Unsupported arguments are removed."""
    print("\n" + "="*70)
    print("TEST 6: Unsupported arguments removal")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a pump",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "block_name": "pump",
                    "x": 100,
                    "y": 200,
                    "unsupported_arg": "should_be_removed",
                    "another_invalid_arg": 999,
                }
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Original args: {plan.steps[0].args}")
    print(f"Valid: {is_valid}")
    if is_valid:
        print(f"Normalized args: {normalized_plan.steps[0].args}")
        assert "unsupported_arg" not in normalized_plan.steps[0].args, "Should remove unsupported args"
        assert "another_invalid_arg" not in normalized_plan.steps[0].args, "Should remove unsupported args"
        print("✓ PASSED: Unsupported arguments removed")
    else:
        print(f"Errors: {errors}")


def test_case_7_multiple_errors():
    """Test: Multiple errors are caught and reported."""
    print("\n" + "="*70)
    print("TEST 7: Multiple errors caught")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Malformed plan",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "name": "nonexistent_symbol",  # Wrong name, wrong symbol
                    "position_x": 100,  # Wrong arg name
                    # Missing y coordinate
                }
            ),
            ExecutionStep(
                tool="unknown_tool",  # Invalid tool
                args={}
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Number of errors caught: {len(errors)}")
    print(f"Errors:")
    for error in errors:
        print(f"  - {error}")
    
    assert not is_valid, "Should have caught multiple errors"
    assert len(errors) > 0, "Should report at least one error"
    print("✓ PASSED: Multiple errors detected")


def test_case_8_valid_plan_with_references():
    """Test: Valid plan with step references."""
    print("\n" + "="*70)
    print("TEST 8: Valid plan with step references")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert two entities and connect them",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "block_name": "pump",
                    "x": 0,
                    "y": 0,
                }
            ),
            ExecutionStep(
                tool="insert_symbol", 
                args={
                    "block_name": "motor",
                    "x": 500,
                    "y": 0,
                }
            ),
            ExecutionStep(
                tool="connect_pipe",
                args={
                    "start_handle": "$step1.entity_handle",
                    "end_handle": "$step2.entity_handle",
                }
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Plan has {len(plan.steps)} steps")
    print(f"Valid: {is_valid}")
    if errors:
        print(f"Errors: {errors}")
    
    assert is_valid, "Should validate valid plan with references"
    assert len(normalized_plan.steps) == 3, "All steps should be present"
    print("✓ PASSED: Valid plan accepted")


def test_case_8b_valid_plan_with_free_space_reference():
    """Test: Valid plan with free-space placement and x/y step references."""
    print("\n" + "="*70)
    print("TEST 8B: Valid plan with free-space placement references")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Insert a motor 100 units to the right of a valve and connect them",
        chat_only=False,
        steps=[
            ExecutionStep(
                tool="find_entity",
                args={"search_term": "4_way_valve"}
            ),
            ExecutionStep(
                tool="find_free_space_near_entity",
                args={"reference_handle": "$step1.entity_handle", "offset_x": 100}
            ),
            ExecutionStep(
                tool="insert_symbol",
                args={"block_name": "motor", "x": "$step2.x", "y": "$step2.y"}
            ),
            ExecutionStep(
                tool="connect_pipe",
                args={"start_handle": "$step1.entity_handle", "end_handle": "$step3.entity_handle"}
            )
        ]
    )
    
    available_symbols = ["pump", "motor", "4_way_valve"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Valid: {is_valid}")
    if errors:
        print(f"Errors: {errors}")
    assert is_valid, "Should validate plan with free-space x/y references"
    print("✓ PASSED: Free-space reference plan validated")


def test_case_9_validation_error_feedback():
    """Test: Validation error feedback for retry."""
    print("\n" + "="*70)
    print("TEST 9: Validation error feedback generation")
    print("="*70)
    
    errors = [
        "Step 1: Unknown tool: find_all_valves",
        "Step 2: Missing required arguments: search_term",
        "Step 3: Unknown symbol: tank_large",
    ]
    
    feedback = get_validation_error_feedback(errors)
    
    print("Validation Error Feedback:")
    print(feedback)
    
    assert "find_all_valves" in feedback, "Should include tool error"
    assert "search_term" in feedback, "Should include argument error"
    assert "parameters defined in tool schemas" in feedback, "Should include rules"
    print("✓ PASSED: Feedback generated correctly")


def run_all_tests():
    """Run all validation tests."""
    print("\n" + "█"*70)
    print("  PLAN VALIDATION AND NORMALIZATION LAYER - TEST SUITE")
    print("█"*70)
    
    tests = [
        test_case_1_invalid_tool_name,
        test_case_2_missing_required_args,
        test_case_3_argument_alias_normalization,
        test_case_4_invalid_symbol_detection,
        test_case_5_unsupported_expression_detection,
        test_case_6_unsupported_args_removal,
        test_case_7_multiple_errors,
        test_case_8_valid_plan_with_references,
        test_case_8b_valid_plan_with_free_space_reference,
        test_case_9_validation_error_feedback,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n✗ FAILED: {e}")
            failed += 1
    
    print("\n" + "█"*70)
    print(f"  TEST RESULTS: {passed} passed, {failed} failed")
    print("█"*70 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    import sys
    success = run_all_tests()
    sys.exit(0 if success else 1)
