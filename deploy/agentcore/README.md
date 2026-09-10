# Deploying the extraction agent to Amazon Bedrock AgentCore

**Status: prepared, not yet deployed.** The runtime, the client that calls it and their
tests are in the repository and run offline. The steps below have not yet been run
against an AWS account.

## What is deployed, and what is not

Only the **untrusted zone** runs on AgentCore: the extraction agent that reads document
text. The ledger, the deterministic engine, the API and the interface stay where the case
data is.

```
local pipeline ── document text ──▶ AgentCore Runtime (agentcore_app.py)
                                      extraction agent, throwaway ledger
local ledger  ◀── proposals ───────  facts with page + quote, fields marked missing
   │
   └─ every proposal replayed through the local LedgerWriter:
      quote located again on the local copy, field and write origin checked,
      text hash compared — anything unverifiable is refused and audited locally
```

The runtime's answer is treated as a proposal, not a result. A compromised or
misconfigured runtime can propose anything and record nothing the local ledger would not
have accepted from a local agent. This is tested in `tests/agents/test_runtime.py`.

## Before you start

1. **Model access.** In the Amazon Bedrock console, in the region you deploy to, request
   access to the Claude model configured in `config/models.yaml`. Confirm the model id the
   console shows; if it differs (for example a regional inference profile), set
   `OVERTURN_MODEL_ID_EXTRACTION` on the runtime rather than editing the file.
2. **Credentials** for an AWS account that can create AgentCore runtimes, with a region
   set (`AWS_REGION`).
3. **Execution role.** The runtime's role needs permission to invoke that model
   (`bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on it). The toolkit
   can create a role for you during configuration.

## Deploy with the starter toolkit

Verified against `bedrock-agentcore-starter-toolkit` (the command formerly called
`launch` is now `deploy`):

```bash
pip install -e ".[agents,agentcore]" bedrock-agentcore-starter-toolkit

agentcore configure \
  --entrypoint agentcore_app.py \
  --name overturn_extraction \
  --requirements-file deploy/agentcore/requirements.txt

agentcore deploy
agentcore status          # note the agent runtime ARN
```

AWS now recommends the newer AgentCore CLI (`npm install -g @aws/agentcore`) over the
Python starter toolkit, and it can import a starter-toolkit configuration with
`agentcore import`. Either produces the same runtime.

## Smoke test

```bash
agentcore invoke '{"doc_id": "doc_smoke", "pages": ["Date of notice: August 1, 2026\nDenial code: CO-50"]}'
```

The response lists proposed facts with their page and quote, the fields marked missing,
and how many writes were refused inside the runtime. A malformed payload returns
`{"error": ...}` without calling the model.

## Point Overturn at it

```bash
export OVERTURN_EXTRACTOR=agentcore
export OVERTURN_AGENTCORE_ARN=arn:aws:bedrock-agentcore:<region>:<account>:runtime/<id>
export AWS_REGION=<region>

uvicorn --factory overturn.api.app:app_from_env --port 8000
python -m overturn.scheduler --interval 900
python -m overturn.eval --extractor agentcore --limit 5
```

Each document is sent in its own runtime session, matching the one-agent-per-document
isolation of the local path.
