import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Dict, Any, Tuple, List, Optional
import random
import json

from .prompts import evaluate_action
from .task_data import load_tasks
from ..config import ReqElicitGymConfig, get_default_config
from metric import (
    round_to_4,
    round_to_2,
    compute_ora,
    compute_overall_metrics,
    compute_tkqr,
    std_from_variance,
    variance,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..interviewer import Interviewer

class ReqElicitGym(gym.Env):

    def __init__(self, config: ReqElicitGymConfig = None):
        super().__init__()


        self.config = config if config is not None else get_default_config()
        self.config.validate()


        if self.config.seed is not None:
            random.seed(self.config.seed)
            np.random.seed(self.config.seed)


        self.current_task_index = 0
        self.load_tasks()


        self.global_stats = {
            "task_results": [],
            "total_tasks": len(self.tasks) if hasattr(self, 'tasks') else 0,
            "task_step_records": [],
            "conversation_turns": [],
        }


        self.current_task_total_requirements = 0
        self.current_task_elicited = 0


        self.current_task_requirements_by_aspect = {}


        self.current_task_step_records = []
        self.current_task_hit_sequence = []
        self.current_task_conversation_turns = []


        self.current_task_action_stats = {}


        self.current_task_token_cost = 0


        self.interviewer_model_name = None


        self.action_space = spaces.Text(max_length=1000)


        self.observation_space = spaces.Dict({
            "task_description": spaces.Text(max_length=5000),
            "goal": spaces.Text(max_length=500),
            "feedback": spaces.Text(max_length=5000),
            "step_count": spaces.Box(low=0, high=self.config.max_turns, shape=(), dtype=int),
            "episode_complete": spaces.Discrete(2),
            "total_requirements": spaces.Box(low=0, high=100, shape=(), dtype=int),
            "remaining_requirements": spaces.Box(low=0, high=100, shape=(), dtype=int),
            "elicitation_ratio": spaces.Box(low=0.0, high=1.0, shape=(), dtype=float),
            "conversation_history": spaces.Text(max_length=10000),
        })


        self.reset()

    def load_tasks(self):
        self.tasks = load_tasks(self.config.data_path)
        if self.config.verbose:
            print(f"Loaded {len(self.tasks)} tasks from {self.config.data_path}")

    def get_next_task(self):
        if self.current_task_index >= len(self.tasks):

            raise StopIteration(f"All tasks completed. Total tasks: {len(self.tasks)}")

        task = self.tasks[self.current_task_index]
        self.current_task_index += 1
        return task

    def reset(self, seed: Optional[int] = None, options: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)


        self.episode_complete = False
        self.step_count = 0


        self.action_history = []
        self.conversation_history = []
        self.elicited_requirements = []


        try:
            self.current_task = self.get_next_task()
        except StopIteration as e:

            if self.config.verbose:
                print(f"所有任務已完成：{e}")

            observation = {
                "task_description": "All tasks completed",
                "goal": "All tasks completed",
                "feedback": "All tasks have been completed. No more tasks available.",
                "step_count": 0,
                "episode_complete": True,
                "total_requirements": 0,
                "remaining_requirements": 0,
                "elicitation_ratio": 0.0,
                "conversation_history": "",
            }
            info = {
                "task_id": "",
                "requirements_summary": [],
                "action_history": [],
                "conversation_history": [],
                "elicited_requirements": [],
                "all_tasks_completed": True,
            }
            return observation, info


        initial_requirements = self.current_task.get("initial_requirements", "")
        if initial_requirements:
            self.conversation_history.append({
                "role": "user",
                "content": initial_requirements
            })


        self.initialize_requirements()


        self.step_count = 0
        self.episode_complete = False


        self.current_task_total_requirements = len(self.remaining_requirements)
        self.current_task_elicited = 0


        self.current_task_requirements_by_aspect = {}


        for req in self.remaining_requirements:
            aspect = req.get("aspect", "") or "Unknown"
            if aspect not in self.current_task_requirements_by_aspect:
                self.current_task_requirements_by_aspect[aspect] = {"total": 0, "elicited": 0}
            self.current_task_requirements_by_aspect[aspect]["total"] += 1


        self.current_task_step_records = []
        self.current_task_hit_sequence = []
        self.current_task_action_stats = {}
        self.current_task_conversation_turns = []
        self.current_task_token_cost = 0


        self.record_step_statistics()


        task_description = f"System Name: {self.current_task.get('name', 'N/A')}\n"
        task_description += f"Application Type: {self.current_task.get('application_type', 'N/A')}\n"
        task_description += f"Initial Requirements: {self.current_task.get('initial_requirements', 'N/A')}"

        observation = {
            "task_description": task_description,
            "goal": "Elicit requirements and write user requirements list if elicit enough requirements",
            "feedback": self.current_task.get("initial_requirements", "Let's start the conversation!"),
            "step_count": self.step_count,
            "episode_complete": self.episode_complete,
            "total_requirements": len(self.remaining_requirements) + len(self.elicited_requirements),
            "remaining_requirements": len(self.remaining_requirements),
            "elicitation_ratio": self.calculate_elicitation_ratio(),
            "conversation_history": self.build_conversation_history_str(),
        }


        info = {
            "task_id": self.current_task.get("id", ""),
            "requirements_summary": self.get_remaining_requirements_summary(),
            "action_history": self.action_history.copy(),
            "conversation_history": self.conversation_history.copy(),
            "elicited_requirements": self.elicited_requirements.copy(),
        }

        if self.config.verbose:
            print("🎯 New Episode Started")
            print(f"Task ID: {info['task_id']}")
            print(f"Task Index: {self.current_task_index - 1}/{len(self.tasks)}")
            print(f"Total Requirements: {observation['total_requirements']}")
            print(f"Task Description: {observation['task_description'][:100]}...")

        return observation, info

    def initialize_requirements(self):
        self.remaining_requirements = []


        implicit_requirements = self.current_task.get("Implicit Requirements", [])

        implicit_req_id_counter = 1
        for req_data in implicit_requirements:

            aspect = req_data.get("Aspect", "")
            requirement_text = req_data.get("RequirementText", "")

            dimension = str(req_data.get("Dimension") or "").strip()

            implicit_req = {
                "id": f"IR{implicit_req_id_counter}",
                "aspect": aspect,
                "requirement": requirement_text,
                "dimension": dimension,
                "elicited": False
            }
            self.remaining_requirements.append(implicit_req)
            implicit_req_id_counter += 1

        if not self.remaining_requirements:
            self.remaining_requirements = []

    def calculate_elicitation_ratio(self) -> float:
        total_requirements = len(self.remaining_requirements) + len(self.elicited_requirements)
        if total_requirements == 0:
            return 0.0
        return len(self.elicited_requirements) / total_requirements

    def get_remaining_requirements_summary(self) -> List[str]:
        return [
            f"{req['id']}: {req.get('aspect', '')}-{req.get('requirement', '')[:50]}..."
            for req in self.remaining_requirements
        ]

    def step(self, action: str) -> Tuple[Dict[str, Any], float, bool, bool, Dict[str, Any]]:
        if self.episode_complete:
            raise ValueError("Episode is complete. Call reset() to start a new episode.")


        self.conversation_history.append({
            "role": "interviewer",
            "content": action
        })


        judge_model_config = {
            "api_key": self.config.judge_api_key,
            "base_url": self.config.judge_base_url,
            "model_name": self.config.judge_model_name,
            "temperature": self.config.judge_temperature,
            "max_tokens": self.config.judge_max_tokens,
            "timeout": self.config.judge_timeout,
            "thinking_level": self.config.judge_thinking_level,
        }


        user_simulator_config = {
            "api_key": self.config.user_api_key,
            "base_url": self.config.user_base_url,
            "model_name": self.config.user_model_name,
            "temperature": self.config.user_temperature,
            "max_tokens": self.config.user_max_tokens,
            "timeout": self.config.user_timeout,
            "thinking_level": self.config.user_thinking_level,
        }

        user_quality_level = self.config.user_answer_quality


        user_response, elicited_requirements, _, judgement = evaluate_action(
            action=action,
            task=self.current_task,
            judge_model_config = judge_model_config,
            user_simulator_config = user_simulator_config,
            conversation_history = self.conversation_history[:-1],
            remaining_requirements = self.remaining_requirements,
            user_quality_level = user_quality_level,
        )


        if elicited_requirements:
            for req_id in elicited_requirements:
                for req in self.remaining_requirements:
                    if req.get("id") == req_id and not req.get("elicited", False):
                        req["elicited"] = True
                        self.elicited_requirements.append(req.copy())


                        aspect = req.get("aspect", "") or "Unknown"
                        if aspect not in self.current_task_requirements_by_aspect:
                            self.current_task_requirements_by_aspect[aspect] = {"total": 0, "elicited": 0}
                        self.current_task_requirements_by_aspect[aspect]["elicited"] += 1
                        break


            self.remaining_requirements = [
                req for req in self.remaining_requirements
                if not req.get("elicited", False)
            ]


        elicited_in_this_step = len(elicited_requirements) if elicited_requirements else 0
        self.current_task_elicited += elicited_in_this_step


        is_hit = judgement.get("is_relevant_to_implied_requirements", False)
        self.current_task_hit_sequence.append(1 if is_hit else 0)


        action_type = judgement.get("action_type", "unknown")
        if action_type not in self.current_task_action_stats:
            self.current_task_action_stats[action_type] = {"total": 0, "effective": 0}
        self.current_task_action_stats[action_type]["total"] += 1
        if is_hit:
            self.current_task_action_stats[action_type]["effective"] += 1


        self.record_step_statistics()


        action_info = judgement.copy()
        action_info["elicited_requirements"] = elicited_requirements
        action_info["user_response"] = user_response


        current_elicitation_ratio = self.calculate_elicitation_ratio()
        conversation_turn = {
            "turn": self.step_count + 1,
            "interviewer": action,
            "user": user_response,
            "action_type": action_info.get("action_type", "unknown"),
            "is_relevant_to_url": action_info.get("is_relevant_to_implied_requirements", False),
            "elicited_requirements": action_info.get("elicited_requirements", []),
            "elicitation_ratio": current_elicitation_ratio,
        }
        self.current_task_conversation_turns.append(conversation_turn)


        self.conversation_history.append({
            "role": "user",
            "content": user_response
        })


        self.step_count +=1


        self.action_history.append(action)

        if action_info.get("action_type") == "finish":
            self.episode_complete = True
            terminated = True
            truncated = False

            self.record_task_statistics()
        elif self.step_count >= self.config.max_turns:
            self.episode_complete = True
            terminated = False
            truncated = True

            self.record_task_statistics()
        else:
            terminated = False
            truncated = False


        task_description = f"System Name: {self.current_task.get('name', 'N/A')}\n"
        task_description += f"Application Type: {self.current_task.get('application_type', 'N/A')}\n"
        task_description += f"Initial Requirements: {self.current_task.get('initial_requirements', 'N/A')}"

        observation = {
            "task_description": task_description,
            "goal": "Elicit requirements and write user requirements list if elicit enough requirements",
            "feedback": user_response,
            "step_count": self.step_count,
            "episode_complete": int(self.episode_complete),
            "total_requirements": len(self.remaining_requirements) + len(self.elicited_requirements),
            "remaining_requirements": len(self.remaining_requirements),
            "elicitation_ratio": self.calculate_elicitation_ratio(),
            "conversation_history": self.build_conversation_history_str(),
        }

        info = {
            "task_id": self.current_task.get("id", ""),
            "requirements_summary": self.get_remaining_requirements_summary(),
            "action_history": self.action_history.copy(),
            "conversation_history": self.conversation_history.copy(),
            "elicited_requirements": self.elicited_requirements.copy(),
            "action_info": action_info,
        }


        return observation, 0.0, terminated, truncated, info

    def get_conversation_history(self) -> List[Dict[str, str]]:
        return self.conversation_history.copy()

    def build_conversation_history_str(self) -> str:
        history_str = ""
        for entry in self.conversation_history:
            role = entry.get("role", "")
            content = entry.get("content", "")
            if role == "interviewer":
                history_str += f"Interviewer: {content}\n\n"
            elif role == "user":
                history_str += f"User: {content}\n\n"
        return history_str.strip()

    def calculate_tkqr(self) -> float:
        return compute_tkqr(self.current_task_hit_sequence, self.current_task_total_requirements)

    def calculate_ora(self) -> float:
        return compute_ora(self.step_count, self.current_task_total_requirements)

    def record_step_statistics(self):
        step_record = {
            "step": self.step_count,
            "total_requirements": self.current_task_total_requirements,
            "total_elicited": self.current_task_elicited,
            "elicitation_ratio": self.current_task_elicited / self.current_task_total_requirements if self.current_task_total_requirements > 0 else 0.0,
        }

        self.current_task_step_records.append(step_record)

    def calculate_action_type_effectiveness(self) -> Dict[str, Dict[str, Any]]:
        action_effectiveness = {}
        for action_type, stats in self.current_task_action_stats.items():
            total = stats["total"]
            effective = stats["effective"]
            effectiveness_ratio = effective / total if total > 0 else 0.0
            action_effectiveness[action_type] = {
                "total": total,
                "effective": effective,
                "effectiveness_ratio": effectiveness_ratio
            }
        return action_effectiveness

    def calculate_aspect_type_elicitation_ratio(self) -> Dict[str, Dict[str, Any]]:
        aspect_elicitation = {}
        for aspect, stats in self.current_task_requirements_by_aspect.items():
            total = stats["total"]
            elicited = stats["elicited"]
            elicitation_ratio = elicited / total if total > 0 else 0.0
            aspect_elicitation[aspect] = {
                "total": total,
                "elicited": elicited,
                "elicitation_ratio": elicitation_ratio
            }
        return aspect_elicitation

    def record_task_statistics(self):
        task_id = self.current_task.get("id", f"task_{self.current_task_index - 1}")


        tkqr = self.calculate_tkqr()
        ora = self.calculate_ora()


        action_effectiveness = self.calculate_action_type_effectiveness()


        aspect_elicitation = self.calculate_aspect_type_elicitation_ratio()

        task_stats = {
            "task_id": task_id,
            "application_type": self.current_task.get("application_type", "Unknown"),
            "total_requirements": self.current_task_total_requirements,
            "total_elicited": self.current_task_elicited,
            "elicitation_ratio": self.current_task_elicited / self.current_task_total_requirements if self.current_task_total_requirements > 0 else 0.0,
            "tkqr": tkqr,
            "ora": ora,
            "turns": self.step_count,
            "optimal_rounds": self.current_task_total_requirements + 1,
            "token_cost": self.current_task_token_cost,
            "action_type_effectiveness": action_effectiveness,
            "aspect_type_elicitation": aspect_elicitation,
            "step_records": self.current_task_step_records.copy(),
        }

        self.global_stats["task_results"].append(task_stats)
        self.global_stats["task_step_records"].append({
            "task_id": task_id,
            "step_records": self.current_task_step_records.copy(),
        })

        self.global_stats["conversation_turns"].append({
            "task_id": task_id,
            "task_name": self.current_task.get("name", ""),
            "initial_requirements": self.current_task.get("initial_requirements", ""),
            "user_answer_quality": self.config.user_answer_quality,
            "interviewer_model": self.interviewer_model_name or "unknown",
            "conversation": self.current_task_conversation_turns.copy(),
            "turns": len(self.current_task_conversation_turns),
        })

        if self.config.verbose:
            print(f"📊 Task {task_id} Statistics:")
            print(f"   Total Requirements: {self.current_task_total_requirements}")
            print(f"   Total Elicited: {self.current_task_elicited} ({task_stats['elicitation_ratio']:.2%})")
            print(f"   TKQR: {tkqr:.4f}")
            print(f"   ORA: {ora:.4f}")
            print(f"   Rounds: {self.step_count} (Optimal: {task_stats['optimal_rounds']})")
            print(f"   Token Cost: {self.current_task_token_cost}")
            print("   Action Type Effectiveness:")
            for action_type, stats in action_effectiveness.items():
                print(f"     {action_type}: {stats['effective']}/{stats['total']} = {stats['effectiveness_ratio']:.2%}")
            print("   Aspect Type Elicitation:")
            for aspect, stats in aspect_elicitation.items():
                if stats['total'] > 0:
                    print(f"     {aspect}: {stats['elicited']}/{stats['total']} = {stats['elicitation_ratio']:.2%}")
            print(f"   Total Steps: {len(self.current_task_step_records)}")

    def evaluate_all_tasks(self) -> Dict[str, Any]:
        if not self.global_stats["task_results"]:
            return {
                "elicitation_ratio": 0.0,
                "tkqr": 0.0,
                "ora": 0.0,
                "action_type_effectiveness": {},
                "aspect_type_elicitation": {},
                "total_tasks": 0,
                "task_results": [],
            }

        return compute_overall_metrics(self.global_stats["task_results"])

    def run_all_tasks(self, interviewer: "Interviewer") -> Dict[str, Any]:
        self.interviewer_model_name = interviewer.model_name

        total_tasks = len(self.tasks)
        task_num = 1

        print("\n" + "="*60)
        print("開始執行所有任務")
        print("="*60)

        while True:

            try:
                observation, info = self.reset()
            except Exception as e:
                print(f"重置環境失敗：{e}")
                import traceback
                traceback.print_exc()
                break


            if info.get("all_tasks_completed", False):
                if self.config.verbose:
                    print("\n所有任務已完成！")
                break

            task_id = info.get("task_id", f"task_{task_num}")
            task_data = self.current_task

            if self.config.verbose:
                print(f"\n{'='*60}")
                print(f"任務 {task_num}/{total_tasks}：{task_id}")
                print(f"{'='*60}")
                print(f"系統名稱：{task_data.get('name', 'N/A')}")
                print(f"應用類型：{task_data.get('application_type', 'N/A')}")
                print(f"初始需求：{task_data.get('initial_requirements', 'N/A')[:100]}...")
                print(f"總需求數：{observation.get('total_requirements', 0)}")
                print("\n開始對話...\n")


            step = 0
            while step < self.config.max_turns:

                if self.config.verbose:
                    print(f"[輪次 {step + 1}]")

                try:
                    interviewer_question, usage_info = interviewer.ask_question(
                        conversation_history=self.get_conversation_history(),
                        return_usage=True
                    )

                    if usage_info:
                        self.current_task_token_cost += usage_info.get("total_tokens", 0)
                except Exception as e:
                    print(f"產生 interviewer 問題失敗：{e}")
                    import traceback
                    traceback.print_exc()
                    print("結束對話")
                    break

                if not interviewer_question:
                    print("無法產生 interviewer 問題。結束對話。")
                    break


                try:
                    observation, reward, terminated, truncated, info = self.step(interviewer_question)
                except Exception as e:
                    print(f"執行步驟失敗：{e}")
                    import traceback
                    traceback.print_exc()
                    break

                action_info = info.get("action_info", {})

                if self.config.verbose:
                    print(f"  動作類型：{action_info.get('action_type', 'unknown')}")
                    print(f"  與隱式需求相關：{action_info.get('is_relevant_to_implied_requirements', False)}")
                    print(f"  已取得的需求：{action_info.get('elicited_requirements', [])}")
                    print(f"  Interviewer: {interviewer_question[:80]}...")
                    user_response = action_info.get("user_response", "")
                    if user_response:
                        print(f"  User: {user_response[:80]}...")
                    print(f"  觀察：總需求={observation.get('total_requirements', 0)}，"
                          f"剩餘={observation.get('remaining_requirements', 0)}，"
                          f"取得比例={observation.get('elicitation_ratio', 0.0):.2%}")

                step += 1

                if terminated or truncated:
                    if terminated:
                        if self.config.verbose:
                            print("\n對話已終止（interviewer 完成）。")
                    else:
                        if self.config.verbose:
                            print(f"\n對話已截斷（達到最大步數：{self.config.max_turns}）。")
                    break

            if self.config.verbose:
                print(f"\n任務 {task_num} 完成：總輪數={len(self.current_task_conversation_turns)}，"
                      f"已取得需求數={len(self.elicited_requirements)}")

            task_num += 1


            if task_num > total_tasks:
                if self.config.verbose:
                    print(f"\n已執行所有 {total_tasks} 個任務，停止。")
                break


        if self.config.verbose:
            print("\n" + "="*60)
            print("計算總體評估指標...")
            print("="*60)

        overall_metrics = self.evaluate_all_tasks()
        turn_values = [
            int(row.get("turns", 0) or 0)
            for row in overall_metrics.get("task_results", []) or []
            if isinstance(row, dict)
        ]
        overall_metrics["average_turn"] = (
            sum(turn_values) / len(turn_values)
            if turn_values else 0.0
        )
        overall_metrics["std_turn"] = std_from_variance(
            variance(turn_values, overall_metrics["average_turn"])
            if turn_values else 0.0
        )

        if self.config.verbose:
            print("\n總體評估結果：")
            print(f"  總測試樣本數：{overall_metrics['total_tasks']}")
            print(f"  總隱式需求數：{overall_metrics['total_requirements_all_tasks']}")
            print("\n平均比例（基於測試樣本平均）：")
            print(f"  平均取得比例：{overall_metrics['elicitation_ratio']:.2%}")
            print(f"  平均 TKQR：{overall_metrics['tkqr']:.4f}")
            print(f"  平均 Turns：{overall_metrics.get('average_turn', 0.0):.2f}")
            print("\n標準差：")
            print(f"  取得比例標準差：{overall_metrics.get('std_elicitation_ratio', 0.0):.4f}")
            print(f"  TKQR 標準差：{overall_metrics.get('std_tkqr', 0.0):.4f}")
            print(f"  Turns 標準差：{overall_metrics.get('std_turn', 0.0):.2f}")
            print("\nToken 消耗：")
            print(f"  平均 Token 消耗：{overall_metrics.get('average_token_cost', 0.0):.2f}")


            if overall_metrics.get('application_type_statistics'):
                print("\n依應用類型統計：")
                for app_type, stats in overall_metrics['application_type_statistics'].items():
                    print(f"  {app_type}:")
                    print(f"    任務數：{stats['num_tasks']}")
                    print(f"    平均取得比例：{stats['average_elicitation_ratio']:.2%}")
                    print(f"    平均 TKQR：{stats['average_tkqr']:.4f}")


            if overall_metrics.get('action_type_effectiveness'):
                print("\n動作類型有效性：")
                for action_type, stats in overall_metrics['action_type_effectiveness'].items():
                    print(f"  {action_type}: {stats['effective']}/{stats['total']} = {stats['effectiveness_ratio']:.2%}")


            if overall_metrics.get('aspect_type_elicitation'):
                print("\n面向類型取得比例：")
                for aspect, stats in overall_metrics['aspect_type_elicitation'].items():
                    if stats['total'] > 0:
                        print(f"  {aspect}: {stats['elicited']}/{stats['total']} = {stats['elicitation_ratio']:.2%}")

        return {
            "overall_metrics": overall_metrics,
            "conversation_results": self.global_stats["conversation_turns"],
        }

    def save_evaluation_results(self, file_path: Optional[str] = None, interviewer_model_name: str = None):

        if file_path is None:
            if self.config.evaluation_result_path is None:
                raise ValueError("file_path must be provided or set config.evaluation_result_path")
            file_path = self.config.evaluation_result_path
        overall_metrics = self.evaluate_all_tasks()
        turn_values = [
            int(row.get("turns", 0) or 0)
            for row in overall_metrics.get("task_results", []) or []
            if isinstance(row, dict)
        ]
        overall_metrics["average_turn"] = (
            sum(turn_values) / len(turn_values)
            if turn_values else 0.0
        )
        overall_metrics["std_turn"] = std_from_variance(
            variance(turn_values, overall_metrics["average_turn"])
            if turn_values else 0.0
        )

        if not overall_metrics or overall_metrics.get("total_tasks", 0) == 0:
            if self.config.verbose:
                print("警告：沒有評估結果可儲存")
            return

        interviewer_model = interviewer_model_name or self.interviewer_model_name or "unknown"


        task_results = []
        for task_stats in overall_metrics.get('task_results', []):
            task_results.append({
                "task_id": task_stats.get("task_id", ""),
                "total_requirements": task_stats.get("total_requirements", 0),
                "total_elicited": task_stats.get("total_elicited", 0),
                "elicitation_ratio": round_to_4(task_stats.get("elicitation_ratio", 0.0)),
                "tkqr": round_to_4(task_stats.get("tkqr", 0.0)),
                "turns": task_stats.get("turns", 0),
                "optimal_rounds": task_stats.get("optimal_rounds", 0),
                "token_cost": task_stats.get("token_cost", 0),
                "action_type_effectiveness": task_stats.get("action_type_effectiveness", {}),
                "aspect_type_elicitation": task_stats.get("aspect_type_elicitation", {}),
            })

        application_type_statistics = {
            app_type: {
                "num_tasks": int((stats or {}).get("num_tasks", 0) or 0),
                "average_elicitation_ratio": float(
                    (stats or {}).get("average_elicitation_ratio", 0.0) or 0.0
                ),
                "average_tkqr": float((stats or {}).get("average_tkqr", 0.0) or 0.0),
            }
            for app_type, stats in overall_metrics.get('application_type_statistics', {}).items()
            if isinstance(stats, dict)
        }

        evaluation_data = {
            "config": {
                "interviewer_model": interviewer_model,
                "judge_model": self.config.judge_model_name,
                "user_model": self.config.user_model_name,
                "user_answer_quality": self.config.user_answer_quality,
                "max_turns": self.config.max_turns,
            },
            "overall_evaluation": {
                "total_test_samples": overall_metrics['total_tasks'],
                "total_hidden_requirements": overall_metrics['total_requirements_all_tasks'],

                "average_elicitation_ratio": round_to_4(overall_metrics['elicitation_ratio']),
                "average_tkqr": round_to_4(overall_metrics['tkqr']),
                "average_turn": round_to_2(overall_metrics.get("average_turn", 0.0)),
                "std_elicitation_ratio": round_to_4(overall_metrics.get('std_elicitation_ratio', 0.0)),
                "std_tkqr": round_to_4(overall_metrics.get('std_tkqr', 0.0)),
                "std_turn": round_to_2(overall_metrics.get("std_turn", 0.0)),

                "average_token_cost": round_to_2(overall_metrics.get('average_token_cost', 0.0)),

                "action_type_effectiveness": overall_metrics.get('action_type_effectiveness', {}),

                "aspect_type_elicitation": overall_metrics.get('aspect_type_elicitation', {}),

                "application_type_statistics": application_type_statistics,
            },
            "task_results": task_results,
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(evaluation_data, f, ensure_ascii=False, indent=2)

        if self.config.verbose:
            print(f"\n評估結果已儲存至：{file_path}")

    def save_conversation_results(self, file_path: Optional[str] = None):

        if file_path is None:
            if self.config.conversation_result_path is None:
                raise ValueError("file_path must be provided or set config.conversation_result_path")
            file_path = self.config.conversation_result_path
        conversation_results = self.global_stats.get("conversation_turns", [])

        if not conversation_results:

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            if self.config.verbose:
                print("警告：沒有對話記錄，已寫入空對話結果檔")
            return

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(conversation_results, f, ensure_ascii=False, indent=2)

        if self.config.verbose:
            print(f"對話過程已儲存至：{file_path}")
            print(f"  包含 {len(conversation_results)} 個任務的對話記錄")
