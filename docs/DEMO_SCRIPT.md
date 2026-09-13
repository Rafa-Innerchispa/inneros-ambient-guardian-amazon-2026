# Demo video outline - under 3 minutes

## 0:00-0:20 - Problem

"Smart homes generate alerts, but people still have to investigate five apps before they know whether anything is actually wrong. Ambient Guardian lets Alexa+ ask InnerOS one higher-level question: what is happening, what should happen next, and can we prove it happened?"

## 0:20-1:05 - Understand

1. Show the web Alexa+ simulation.
2. Trigger `Unknown person`.
3. Ask: "Alexa, is everything okay at home?"
4. Show `attention_required`, the concise answer, and the event context.
5. Point out local-Qwen mode when the local endpoint is connected.

## 1:05-1:50 - Act safely

1. Ask: "Alexa, lock the front door."
2. Show that the system prepares the action but explicitly says it was **not executed**.
3. Click approve.
4. Show post-action verification and the evidence ID.
5. Replay the approval token if useful to show fail-closed behavior.

## 1:50-2:25 - Architecture

Show the simple flow: Alexa+ -> MCP -> InnerOS local reasoning -> adapter -> approval -> verification -> evidence. Mention that AWS Strands is optional orchestration and cannot authorize physical actions.

## 2:25-2:55 - Why it matters

"The product is not another dashboard. It reduces the distance between 'What is happening?' and 'What safely happened next?' while keeping sensitive context local and keeping the human in control."
