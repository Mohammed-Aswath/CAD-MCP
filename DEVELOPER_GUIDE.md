## Plan Validation Layer - Developer Guide

Quick reference for implementing and extending the Plan Validation & Normalization Layer.

---

## Quick Start

### Enable Validation Automatically

Validation is **automatically enabled** in the agent system. No configuration needed.

```python
from agent_engine import AIAgent

agent = AIAgent()
response = agent.process_message("Add a pump to the drawing")

# Validation happens automatically:
# 1. Gemini generates plan
# 2. Validator checks plan
# 3. If invalid, retry with feedback
# 4. If still invalid, fallback to chat
# 5. Execute validated plan
```

---

## How Validation Works

### 1. Basic Validation Flow

```python
from plan_validator import validate_plan
from execution_models import ExecutionPlan, ExecutionStep

# Create a plan (normally from Gemini)
plan = ExecutionPlan(
    thought="Insert pump and motor",
    chat_only=False,
    steps=[
        ExecutionStep(tool="insert_symbol", args={"block_name": "pump", "x": 0, "y": 0}),
        ExecutionStep(tool="insert_symbol", args={"block_name": "motor", "x": 500, "y": 0}),
    ]
)

# Get available symbols
available_symbols = ["pump", "motor", "4_way_valve"]

# Validate plan
is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)

if is_valid:
    print("✓ Plan valid, ready to execute")
    # Use normalized_plan for execution
else:
    print(f"✗ Plan invalid: {errors}")
    # Retry or fallback
```

### 2. Validate Single Step

```python
from plan_validator import validate_and_normalize_step

step = {"tool": "insert_symbol", "args": {"name": "pump", "x": 100, "y": 200}}
available_symbols = ["pump", "motor", "4_way_valve"]
prior_results = {}  # No prior steps

is_valid, normalized_step, error = validate_and_normalize_step(
    step, 
    available_symbols, 
    prior_results
)

if is_valid:
    print(f"Normalized: {normalized_step.args}")
    # Output: {"block_name": "pump", "x": 100, "y": 200}
else:
    print(f"Error: {error}")
```

---

## Adding Custom Argument Aliases

Aliases allow automatic correction of common misspellings.

### Location: `plan_validator.py`

```python
ARG_ALIASES = {
    "insert_symbol": {
        "name": "block_name",           # Current aliases
        "symbol": "block_name",
        # Add your own below
        "symbol_type": "block_name",   # Custom alias
        "type": "block_name",          # Custom alias
    },
    "move_entity": {
        "handle": "entity_handle",      # Current aliases
        # Add below
        "ent_handle": "entity_handle",  # Custom alias
    }
}
```

### Example: Add alias for offset parameters

```python
# Before: User request sends "move_distance_x"
ARG_ALIASES["move_entity"] = {
    "handle": "entity_handle",
    "dx": "dx",
    "dy": "dy",
    "dz": "dz",
    "move_distance_x": "dx",    # NEW
    "move_distance_y": "dy",    # NEW
    "move_distance_z": "dz",    # NEW
}

# After: Validator auto-corrects to "dx", "dy", "dz"
```

---

## Adding New Validation Rules

### 1. Add to Expression Detection

**Location:** `plan_validator.py` - `_detect_unsupported_expressions()`

```python
def _detect_unsupported_expressions(value: Any) -> Optional[str]:
    """Detect unsupported expressions in arguments."""
    if not isinstance(value, str):
        return None
    
    # Existing checks...
    
    # Add new check for parentheses expressions
    if re.search(r'angle\s*\(\s*\w+\s*\)', value):
        return f"Function call not supported: {value}. Provide numeric value directly."
    
    # Add check for conditional syntax
    if " if " in value.lower() or " else " in value.lower():
        return f"Conditional expressions not supported: {value}"
    
    return None
```

### 2. Add to Tool Validation Schema

**Location:** `plan_validator.py` - `TOOL_VALIDATION_SCHEMA`

```python
TOOL_VALIDATION_SCHEMA = {
    # Existing tools...
    
    "my_new_tool": {
        "required": ["param1", "param2"],
        "optional": ["param3", "param4"],
        "type_hints": {
            "param1": "string",
            "param2": "number",
            "param3": "number",
        }
    }
}
```

### 3. Add Semantic Validation

Add custom validation in `validate_and_normalize_step()`:

```python
def validate_and_normalize_step(step, available_symbols, prior_step_results):
    # ... existing code ...
    
    # Add custom validation after argument normalization
    if tool_name == "my_custom_tool":
        # Validate custom business logic
        if normalized_args.get("param1") == "invalid_value":
            return False, ExecutionStep(tool="", args={}), "Invalid value for param1"
        
        # Validate relationships between arguments
        if normalized_args.get("x", 0) > normalized_args.get("y", 0):
            _log("VALIDATOR", "Warning: x > y is unusual but allowed")
    
    # ... rest of function ...
```

