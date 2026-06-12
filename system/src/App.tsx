import { Fragment, useEffect, useState } from "react";
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
import { useBootstrap } from "@/hooks/useBootstrap";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";
import type { FileTreeNode } from "@/types/api";

const LAYOUT_KEY = "plant-layout-v16";
const TABLET_LAYOUT_KEY = "plant-layout-tablet-v1";
const TABLET_AUX_LAYOUT_KEY = "plant-layout-tablet-aux-v1";
const EMPTY_ITEMS: FileTreeNode[] = [];

type LayoutMode = "desktop" | "tablet" | "mobile";

function currentLayoutMode(): LayoutMode {
  if (typeof window === "undefined") return "desktop";
  if (window.innerWidth < 768) return "mobile";
  if (window.innerWidth < 1200) return "tablet";
  return "desktop";
}

function useLayoutMode() {
  const [mode, setMode] = useState<LayoutMode>(() => currentLayoutMode());

  useEffect(() => {
    const update = () => setMode(currentLayoutMode());
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  return mode;
}

export default function App() {
  const projectId = useUiStore((s) => s.activeProjectId);
  const setActiveProjectId = useUiStore((s) => s.setActiveProjectId);
  const clearMessages = useChatStore((s) => s.clearMessages);
  const clearAttachedDocs = useUiStore((s) => s.clearAttachedDocs);
  const setEnabledAgents = useUiStore((s) => s.setEnabledAgents);
  const visiblePanels = useUiStore((s) => s.visiblePanels);
  const layoutMode = useLayoutMode();
  const bootstrap = useBootstrap();
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

  useEffect(() => {
    if (!projectId || !bootstrap.data) return;
    const exists = bootstrap.data.projects.some(
      (project) => project.project_id === projectId,
    );
    if (!exists) setActiveProjectId(null);
  }, [bootstrap.data, projectId, setActiveProjectId]);

  const items = artifacts.data?.items ?? EMPTY_ITEMS;
  const panelCount = Object.values(visiblePanels).filter(Boolean).length;

  const referencesPanel = visiblePanels.references ? (
    <Panel key="references" defaultSize={20} minSize={14}>
      <ReferencePanel projectId={projectId} />
    </Panel>
  ) : null;
  const workspacePanel = visiblePanels.workspace ? (
    <Panel key="workspace" defaultSize={45} minSize={30}>
      <MeetingPanel projectId={projectId} />
    </Panel>
  ) : null;
  const outputPanel = visiblePanels.output ? (
    <Panel key="output" defaultSize={35} minSize={22}>
      <ResultPreview projectId={projectId} items={items} />
    </Panel>
  ) : null;

  const renderPanels = (panels: Array<React.ReactNode>) =>
    panels.filter(Boolean).map((panel, index) => (
      <Fragment key={index}>
        {index > 0 && <PanelResizeHandle />}
        {panel}
      </Fragment>
    ));

  const renderDesktopLayout = () => (
    <PanelGroup
      direction="horizontal"
      autoSaveId={LAYOUT_KEY}
      className="h-full"
    >
      {renderPanels([referencesPanel, workspacePanel, outputPanel])}
    </PanelGroup>
  );

  const renderTabletLayout = () => {
    const auxItems = [
      visiblePanels.references && {
        key: "references",
        node: <ReferencePanel projectId={projectId} />,
      },
      visiblePanels.output && {
        key: "output",
        node: <ResultPreview projectId={projectId} items={items} />,
      },
    ].filter(Boolean) as Array<{ key: string; node: React.ReactNode }>;
    const auxGroup =
      auxItems.length === 0 ? null : auxItems.length === 1 ? (
        <Panel key="aux-single" defaultSize={34} minSize={24}>
          {auxItems[0].node}
        </Panel>
      ) : (
        <Panel key="aux" defaultSize={34} minSize={24}>
          <PanelGroup
            direction="vertical"
            autoSaveId={TABLET_AUX_LAYOUT_KEY}
            className="h-full"
          >
            {renderPanels(
              auxItems.map((item) => (
                <Panel key={`${item.key}-inner`} defaultSize={50} minSize={24}>
                  {item.node}
                </Panel>
              )),
            )}
          </PanelGroup>
        </Panel>
      );

    if (panelCount === 1) {
      const only = visiblePanels.workspace ? (
        <MeetingPanel projectId={projectId} />
      ) : visiblePanels.output ? (
        <ResultPreview projectId={projectId} items={items} />
      ) : (
        <ReferencePanel projectId={projectId} />
      );
      return (
        <PanelGroup direction="horizontal" className="h-full">
          <Panel defaultSize={100} minSize={24}>
            {only}
          </Panel>
        </PanelGroup>
      );
    }

    if (panelCount === 2 && visiblePanels.workspace) {
      const side = visiblePanels.references ? (
        <ReferencePanel projectId={projectId} />
      ) : (
        <ResultPreview projectId={projectId} items={items} />
      );
      return (
        <PanelGroup
          direction="horizontal"
          autoSaveId={TABLET_LAYOUT_KEY}
          className="h-full"
        >
          <Panel key="side-tablet" defaultSize={34} minSize={24}>
            {side}
          </Panel>
          <PanelResizeHandle />
          <Panel key="workspace-tablet" defaultSize={66} minSize={40}>
            <MeetingPanel projectId={projectId} />
          </Panel>
        </PanelGroup>
      );
    }

    if (!workspacePanel && auxGroup) {
      return auxItems.length === 1 ? (
        <PanelGroup direction="horizontal" className="h-full">
          <Panel defaultSize={100} minSize={24}>
            {auxItems[0].node}
          </Panel>
        </PanelGroup>
      ) : (
        <PanelGroup
          direction="vertical"
          autoSaveId={TABLET_AUX_LAYOUT_KEY}
          className="h-full"
        >
          {renderPanels(
            auxItems.map((item) => (
              <Panel key={`${item.key}-only`} defaultSize={50} minSize={24}>
                {item.node}
              </Panel>
            )),
          )}
        </PanelGroup>
      );
    }

    return (
      <PanelGroup
        direction="horizontal"
        autoSaveId={TABLET_LAYOUT_KEY}
        className="h-full"
      >
        {renderPanels([
          auxGroup,
          visiblePanels.workspace && (
            <Panel key="workspace-tablet" defaultSize={66} minSize={40}>
              <MeetingPanel projectId={projectId} />
            </Panel>
          ),
        ])}
      </PanelGroup>
    );
  };

  const renderMobileLayout = () => (
    <div className="mobile-layout-scroll flex h-full flex-col gap-2 overflow-y-auto pb-2">
      {visiblePanels.workspace && (
        <section className="h-[78vh] min-h-[560px] shrink-0">
          <MeetingPanel projectId={projectId} />
        </section>
      )}
      {visiblePanels.output && (
        <section className="h-[72vh] min-h-[480px] shrink-0">
          <ResultPreview projectId={projectId} items={items} />
        </section>
      )}
      {visiblePanels.references && (
        <section className="h-[56vh] min-h-[360px] shrink-0">
          <ReferencePanel projectId={projectId} />
        </section>
      )}
    </div>
  );

  return (
    <div className="flex h-full flex-col overflow-hidden bg-slate-50">
      <HeaderBar />
      <NoticeStack />
      <div className="min-h-0 flex-1 p-1">
        {panelCount === 0 ? (
          <div className="flex h-full items-center justify-center rounded-surface border border-gray-200 bg-white text-sm font-medium text-slate-400">
            尚未開啟任何面板
          </div>
        ) : layoutMode === "mobile" ? (
          renderMobileLayout()
        ) : layoutMode === "tablet" ? (
          renderTabletLayout()
        ) : (
          renderDesktopLayout()
        )}
      </div>
    </div>
  );
}
