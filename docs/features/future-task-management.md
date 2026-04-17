# Future Task Management

This document describes how AstrBot's "Future Task Management" feature works in the current codebase.

## What It Does

AstrBot can store scheduled tasks, wake up at the scheduled time, run the task through the main Agent, and deliver the result back to the original conversation session.

The current implementation supports two task shapes:

- Recurring tasks driven by a cron expression.
- One-off tasks driven by an ISO datetime `run_at`.

In the WebUI and public cron API, the main task type is `active_agent`. The scheduler also supports `basic` jobs for internal handler-based execution, but that path is not exposed by the current WebUI.

## Preconditions

For user-facing proactive scheduling to work as expected:

- `provider_settings.proactive_capability.add_cron_tools` must be enabled, so the Agent can call future-task tools.
- The target platform must support proactive messaging, otherwise the Agent may execute but cannot actively push the result back to the user.
- A valid session identifier is required. The WebUI expects `platform_id:message_type:session_id`.

Relevant code:

- Tool injection: `astrbot/core/astr_main_agent.py`
- Config metadata hint: `astrbot/core/config/default.py`
- WebUI page: `dashboard/src/views/CronJobPage.vue`

## Main Components

### 1. Persistence Model

Cron jobs are stored in the `cron_jobs` table via `CronJob`.

Important fields:

- `job_id`: public UUID-like identifier.
- `job_type`: `basic` or `active_agent`.
- `cron_expression`: cron string for recurring jobs.
- `payload`: JSON payload, including session and note.
- `run_once`: distinguishes one-off jobs from recurring jobs.
- `next_run_time`, `last_run_at`, `last_error`: runtime bookkeeping.

Code:

- `astrbot/core/db/po.py`
- `astrbot/core/db/sqlite.py`

### 2. Scheduler

`CronJobManager` is the runtime scheduler.

Behavior:

- Starts an `AsyncIOScheduler`.
- Loads persistent jobs from DB on startup.
- Builds `CronTrigger` for recurring jobs.
- Builds `DateTrigger` for one-off jobs.
- Updates `next_run_time` after scheduling.
- Marks runtime state in DB when a job starts or fails.
- Deletes one-off jobs after execution, regardless of success.

Code:

- `astrbot/core/cron/manager.py`
- `astrbot/core/core_lifecycle.py`

## Execution Flow

### Chat-created task

If proactive cron tools are enabled, the main Agent receives:

- `create_future_task`
- `delete_future_task`
- `list_future_tasks`

`create_future_task` collects:

- `note`
- `cron_expression` for recurring jobs, or
- `run_at` + `run_once=true` for one-off jobs

The tool stores:

- current session
- sender id
- task note
- `origin="tool"`

Code:

- `astrbot/core/tools/cron_tools.py`
- `astrbot/core/astr_main_agent.py`

### WebUI / API-created task

The dashboard calls:

- `GET /api/cron/jobs`
- `POST /api/cron/jobs`
- `PATCH /api/cron/jobs/<job_id>`
- `DELETE /api/cron/jobs/<job_id>`

`POST /api/cron/jobs` currently creates `active_agent` jobs only.

The request payload includes:

- `name`
- `note`
- `session`
- `cron_expression` or `run_at`
- optional `timezone`
- `enabled`

The route stores `origin="api"` in payload.

Code:

- `astrbot/dashboard/routes/cron.py`
- `dashboard/src/views/CronJobPage.vue`

### Runtime wake-up

When the trigger fires, `CronJobManager._run_job()`:

1. Loads the job from DB.
2. Marks it as running.
3. Dispatches by `job_type`.
4. Updates `last_run_at`, `next_run_time`, and `last_error`.

For `active_agent` jobs, the manager:

1. Builds a synthetic `CronMessageEvent`.
2. Restores the original conversation by session.
3. Injects cron metadata into `extras`.
4. Appends a scheduled-task system prompt.
5. Builds the main Agent.
6. Adds `SEND_MESSAGE_TO_USER_TOOL`.
7. Lets the Agent run until done.
8. Persists an execution summary into conversation history.

Code:

- `astrbot/core/cron/events.py`
- `astrbot/core/cron/manager.py`
- `astrbot/core/astr_main_agent_resources.py`

## Current Behavior Notes

- One-off jobs ignore `cron_expression`; recurring jobs require it.
- One-off jobs are deleted after execution. They are not retained as history records in `cron_jobs`.
- WebUI hides internal `status` when serializing jobs, to avoid misleading recurring-task semantics.
- The WebUI currently labels task type from `run_once` and `job_type`, but creation only covers `active_agent`.
- `persona_id` and `provider_id` can be accepted by the route payload and stored in payload, but the current scheduler wake-up path does not actively switch execution by those fields here.

## Limitations

- No dedicated execution history table for completed one-off jobs.
- No retry policy beyond the scheduler's normal next trigger for recurring jobs.
- No public WebUI path for internal `basic` jobs.
- Delivery depends on platform proactive-message capability and a valid session target.

## Practical Summary

This feature is implemented as "persistent cron job + synthetic message event + main Agent wake-up".

That means:

- scheduling is durable across restarts
- execution reuses normal Agent capabilities and conversation context
- result delivery follows the same messaging infrastructure as normal proactive sends
