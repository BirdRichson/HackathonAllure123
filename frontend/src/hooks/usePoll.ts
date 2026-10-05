import { useEffect, useRef, useState } from "react";

/**
 * Загружает данные сразу и затем каждые `ms` миллисекунд, а также при смене `deps`.
 * Ошибки не роняют экран: остаются последние успешные данные.
 */
export function usePoll<T>(load: () => Promise<T>, deps: unknown[], ms = 5000): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let alive = true;
    const run = () =>
      loadRef
        .current()
        .then((d) => {
          if (alive) {
            setData(d);
            setError(null);
          }
        })
        .catch((e: Error) => alive && setError(e.message));
    void run();
    const id = setInterval(run, ms);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error };
}
