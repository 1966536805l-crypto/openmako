# Extreme Planner

AI-powered code generation planner with extreme context building and prompt caching.

## Overview

Extreme Planner adds AI-powered code generation with local context building. Its current success-rate and cost numbers are targets/estimates that still require a full benchmark run; the verified part in this repository is the planner interface, local context assembly, verifier/fixer flow, and targeted regression suite.

1. **Extreme Context Building** (0 AI calls, all local)
   - Semantic search using local embeddings
   - Static dependency analysis
   - Project convention extraction
   - Similar code retrieval
   - Type information from LSP

2. **Prompt Engineering**
   - Rich context injection
   - Project-specific conventions
   - Common mistake warnings
   - Similar implementation examples

3. **Prompt Caching**
   - Cacheable system prompt (project context)
   - Variable user prompt (specific task)
   - Designed to reduce repeated context cost when provider caching is available

## Architecture

```
Task Input
    ↓
ExtremeContextBuilder (0 AI calls)
    ├─ Semantic search (local embeddings)
    ├─ Dependency analysis (static)
    ├─ Convention extraction (AST)
    ├─ Similar code retrieval
    └─ Common mistakes DB
    ↓
TaskContext (rich, local)
    ↓
ExtremePlanner
    ├─ Build extreme prompt
    ├─ Split cacheable/variable parts
    └─ Generate with caching (1 AI call)
    ↓
Operations (write_text, etc.)
```

## Cost Comparison

| Planner | Cost per Task | AI Calls | Context Quality | Success Rate |
|---------|---------------|----------|-----------------|--------------|
| Old (cheap_plan) | benchmark required | task-dependent | Basic | benchmark required |
| **Extreme Planner** | **target: <$0.05** | **target: 1 planning call** | **Rich local context** | **target: 80%+** |

Cost breakdown:
- Context building: $0 (all local)
- First planning call: provider/model dependent
- Cache hit: provider/model dependent

## Usage

### Basic Usage

```python
from pathlib import Path
from quantagent.extreme_planner import plan_task_to_operations

# Plan a task
result = plan_task_to_operations(
    project=Path("/path/to/project"),
    task="Add a function to calculate Fibonacci numbers with memoization"
)

if result["ok"]:
    for op in result["operations"]:
        print(f"Operation: {op['op']}")
        print(f"Path: {op['path']}")
        print(f"Content preview: {op['text'][:100]}...")
else:
    print(f"Error: {result['error']}")
```

### CLI Integration

```bash
# Use extreme planner (default in new versions)
mako agent "add user authentication to the API"

# Force extreme planner
mako agent "refactor database layer" --planner extreme

# Use old planner (for comparison)
mako agent "simple task" --planner cheap
```

### Programmatic Usage

```python
from quantagent.extreme_planner import ExtremePlanner
from pathlib import Path

planner = ExtremePlanner(Path("/path/to/project"))

# Plan a task
result = planner.plan("Add input validation to user registration")

# Result structure:
# {
#     "ok": True,
#     "operations": [
#         {"op": "write_text", "path": "src/validation.py", "text": "..."},
#         {"op": "write_text", "path": "tests/test_validation.py", "text": "..."}
#     ]
# }
```

## Context Building Details

### 1. Semantic Search (Local)

Finds relevant files using BM25 + PageRank:

```python
from quantagent.extreme_context import build_extreme_context

context = build_extreme_context(project_root, task)

# context.relevant_files contains:
# - File paths with relevance scores
# - Symbol names (functions, classes)
# - Code previews
```

### 2. Dependency Analysis

Static analysis of import relationships:

```python
# Automatically extracts:
# - Import graph
# - Module dependencies
# - Symbol references
```

### 3. Convention Extraction

Learns from existing codebase:

```python
# Detected conventions:
# - Naming style (snake_case, camelCase, PascalCase)
# - Docstring style (google, numpy, sphinx)
# - Type hints usage
# - Test framework (pytest, unittest)
# - Quote style (single, double)
# - Line length
```

### 4. Similar Code Retrieval

Finds similar implementations:

