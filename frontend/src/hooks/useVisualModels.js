// src/hooks/useVisualModels.js
// Danh sách model lấy TỪ BACKEND (GET /models): model nào có index trên đĩa của
// backend đó thì chọn được. Hỏng kết nối / backend bản cũ -> rơi về danh sách
// cứng trong constants/models.js.
import { useEffect, useState } from "react";
import { subscribeBaseUrl } from "../api/apiClient";
import { getModels } from "../api/searchService";
import {
  DEFAULT_VISUAL_MODEL,
  FALLBACK_SINGLES,
  ensembleMembersOf,
  pickDefaultModel,
  toSingleOptions,
} from "../constants/models";

const FALLBACK = {
  singles: FALLBACK_SINGLES,
  envMembers: [],
  defaultModel: DEFAULT_VISUAL_MODEL,
  fromBackend: false,
};

export function useVisualModels() {
  const [state, setState] = useState(FALLBACK);

  useEffect(() => {
    let alive = true;

    const load = async () => {
      try {
        const data = await getModels();
        if (!alive) return;
        setState({
          singles: toSingleOptions(data),
          envMembers: ensembleMembersOf(data),
          defaultModel: pickDefaultModel(data),
          fromBackend: true,
        });
      } catch {
        if (alive) setState(FALLBACK);
      }
    };

    load();
    // Đổi Backend URL = máy khác, kho index khác. Danh sách phải đi theo.
    const unsubscribe = subscribeBaseUrl(load);
    return () => {
      alive = false;
      unsubscribe();
    };
  }, []);

  return state;
}
