# Loom Link
https://www.loom.com/share/9e22a699a24b41c8ba7f2cb08948f966

# Tool routing strategy
In the give problem we had 191 tools across 7 services: github 86, googlecalendar 29, linear 25, gmail 20, googledrive 20, slack 10, perplexity 1. Generally the more tool we have the harder and more expensive it becomes for one ai llm model to find the right tool, i wanted to have a strategy that is scalable to multiple services and tools, with good reliabiliy and low cost. Generally tool selection quality degrades and cost explodes around 30 tools(this is an assumption and more testing needs to be done for exact number, but the architechture is very easily scalable for any such number, i currently took it as 28 if this number is say 20 instead of 30 then we can put 18 instead). The first idea was a form of embedding and semantic search but this will likely struggle with multi tool calling as there may be some implicity tool to be called in the future that is not obvious. LLM work well for finding the right tool but large context become very expensive. Thus this is my proposed routing strategy:

1) Stage 1:  A lenient service classifier, where for each of the seven services we have written what each of them do, then an llm tells based on given use input which of those services can be useful now or in the future and then give that list, this is a pretty simple task so i used gpt-4.1-mini, though a higher power model can be used as well without any significant impact on net cost.

2) Stage 2: Here there are two cases depending on if the total tool in the services given by stage 1 is more than or less than 28, say in a given case we have only slack and perplexity then total tools are 11 i.e less than 28, in that case we dont do anything, alternatively say we have github, then we give an llm  one line per tool descrption and asks it to select top 28 tools that may be useful for that task. Here i used gpt-4.1 since this is an important task, and the input and output are both small so not that big cost impact and this is useful as a failsafe as told in stage 4.

3) Stage 3: Then we have our Orchestrator loop, which is described in more detail later. This chooses the best tool of those 28, since there json can be long and it has to fill them this can be costly thus i used gpt-4.1-mini.

4) Stage 4: Escape hatch — find_more_tools: a synthetic meta-tool present in every loop when called with "what I need" it re-runs the finder over the entire catalog and merges results into the active toolset. Covers both failure modes i.e. bad initial routing, and multi-step plans where step 3's tool is only knowable after step 1's result. 

# Orchestration loop structure
This has differnet aspects as noted below:

Parallel vs serial: decided by the model per iteration, guided by prompt policy ,independent lookups are requested together in one iteration (parallel_tool_calls=True), dependent steps (find email → then post summary) come in sequential iterations because step 2's arguments need step 1's results.

Multi-step reasoning: emerges from the iterate and feedback structure , each iteration the model sees all prior results and decides the next step. If a later step needs a tool that wasn't routed, it calls find_more_tools (escape hatch) to pull more from the full catalog mid-loop.

Ambiguity — first try cheap read only lookups and if exactly one match then we proceed. Only if genuinely ambiguous case we ask one clarifying question and stop. I also set a hard rule to never mutate a guessed target, asking costs a turn, a wrong delete/send that will fails the end state check. Once the user answers we complete the action same turn without any re asking.

Stopping: We stop with the tool callings in the following cases

1)  model returns text with no tool calls. this is the normal case when no other tool call is needed

2) we have set max iteration as 8 and max tool call as 24 as a hard stop, then it tells the report and not claim sucess, one issue is i dont know the validations done and so this might be too little, but in normal cases this seems enough and logical to me.

3) breakers like duplicate call (same tool + identical args) and say a tool that fails twice → further calls refused with "report the failure honestly"

# Future improvements (with extra 8 hours)
The biggest thing is evaluation and testing, i really would like to test a lot of differnent scenarios, try differnt models for differnet parts and see how they effect the cost vs accuracy vs latency. My current evaluation pipeline is very limited, particularly really complex cases are not tested. Similarly prompt injection needs to be tested.

Then to scale to say 1000+ tools i would like to add a hybrid retrieval fallback like a mixture with say BM25 embeddings, to reduce the cost and time even lower.

Ideally i would build a pipeline that evaluates against full diverse cases and then even suggest where the issue is and a likely soultion. 

Parallel calls are also yet to be tested. And ofcouse some more constraints and cleanups like latent JSON structure at places.

# Own evaluation run

This is done in three parts,

