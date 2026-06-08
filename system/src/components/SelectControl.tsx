import { ChevronDown } from "lucide-react";
import type { SelectHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

export const selectControlClassName =
  "appearance-none rounded-control border border-gray-200 bg-white py-1 pl-2.5 pr-7 text-xs text-slate-700 hover:border-gray-300 focus:border-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-50";

interface SelectControlProps extends SelectHTMLAttributes<HTMLSelectElement> {
  wrapperClassName?: string;
}

export function SelectControl({
  className,
  wrapperClassName,
  children,
  ...props
}: SelectControlProps) {
  return (
    <div className={cn("relative", wrapperClassName)}>
      <select className={cn(selectControlClassName, className)} {...props}>
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
    </div>
  );
}
