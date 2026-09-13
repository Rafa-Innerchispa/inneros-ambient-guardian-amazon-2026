# Amazon integration map

## Alexa+ primary track

Implemented:

- self-hosted MCP endpoint
- advertised protocol `2025-11-25`
- Streamable-HTTP-compatible session lifecycle
- tool discovery and tool calls
- simulated Alexa+ web experience with voice input/output when the browser supports it

Remaining validation:

- run the endpoint against the Alexa+ hackathon preview/test surface and capture evidence/screenshots
- record the final demo using the exact participant-facing Amazon tooling if access is available

## AWS Builder mini challenge

Implemented:

- optional `strands-agents` dependency
- real Strands SDK import and `Agent` execution path in `src/ambient_guardian/aws_strands.py`
- explicit separation from the safety-critical local path

Current account note:

- Bedrock access is not required for the local demo. If account eligibility continues returning `ValidationException: Operation not allowed`, the project remains functional and Strands is enabled only when the account/runtime is available.

## Ring

Implemented:

- normalized Ring-compatible event contract
- safe simulator events used by the demo
- adapter boundary ready for official Ring API/device work

Not yet claimed:

- Ring primary track qualification. We will only select Ring once an official Ring API, SDK, simulator, or physical device is shown working in code and video.
