export {};

declare module "react-router-dom" {
  interface MemoryRouterProps {
    future?: {
      v7_startTransition?: boolean;
      v7_relativeSplatPath?: boolean;
    };
  }
}
