import { useQuery } from "@tanstack/react-query";
import { fetchBootstrap } from "@/api/bootstrap";

export function useBootstrap() {
  return useQuery({
    queryKey: ["bootstrap"],
    queryFn: fetchBootstrap,
    refetchInterval: 30_000,
  });
}