First is the normal "pnpm --filter backend test " :  here i have added 14 and removed 1 so it will say 69 instead of 56

The second is by running test_live_scenarios.py in backend/tests
This can be run with the following command 

RUN_LIVE_TESTS=1 ./backend/.venv/bin/python -m unittest backend.tests.test_live_scenarios -v

This does hard checks against 11 cases and tell if it passed or not, below is a response from one of these runs 

test_ambiguous_request_asks_without_mutating (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_ambiguous_request_asks_without_mutating) ... 2026-07-02 16:40:49,949 solution.orchestrator turn done: 9.40s | 13 tools routed | 1 tool calls (0 errored) | 4 llm calls | 14685 in / 240 out tokens | est $0.0063
ok
test_clarification_answer_completes_the_task (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_clarification_answer_completes_the_task) ... 2026-07-02 16:41:00,186 solution.orchestrator turn done: 10.21s | 12 tools routed | 1 tool calls (0 errored) | 4 llm calls | 14531 in / 216 out tokens | est $0.0062
2026-07-02 16:41:16,121 solution.orchestrator turn done: 15.93s | 8 tools routed | 4 tool calls (0 errored) | 7 llm calls | 33379 in / 471 out tokens | est $0.0141
ok
test_cross_service_pipeline_mutates_slack (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_cross_service_pipeline_mutates_slack) ... 2026-07-02 16:41:27,856 solution.orchestrator turn done: 11.71s | 6 tools routed | 3 tool calls (0 errored) | 5 llm calls | 10040 in / 320 out tokens | est $0.0045
ok
test_github_query_answers_without_asking_scope (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_github_query_answers_without_asking_scope) ... 2026-07-02 16:41:35,176 solution.orchestrator turn done: 7.30s | 6 tools routed | 1 tool calls (0 errored) | 4 llm calls | 9369 in / 276 out tokens | est $0.0042
ok
test_missing_file_is_reported_not_fabricated (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_missing_file_is_reported_not_fabricated) ... 2026-07-02 16:41:42,702 solution.orchestrator turn done: 7.51s | 20 tools routed | 1 tool calls (0 errored) | 3 llm calls | 11523 in / 117 out tokens | est $0.0048
ok
test_parallel_independent_lookups (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_parallel_independent_lookups) ... 2026-07-02 16:41:53,811 solution.orchestrator turn done: 11.06s | 4 tools routed | 2 tool calls (0 errored) | 4 llm calls | 7470 in / 356 out tokens | est $0.0036
ok
test_relative_dates_use_mock_today (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_relative_dates_use_mock_today) ... 2026-07-02 16:42:07,840 solution.orchestrator turn done: 14.01s | 4 tools routed | 2 tool calls (0 errored) | 5 llm calls | 10901 in / 353 out tokens | est $0.0049
ok
test_single_service_lookup (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_single_service_lookup) ... 2026-07-02 16:42:12,822 solution.orchestrator turn done: 4.97s | 10 tools routed | 1 tool calls (0 errored) | 3 llm calls | 5108 in / 125 out tokens | est $0.0022
ok
test_smalltalk_makes_no_tool_calls (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_smalltalk_makes_no_tool_calls) ... 2026-07-02 16:42:19,311 solution.orchestrator turn done: 6.48s | 0 tools routed | 0 tool calls (0 errored) | 2 llm calls | 1314 in / 16 out tokens | est $0.0006
ok
test_unambiguous_mutation_executes (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_unambiguous_mutation_executes) ... 2026-07-02 16:42:32,240 solution.orchestrator turn done: 12.91s | 25 tools routed | 2 tool calls (0 errored) | 4 llm calls | 25333 in / 187 out tokens | est $0.0104
ok
test_web_search_routes_to_perplexity (backend.tests.test_live_scenarios.LiveChatScenarioTests.test_web_search_routes_to_perplexity) ... 2026-07-02 16:42:35,643 solution.orchestrator turn done: 3.38s | 1 tools routed | 1 tool calls (0 errored) | 3 llm calls | 2891 in / 80 out tokens | est $0.0013
ok

----------------------------------------------------------------------
Ran 11 tests in 115.110s

OK

