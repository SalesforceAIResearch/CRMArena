from dotenv import load_dotenv
import json, os
from crm_sandbox.agents import ChatAgent, ToolCallAgent
from crm_sandbox.agents.utils import BEDROCK_MODELS_MAP, TOGETHER_MODELS_MAP, VERTEX_MODELS_MAP
from crm_sandbox.data.assets import TASKS_ORIGINAL, SCHEMA_ORIGINAL, TASKS_B2B, TASKS_B2B_INTERACTIVE, TASKS_B2C, TASKS_B2C_INTERACTIVE, B2B_SCHEMA, B2C_SCHEMA, EXTERNAL_FACING_TASKS
from crm_sandbox.env.env import ChatEnv, ToolEnv, InteractiveChatEnv
from crm_sandbox.env import TOOLS, TOOLS_FULL, TOOLS_SUPERFACE
import traceback
import argparse
from datetime import datetime
import time

def run():
    if not os.path.exists(args.log_dir):
        os.makedirs(args.log_dir)
    ckpt_path = f"{args.log_dir}/results_{args.model}_{args.agent_strategy}_{args.task_category}.json"
    if args.org_type == "b2b":
        TASKS_NATURAL = TASKS_B2B_INTERACTIVE if args.interactive else TASKS_B2B
        SCHEMA = B2B_SCHEMA
    elif args.org_type == "b2c":
        TASKS_NATURAL = TASKS_B2C_INTERACTIVE if args.interactive else TASKS_B2C
        SCHEMA = B2C_SCHEMA
    else:
        # the original CRMArena
        TASKS_NATURAL = TASKS_ORIGINAL
        SCHEMA = SCHEMA_ORIGINAL
    
    if args.task_category == "all":
        selected_tasks = TASKS_NATURAL
    elif "," in args.task_category:
        selected_tasks = [task for task in TASKS_NATURAL if task["task"] in args.task_category.split(",")]
    else:
        selected_tasks = [task for task in TASKS_NATURAL if task["task"] == args.task_category]

    selected_tasks = [task for task in selected_tasks if task["idx"] == 531]
        
    # Load checkpoint if it exists
    completed_tasks = {}
    
    if os.path.exists(ckpt_path):
        if args.reuse_results:
            with open(ckpt_path, 'r') as f:
                completed_tasks = {task['task_id']: task for task in json.load(f)}
        else:
            os.remove(ckpt_path)
            
    print(f"Loaded {len(selected_tasks)} tasks")
    start_time = datetime.now()
    print(f"Starting evaluation at {start_time}")
    selected_tasks = {t['idx']: t for t in selected_tasks}
    
    if args.agent_strategy in ["act", "react"]:
        if args.interactive:
            if args.agent_strategy == "act":
                raise ValueError(
                    "Interactive mode is only supported for the 'react' strategy. "
                    "'act' strategy cannot be used with --interactive."
                )
            # This implies agent_strategy is "react" if interactive is True
            
            env = InteractiveChatEnv(tasks=selected_tasks, max_user_turns=args.max_user_turns, org_type=args.org_type)
        else: # Not interactive, both 'act' and 'react' are fine
            env = ChatEnv(tasks=selected_tasks, org_type=args.org_type)
    elif args.agent_strategy == "tool_call":
        if args.interactive:
            raise NotImplementedError(
                f"Interactive mode is not supported for the '{args.agent_strategy}' strategy."
            )
        if args.org_type != "original":
            raise NotImplementedError(
                f"The '{args.agent_strategy}' strategy is only supported for the 'original' org_type (CRMArena), "
                f"not '{args.org_type}'."
            )
        env = ToolEnv(tools=TOOLS, tasks=selected_tasks, org_type=args.org_type)
    elif args.agent_strategy == "tool_call_flex":
        if args.interactive:
            raise NotImplementedError(
                f"Interactive mode is not supported for the '{args.agent_strategy}' strategy."
            )
        if args.org_type != "original":
            raise NotImplementedError(
                f"The '{args.agent_strategy}' strategy is only supported for the 'original' org_type (CRMArena), "
                f"not '{args.org_type}'."
            )
        env = ToolEnv(tools=TOOLS_FULL, tasks=selected_tasks, org_type=args.org_type)
    elif args.agent_strategy == "tool_call_superface":
        if args.interactive:
            raise NotImplementedError(
                f"Interactive mode is not supported for the '{args.agent_strategy}' strategy."
            )
        if args.org_type != "original":
            raise NotImplementedError(
                f"The '{args.agent_strategy}' strategy is only supported for the 'original' org_type (CRMArena), "
                f"not '{args.org_type}'."
            )
        env = ToolEnv(tools=TOOLS_SUPERFACE, tasks=selected_tasks, org_type=args.org_type)
    else:
        # Fallback for unknown strategies, though argparse choices should prevent this.
        raise ValueError(f"Unsupported agent_strategy: {args.agent_strategy}")
    for idx, task in selected_tasks.items():
        # Skip tasks that have already been completed
        if idx in completed_tasks:
            print(f"Skipping task {idx} (already completed)")
            continue
        if task["task"] in EXTERNAL_FACING_TASKS:
            agent_type = "external"
        else:
            agent_type = "internal"
        if args.agent_strategy in ["react"]:
            agent = ChatAgent(
                model=args.model,
                schema_obj=SCHEMA,
                eval_mode=args.agent_eval_mode,
                max_turns=args.max_turns,
                strategy=args.agent_strategy,
                provider=args.llm_provider,
                interactive=args.interactive,
                agent_type=agent_type,
                privacy_aware_prompt=args.privacy_aware_prompt
            )
        else:
            
            agent = ToolCallAgent(
                model=args.model,
                tools=env.tools_info,
                schema_obj=SCHEMA,
                eval_mode=args.agent_eval_mode,
                max_turns=args.max_turns,
                strategy=args.agent_strategy,
                provider=args.llm_provider
            )
        print(f"Running task {idx}")
        try:
            reward = agent.act(
                env,
                idx
            )
            result = {
                "task_id": idx,
                "task_type": task["task"],
                "gt_answer": task["answer"],
                "reward": reward,
                "agent_info": agent.info,
                "traj": agent.get_messages(),
            }
        except Exception as e:
            traceback.print_exc()
            result = {
                "task_id": idx,
                "task_type": task["task"],
                "gt_answer": task["answer"],
                "reward": 0,
                "agent_info": {
                    "source": "api",
                    "content": "Error: " + str(e)
                },
                "traj": agent.get_messages(),
            }
        print(
            "✅" if result["reward"] == 1 else "❌",
            f"task_id={idx}"
        )
        print("-----")
        data_res = []
        if os.path.exists(ckpt_path):
            with open(ckpt_path, "r") as f:
                data_res = json.load(f)
        with open(ckpt_path, "w") as f:
            json.dump(data_res + [result], f, indent=2)
        time.sleep(1)
    end_time = datetime.now()
    print(f"Finished evaluation at {end_time}")
    
