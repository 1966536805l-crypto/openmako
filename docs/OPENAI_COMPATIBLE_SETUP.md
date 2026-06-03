# OpenAI-Compatible Model Setup

Internal legacy QuantAgent setup note. This is not the current public v0.1 capability claim; the current public proof is the focused learning-effect gate linked from README.md and issue #1.

QuantAgent can call any Chat Completions compatible endpoint.

## Environment Variables

Do not write API keys into source files, `CLAUDE.md`, handoff files, or git-tracked docs.

```bash
export QUANTAGENT_OPENAI_BASE_URL="https://api.openai.com/v1"
export QUANTAGENT_OPENAI_API_KEY="YOUR_KEY_HERE"
export QUANTAGENT_MODEL="gpt-5.5"
export QUANTAGENT_REASONING_EFFORT="high"
```

For OpenAI-compatible gateways, replace the base URL with the vendor endpoint
you are authorized to use:

```bash
export QUANTAGENT_OPENAI_BASE_URL="https://gateway.example.com/v1"
```

## Test

```bash
qagent model-test --model gpt-5.5
qagent ask --model gpt-5.5 "用三句话总结当前量化项目状态"
```

If a gateway does not expose `gpt-5.5`, try listing or testing the exact model names provided by the vendor.

`bin/qagent` also loads `$HOME/.quantagent/secrets.env` automatically when it exists. Keep that file mode `600`.
