import { Fragment, type ReactNode } from "react";
import {
  Panel,
  PanelGroup,
  PanelResizeHandle,
} from "react-resizable-panels";

import { MeetingPanel } from "@/features/meeting/MeetingPanel";
import { ResultPreview } from "@/features/output/ResultPreview";
import { ReferencePanel } from "@/features/upload/ReferencePanel";
import type { FileTreeNode } from "@/types/api";


const DESKTOP_LAYOUT_KEY = "plant-layout-v16";
const TABLET_LAYOUT_KEY = "plant-layout-tablet-v1";
const TABLET_AUX_LAYOUT_KEY = "plant-layout-tablet-aux-v1";

export type LayoutMode = "desktop" | "tablet" | "mobile";

interface VisiblePanels {
  references: boolean;
  workspace: boolean;
  output: boolean;
}

interface WorkspaceLayoutProps {
  emptyLabel: string;
  items: FileTreeNode[];
  layoutMode: LayoutMode;
  projectId: string | null;
  visiblePanels: VisiblePanels;
}

interface KeyedPanel {
  key: string;
  node: ReactNode;
}

function PanelSequence({ panels }: { panels: KeyedPanel[] }) {
  return panels.map((panel, index) => (
    <Fragment key={panel.key}>
      {index > 0 && <PanelResizeHandle />}
      {panel.node}
    </Fragment>
  ));
}

function DesktopLayout({
  items,
  projectId,
  visiblePanels,
}: Omit<WorkspaceLayoutProps, "emptyLabel" | "layoutMode">) {
  const panels: KeyedPanel[] = [];
  if (visiblePanels.references) {
    panels.push({
      key: "references",
      node: (
        <Panel defaultSize={20} minSize={14}>
          <ReferencePanel projectId={projectId} />
        </Panel>
      ),
    });
  }
  if (visiblePanels.workspace) {
    panels.push({
      key: "workspace",
      node: (
        <Panel defaultSize={45} minSize={30}>
          <MeetingPanel projectId={projectId} />
        </Panel>
      ),
    });
  }
  if (visiblePanels.output) {
    panels.push({
      key: "output",
      node: (
        <Panel defaultSize={35} minSize={22}>
          <ResultPreview projectId={projectId} items={items} />
        </Panel>
      ),
    });
  }

  return (
    <PanelGroup direction="horizontal" autoSaveId={DESKTOP_LAYOUT_KEY} className="h-full">
      <PanelSequence panels={panels} />
    </PanelGroup>
  );
}

function buildTabletAuxiliaryPanels({
  items,
  projectId,
  visiblePanels,
}: Omit<WorkspaceLayoutProps, "emptyLabel" | "layoutMode">): KeyedPanel[] {
  const panels: KeyedPanel[] = [];
  if (visiblePanels.references) {
    panels.push({
      key: "references",
      node: <ReferencePanel projectId={projectId} />,
    });
  }
  if (visiblePanels.output) {
    panels.push({
      key: "output",
      node: <ResultPreview projectId={projectId} items={items} />,
    });
  }
  return panels;
}

function FullSizePanel({ children }: { children: ReactNode }) {
  return (
    <PanelGroup direction="horizontal" className="h-full">
      <Panel defaultSize={100} minSize={24}>
        {children}
      </Panel>
    </PanelGroup>
  );
}

function TabletLayout(props: Omit<WorkspaceLayoutProps, "emptyLabel" | "layoutMode">) {
  const { projectId, visiblePanels } = props;
  const panelCount = Object.values(visiblePanels).filter(Boolean).length;
  const auxiliaryPanels = buildTabletAuxiliaryPanels(props);

  if (panelCount === 1) {
    if (visiblePanels.workspace) {
      return <FullSizePanel><MeetingPanel projectId={projectId} /></FullSizePanel>;
    }
    return <FullSizePanel>{auxiliaryPanels[0].node}</FullSizePanel>;
  }

  if (panelCount === 2 && visiblePanels.workspace) {
    return (
      <PanelGroup direction="horizontal" autoSaveId={TABLET_LAYOUT_KEY} className="h-full">
        <Panel defaultSize={34} minSize={24}>
          {auxiliaryPanels[0].node}
        </Panel>
        <PanelResizeHandle />
        <Panel defaultSize={66} minSize={40}>
          <MeetingPanel projectId={projectId} />
        </Panel>
      </PanelGroup>
    );
  }

  if (!visiblePanels.workspace) {
    if (auxiliaryPanels.length === 1) {
      return <FullSizePanel>{auxiliaryPanels[0].node}</FullSizePanel>;
    }
    return (
      <PanelGroup direction="vertical" autoSaveId={TABLET_AUX_LAYOUT_KEY} className="h-full">
        <PanelSequence
          panels={auxiliaryPanels.map(({ key, node }) => ({
            key,
            node: <Panel defaultSize={50} minSize={24}>{node}</Panel>,
          }))}
        />
      </PanelGroup>
    );
  }

  const auxiliaryGroup = (
    <Panel defaultSize={34} minSize={24}>
      <PanelGroup direction="vertical" autoSaveId={TABLET_AUX_LAYOUT_KEY} className="h-full">
        <PanelSequence
          panels={auxiliaryPanels.map(({ key, node }) => ({
            key,
            node: <Panel defaultSize={50} minSize={24}>{node}</Panel>,
          }))}
        />
      </PanelGroup>
    </Panel>
  );

  return (
    <PanelGroup direction="horizontal" autoSaveId={TABLET_LAYOUT_KEY} className="h-full">
      <PanelSequence
        panels={[
          { key: "auxiliary", node: auxiliaryGroup },
          {
            key: "workspace",
            node: (
              <Panel defaultSize={66} minSize={40}>
                <MeetingPanel projectId={projectId} />
              </Panel>
            ),
          },
        ]}
      />
    </PanelGroup>
  );
}

function MobileLayout({
  items,
  projectId,
  visiblePanels,
}: Omit<WorkspaceLayoutProps, "emptyLabel" | "layoutMode">) {
  return (
    <div className="mobile-layout-scroll flex h-full min-w-0 flex-col gap-2 overflow-y-auto overflow-x-hidden pb-2">
      {visiblePanels.workspace && (
        <section className="h-[78vh] min-h-[560px] min-w-0 shrink-0 overflow-hidden">
          <MeetingPanel projectId={projectId} />
        </section>
      )}
      {visiblePanels.output && (
        <section className="h-[72vh] min-h-[480px] min-w-0 shrink-0 overflow-hidden">
          <ResultPreview projectId={projectId} items={items} />
        </section>
      )}
      {visiblePanels.references && (
        <section className="h-[56vh] min-h-[360px] min-w-0 shrink-0 overflow-hidden">
          <ReferencePanel projectId={projectId} />
        </section>
      )}
    </div>
  );
}

export function WorkspaceLayout(props: WorkspaceLayoutProps) {
  if (!Object.values(props.visiblePanels).some(Boolean)) {
    return (
      <div className="flex h-full items-center justify-center rounded-surface border border-gray-200 bg-white text-sm font-medium text-slate-400">
        {props.emptyLabel}
      </div>
    );
  }
  if (props.layoutMode === "mobile") return <MobileLayout {...props} />;
  if (props.layoutMode === "tablet") return <TabletLayout {...props} />;
  return <DesktopLayout {...props} />;
}
