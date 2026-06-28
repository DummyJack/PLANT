import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { UI_TEXT } from "@/i18n";
import { useUiStore } from "@/stores/uiStore";
import App from "./App";
import "./index.css";

const FRONTEND_HOST = (import.meta.env.frontend_host ?? "plant.dummyjack.com").trim();

function isLocalFrontendHost(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname.endsWith(".localhost")
  );
}

function isAllowedFrontendHost(): boolean {
  const hostname = window.location.hostname;
  return isLocalFrontendHost(hostname) || hostname === FRONTEND_HOST;
}

function isKnownFrontendPath(): boolean {
  return window.location.pathname === "/" || window.location.pathname === "/index.html";
}

function StatusPage({
  title,
  message,
  action,
}: {
  title: string;
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full items-center justify-center bg-white p-6">
      <div className="flex -translate-y-8 flex-col items-center text-center">
        <div className="flex h-32 w-32 items-center justify-center rounded-full bg-slate-100 shadow-sm">
          <img src="/logo.png" alt="PLANT" className="h-24 w-24 object-contain" />
        </div>
        <h1 className="mt-14 text-5xl font-bold tracking-normal text-slate-950">
          {title}
        </h1>
        <p className="mt-6 text-xl font-normal leading-8 text-slate-800">
          {message}
        </p>
        {action ? <div className="mt-10">{action}</div> : null}
      </div>
    </div>
  );
}

function ForbiddenFrontendMode() {
  return (
    <StatusPage
      title="Forbidden (403)"
      message="Sorry, you cannot access this page"
    />
  );
}

function NotFoundPage() {
  const t = UI_TEXT[useUiStore.getState().language];
  return (
    <StatusPage
      title="Not Found (404)"
      message="Sorry, we cannot find this page"
      action={
        <a
          href="/"
          className="inline-flex h-11 items-center justify-center rounded-control bg-slate-950 px-6 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
        >
          {t.backHome}
        </a>
      }
    />
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      retry: 1,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {!isAllowedFrontendHost() ? (
      <ForbiddenFrontendMode />
    ) : isKnownFrontendPath() ? (
      <QueryClientProvider client={queryClient}>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </QueryClientProvider>
    ) : (
      <NotFoundPage />
    )}
  </StrictMode>,
);