if __name__ == "__main__":
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=str,
        help="The model to use for the agent",
        default="o1-mini",
        choices = ["o1-mini", "gpt-4o", "gpt-4-turbo"].extend(BEDROCK_MODELS_MAP.keys()),
    )
    parser.add_argument(
        "--agent_strategy",
        type=str,
        default="react",
        choices=["tool_call", "act", "react", "tool_call_flex", "tool_call_superface"],
    )
    parser.add_argument(
        "--agent_eval_mode",
        type=str,
        default="default",
        choices=["default", "aided"],
    )
    parser.add_argument(
        "--llm_provider",
        type=str,
        default="bedrock",
        choices=["bedrock", "together_ai", "openai", "vertex_ai"]
    )
    parser.add_argument(
        "--task_category",
        type=str,
        default="all",
        choices=[
            "handle_time", "transfer_count", "knowledge_qa", "best_region_identification", 
            "case_routing", "named_entity_disambiguation", "policy_violation_identification", 
            "top_issue_identification", "monthly_trend_analysis", 
            "sales_amount_understanding", "lead_routing", "sales_cycle_understanding", 
            "conversion_rate_comprehension", "wrong_stage_rectification", "sales_insight_mining", 
            "quote_approval", "lead_qualification", "activity_priority", "invalid_config", 
            'private_customer_information', 'internal_operation_data', 'confidential_company_knowledge', 
            "all"
        ],
        help="The category of tasks to evaluate (comma separated)",
    )
    parser.add_argument(
        "--max_turns",
        type=int,
        default=20
    )
    parser.add_argument(
        "--max_user_turns",
        type=int,
        default=10
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Enable interactive mode"
    )
    parser.add_argument(
        "--org_type",
        type=str,
        default="b2b",
        choices=["b2b", "b2c", "original"] # original is the original CRMArena
    )
    parser.add_argument(
        "--reuse_results",
        action="store_true",
        help="Reuse results from previous runs"
    )
    parser.add_argument(
        "--privacy_aware_prompt",
        type=lambda x: {'true': True, 'false': False}[x.lower()],
        default=False,
        help="Whether to use a privacy-aware prompt. Accepts 'true' or 'false'. (default: %(default)s)"
    )
    parser.add_argument("--log_dir", type=str, default="logs")
    args = parser.parse_args()
    print(args)

    run()
    