---

## Handling Validation Failures

### Manual Handling

```python
from plan_validator import validate_plan, get_validation_error_feedback

plan = ...  # From Gemini
available_symbols = [...]

is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)

if not is_valid:
    # Option 1: Retry with feedback
    feedback = get_validation_error_feedback(errors)
    print(f"Validation failed. Feedback:\n{feedback}")
    
    # Regenerate plan with feedback injected
    retry_prompt = f"{base_prompt}\n{feedback}"
    new_plan = gemini.generate(retry_prompt)
    
    # Option 2: Fallback to chat
    print("Plan validation failed. Falling back to chat-only response.")
    fallback_plan = ExecutionPlan(thought="Validation failed", chat_only=True, steps=[])
    
    # Option 3: Show error to user
    print(f"Could not plan execution: {errors}")
```

---

## Logging and Debugging

### Enable Debug Logging

The validator logs validation actions:

```python
[VALIDATOR] Validation found 2 errors
[VALIDATOR] Normalized arguments in insert_symbol:
  - name → block_name
  - position_x → x
[VALIDATOR] Removed unsupported arguments from insert_symbol: color, tag
[VALIDATOR] Plan validation passed
[VALIDATOR] Auto-correcting symbol pump_v2 → pump
```

### Get Detailed Validation Info

```python
from plan_validator import validate_and_normalize_step

step = {"tool": "insert_symbol", "args": {"x": "100", "y": "200"}}
is_valid, normalized, error = validate_and_normalize_step(step, ["pump"], {})

print(f"Original: {step['args']}")
print(f"Normalized: {normalized.args}")
print(f"Valid: {is_valid}")
# Output:
# Original: {'x': '100', 'y': '200'}
# Normalized: {'x': 100.0, 'y': 200.0}
# Valid: False (missing block_name)
```

---

## Testing Validation Rules

### Run Full Test Suite

```bash
python test_plan_validator.py
```

### Run Specific Test

```python
from test_plan_validator import test_case_3_argument_alias_normalization

test_case_3_argument_alias_normalization()
```

### Add New Test

```python
# In test_plan_validator.py
def test_case_my_new_validation():
    """Test: My new validation rule."""
    print("\n" + "="*70)
    print("TEST: My new validation rule")
    print("="*70)
    
    plan = ExecutionPlan(
        thought="Test scenario",
        chat_only=False,
        steps=[
            ExecutionStep(tool="my_tool", args={"param": "test_value"})
        ]
    )
    
    available_symbols = ["pump"]
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    print(f"Valid: {is_valid}")
    print(f"Errors: {errors}")
    
    assert is_valid, "Should pass validation"
    print("✓ PASSED: My validation rule works")
```

---

## Integration with Agent Engine

### Current Flow

```python
# In agent_engine.py process_message():

# 1. Generate plan
plan = self._generate_plan_with_gemini(user_message, context_summary)

# 2. Validate and normalize (NEW)
if plan.steps and not plan.chat_only:
    available_symbols = get_available_symbols()
    is_valid, normalized_plan, errors = validate_plan(plan, available_symbols)
    
    # 3. Retry if invalid (NEW)
    if not is_valid and retry_count < 1:
        feedback = get_validation_error_feedback(errors)
        plan = self._generate_plan_with_gemini(
            user_message, 
            context_summary, 
            validation_feedback=feedback
        )
        # Re-validate...
    
    # 4. Use validated plan
    plan = normalized_plan

# 5. Execute plan
execution_context = self.execution_engine.execute_plan(plan)
```

---

## Performance Considerations

### Validation Overhead

- **Time:** ~5-10ms per plan (typically <1 step overhead)
- **Memory:** <1KB per plan
- **No impact** on CAD execution

### Optimization Tips

1. **Cache schemas:** Don't rebuild TOOL_VALIDATION_SCHEMA repeatedly
   ```python
   _SCHEMA_CACHE = None
   def get_schema():
       global _SCHEMA_CACHE
       if _SCHEMA_CACHE is None:
           _SCHEMA_CACHE = TOOL_VALIDATION_SCHEMA
       return _SCHEMA_CACHE
   ```

2. **Batch validation:** Validate multiple plans at once
   ```python
   plans = [plan1, plan2, plan3]
   results = [validate_plan(p, symbols) for p in plans]
   ```

3. **Skip validation for trusted sources:**
   ```python
   if source == "human" and confidence > 0.95:
       skip_validation = True
   ```

