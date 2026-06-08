# Handles project manager logic for shared utility behavior for the Plant runtime.
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from storage import Store
from utils.language import sync_output_language


# ========
# Defines ProjectSession class for this module workflow.
# ========
@dataclass
class ProjectSession:
    project_id: str
    is_continue: bool
    rough_idea: str
    artifact: Optional[Dict[str, Any]] = None


# ========
# Defines ProjectManager class for this module workflow.
# ========
class ProjectManager:
    # ========
    # Defines select or create project function for this module workflow.
    # ========
    @staticmethod
    def select_or_create_project(store) -> Tuple[str, bool]:
        temp_store = Store(store.base_dir)
        projects = temp_store.list_projects()

        if not projects:
            print("\n目前沒有任何專案，將創建新專案")
            return None, False

        print("\n" + "=" * 60)
        print("現有專案列表\n")

        for i, project in enumerate(projects, 1):
            created_at = project.get("created_at", "未知")
            if "T" in created_at:
                try:
                    dt = datetime.fromisoformat(created_at)
                    created_at = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            print(f"{i}. 專案 ID: {project['project_id']}")
            print(f"   創建時間: {created_at}")
            print(f"   初始想法: {project.get('rough_idea', '未知')}\n")

        print("=" * 60)
        print()

        while True:
            try:
                choice = input("請選擇專案編號 (或 0 創建新專案)：").strip()
                if not choice:
                    print("❌ 請輸入專案編號")
                    continue

                choice_num = int(choice)
                if choice_num == 0:
                    return None, False
                elif 1 <= choice_num <= len(projects):
                    project_id = projects[choice_num - 1]["project_id"]
                    print(f"\n✓ 已選擇專案：{project_id}")
                    return project_id, True
                else:
                    print(f"❌ 請輸入有效的專案編號 (0-{len(projects)})")
            except ValueError:
                print("❌ 請輸入數字")

    # ========
    # Defines display project info function for this module workflow.
    # ========
    @staticmethod
    def display_project_info(store, project_id: str):
        artifact = store.load_artifact()

        created_at = "未知"
        if store.project_dir.exists():
            created_at = datetime.fromtimestamp(
                store.project_dir.stat().st_ctime
            ).strftime("%Y-%m-%d %H:%M:%S")

        print("\n" + "=" * 60)
        print(f"專案資訊：{project_id}")
        print("=" * 60)
        print(f"創建時間: {created_at}")
        if artifact:
            print(f"初始想法: {artifact.get('rough_idea', '未知')}")
            discussions = artifact.get("discussions", [])
            print(f"已完成輪數: {len(discussions)}")
        print("=" * 60 + "\n")

    # ========
    # Defines prepare project session function for this module workflow.
    # ========
    @staticmethod
    def prepare_project_session(base_dir: Path, base_store) -> ProjectSession:
        project_id, is_continue = ProjectManager.select_or_create_project(base_store)

        artifact = None
        if not is_continue:
            rough_idea = input(
                "\n請輸入您的初始想法(可以是一個模糊的系統概念、問題描述或需求)："
            ).strip()

            if not rough_idea:
                raise ValueError("請提供初始想法")

            project_id = base_store.create_project()
            print(f"\n✓ 已創建專案：{project_id}\n")
            return ProjectSession(
                project_id=project_id,
                is_continue=False,
                rough_idea=rough_idea,
                artifact=None,
            )

        project_store = Store(base_dir, project_id)
        ProjectManager.display_project_info(project_store, project_id)

        artifact = project_store.load_artifact()
        if artifact:
            rough_idea = artifact.get("rough_idea", "")
            sync_output_language(rough_idea, artifact)
            print(f"專案的初始想法：{rough_idea}\n")
            return ProjectSession(
                project_id=project_id,
                is_continue=True,
                rough_idea=rough_idea,
                artifact=artifact,
            )

        print("⚠️  警告：無法載入專案的 artifact，將作為新專案處理\n")
        rough_idea = input("請輸入您的初始想法：").strip()
        if not rough_idea:
            raise ValueError("請提供初始想法")
        sync_output_language(rough_idea)
        project_id = base_store.create_project()
        return ProjectSession(
            project_id=project_id,
            is_continue=False,
            rough_idea=rough_idea,
            artifact=None,
        )