Furthurmore i added another file called run_prompts in backend/helpers
these can be run by "python -m backend.helpers.run_prompts"
In this we have a list called PROMPTS where we can write the prompt we want to run against, it gives full endpoint response in json format with other values like how many tools called, latency and estimated cost for a visual check. Here is a response from one of its runs

SCENARIO 1/4: Find emails about the Q3 budgetWhat conversations do I have in Slack?
2026-07-02 17:35:42,493 solution.orchestrator turn done: 9.37s | 4 tools routed | 2 tool calls (0 errored) | 4 llm calls | 5856 in / 270 out tokens | est $0.0048
{
  "messages": [
    {
      "role": "user",
      "content": "Find emails about the Q3 budgetWhat conversations do I have in Slack?"
    },
    {
      "role": "assistant",
      "content": "I found no emails about the Q3 budget in your inbox.\n\nRegarding your Slack conversations, you have:\n- A direct message conversation with Morgan.\n- A public channel named \"engineering\" for planning and launches.\n- A multi-person instant message group called \"launch-war-room.\"\n- A private channel named \"leadership-private\" for leadership coordination.\n\nLet me know if you want to see messages or details from any of these Slack conversations."
    }
  ],
  "tool_calls": [
    {
      "name": "GMAIL_FETCH_EMAILS",
      "arguments": {
        "user_id": "me",
        "query": "Q3 budget",
        "max_results": 5,
        "verbose": true,
        "ids_only": false,
        "include_payload": true,
        "include_spam_trash": false
      },
      "result": {
        "messages": [],
        "nextPageToken": null,
        "resultSizeEstimate": 0
      },
      "error": null
    },
    {
      "name": "slack_list_conversations",
      "arguments": {
        "limit": 100,
        "types": "public_channel,private_channel,mpim,im",
        "discover_dms": false
      },
      "result": {
        "conversations": [
          {
            "id": "D001",
            "name": "dm-avery-morgan",
            "conversation_type": "im",
            "topic_value": "Direct messages between Avery and Morgan",
            "member_ids": [
              "U001",
              "U002"
            ],
            "member_names": [
              "avery",
              "morgan"
            ],
            "is_archived": false
          },
          {
            "id": "C001",
            "name": "engineering",
            "conversation_type": "public_channel",
            "topic_value": "Engineering planning and launches",
            "member_ids": [
              "U001",
              "U002",
              "U004",
              "U005"
            ],
            "member_names": [
              "avery",
              "morgan",
              "ops-bot",
              "jordan"
            ],
            "is_archived": false
          },
          {
            "id": "G001",
            "name": "launch-war-room",
            "conversation_type": "mpim",
            "topic_value": "Launch war room",
            "member_ids": [
              "U001",
              "U002",
              "U004",
              "U005"
            ],
            "member_names": [
              "avery",
              "morgan",
              "ops-bot",
              "jordan"
            ],
            "is_archived": false
          },
          {
            "id": "C002",
            "name": "leadership-private",
            "conversation_type": "private_channel",
            "topic_value": "Leadership coordination",
            "member_ids": [
              "U001",
              "U002",
              "U005"
            ],
            "member_names": [
              "avery",
              "morgan",
              "jordan"
            ],
            "is_archived": false
          }
        ],
        "result_count": 4
      },
      "error": null
    }
  ]
}
--- latency 9.37s | 2 tool calls | 4 llm calls | 5856 in / 270 out tokens | est cost $0.0048

