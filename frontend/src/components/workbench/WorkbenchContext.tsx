import { createContext, useContext } from "react";
import type { TranscriptionWord } from "../../types/review";

export interface WorkbenchContextValue {
  jobId: string;
  wordsMap: Map<number, TranscriptionWord>;
}

export const WorkbenchContext = createContext<WorkbenchContextValue>({
  jobId: "",
  wordsMap: new Map(),
});

export function useWorkbench(): WorkbenchContextValue {
  return useContext(WorkbenchContext);
}
