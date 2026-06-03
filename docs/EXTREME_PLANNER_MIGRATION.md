# Migrating from Old Planner to Extreme Planner

Guide for transitioning from `cheap_plan` to `extreme_planner`.

## Quick Migration

### Before (Old Planner)

```python
from quantagent.cheap_plan import build_cheap_plan

plan = build_cheap_plan(project="/path/to/project", task="add feature")

# Returns: CheapPlan with free_first_commands and paid_next_step
for cmd in plan.free_first_commands:
    print(f"Run: {cmd}")
```

### After (Extreme Planner)

```python
from quantagent.extreme_planner import plan_task_to_operations

result = plan_task_to_operations(
    project=Path("/path/to/project"),
    task="add feature"
)

# Returns: dict with operations
if result["ok"]:
    for op in result["operations"]:
        # Execute operation (write_text, etc.)
        pass
```

## Key Differences

| Aspect | Old Planner | Extreme Planner |
|--------|-------------|-----------------|
| **Output** | Commands to run | Operations to execute |
| **AI Calls** | task-dependent | target: 1 planning call |
| **Cost** | benchmark required | target: <$0.05 |
| **Context** | Basic | Rich (local) |
| **Success Rate** | benchmark required | target: 80%+ |
| **Caching** | No | Yes |

## Migration Steps

### Step 1: Update Imports

```python
# Old
from quantagent.cheap_plan import build_cheap_plan

# New
from quantagent.extreme_planner import plan_task_to_operations
```

### Step 2: Update Function Calls

```python
# Old
plan = build_cheap_plan(project, task)
commands = plan.free_first_commands
next_step = plan.paid_next_step

# New
result = plan_task_to_operations(project, task)
operations = result["operations"] if result["ok"] else []
error = result.get("error")
```

### Step 3: Update Operation Handling

```python
# Old: Execute commands
for cmd in plan.free_first_commands:
    subprocess.run(cmd, shell=True)

# New: Execute operations
for op in result["operations"]:
    if op["op"] == "write_text":
        path = project / op["path"]
        path.write_text(op["text"])
```

### Step 4: Update Error Handling

```python
# Old
if plan.pressure_state == "critical":
    print("Token budget exceeded")

# New
if not result["ok"]:
    print(f"Planning failed: {result['error']}")
```

## CLI Migration

### Old Commands

```bash
# Old: cheap planner (implicit)
mako agent "add feature"

# Old: explicit cheap plan
mako plan --cheap "add feature"
```

### New Commands

```bash
# New: extreme planner (default)
mako agent "add feature"

# New: explicit extreme planner
mako agent "add feature" --planner extreme

# Fallback to old planner
mako agent "add feature" --planner cheap
```

## Configuration Migration

### Old Config

```json
{
  "planner": {
    "type": "cheap",
    "token_budget": 8000,
    "context_mode": "auto"
  }
}
```

### New Config

```json
{
  "planner": {
    "type": "extreme",
    "temperature": 0.2,
    "max_tokens": 4000,
    "enable_caching": true,
    "context_builder": {
      "relevant_files_limit": 10,
      "similar_code_limit": 3,
      "sample_files_limit": 20
    }
  }
}
```

## Code Patterns

### Pattern 1: Simple Task Planning

**Before:**
```python
def plan_simple_task(project, task):
    plan = build_cheap_plan(project, task)
    return {
        "commands": list(plan.free_first_commands),
        "cost": plan.model_calls * 0.10,
    }
```

**After:**
```python
def plan_simple_task(project, task):
    result = plan_task_to_operations(project, task)
    return {
        "operations": result["operations"],
        "cost": "provider/model dependent",
    }
```

### Pattern 2: Multi-Step Planning

**Before:**
```python
def plan_multi_step(project, tasks):
    plans = []
    for task in tasks:
        plan = build_cheap_plan(project, task)
        plans.append(plan)
    return plans
```

**After:**
```python
def plan_multi_step(project, tasks):
    results = []
    for task in tasks:
        result = plan_task_to_operations(project, task)
        results.append(result)
    return results
```

### Pattern 3: Conditional Planning

**Before:**
```python
def conditional_plan(project, task):
    plan = build_cheap_plan(project, task)

    if plan.pressure_state == "critical":
        # Reduce context
        plan = build_cheap_plan(project, task)

    return plan
```

**After:**
```python
def conditional_plan(project, task):
    result = plan_task_to_operations(project, task)

    if not result["ok"]:
        # Retry with simpler task
        result = plan_task_to_operations(project, simplified_task)

    return result
```

## Testing Migration

### Update Test Fixtures

**Before:**
```python
def test_planning():
    plan = build_cheap_plan("/tmp/project", "add test")
    assert len(plan.free_first_commands) > 0
    assert plan.model_calls == 0
```

