# AI Coding Agent — Telegram-Driven Architecture

High-level container list and communication diagram for the Telegram-driven AI coding agent system (multi-agent debate, sandboxed testing, tokenised code review).

## Docker containers to build

| # | Container | What it does |
|---|---|---|
| 1 | **Telegram Gateway** | Only interface to Telegram. Translates bot messages ↔ internal queue messages. Renders buttons (Accept/Reject/Request Revision, mode choices) — no free-typed commands. Also where the user's global reset is triggered. |
| 2 | **RabbitMQ** | Internal message broker. Carries all traffic between Telegram Gateway, Debate Orchestrator, Agent A/B, Summariser, and Sandbox Orchestrator. |
| 3 | **Debate Orchestrator** | Deterministic coordinator, not an LLM. Runs the turn order (random start, alternating), applies the round cap, detects agreement, runs the closing-judgment/clean-up step, tracks task state in memory, handles reject/continue/restart branching, and joins the final result + summary before sending to Telegram Gateway. |
| 4 | **Agent A** | LLM agent, one side of the code debate. Also handles single-agent revision loops when it was the last debater. |
| 5 | **Agent B** | LLM agent, other side of the code debate. Same revision-handling role when applicable. |
| 6 | **Summariser Agent** | LLM agent, text-only. Writes the human-readable reasoning/weightage summary from a two-agent debate. Not used for single-agent revisions. |
| 7 | **Sandbox Orchestrator** | Spins up disposable, ephemeral test containers (CI-style: build from patched code, run, discard) for every debate turn and every revision. Feeds objective evidence (tests, lint, security scan) back to the Debate Orchestrator. Has no git access and is never internet-facing. |
| 8 | **Repo/Git Container** | Owns all git credentials and all git operations — pulls (only when user allows), pushes, manages working copies/branches, prepares diff artifacts, and wipes working state on an actual reject. Never exposed to the internet. |
| 9 | **Review API** | Thin, purpose-built gateway. Mints the tokenised link + bearer token, serves the diff to the frontend, accepts Accept/Reject/Revision decisions, enforces TTL and invalidates on decision or reject. The only container that talks to the public frontend. |
| 10 | **Reverse Proxy / Ingress** | The single container actually exposed to the internet. Terminates TLS, routes only to Review API endpoints. Nothing else in the stack is reachable externally. |
| 11 | **Redis (or similar TTL store)** | Holds token/session TTLs and in-memory debate/task state (turn history, accumulated feedback brief). Supports the day-long auto-expiry and the user-triggered global reset. |

Not a container, but part of the same design: the **isolated Docker bridge network** these all sit on, plus **ephemeral sandbox containers** (dynamically created/destroyed per test run by #7 — not a standing service), and the **Netlify-hosted frontend**, which is external and only ever talks to the Reverse Proxy.

## High-level communication diagram

```text
                                   Internet
                                       │
                              ┌────────┴────────┐
                              │  Netlify Frontend │  (external, static)
                              └────────┬────────┘
                                       │ HTTPS (token + bearer)
                              ┌────────┴────────┐
                              │  Reverse Proxy   │  ◄── only internet-facing container
                              └────────┬────────┘
                                       │
 ─────────────────────── isolated docker bridge network ───────────────────────
                                       │
                              ┌────────┴────────┐
                              │   Review API     │───┐
                              └────────┬────────┘   │ token/session TTL
                                       │             ▼
                              ┌────────┴────────┐  ┌─────────┐
                              │  Repo/Git        │  │  Redis  │
                              │  Container       │  └────┬────┘
                              └────────┬────────┘       │ task state / TTL
                                       │                 │
                              ┌────────┴────────┐        │
                Telegram ◄──► │  Telegram        │        │
                (bot msgs)    │  Gateway         │        │
                              └────────┬────────┘        │
                                       │                 │
                              ┌────────┴────────┐        │
                              │    RabbitMQ      │◄───────┘
                              └───┬────┬────┬───┘
                                  │    │    │
                     ┌────────────┘    │    └────────────┐
                     ▼                 ▼                 ▼
           ┌──────────────┐  ┌──────────────────┐ ┌──────────────┐
           │ Debate        │  │ Sandbox           │ │ Summariser   │
           │ Orchestrator  │◄─┤ Orchestrator      │ │ Agent        │
           └───┬───────┬───┘  └────────┬──────────┘ └──────────────┘
               │       │               │
               ▼       ▼               ▼
          ┌────────┐ ┌────────┐  ┌─────────────────┐
          │Agent A │ │Agent B │  │Ephemeral sandbox │
          └────────┘ └────────┘  │containers (spawned│
                                  │per test run, then │
                                  │destroyed)          │
                                  └────────────────────┘
```

Everything below the Reverse Proxy line stays inside the isolated bridge network; the Reverse Proxy is the only door in, and it only leads to the Review API. Repo/Git Container is the only holder of git credentials; Sandbox Orchestrator is the only thing that executes untrusted code, and it never touches git or the internet.
