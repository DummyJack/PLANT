import type { ReactNode } from "react";
import { cn } from "@/utils/cn";

interface PanelChromeProps {
  title: string;
  actions?: ReactNode;
  trailing?: ReactNode;
  subheader?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  centerTitle?: boolean;
}

export function PanelChrome({
  title,
  actions,
  trailing,
  subheader,
  children,
  className,
  bodyClassName,
  centerTitle = false,
}: PanelChromeProps) {
  return (
    <div className={cn("card relative flex h-full flex-col overflow-hidden", className)}>
      <div className="relative flex shrink-0 items-center gap-3 border-b border-gray-100 px-4 py-2.5">
        {centerTitle ? (
          <>
            <div className="flex min-w-0 flex-1 items-center gap-2.5">{actions}</div>
            <span className="section-title pointer-events-none absolute left-1/2 -translate-x-1/2">
              {title}
            </span>
          </>
        ) : (
          <div className="flex min-w-0 flex-1 items-center gap-2.5">
            <span className="section-title shrink-0">{title}</span>
            {actions}
          </div>
        )}
        {trailing && (
          <div className="flex shrink-0 items-center gap-1.5">{trailing}</div>
        )}
      </div>
      {subheader}
      <div className={cn("min-h-0 flex-1 overflow-hidden", bodyClassName)}>
        {children}
      </div>
    </div>
  );
}