**After:**
```python
def test_planning():
    result = plan_task_to_operations(Path("/tmp/project"), "add test")
    assert result["ok"]
    assert len(result["operations"]) > 0
```

### Update Mock Objects

**Before:**
```python
@patch('quantagent.cheap_plan.build_context_pack')
def test_with_mock(mock_pack):
    mock_pack.return_value = MockContextPack()
    plan = build_cheap_plan("/tmp/project", "task")
```

**After:**
```python
@patch('quantagent.extreme_planner.build_extreme_context')
def test_with_mock(mock_context):
    mock_context.return_value = MockTaskContext()
    result = plan_task_to_operations(Path("/tmp/project"), "task")
```

## Gradual Migration Strategy

### Phase 1: Parallel Running (Week 1)

Run both planners and compare:

```python
def plan_with_comparison(project, task):
    # Old planner
    old_plan = build_cheap_plan(project, task)

    # New planner
    new_result = plan_task_to_operations(project, task)

    # Log comparison
    log_comparison(old_plan, new_result)

    # Use new planner
    return new_result
```

### Phase 2: Selective Migration (Week 2)

Use new planner for specific task types:

```python
def plan_adaptive(project, task):
    if is_simple_task(task):
        # Use new planner for simple tasks
        return plan_task_to_operations(project, task)
    else:
        # Keep old planner for complex tasks
        return build_cheap_plan(project, task)
```

### Phase 3: Full Migration (Week 3)

Switch to new planner with fallback:

```python
def plan_with_fallback(project, task):
    result = plan_task_to_operations(project, task)

    if not result["ok"]:
        # Fallback to old planner
        plan = build_cheap_plan(project, task)
        return convert_plan_to_result(plan)

    return result
```

### Phase 4: Cleanup (Week 4)

Remove old planner code:

```python
# Remove all imports of cheap_plan
# Remove fallback logic
# Update all tests
```

## Common Issues

### Issue 1: Missing Context

**Problem:** Extreme planner fails due to missing repo map.

**Solution:**
```bash
mako repo-map rebuild
```

### Issue 2: Different Output Format

**Problem:** Code expects `free_first_commands`, gets `operations`.

**Solution:**
```python
# Add adapter
def adapt_result(result):
    if result["ok"]:
        return {
            "commands": [f"# Operation: {op['op']}" for op in result["operations"]],
            "operations": result["operations"]
        }
    return {"commands": [], "operations": []}
```

### Issue 3: Cost Tracking

**Problem:** Old cost tracking assumes multiple AI calls.

**Solution:**
```python
# Old
cost = plan.model_calls * 0.10

# New
cost = measured_model_cost(result)
```

### Issue 4: Token Budget

**Problem:** Old code checks `token_pressure`.

**Solution:**
```python
# Old
if plan.token_pressure > 0.9:
    reduce_context()

# New
# Extreme planner handles context automatically
# No manual token management needed
```

## Rollback Plan

If migration causes issues:

### Quick Rollback

```python
# In config
{
  "planner": {
    "type": "cheap"  # Switch back to old planner
  }
}
```

### Gradual Rollback

```python
# Add feature flag
USE_EXTREME_PLANNER = os.getenv("USE_EXTREME_PLANNER", "false") == "true"

def plan_task(project, task):
    if USE_EXTREME_PLANNER:
        return plan_task_to_operations(project, task)
    else:
        return build_cheap_plan(project, task)
```

## Performance Comparison

### Before Migration (100 tasks)

- Total cost: benchmark required
- Total time: benchmark required
- Success rate: benchmark required
- AI calls: benchmark required

### After Migration Target (100 tasks)

- Total cost: target lower than baseline
- Total time: target lower than baseline
- Success rate: target 80%+
- AI calls: target fewer than baseline

## Checklist

- [ ] Update imports from `cheap_plan` to `extreme_planner`
- [ ] Change function calls to `plan_task_to_operations`
- [ ] Update operation handling (commands → operations)
- [ ] Update error handling
- [ ] Update CLI commands
- [ ] Migrate configuration files
- [ ] Update tests and mocks
- [ ] Run parallel comparison (optional)
- [ ] Monitor success rate and cost
- [ ] Remove old planner code (after validation)

## Support

If you encounter issues during migration:

1. Check [EXTREME_PLANNER.md](EXTREME_PLANNER.md) for usage details
2. Run `mako doctor` to verify setup
3. Compare old vs new output with `--debug` flag
4. Report issues with reproduction steps

## Next Steps

After successful migration:

1. Monitor success rate and cost metrics
2. Tune configuration for your project
3. Provide feedback on edge cases
4. Explore advanced features (caching, adaptive context)
