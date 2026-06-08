import { useEffect } from "react";
import { fetchConfig } from "@/api/config";
import {
  Panel,
  PanelGroup,
  PanelResizeHandle,
} from "react-resizable-panels";
import { HeaderBar } from "@/features/header/HeaderBar";
import { MeetingPanel } from "@/features/meeting/MeetingPanel";
import { ResultPreview } from "@/features/output/ResultPreview";
import { ReferencePanel } from "@/features/upload/ReferencePanel";
import { NoticeStack } from "@/components/NoticeStack";
import { useProjectData } from "@/hooks/useProjectData";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { FileTreeNode } from "@/types/api";

const LAYOUT_KEY = "plant-layout-v16";
const EMPTY_ITEMS: FileTreeNode[] = [];

export default function App() {
  const projectId = useUiStore((s) => s.activeProjectId);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const clearAttachedDocs = useUiStore((s) => s.clearAttachedDocs);
  const setEnabledAgents = useUiStore((s) => s.setEnabledAgents);
  const { artifacts } = useProjectData(projectId);

  useEffect(() => {
    void fetchConfig()
      .then(({ config }) => {
        if (config.enable_agents) {
          setEnabledAgents({
            ...useUiStore.getState().enabledAgents,
            ...config.enable_agents,
          });
        }
      })
      .catch(() => {
        /* keep uiStore defaults */
      });
  }, [setEnabledAgents]);

  useEffect(() => {
    clearMessages();
    clearAttachedDocs();
  }, [projectId, clearMessages, clearAttachedDocs]);

  const items = artifacts.data?.items ?? EMPTY_ITEMS;

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      <HeaderBar />
      <NoticeStack />
      <div className="min-h-0 flex-1 p-1">
        <PanelGroup
          direction="horizontal"
          autoSaveId={LAYOUT_KEY}
          className="h-full gap-1"
        >
          <Panel defaultSize={20} minSize={14}>
            <ReferencePanel projectId={projectId} />
          </Panel>
          <PanelResizeHandle />
          <Panel defaultSize={45} minSize={30}>
            <MeetingPanel projectId={projectId} />
          </Panel>
          <PanelResizeHandle />
          <Panel defaultSize={35} minSize={22}>
            <ResultPreview projectId={projectId} items={items} />
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}