======================================================================
SCENARIO 2/4: Find the most recent email about the Q1 revenue review and post a summary to the
2026-07-02 17:35:53,818 solution.orchestrator turn done: 11.32s | 6 tools routed | 3 tool calls (0 errored) | 5 llm calls | 10174 in / 329 out tokens | est $0.0069
{
  "messages": [
    {
      "role": "user",
      "content": "Find the most recent email about the Q1 revenue review and post a summary to the leadership Slack channel."
    },
    {
      "role": "assistant",
      "content": "I found the most recent email about the Q1 revenue review. The CFO requested a summary of the revenue deltas for the board meeting, focusing on enterprise upsell and new logo pipeline. I have posted this summary to the leadership Slack channel."
    }
  ],
  "tool_calls": [
    {
      "name": "GMAIL_FETCH_EMAILS",
      "arguments": {
        "user_id": "me",
        "query": "Q1 revenue review",
        "max_results": 1,
        "verbose": true,
        "ids_only": false,
        "include_payload": true,
        "include_spam_trash": false
      },
      "result": {
        "messages": [
          {
            "id": "msg_002",
            "threadId": "thr_001",
            "labelIds": [
              "INBOX",
              "Label_101"
            ],
            "snippet": "Please summarize the revenue deltas for the board meeting.",
            "historyId": "9002",
            "internalDate": "1775622000000",
            "sizeEstimate": 108,
            "payload": {
              "partId": "",
              "mimeType": "text/plain",
              "filename": "",
              "headers": [
                {
                  "name": "From",
                  "value": "cfo@corp.com"
                },
                {
                  "name": "To",
                  "value": "me@example.com"
                },
                {
                  "name": "Subject",
                  "value": "Re: Q1 revenue review"
                },
                {
                  "name": "Date",
                  "value": "2026-04-08T04:20:00+00:00"
                },
                {
                  "name": "Message-ID",
                  "value": "<msg_002@mock.gmail.local>"
                }
              ],
              "body": {
                "size": 0,
                "data": null,
                "attachmentId": null
              },
              "parts": [
                {
                  "partId": "0",
                  "mimeType": "text/plain",
                  "filename": "",
                  "headers": [],
                  "body": {
                    "size": 108,
                    "data": "UGxlYXNlIHN1bW1hcml6ZSB0aGUgcmV2ZW51ZSBkZWx0YXMgZm9yIHRoZSBib2FyZCBtZWV0aW5nLiBGb2N1cyBvbiBlbnRlcnByaXNlIHVwc2VsbCBhbmQgbmV3IGxvZ28gcGlwZWxpbmUu",
                    "attachmentId": null
                  }
                }
              ]
            },
            "raw": null
          }
        ],
        "nextPageToken": "1",
        "resultSizeEstimate": 2
      },
      "error": null
    },
    {
      "name": "slack_list_conversations",
      "arguments": {
        "limit": 100,
        "types": "public_channel,private_channel,mpim,im",
        "discover_dms": false
      },
      "result": {
        "conversations": [
          {
            "id": "D001",
            "name": "dm-avery-morgan",
            "conversation_type": "im",
            "topic_value": "Direct messages between Avery and Morgan",
            "member_ids": [
              "U001",
              "U002"
            ],
            "member_names": [
              "avery",
              "morgan"
            ],
            "is_archived": false
          },
          {
            "id": "C001",
            "name": "engineering",
            "conversation_type": "public_channel",
            "topic_value": "Engineering planning and launches",
            "member_ids": [
              "U001",
              "U002",
              "U004",
              "U005"
            ],
            "member_names": [
              "avery",
              "morgan",
              "ops-bot",
              "jordan"
            ],
            "is_archived": false
          },
          {
            "id": "G001",
            "name": "launch-war-room",
            "conversation_type": "mpim",
            "topic_value": "Launch war room",
            "member_ids": [
              "U001",
              "U002",
              "U004",
              "U005"
            ],
            "member_names": [
              "avery",
              "morgan",
              "ops-bot",
              "jordan"
            ],
            "is_archived": false
          },
          {
            "id": "C002",
            "name": "leadership-private",
            "conversation_type": "private_channel",
            "topic_value": "Leadership coordination",
            "member_ids": [
              "U001",
              "U002",
              "U005"
            ],
            "member_names": [
              "avery",
              "morgan",
              "jordan"
            ],
            "is_archived": false
          }
        ],
        "result_count": 4
      },
      "error": null
    },
    {
      "name": "slack_send_message",
      "arguments": {
        "text": "Summary of the most recent email about the Q1 revenue review:\nThe CFO requested a summary of the revenue deltas for the board meeting, with a focus on enterprise upsell and new logo pipeline.",
        "channel": "C002"
      },
      "result": {
        "type": "message",
        "user": "U001",
        "text": "Summary of the most recent email about the Q1 revenue review:\nThe CFO requested a summary of the revenue deltas for the board meeting, with a focus on enterprise upsell and new logo pipeline.",
        "ts": "1775651400.001000",
        "channel": "C002",
        "thread_ts": null,
        "reply_count": 0,
        "replies": [],
        "user_name": "avery",
        "real_name": "Avery Quinn",
        "channel_name": null,
        "thread": null
      },
      "error": null
    }
  ]
}
--- latency 11.32s | 3 tool calls | 5 llm calls | 10174 in / 329 out tokens | est cost $0.0069