```python
# Returns:
# - Similar code snippets
# - Reason for similarity
# - Relevance score
```

## Prompt Engineering

### System Prompt (Cacheable)

Contains project-wide context:
- Python version
- Framework (Django, Flask, FastAPI)
- Test framework
- Project conventions
- Common patterns

### User Prompt (Variable)

Contains task-specific information:
- Task description
- Relevant code snippets
- Similar implementations
- Common mistakes to avoid

### Output Format

Model generates structured output:

```
FILE: path/to/file.py
<complete file content>

FILE: tests/test_file.py
<complete test content>
```

## Success Rate Optimization

Target: 80%+ first-try success

Strategies:
1. **Rich Context**: Provide all relevant information upfront
2. **Convention Following**: Enforce project style automatically
3. **Edge Case Handling**: Warn about common mistakes
4. **Complete Output**: Require production-ready code
5. **Low Temperature**: Use 0.2 for consistency

## Enabling/Disabling

### Enable Extreme Planner (Default)

```python
# In code
from quantagent.extreme_planner import plan_task_to_operations

result = plan_task_to_operations(project, task)
```

```bash
# CLI (default)
mako agent "your task"
```

### Disable (Use Old Planner)

```python
# In code
from quantagent.cheap_plan import build_cheap_plan

plan = build_cheap_plan(project, task)
```

```bash
# CLI
mako agent "your task" --planner cheap
```

### Configuration

Add to project `.quantagent/config.json`:

```json
{
  "planner": {
    "type": "extreme",
    "temperature": 0.2,
    "max_tokens": 4000,
    "enable_caching": true
  }
}
```

## Benchmark Targets

These numbers are acceptance targets, not completed benchmark results.

| Task Type | Old Planner | Extreme Planner | Improvement |
|-----------|-------------|-----------------|-------------|
| Add function | baseline needed | target: 80%+ | unverified |
| Refactor code | baseline needed | target: 75%+ | unverified |
| Add tests | baseline needed | target: 80%+ | unverified |
| Fix bug | baseline needed | target: 80%+ | unverified |
| Add validation | baseline needed | target: 80%+ | unverified |
| **Average** | **baseline needed** | **target: 80%+** | **unverified** |

### Cost Analysis (100 tasks)

| Metric | Old Planner | Extreme Planner | Savings |
|--------|-------------|-----------------|---------|
| Total cost | benchmark required | target: lower | unverified |
| Avg per task | benchmark required | target: <$0.05 | unverified |
| AI calls | benchmark required | target: fewer | unverified |
| Context build cost | benchmark required | $0 model spend | local-only context |

### Time Performance

| Phase | Old Planner | Extreme Planner |
|-------|-------------|-----------------|
| Context building | benchmark required | local, benchmark required |
| Planning | benchmark required | model/provider dependent |
| **Total** | **benchmark required** | **benchmark required** |

## Limitations

1. **Requires local embeddings**: First-time setup needed
2. **Large projects**: Context building may take longer (still local)
3. **Novel patterns**: May struggle with completely new architectures
4. **Model dependency**: Requires capable model (GPT-4, Claude 3+)

## Troubleshooting

### Context Building Fails

```bash
# Rebuild repo map
mako repo-map rebuild

# Check embedding provider
mako doctor --check embeddings
```

### Low Success Rate

```bash
# Increase context quality
mako agent "task" --context-mode rich

# Check conventions detection
mako conventions show
```

### High Cost

```bash
# Verify caching is enabled
mako config show planner.enable_caching

# Check cache hit rate
mako stats planner --cache-hits
```

## Future Improvements

1. **Adaptive context**: Adjust context size based on task complexity
2. **Failure learning**: Learn from failed attempts
3. **Multi-shot refinement**: Automatic retry with feedback
4. **Custom conventions**: User-defined project rules
5. **Incremental updates**: Reuse previous context for related tasks

## Related Documentation

- [Migration Guide](EXTREME_PLANNER_MIGRATION.md)
- [Context Engine](CONTEXT_ENGINE.md)
- [Design Decisions](DESIGN_DECISIONS.md)
- [Comparison with Other Tools](COMPARISON.md)