---

## Extending Validation Capabilities

### 1. Symbol Similarity Matching

**What:** Auto-correct common symbol name variations

```python
# Add to plan_validator.py
def _find_similar_symbol_advanced(name: str, available_symbols: List[str]) -> Optional[str]:
    """Advanced fuzzy matching with domain knowledge."""
    variants = {
        "compressor": "pump",
        "tank_large": "vessel",
        "gate": "4_way_valve",
        "solenoid": "valve",
    }
    
    if name in variants:
        return variants[name]
    
    # Fall back to existing fuzzy matching
    return _find_similar_symbol(name, available_symbols)
```

### 2. Context-Aware Validation

**What:** Validate based on prior steps

```python
# In validate_and_normalize_step()
if prior_step_results.get("last_tool") == "find_entity":
    # If last step found entities, next step should reference them
    if tool_name == "move_entity":
        if "$step" not in str(normalized_args.get("entity_handle")):
            _log("VALIDATOR", "Warning: Should reference prior found entities")
```

### 3. Tool Capability Matrix

**What:** Validate argument combinations

```python
TOOL_CONSTRAINTS = {
    "insert_symbol": {
        "if_scale_present": ["rotation", "layer"],  # These allowed with scale
        "incompatible_args": [],
    },
    "connect_pipe": {
        "requires_both": ["start_handle", "end_handle"],  # Both required
    }
}

# Use in validation:
for required_pair in TOOL_CONSTRAINTS.get(tool_name, {}).get("requires_both", []):
    if required_pair not in normalized_args:
        return False, ..., f"Required argument: {required_pair}"
```

---

## API Reference

### Main Functions

```python
# Validate entire plan
validate_plan(plan: ExecutionPlan, available_symbols: List[str]) 
    → (is_valid: bool, normalized_plan: ExecutionPlan, errors: List[str])

# Validate single step
validate_and_normalize_step(step: Dict, available_symbols: List[str], prior_results: Dict)
    → (is_valid: bool, normalized_step: ExecutionStep, error: Optional[str])

# Get retry feedback
get_validation_error_feedback(errors: List[str]) → str

# Detect expressions
_detect_unsupported_expressions(value: Any) → Optional[str]

# Resolve variables
_resolve_variable_reference(reference: str, prior_results: Dict) → Any

# Find similar symbol
_find_similar_symbol(name: str, available_symbols: List[str]) → Optional[str]
```

---

## Common Patterns

### Pattern 1: Validate Before Execute

```python
plan = generate_plan()
is_valid, corrected_plan, _ = validate_plan(plan, symbols)
if is_valid:
    execute(corrected_plan)
else:
    chat_response("Plan validation failed")
```

### Pattern 2: Collect All Errors

```python
_, _, errors = validate_plan(plan, symbols)
if errors:
    feedback = get_validation_error_feedback(errors)
    retry_plan = regenerate_with_feedback(feedback)
```

### Pattern 3: Auto-Correct and Continue

```python
is_valid, corrected, _ = validate_plan(plan, symbols)
if is_valid:
    results = execute(corrected)
else:
    results = fallback()
```

---

## Troubleshooting

### Issue: Validation always fails

**Check:**
1. Available symbols list is not empty: `print(get_available_symbols())`
2. Tool names match schema: `print(TOOL_VALIDATION_SCHEMA.keys())`
3. Required args are present: `print(schema["required"])`

### Issue: Alias not working

**Check:**
1. Alias is in ARG_ALIASES dict
2. Tool name matches exactly
3. Alias key is lowercase
4. Validator logs show alias application

### Issue: Custom validation not running

**Check:**
1. Validation function is in correct module
2. Function is imported in agent_engine.py
3. Logic is in validate_and_normalize_step()
4. Logs show validation execution

---

## Best Practices

✅ **DO:**
- Always validate before execution
- Provide detailed error feedback
- Log normalization actions
- Test new rules with test suite
- Cache expensive computations
- Use type hints in schemas

❌ **DON'T:**
- Skip validation for "known good" sources
- Modify TOOL_SCHEMAS at runtime
- Swallow errors without logging
- Use unsafe eval() on plan content
- Assume Gemini output is correct
- Ignore validation feedback

---

## Support & Questions

For issues with plan validation:

1. Check logs: Look for `[VALIDATOR]` prefix messages
2. Run tests: `python test_plan_validator.py`
3. Review examples: See `GEMINI_HALLUCINATIONS_AND_CORRECTIONS.md`
4. Debug: Add print statements in `plan_validator.py`

---

**Version:** 1.0  
**Status:** Production Ready  
**Last Updated:** 2024