======================================================================
SCENARIO 3/4: Delete the file 'budget_2025.xlsx' from my Drive.
2026-07-02 17:36:00,309 solution.orchestrator turn done: 6.49s | 20 tools routed | 1 tool calls (0 errored) | 3 llm calls | 11619 in / 117 out tokens | est $0.0048
{
  "messages": [
    {
      "role": "user",
      "content": "Delete the file 'budget_2025.xlsx' from my Drive."
    },
    {
      "role": "assistant",
      "content": "I could not find a file named 'budget_2025.xlsx' in your Drive. Please check the file name and try again."
    }
  ],
  "tool_calls": [
    {
      "name": "GOOGLEDRIVE_FIND_FILE",
      "arguments": {
        "q": "name='budget_2025.xlsx'",
        "spaces": "drive",
        "pageSize": 100,
        "fields": "files(id,name)",
        "supportsAllDrives": true,
        "includeItemsFromAllDrives": false
      },
      "result": {
        "files": [],
        "nextPageToken": null,
        "incompleteSearch": false
      },
      "error": null
    }
  ]
}
--- latency 6.49s | 1 tool calls | 3 llm calls | 11619 in / 117 out tokens | est cost $0.0048

======================================================================
SCENARIO 4/4: Schedule a 30-minute meeting with everyone on the project next week.
2026-07-02 17:36:09,117 solution.orchestrator turn done: 8.80s | 13 tools routed | 1 tool calls (0 errored) | 4 llm calls | 15183 in / 219 out tokens | est $0.0098
{
  "messages": [
    {
      "role": "user",
      "content": "Schedule a 30-minute meeting with everyone on the project next week."
    },
    {
      "role": "assistant",
      "content": "There are three projects currently: \"Tool Orchestrator,\" \"Renewals Risk,\" and \"Onboarding Refresh.\" Could you please specify which project you want to schedule the meeting for?"
    }
  ],
  "tool_calls": [
    {
      "name": "linear_list_projects",
      "arguments": {
        "limit": 50,
        "orderBy": "updatedAt",
        "includeArchived": false
      },
      "result": {
        "projects": [
          {
            "id": "proj_orchestrator",
            "name": "Tool Orchestrator",
            "team": "team_eng",
            "lead": "user_me",
            "summary": "Multi-tool chat harness backed by 191 mock tools.",
            "description": "Owns the orchestration layer, routing strategy, and evaluation harness.",
            "state": "started",
            "priority": 1,
            "icon": "\ud83e\udd16",
            "color": "#6366f1",
            "labels": [
              "plabel_launch"
            ],
            "startDate": "2026-03-25",
            "targetDate": "2026-04-22",
            "initiatives": [
              "init_h1_platform"
            ],
            "createdAt": "2026-03-25T13:00:00+00:00",
            "updatedAt": "2026-04-08T11:00:00+00:00"
          },
          {
            "id": "proj_renewals",
            "name": "Renewals Risk",
            "team": "team_gro",
            "lead": "user_jordan",
            "summary": "Reduce churn on at-risk renewals.",
            "description": "Outreach playbooks, retention dashboards, customer-success workflows.",
            "state": "started",
            "priority": 1,
            "icon": "\ud83d\udcc9",
            "color": "#ef4444",
            "labels": [],
            "startDate": "2026-03-18",
            "targetDate": "2026-05-08",
            "initiatives": [],
            "createdAt": "2026-03-18T13:00:00+00:00",
            "updatedAt": "2026-04-08T05:00:00+00:00"
          },
          {
            "id": "proj_onboarding",
            "name": "Onboarding Refresh",
            "team": "team_gro",
            "lead": "user_nadia",
            "summary": "Refresh new-hire onboarding flow.",
            "description": "Lifecycle emails, onboarding tasks, and welcome assets.",
            "state": "planned",
            "priority": 2,
            "icon": "\ud83c\udf89",
            "color": "#22c55e",
            "labels": [],
            "startDate": "2026-04-15",
            "targetDate": "2026-05-06",
            "initiatives": [],
            "createdAt": "2026-04-01T13:00:00+00:00",
            "updatedAt": "2026-04-08T01:00:00+00:00"
          }
        ],
        "pageInfo": {
          "hasNextPage": false,
          "hasPreviousPage": false,
          "endCursor": "proj_onboarding",
          "startCursor": "proj_orchestrator"
        },
        "totalCount": 3
      },
      "error": null
    }
  ]
}
--- latency 8.80s | 1 tool calls | 4 llm calls | 15183 in / 219 out tokens | est cost $0.0098
2026-07-02 17:36:30,592 solution.orchestrator turn done: 21.47s | 10 tools routed | 6 tool calls (0 errored) | 7 llm calls | 37104 in / 627 out tokens | est $0.0191
{
  "messages": [
    {
      "role": "user",
      "content": "Schedule a 30-minute meeting with everyone on the project next week."
    },
    {
      "role": "assistant",
      "content": "There are three projects currently: \"Tool Orchestrator,\" \"Renewals Risk,\" and \"Onboarding Refresh.\" Could you please specify which project you want to schedule the meeting for?"
    },
    {
      "role": "user",
      "content": "The Tool Orchestrator project. Monday next week at 10am works."
    },
    {
      "role": "assistant",
      "content": "I have scheduled a 30-minute meeting for the Tool Orchestrator project on Monday next week, April 13, 2026, at 10:00 AM (EDT). The meeting invite has been sent to everyone on the project: Avery Quinn, Jordan Rivera, and Morgan Lee."
    }
  ],
  "tool_calls": [
    {
      "name": "linear_get_project",
      "arguments": {
        "query": "Tool Orchestrator"
      },
      "result": {
        "project": {
          "id": "proj_orchestrator",
          "name": "Tool Orchestrator",
          "team": "team_eng",
          "lead": "user_me",
          "summary": "Multi-tool chat harness backed by 191 mock tools.",
          "description": "Owns the orchestration layer, routing strategy, and evaluation harness.",
          "state": "started",
          "priority": 1,
          "icon": "\ud83e\udd16",
          "color": "#6366f1",
          "labels": [
            "plabel_launch"
          ],
          "startDate": "2026-03-25",
          "targetDate": "2026-04-22",
          "initiatives": [
            "init_h1_platform"
          ],
          "createdAt": "2026-03-25T13:00:00+00:00",
          "updatedAt": "2026-04-08T11:00:00+00:00"
        }
      },
      "error": null
    },
    {
      "name": "linear_list_projects",
      "arguments": {
        "limit": 50,
        "query": "Tool Orchestrator",
        "orderBy": "updatedAt",
        "includeArchived": false
      },
      "result": {
        "projects": [
          {
            "id": "proj_orchestrator",
            "name": "Tool Orchestrator",
            "team": "team_eng",
            "lead": "user_me",
            "summary": "Multi-tool chat harness backed by 191 mock tools.",
            "description": "Owns the orchestration layer, routing strategy, and evaluation harness.",
            "state": "started",
            "priority": 1,
            "icon": "\ud83e\udd16",
            "color": "#6366f1",
            "labels": [
              "plabel_launch"
            ],
            "startDate": "2026-03-25",
            "targetDate": "2026-04-22",
            "initiatives": [
              "init_h1_platform"
            ],
            "createdAt": "2026-03-25T13:00:00+00:00",
            "updatedAt": "2026-04-08T11:00:00+00:00"
          }
        ],
        "pageInfo": {
          "hasNextPage": false,
          "hasPreviousPage": false,
          "endCursor": "proj_orchestrator",
          "startCursor": "proj_orchestrator"
        },
        "totalCount": 1
      },
      "error": null
    },
    {
      "name": "linear_list_issues",
      "arguments": {
        "team": "team_eng",
        "project": "proj_orchestrator",
        "limit": 50,
        "orderBy": "updatedAt",
        "includeArchived": true
      },
      "result": {
        "issues": [
          {
            "id": "ENG-1",
            "title": "Wire /chat endpoint to orchestrator",
            "description": "Implement POST /chat to drive the multi-tool harness. Required for case study.",
            "team": "team_eng",
            "state": "status_eng_in_progress",
            "assignee": "user_me",
            "delegate": null,
            "cycle": "cycle_eng_current",
            "project": "proj_orchestrator",
            "milestone": null,
            "parentId": null,
            "priority": 1,
            "dueDate": "2026-04-11",
            "labels": [
              "label_feature",
              "label_eng_infra"
            ],
            "links": [],
            "blocks": [
              "ENG-2"
            ],
            "blockedBy": [],
            "relatedTo": [],
            "duplicateOf": null,
            "comments": [
              "comment_eng1_1"
            ],
            "createdAt": "2026-04-05T13:00:00+00:00",
            "updatedAt": "2026-04-08T12:00:00+00:00",
            "archived": false
          },
          {
            "id": "ENG-3",
            "title": "Launch delay: orchestrator latency spike",
            "description": "Tool dispatch p95 jumped from 320ms to 1.4s after the registry refactor.",
            "team": "team_eng",
            "state": "status_eng_in_review",
            "assignee": "user_jordan",
            "delegate": null,
            "cycle": "cycle_eng_current",
            "project": "proj_orchestrator",
            "milestone": null,
            "parentId": null,
            "priority": 1,
            "dueDate": "2026-04-09",
            "labels": [
              "label_bug",
              "label_eng_infra"
            ],
            "links": [
              {
                "url": "https://example.com/perf-report",
                "title": "Perf report"
              }
            ],
            "blocks": [],
            "blockedBy": [],
            "relatedTo": [
              "ENG-1"
            ],
            "duplicateOf": null,
            "comments": [],
            "createdAt": "2026-04-08T01:00:00+00:00",
            "updatedAt": "2026-04-08T11:00:00+00:00",
            "archived": false
          },
          {
            "id": "ENG-2",
            "title": "Tool routing strategy decision doc",
            "description": "Pick between two-stage routing, semantic retrieval, or service-first.",
            "team": "team_eng",
            "state": "status_eng_todo",
            "assignee": "user_morgan",
            "delegate": null,
            "cycle": "cycle_eng_current",
            "project": "proj_orchestrator",
            "milestone": null,
            "parentId": null,
            "priority": 2,
            "dueDate": "2026-04-15",
            "labels": [
              "label_eng_infra"
            ],
            "links": [],
            "blocks": [],
            "blockedBy": [
              "ENG-1"
            ],
            "relatedTo": [],
            "duplicateOf": null,
            "comments": [],
            "createdAt": "2026-04-06T13:00:00+00:00",
            "updatedAt": "2026-04-08T09:00:00+00:00",
            "archived": false
          },
          {
            "id": "ENG-4",
            "title": "Add Datadog dashboard for tool calls",
            "description": "Per-tool latency, error rate, and call count.",
            "team": "team_eng",
            "state": "status_eng_backlog",
            "assignee": null,
            "delegate": null,
            "cycle": null,
            "project": "proj_orchestrator",
            "milestone": null,
            "parentId": null,
            "priority": 3,
            "dueDate": null,
            "labels": [
              "label_eng_infra"
            ],
            "links": [],
            "blocks": [],
            "blockedBy": [],
            "relatedTo": [],
            "duplicateOf": null,
            "comments": [],
            "createdAt": "2026-04-03T13:00:00+00:00",
            "updatedAt": "2026-04-03T13:00:00+00:00",
            "archived": false
          },
          {
            "id": "ENG-5",
            "title": "Resolved last cycle: harness skeleton",
            "description": "Initial scaffolding committed last cycle.",
            "team": "team_eng",
            "state": "status_eng_done",
            "assignee": "user_me",
            "delegate": null,
            "cycle": "cycle_eng_previous",
            "project": "proj_orchestrator",
            "milestone": null,
            "parentId": null,
            "priority": 2,
            "dueDate": null,
            "labels": [
              "label_feature"
            ],
            "links": [],
            "blocks": [],
            "blockedBy": [],
            "relatedTo": [],
            "duplicateOf": null,
            "comments": [],
            "createdAt": "2026-03-21T13:00:00+00:00",
            "updatedAt": "2026-03-31T13:00:00+00:00",
            "archived": false
          }
        ],
        "pageInfo": {
          "hasNextPage": false,
          "hasPreviousPage": false,
          "endCursor": "ENG-5",
          "startCursor": "ENG-1"
        },
        "totalCount": 5
      },
      "error": null
    },
    {
      "name": "linear_list_users",
      "arguments": {
        "team": "team_eng"
      },
      "result": {
        "users": [
          {
            "id": "user_me",
            "name": "Avery Quinn",
            "email": "avery@corp.com",
            "displayName": "avery",
            "active": true,
            "isMe": true
          },
          {
            "id": "user_jordan",
            "name": "Jordan Rivera",
            "email": "jordan@corp.com",
            "displayName": "jordan",
            "active": true,
            "isMe": false
          },
          {
            "id": "user_morgan",
            "name": "Morgan Lee",
            "email": "morgan@corp.com",
            "displayName": "morgan",
            "active": true,
            "isMe": false
          }
        ],
        "count": 3
      },
      "error": null
    },
    {
      "name": "linear_get_team",
      "arguments": {
        "query": "team_eng"
      },
      "result": {
        "team": {
          "id": "team_eng",
          "key": "ENG",
          "name": "Engineering",
          "description": "Platform and product engineering",
          "createdAt": "2026-01-08T13:00:00+00:00",
          "updatedAt": "2026-04-07T13:00:00+00:00"
        },
        "memberIds": [
          "user_me",
          "user_morgan",
          "user_jordan"
        ]
      },
      "error": null
    },
    {
      "name": "GOOGLECALENDAR_CREATE_EVENT",
      "arguments": {
        "summary": "Tool Orchestrator Project Meeting",
        "timezone": "America/New_York",
        "attendees": [
          "avery@corp.com",
          "jordan@corp.com",
          "morgan@corp.com"
        ],
        "eventType": "default",
        "visibility": "default",
        "calendar_id": "primary",
        "description": "Meeting with everyone on the Tool Orchestrator project.",
        "send_updates": true,
        "transparency": "opaque",
        "start_datetime": "2026-04-13T10:00:00-04:00",
        "exclude_organizer": false,
        "guests_can_modify": false,
        "event_duration_hour": 0,
        "event_duration_minutes": 30
      },
      "result": {
        "kind": "calendar#event",
        "etag": "\"evt_1001-etag\"",
        "id": "evt_1001",
        "status": "confirmed",
        "htmlLink": "https://calendar.google.com/calendar/event?eid=evt_1001",
        "created": "2026-04-11T10:00:00-04:00",
        "updated": "2026-04-11T12:00:00-04:00",
        "summary": "Tool Orchestrator Project Meeting",
        "description": "Meeting with everyone on the Tool Orchestrator project.",
        "location": null,
        "creator": {
          "email": "me@example.com",
          "self": true
        },
        "organizer": {
          "email": "me@example.com",
          "self": true
        },
        "start": {
          "dateTime": "2026-04-13T10:00:00-04:00",
          "date": null,
          "timeZone": "America/New_York"
        },
        "end": {
          "dateTime": "2026-04-13T10:30:00-04:00",
          "date": null,
          "timeZone": "America/New_York"
        },
        "eventType": "default",
        "visibility": "default",
        "transparency": "opaque",
        "guestsCanModify": false,
        "guestsCanInviteOthers": true,
        "guestsCanSeeOtherGuests": true,
        "sequence": 0,
        "reminders": {
          "useDefault": true
        },
        "iCalUID": "evt_1001@mock.calendar.local",
        "attendees": [
          {
            "email": "avery@corp.com",
            "responseStatus": "accepted"
          },
          {
            "email": "jordan@corp.com",
            "responseStatus": "needsAction"
          },
          {
            "email": "morgan@corp.com",
            "responseStatus": "needsAction"
          }
        ],
        "recurrence": null,
        "conferenceData": null,
        "focusTimeProperties": null,
        "outOfOfficeProperties": null,
        "workingLocationProperties": null,
        "birthdayProperties": null,
        "recurringEventId": null,
        "originalStartTime": null
      },
      "error": null
    }
  ]
}
--- latency 21.47s | 6 tool calls | 7 llm calls | 37104 in / 627 out tokens | est cost $0.0191

TOTAL: 57.45s | 13 tool calls | 23 llm calls | est cost $0.0455 across 4 scenarios
